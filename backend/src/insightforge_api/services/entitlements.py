"""Plan entitlements, quotas, metering. The internal engine is authoritative;
external payment collection (Stripe Billing adapter) is MVP 3 scope."""

import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BillingEvent, MeterReading, Plan, Tenant

DEFAULT_LIMITS = {"datasets": 3, "members": 3, "connections": 1, "dashboards": 3,
                  "min_sync_interval": 1440, "reports": 1, "alerts": 2}


async def get_plan(session: AsyncSession, tenant_id: uuid.UUID) -> tuple[str, dict]:
    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    code = tenant.plan_code if tenant else "free"
    plan = (await session.execute(select(Plan).where(Plan.code == code))).scalar_one_or_none()
    return code, (plan.limits if plan else DEFAULT_LIMITS)


async def enforce_quota(session: AsyncSession, tenant_id: uuid.UUID, resource: str, model,
                        extra_where=None) -> None:
    code, limits = await get_plan(session, tenant_id)
    limit = limits.get(resource)
    if limit is None:
        return
    q = select(func.count()).select_from(model)
    if extra_where is not None:
        q = q.where(extra_where)
    count = (await session.execute(q)).scalar_one()
    if count >= limit:
        raise HTTPException(
            403, f"Plan limit reached: the {code} plan allows {limit} {resource}. "
                 f"Upgrade in Billing to add more.")


async def enforce_min_interval(session: AsyncSession, tenant_id: uuid.UUID,
                               interval_minutes: int) -> None:
    code, limits = await get_plan(session, tenant_id)
    floor = limits.get("min_sync_interval", 1440)
    if interval_minutes < floor:
        raise HTTPException(
            403, f"Plan limit: the {code} plan allows schedules of {floor} minutes or longer.")


async def record_billing_event(session: AsyncSession, tenant_id: uuid.UUID, kind: str,
                               quantity: float = 1, **meta) -> None:
    session.add(BillingEvent(tenant_id=tenant_id, kind=kind, quantity=quantity, meta=meta))


async def meter(session: AsyncSession, tenant_id: uuid.UUID, name: str, value: float) -> None:
    session.add(MeterReading(tenant_id=tenant_id, meter=name, value=value))


async def enforce_ai_quota(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Cost control for the AI layer: per-plan daily question allowance,
    counted from the audit trail (every /ask records ai.question). The
    deterministic parser is nearly free — this guardrail exists so a future
    LLM adapter inherits a working budget mechanism, and so runaway scripted
    callers are bounded today."""
    from sqlalchemy import func
    from sqlalchemy import select as _select

    from ..models import AuditEvent

    plan_code, limits = await get_plan(session, tenant_id)
    limit = (limits or {}).get("ai_questions_per_day")
    if not limit:
        return
    today_count = (await session.execute(
        _select(func.count()).select_from(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action == "ai.question",
            AuditEvent.created_at >= func.date_trunc(
                "day", func.now())))).scalar_one()
    if today_count >= limit:
        raise HTTPException(
            429, f"Daily AI question limit reached ({limit} on the "
                 f"'{plan_code}' plan). The counter resets at midnight UTC; "
                 "upgrading raises the allowance.")
