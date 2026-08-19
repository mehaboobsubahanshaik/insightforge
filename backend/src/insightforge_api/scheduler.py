"""In-process background scheduler (15 s poll). Discovery runs under the
job_runner RLS arm (read-only); every job then executes inside its own
tenant-scoped session. Failure handling uses a dedicated recovery session so
bookkeeping (consecutive_failures, exponential backoff, failed SyncRun row)
survives the rollback of the failed work — a lesson baked in from the
previous build. For horizontal scale the loop moves to a worker container;
the run functions are already stateless."""

import asyncio
import logging
import uuid
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
    User,
)
from .services import entitlements, mailer, narrative, notify, querysvc, syncsvc
from .services.reportsvc import render_dashboard_pdf

log = logging.getLogger("insightforge.scheduler")
last_heartbeat: dict = {"at": None}
MAX_BACKOFF_MULTIPLIER = 8
NOTIFY_AFTER_FAILURES = 3  # email the connection owner once at this streak
REPORT_RETRY_MINUTES = 10  # one quick retry before waiting a full interval


async def _notify_sync_failures(s, tenant_id, conn):
    """At exactly NOTIFY_AFTER_FAILURES consecutive failures, tell the owner —
    once per streak, so a flapping connector cannot spam anyone."""
    if conn.consecutive_failures != NOTIFY_AFTER_FAILURES:
        return
    owner = (await s.execute(select(User).where(
        User.id == conn.created_by))).scalar_one_or_none()
    if owner is None:
        return
    await mailer.send(
        s, tenant_id=tenant_id, to_email=owner.email, kind="sync_failure",
        subject=f"InsightForge: sync for '{conn.name}' keeps failing",
        body=(f"The scheduled sync for connection '{conn.name}' has failed "
              f"{conn.consecutive_failures} times in a row.\n"
              f"Last error: {conn.last_error}\n\n"
              "Retries continue automatically with increasing delays. Open "
              "Sources in InsightForge to fix the connection or run a manual "
              "sync once it's resolved — a successful sync resets everything."))


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
                    await _notify_sync_failures(s, tenant_id, conn)
                    if conn.consecutive_failures == NOTIFY_AFTER_FAILURES:
                        await notify.deliver_event(s, tenant_id, "sync.failed", {
                            "message": f"Connection '{conn.name}' has failed "
                                       f"{conn.consecutive_failures} times in a row.",
                            "connection_id": str(conn.id)})
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
                await _notify_sync_failures(s, tenant_id, conn)
                if conn.consecutive_failures == NOTIFY_AFTER_FAILURES:
                    await notify.deliver_event(s, tenant_id, "sync.failed", {
                        "message": f"Connection '{conn.name}' has failed "
                                   f"{conn.consecutive_failures} times in a row.",
                        "connection_id": str(conn.id)})
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
                # R16: scheduled snapshot artifact alongside the report
                import json as _json
                import os as _os

                outdir = _os.environ.get("OUTBOX_DIR", "/srv/outbox")
                _os.makedirs(outdir, exist_ok=True)
                snap_name = (f"snapshot-{d.id}-"
                             f"{now.strftime('%Y%m%dT%H%M%S')}.json")
                with open(_os.path.join(outdir, snap_name), "w") as fh:
                    _json.dump({"dashboard": d.name, "scheduled": True,
                                "taken_at": now.isoformat(),
                                **hydrated}, fh, default=str)
                ds_by_id = {}
                for w in v.widgets:
                    if w["dataset_id"] not in ds_by_id:
                        ds_by_id[w["dataset_id"]] = (await s.execute(
                            select(Dataset).where(
                                Dataset.id == uuid.UUID(w["dataset_id"])
                            ))).scalar_one_or_none()
                brief = await narrative.executive_brief(
                    s, d.name, v.widgets, ds_by_id)
                for email in report.recipients:
                    await mailer.send(
                        s, tenant_id=tenant_id, to_email=email, kind="report",
                        subject=f"Scheduled report: {d.name}",
                        body=(brief["text"]
                              + f"\n\nThe full report PDF is attached "
                                f"(published version v{d.published_version})."),
                        attachment=(f"{d.name[:40]}.pdf", pdf))
                await notify.deliver_event(s, tenant_id, "report.sent", {
                    "message": f"Report '{d.name}' sent to "
                               f"{len(report.recipients)} recipient(s).",
                    "dashboard_id": str(d.id), "dashboard": d.name})
                await entitlements.record_billing_event(s, tenant_id, "report.sent",
                                                        len(report.recipients))
                report.last_status = "sent"
                ran += 1
            except Exception as e:  # noqa: BLE001
                log.warning("report %s failed: %s", report_id, e)
                if report.last_status == "retrying":
                    # the quick retry also failed: give up until next interval
                    report.last_status = "failed"
                else:
                    # first failure: one fast retry before a full interval wait
                    report.last_status = "retrying"
                    report.next_run_at = now + timedelta(
                        minutes=min(REPORT_RETRY_MINUTES, report.interval_minutes))
    return ran


