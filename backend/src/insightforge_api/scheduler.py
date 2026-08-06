"""In-process background scheduler (15 s poll). Discovery runs under the
job_runner RLS arm (read-only); every job then executes inside its own
tenant-scoped session. Failure handling uses a dedicated recovery session so
bookkeeping (consecutive_failures, exponential backoff, failed SyncRun row)
survives the rollback of the failed work — a lesson baked in from the
previous build. For horizontal scale the loop moves to a worker container;
the run functions are already stateless."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from .db import session_factory, tenant_scoped_session
from .models import (
    AlertEvent,
    AlertRule,
    Connection,
    Dashboard,
    DashboardVersion,
    Dataset,
    ReportSchedule,
    SyncRun,
    SyncSchedule,
)
from .services import entitlements, mailer, querysvc, syncsvc
from .services.reportsvc import render_dashboard_pdf

log = logging.getLogger("insightforge.scheduler")
MAX_BACKOFF_MULTIPLIER = 8


async def _due(model, when_col):
    async with session_factory()() as s:
        async with s.begin():
            await s.execute(text("SELECT set_config('app.job_runner', 'true', true)"))
            rows = (await s.execute(select(model).where(
                model.enabled.is_(True),
                when_col <= datetime.now(timezone.utc)))).scalars().all()
            return [(r.id, r.tenant_id) for r in rows]


async def run_due_schedules_once() -> int:
    ran = 0
    for schedule_id, tenant_id in await _due(SyncSchedule, SyncSchedule.next_run_at):
        try:
            async with tenant_scoped_session(tenant_id) as s:
                schedule = (await s.execute(select(SyncSchedule).where(
                    SyncSchedule.id == schedule_id))).scalar_one_or_none()
                if schedule is None:
                    continue
                conn = (await s.execute(select(Connection).where(
                    Connection.id == schedule.connection_id))).scalar_one()
                run = await syncsvc.run_sync(s, conn, actor_user_id=conn.created_by,
                                             mode="incremental", trigger="scheduled")
                now = datetime.now(timezone.utc)
                schedule.last_run_at = now
                if run.status == "failed":
                    conn.consecutive_failures += 1
                    conn.last_error = run.error
                    backoff = min(2 ** conn.consecutive_failures, MAX_BACKOFF_MULTIPLIER)
                    schedule.next_run_at = now + timedelta(
                        minutes=schedule.interval_minutes * backoff)
                else:
                    conn.consecutive_failures = 0
                    conn.last_error = ""
                    schedule.next_run_at = now + timedelta(minutes=schedule.interval_minutes)
                ran += 1
        except Exception as e:  # noqa: BLE001 - recovery bookkeeping below
            log.warning("scheduled sync %s failed: %s", schedule_id, e)
            async with tenant_scoped_session(tenant_id) as s:
                schedule = (await s.execute(select(SyncSchedule).where(
                    SyncSchedule.id == schedule_id))).scalar_one_or_none()
                if schedule is None:
                    continue
                conn = (await s.execute(select(Connection).where(
                    Connection.id == schedule.connection_id))).scalar_one()
                conn.consecutive_failures += 1
                conn.last_error = str(e)[:1000]
                now = datetime.now(timezone.utc)
                backoff = min(2 ** conn.consecutive_failures, MAX_BACKOFF_MULTIPLIER)
                schedule.last_run_at = now
                schedule.next_run_at = now + timedelta(
                    minutes=schedule.interval_minutes * backoff)
                s.add(SyncRun(tenant_id=tenant_id, connection_id=conn.id,
                              mode="incremental", trigger="scheduled", status="failed",
                              error=str(e)[:1000], finished_at=now))
                ran += 1
    return ran


async def run_due_reports_once() -> int:
    ran = 0
    for report_id, tenant_id in await _due(ReportSchedule, ReportSchedule.next_run_at):
        async with tenant_scoped_session(tenant_id) as s:
            report = (await s.execute(select(ReportSchedule).where(
                ReportSchedule.id == report_id))).scalar_one_or_none()
            if report is None:
                continue
            now = datetime.now(timezone.utc)
            report.last_run_at = now
            report.next_run_at = now + timedelta(minutes=report.interval_minutes)
            try:
                d = (await s.execute(select(Dashboard).where(
                    Dashboard.id == report.dashboard_id))).scalar_one()
                if d.archived or d.published_version is None:
                    report.last_status = "skipped"
                    continue
                v = (await s.execute(select(DashboardVersion).where(
                    DashboardVersion.dashboard_id == d.id,
                    DashboardVersion.version == d.published_version))).scalar_one()
                from .routers.dashboards import _hydrate

                hydrated = await _hydrate(s, tenant_id, v.widgets, [])
                hydrated["name"] = d.name
                pdf = render_dashboard_pdf(hydrated)
                for email in report.recipients:
                    await mailer.send(
                        s, tenant_id=tenant_id, to_email=email, kind="report",
                        subject=f"Scheduled report: {d.name}",
                        body=f"Your scheduled InsightForge report '{d.name}' is attached.\n"
                             f"Published version v{d.published_version}.",
                        attachment=(f"{d.name[:40]}.pdf", pdf))
                await entitlements.record_billing_event(s, tenant_id, "report.sent",
                                                        len(report.recipients))
                report.last_status = "sent"
                ran += 1
            except Exception as e:  # noqa: BLE001
                log.warning("report %s failed: %s", report_id, e)
                report.last_status = "failed"
    return ran


_OPS = {"gt": lambda v, t: v > t, "gte": lambda v, t: v >= t,
        "lt": lambda v, t: v < t, "lte": lambda v, t: v <= t}


async def run_due_alerts_once() -> int:
    fired = 0
    for rule_id, tenant_id in await _due(AlertRule, AlertRule.next_check_at):
        async with tenant_scoped_session(tenant_id) as s:
            rule = (await s.execute(select(AlertRule).where(
                AlertRule.id == rule_id))).scalar_one_or_none()
            if rule is None:
                continue
            now = datetime.now(timezone.utc)
            rule.next_check_at = now + timedelta(minutes=rule.interval_minutes)
            ds = (await s.execute(select(Dataset).where(
                Dataset.id == rule.dataset_id))).scalar_one_or_none()
            if ds is None or ds.archived:
                continue
            try:
                result = await querysvc.execute_formula(
                    s, dataset_id=ds.id, current_import_id=ds.current_import_id,
                    dataset_schema=ds.schema_def, formula=rule.formula)
            except querysvc.QueryError:
                continue
            value = result.get("value")
            breached = value is not None and _OPS[rule.operator](value, rule.threshold)
            if breached and rule.last_state == "ok":  # state-change-only firing
                rule.last_state = "fired"
                message = (f"Alert '{rule.name}': {rule.formula} = {value:,.2f} is "
                           f"{rule.operator} threshold {rule.threshold:,.2f} "
                           f"(dataset: {ds.name})")
                s.add(AlertEvent(tenant_id=tenant_id, rule_id=rule.id, value=value,
                                 message=message))
                for email in rule.recipients:
                    await mailer.send(s, tenant_id=tenant_id, to_email=email, kind="alert",
                                      subject=f"InsightForge alert: {rule.name}",
                                      body=message + "\nYou'll be notified again only after "
                                                     "the value recovers and breaches again.")
                fired += 1
            elif not breached and rule.last_state == "fired":
                rule.last_state = "ok"
    return fired


async def scheduler_loop(poll_seconds: float = 15.0):
    log.info("scheduler started (poll every %ss)", poll_seconds)
    while True:
        try:
            await run_due_schedules_once()
            await run_due_reports_once()
            await run_due_alerts_once()
        except Exception:  # noqa: BLE001 - the loop itself must survive anything
            log.exception("scheduler tick failed")
        await asyncio.sleep(poll_seconds)