_OPS = {"gt": lambda v, t: v > t, "gte": lambda v, t: v >= t,
        "lt": lambda v, t: v < t, "lte": lambda v, t: v <= t}


def _in_quiet_hours(lifecycle: dict, now_hm: str) -> bool:
    qs, qe = lifecycle.get("quiet_start"), lifecycle.get("quiet_end")
    if not qs or not qe:
        return False
    if qs <= qe:
        return qs <= now_hm < qe
    return now_hm >= qs or now_hm < qe  # window crosses midnight


async def run_escalations_once() -> int:
    """R6: unacked firings past their rule's escalation window get ONE
    escalation email to the configured address."""
    from datetime import datetime, timedelta, timezone

    from .db import session_factory, tenant_scoped_session
    from .models import AlertEvent, AlertRule
    from .services import mailer

    sent = 0
    async with session_factory()() as s:
        rules = (await s.execute(select(AlertRule))).scalars().all()
    for rule in rules:
        lc = rule.lifecycle or {}
        mins, to = lc.get("escalate_after_minutes"), lc.get("escalate_to")
        if not mins or not to:
            continue
        async with tenant_scoped_session(rule.tenant_id) as ts:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=mins)
            evs = (await ts.execute(select(AlertEvent).where(
                AlertEvent.rule_id == rule.id,
                AlertEvent.acked_at.is_(None),
                AlertEvent.fired_at < cutoff))).scalars().all()
            for ev in evs:
                if (ev.message or "").endswith("[escalated]"):
                    continue
                await mailer.send(
                    ts, tenant_id=rule.tenant_id, to_email=to,
                    kind="alert",
                    subject=f"ESCALATION: '{rule.name}' unacknowledged",
                    body=f"Alert '{rule.name}' fired at "
                         f"{ev.fired_at.isoformat()} (value {ev.value}) "
                         f"and has not been acknowledged for {mins}+ "
                         "minutes.")
                ev.message = (ev.message or "") + " [escalated]"
                sent += 1
            await ts.commit()
    return sent


async def run_dataset_health_once() -> int:
    """R7: data-freshness + data-quality alerts, configured per dataset in
    governance.alerts = {"freshness_hours": 24, "min_quality": 90}.
    Fires at most once per UTC day per dataset via a stamp in governance."""
    import copy as _copy
    from datetime import datetime, timezone

    from .db import session_factory, tenant_scoped_session
    from .models import Dataset
    from .services import notify

    fired = 0
    today = datetime.now(timezone.utc).date().isoformat()
    async with session_factory()() as s:
        ds_ids = (await s.execute(select(Dataset.id, Dataset.tenant_id).where(
            Dataset.archived.is_(False)))).all()
    for ds_id, tid in ds_ids:
        async with tenant_scoped_session(tid) as ts:
            ds = (await ts.execute(select(Dataset).where(
                Dataset.id == ds_id))).scalar_one_or_none()
            if ds is None:
                continue
            cfg = (ds.governance or {}).get("alerts") or {}
            if not cfg or cfg.get("_last_fired") == today:
                continue
            msgs = []
            fh = cfg.get("freshness_hours")
            if fh and ds.ingested_at:
                age_h = (datetime.now(timezone.utc)
                         - ds.ingested_at).total_seconds() / 3600
                if age_h > fh:
                    msgs.append(f"'{ds.name}' data is {age_h:.0f}h old "
                                f"(freshness SLA {fh}h).")
            mq = cfg.get("min_quality")
            if mq and (ds.quality_score or 100) < mq:
                msgs.append(f"'{ds.name}' quality score "
                            f"{ds.quality_score}/100 is below the "
                            f"{mq} floor.")
            if not msgs:
                continue
            await notify.deliver_event(ts, tid, "alert.triggered", {
                "message": " ".join(msgs), "dataset_id": str(ds.id),
                "kind": "dataset_health"})
            gov = _copy.deepcopy(ds.governance or {})
            gov.setdefault("alerts", {})["_last_fired"] = today
            ds.governance = gov
            await ts.commit()
            fired += 1
    return fired


async def run_due_alerts_once() -> int:
    fired = 0
    for rule_id, tenant_id in await _due(AlertRule, AlertRule.next_check_at):
        async with tenant_scoped_session(tenant_id) as s:
            rule = (await s.execute(select(AlertRule).where(
                AlertRule.id == rule_id))).scalar_one_or_none()
            if rule is not None:
                from datetime import datetime as _dt
                from datetime import timezone as _tz

                hm = _dt.now(_tz.utc).strftime("%H:%M")
                if _in_quiet_hours(rule.lifecycle or {}, hm):
                    rule.next_check_at = _dt.now(_tz.utc) + timedelta(
                        minutes=rule.interval_minutes)
                    await s.commit()
                    continue
            if rule is None:
                continue
            now = datetime.now(timezone.utc)
            rule.next_check_at = now + timedelta(minutes=rule.interval_minutes)
            lc = rule.lifecycle or {}
            ds = (await s.execute(select(Dataset).where(
                Dataset.id == rule.dataset_id))).scalar_one_or_none()
            if ds is None or ds.archived:
                continue
            if rule.kind == "anomaly":
                fired += await _check_anomaly_rule(s, tenant_id, rule, ds)
                continue
            try:
                result = await querysvc.execute_formula(
                    s, dataset_id=ds.id, current_import_id=ds.current_import_id,
                    dataset_schema=ds.schema_def, formula=rule.formula)
            except querysvc.QueryError:
                continue
            value = result.get("value")
            if lc.get("relative_pct") and lc.get("date_column"):
                # R7 relative-change alert: PoP % move vs prior equal window
                from .services import narrative as _nar

                pop = await _nar.pop_kpi(s, ds, rule.formula,
                                         lc["date_column"], None)
                prev = pop.get("previous") or 0
                chg = (abs(pop["change"]) / abs(prev) * 100) if prev else 0
                value = round(chg, 2)
                breached = chg >= float(lc["relative_pct"])
            else:
                breached = value is not None and _OPS[rule.operator](
                    value, rule.threshold)
            if breached and rule.last_state == "ok":  # state-change-only firing
                rule.last_state = "fired"
                message = (f"Alert '{rule.name}': {rule.formula} = {value:,.2f} is "
                           f"{rule.operator} threshold {rule.threshold:,.2f} "
                           f"(dataset: {ds.name})")
                s.add(AlertEvent(tenant_id=tenant_id, rule_id=rule.id, value=value,
                                 message=message))
                await notify.deliver_event(s, tenant_id, "alert.triggered", {
                    "message": message, "rule_id": str(rule.id),
                    "value": value, "dataset": ds.name})
                for email in rule.recipients:
                    await mailer.send(s, tenant_id=tenant_id, to_email=email, kind="alert",
                                      subject=f"InsightForge alert: {rule.name}",
                                      body=message + "\nYou'll be notified again only after "
                                                     "the value recovers and breaches again.")
                fired += 1
            elif not breached and rule.last_state == "fired":
                rule.last_state = "ok"
    return fired


async def _check_anomaly_rule(s, tenant_id, rule, ds) -> int:
    """Anomaly-triggered alerts (MVP3 P2): aggregate the rule's formula per
    day and flag when the LATEST day is a statistical anomaly (robust z via
    insightforge_ml — same explainable detector as the Insights panel).
    State-change-only firing, like threshold alerts."""
    from insightforge_ml import detect_anomalies

    if not rule.date_column:
        return 0
    try:
        result = await querysvc.execute_formula(
            s, dataset_id=ds.id, current_import_id=ds.current_import_id,
            dataset_schema=ds.schema_def, formula=rule.formula,
            group_by=rule.date_column)
    except querysvc.QueryError:
        return 0
    groups = sorted((g for g in result.get("groups", [])
                     if g.get("group") is not None),
                    key=lambda g: str(g["group"]))
    if len(groups) < 5:
        return 0
    series = [float(g["value"] or 0) for g in groups]
    labels = [str(g["group"]) for g in groups]
    found = detect_anomalies(series, labels=labels)
    latest_hit = next((a for a in found.get("anomalies", [])
                       if a.get("label") == labels[-1]), None)
    if latest_hit and rule.last_state == "ok":
        rule.last_state = "fired"
        message = (f"Anomaly alert '{rule.name}': {rule.formula} on "
                   f"{labels[-1]} was {series[-1]:,.2f} — a "
                   f"{latest_hit.get('direction', 'shift')} vs the recent "
                   f"pattern (dataset: {ds.name}).")
        s.add(AlertEvent(tenant_id=tenant_id, rule_id=rule.id,
                         value=series[-1], message=message))
        for email in rule.recipients:
            await mailer.send(s, tenant_id=tenant_id, to_email=email,
                              kind="alert",
                              subject=f"InsightForge anomaly: {rule.name}",
                              body=message + "\nYou'll be notified again only "
                                             "after the pattern normalizes and "
                                             "breaks again.")
        await notify.deliver_event(s, tenant_id, "anomaly.detected", {
            "message": message, "rule_id": str(rule.id),
            "value": series[-1], "date": labels[-1], "dataset": ds.name})
        return 1
    if not latest_hit and rule.last_state == "fired":
        rule.last_state = "ok"
    return 0


async def run_lifecycle_once() -> int:
    """P3 lifecycle jobs: expire unconverted trials to free (with an email),
    and purge tenants whose offboarding grace period has passed."""
    from sqlalchemy import text as _text

    from .db import session_factory
    from .models import Membership, Tenant, User

    acted = 0
    async with session_factory()() as s:
        now = datetime.now(timezone.utc)
        expired = (await s.execute(select(Tenant).where(
            Tenant.trial_ends_at.is_not(None), Tenant.trial_ends_at < now,
            Tenant.plan_code == "growth"))).scalars().all()
        for t in expired:
            t.plan_code = "free"
            t.trial_ends_at = None
            owner = (await s.execute(
                select(User.email).join(Membership, Membership.user_id == User.id)
                .where(Membership.tenant_id == t.id,
                       Membership.role == "tenant_owner").limit(1))).scalar_one_or_none()
            if owner:
                await mailer.send(s, tenant_id=t.id, to_email=owner,
                                  kind="billing",
                                  subject="Your InsightForge trial ended",
                                  body="Your 14-day Growth trial has ended and "
                                       "the organization is back on the free "
                                       "plan. Nothing was deleted. Choose a "
                                       "plan in Billing to restore Growth "
                                       "limits.")
            acted += 1
        # advanced retention (G2): purge rows past each dataset's window
        from .models import Dataset as _DS

        held = {t.id for t in (await s.execute(select(Tenant))).scalars()
                if ((t.features or {}).get("legal_hold") or {}).get(
                    "enabled")}
        rds = (await s.execute(select(_DS).where(
            _DS.governance.isnot(None)))).scalars().all()
        for ds in rds:
            ret = (ds.governance or {}).get("retention")
            if not ret:
                continue
            if ds.tenant_id in held:
                log.info("legal hold: skipping retention purge for %s",
                         ds.name)
                continue
            async with tenant_scoped_session(ds.tenant_id) as ts:
                res = await ts.execute(_text(
                    "DELETE FROM dataset_rows WHERE dataset_id = :d "
                    "AND (data->>:c)::date < (now() - make_interval("
                    "days => :n))::date"),
                    {"d": str(ds.id), "c": ret["column"], "n": ret["days"]})
                if res.rowcount:
                    acted += 1
                    log.info("retention purged %s rows from %s",
                             res.rowcount, ds.name)
        due = (await s.execute(select(Tenant).where(
            Tenant.status == "offboarding",
            Tenant.deletion_due_at.is_not(None),
            Tenant.deletion_due_at < now))).scalars().all()
        due = [t for t in due
               if not ((t.features or {}).get("legal_hold") or {}).get(
                   "enabled")]
        for t in due:
            async with tenant_scoped_session(t.id) as ts:
                for table in ("dataset_rows", "dq_results", "dq_history",
                              "alert_events", "alert_rules", "measures",
                              "report_schedules", "dashboard_views",
                              "dashboard_versions", "dashboards",
                              "webhooks", "ai_feedback", "datasets"):
                    await ts.execute(_text(
                        f"DELETE FROM {table} "  # noqa: S608 - fixed list
                        "WHERE tenant_id = :t"), {"t": str(t.id)})
            t.status = "purged"
            t.deletion_due_at = None
            log.info("tenant %s purged after offboarding grace", t.slug)
            acted += 1
        await s.commit()
    return acted


async def run_siem_once() -> int:
    """SIEM integration (G4): stream security-relevant audit events to
    webhooks subscribed to 'siem.audit', with a per-tenant cursor so each
    event ships exactly once."""
    from .db import session_factory, tenant_scoped_session
    from .models import AuditEvent, Tenant, Webhook
    from .routers.enterprise import SIEM_ACTIONS
    from .services import notify

    shipped = 0
    async with session_factory()() as s:
        tenants = (await s.execute(select(Tenant.id))).scalars().all()
    for tid in tenants:
        async with tenant_scoped_session(tid) as ts:
            hooks = (await ts.execute(select(Webhook).where(
                Webhook.tenant_id == tid,
                Webhook.active.is_(True)))).scalars().all()
            if not any("siem.audit" in (h.events or []) for h in hooks):
                continue
            t = (await ts.execute(select(Tenant).where(
                Tenant.id == tid))).scalar_one()
            cursor = (t.features or {}).get("siem_cursor")
            q = select(AuditEvent).where(
                AuditEvent.tenant_id == tid,
                AuditEvent.action.in_(SIEM_ACTIONS))
            if cursor:
                from datetime import datetime as _dt

                q = q.where(AuditEvent.created_at
                            > _dt.fromisoformat(cursor))
            events = (await ts.execute(q.order_by(
                AuditEvent.created_at).limit(200))).scalars().all()
            if not events:
                continue
            batch = [{"at": e.created_at.isoformat(), "action": e.action,
                      "resource": f"{e.resource_type}:{e.resource_id}"}
                     for e in events]
            await notify.deliver_event(ts, tid, "siem.audit", {
                "message": f"{len(batch)} security audit event(s)",
                "events": batch})
            t.features = {**(t.features or {}),
                          "siem_cursor": events[-1].created_at.isoformat()}
            await ts.commit()
            shipped += len(batch)
    return shipped


async def run_proactive_forecasts_once() -> int:
    """Proactive forecasting (MVP6 A3): for each registered forecast model,
    forecast the next step; a projected breach (>30% off the recent mean)
    emits a forecast.breach webhook event — the forecast comes to you."""
    from insightforge_ml import forecast_series

    from .db import session_factory, tenant_scoped_session
    from .models import Dataset, MLModel
    from .routers.mlops import _series
    from .services import notify

    fired = 0
    async with session_factory()() as s:
        models = (await s.execute(select(MLModel).where(
            MLModel.kind == "forecast",
            MLModel.status == "active"))).scalars().all()
    for m in models:
        async with tenant_scoped_session(m.tenant_id) as ts:
            ds = (await ts.execute(select(Dataset).where(
                Dataset.id == m.dataset_id))).scalar_one_or_none()
            if ds is None:
                continue
            try:
                series = await _series(ts, ds, m.config["value_column"],
                                       m.config["date_column"])
            except Exception as e:  # noqa: BLE001
                log.warning("proactive forecast skip %s: %s", m.name, e)
                continue
            if len(series) < 5:
                continue
            nxt = forecast_series(series, horizon=1)["points"][0]["forecast"]
            recent = sum(series[-7:]) / len(series[-7:])
            if recent and abs(nxt - recent) / abs(recent) > 0.3:
                await notify.deliver_event(ts, m.tenant_id,
                                           "forecast.breach", {
                    "message": f"Model '{m.name}': next-step forecast "
                               f"{nxt:,.0f} deviates "
                               f"{abs(nxt - recent) / abs(recent) * 100:.0f}%"
                               f" from the recent mean {recent:,.0f}.",
                    "model_id": str(m.id)})
                await ts.commit()
                fired += 1
    return fired


async def scheduler_loop(poll_seconds: float = 15.0):
    log.info("scheduler started (poll every %ss)", poll_seconds)
    while True:
        last_heartbeat["at"] = datetime.now(timezone.utc).isoformat()
        try:
            await run_due_schedules_once()
            await run_due_reports_once()
            await run_due_alerts_once()
            await run_lifecycle_once()
            await run_siem_once()
            await run_proactive_forecasts_once()
            await run_escalations_once()
            await run_dataset_health_once()
        except Exception:  # noqa: BLE001 - the loop itself must survive anything
            log.exception("scheduler tick failed")
        await asyncio.sleep(poll_seconds)
