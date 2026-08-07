"""Tenant administration: members, invitations, roles, activity feed,
notifications, billing & usage, plan changes, diagnostics."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import desc, func, select

from .. import audit
from ..deps import TenantContext, get_session, require
from ..models import (
    AuditEvent,
    BillingEvent,
    Connection,
    Dashboard,
    Dataset,
    EmailOutbox,
    Invitation,
    Membership,
    Plan,
    SyncRun,
    Tenant,
    User,
)
from ..roles import TENANT_OWNER
from ..security import new_opaque_token
from ..services import entitlements, mailer
from .auth import _uuid_or_422, _validate_role

router = APIRouter(prefix="/api/v1", tags=["tenant"])


@router.get("/tenants/current")
async def current_tenant(ctx: TenantContext = Depends(require("dataset:read")),
                         session=Depends(get_session)):
    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == ctx.tenant_id))).scalar_one()
    code, limits = await entitlements.get_plan(session, ctx.tenant_id)
    return {"id": str(tenant.id), "slug": tenant.slug, "name": tenant.name,
            "status": tenant.status, "plan_code": code, "limits": limits,
            "features": tenant.features}


class MemberOut(BaseModel):
    membership_id: str
    user_id: str
    email: str
    display_name: str
    role: str


@router.get("/members", response_model=list[MemberOut])
async def list_members(ctx: TenantContext = Depends(require("dataset:read")),
                       session=Depends(get_session)):
    rows = (await session.execute(
        select(Membership, User).join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == ctx.tenant_id).order_by(Membership.created_at))).all()
    return [MemberOut(membership_id=str(m.id), user_id=str(u.id), email=u.email,
                      display_name=u.display_name, role=m.role) for m, u in rows]


class InviteIn(BaseModel):
    email: EmailStr
    role: str = "analyst"


@router.post("/members/invitations", status_code=201)
async def invite_member(body: InviteIn, ctx: TenantContext = Depends(require("member:manage")),
                        session=Depends(get_session)):
    _validate_role(body.role)
    await entitlements.enforce_quota(session, ctx.tenant_id, "members", Membership,
                                     Membership.tenant_id == ctx.tenant_id)
    raw, token_hash = new_opaque_token()
    invite = Invitation(tenant_id=ctx.tenant_id, email=body.email.lower(), role=body.role,
                        token_hash=token_hash, created_by=ctx.user_id,
                        expires_at=datetime.now(timezone.utc) + timedelta(days=7))
    session.add(invite)
    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == ctx.tenant_id))).scalar_one()
    await mailer.send(
        session, tenant_id=ctx.tenant_id, to_email=body.email, kind="invitation",
        subject=f"You're invited to {tenant.name} on InsightForge",
        body=f"You've been invited to join {tenant.name} as {body.role}.\n\n"
             f"Invitation token:\n{raw}\n\n"
             f"Open InsightForge -> Accept invitation, or POST /api/v1/auth/invitations/accept."
             f"\nThis invitation expires in 7 days.")
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="member.invited", resource_type="invitation",
                       resource_id=str(invite.id), detail={"role": body.role},
                       correlation_id=ctx.correlation_id)
    await session.commit()
    return {"invitation_id": str(invite.id), "expires_at": invite.expires_at.isoformat()}


@router.get("/members/invitations")
async def list_invitations(ctx: TenantContext = Depends(require("member:manage")),
                           session=Depends(get_session)):
    rows = (await session.execute(select(Invitation).where(
        Invitation.tenant_id == ctx.tenant_id).order_by(desc(Invitation.created_at)))).scalars()
    return [{"id": str(i.id), "email": i.email, "role": i.role, "accepted": i.accepted,
             "expires_at": i.expires_at.isoformat()} for i in rows]


class RolePatch(BaseModel):
    role: str


@router.patch("/members/{membership_id}")
async def change_role(membership_id: str, body: RolePatch,
                      ctx: TenantContext = Depends(require("member:manage")),
                      session=Depends(get_session)):
    _validate_role(body.role)
    mid = _uuid_or_422(membership_id, "membership_id")
    membership = (await session.execute(select(Membership).where(
        Membership.id == mid, Membership.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if membership is None:
        raise HTTPException(404, "Member not found")
    if membership.role == TENANT_OWNER and body.role != TENANT_OWNER:
        owners = (await session.execute(select(func.count()).select_from(Membership).where(
            Membership.tenant_id == ctx.tenant_id,
            Membership.role == TENANT_OWNER))).scalar_one()
        if owners <= 1:
            raise HTTPException(409, "Cannot demote the last owner — promote someone else first")
    membership.role = body.role
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="member.role_changed", resource_type="membership",
                       resource_id=str(mid), detail={"role": body.role})
    await session.commit()  # persist the role change before responding
    return {"membership_id": str(mid), "role": body.role}


@router.get("/activity")
async def activity_feed(limit: int = 30,
                        ctx: TenantContext = Depends(require("dataset:read")),
                        session=Depends(get_session)):
    """Tenant activity feed derived from the immutable audit trail."""
    rows = (await session.execute(
        select(AuditEvent, User.display_name)
        .join(User, User.id == AuditEvent.actor_user_id, isouter=True)
        .where(AuditEvent.tenant_id == ctx.tenant_id)
        .order_by(desc(AuditEvent.created_at)).limit(min(max(limit, 1), 100)))).all()
    return [{"action": e.action, "resource_type": e.resource_type,
             "resource_id": e.resource_id, "actor": name or "system",
             "at": e.created_at.isoformat(), "detail": e.detail} for e, name in rows]


@router.get("/audit")
async def audit_log(limit: int = 100, ctx: TenantContext = Depends(require("audit:read")),
                    session=Depends(get_session)):
    rows = (await session.execute(select(AuditEvent).where(
        AuditEvent.tenant_id == ctx.tenant_id)
        .order_by(desc(AuditEvent.created_at)).limit(min(max(limit, 1), 500)))).scalars()
    return [{"id": str(e.id), "action": e.action, "actor_user_id":
             str(e.actor_user_id) if e.actor_user_id else None,
             "resource_type": e.resource_type, "resource_id": e.resource_id,
             "detail": e.detail, "correlation_id": e.correlation_id,
             "at": e.created_at.isoformat()} for e in rows]


@router.get("/notifications")
async def notifications(ctx: TenantContext = Depends(require("dataset:read")),
                        session=Depends(get_session)):
    """The current user's delivered messages (invites, alerts, reports)."""
    user = (await session.execute(select(User).where(User.id == ctx.user_id))).scalar_one()
    rows = (await session.execute(select(EmailOutbox).where(
        EmailOutbox.tenant_id == ctx.tenant_id, EmailOutbox.to_email == user.email)
        .order_by(desc(EmailOutbox.created_at)).limit(50))).scalars()
    return [{"id": str(m.id), "kind": m.kind, "subject": m.subject, "status": m.status,
             "at": m.created_at.isoformat()} for m in rows]


@router.get("/billing/summary")
async def billing_summary(ctx: TenantContext = Depends(require("usage:read")),
                          session=Depends(get_session)):
    code, limits = await entitlements.get_plan(session, ctx.tenant_id)
    plans = (await session.execute(select(Plan).order_by(Plan.monthly_price_usd))).scalars()

    async def count(model, *extra):
        return (await session.execute(
            select(func.count()).select_from(model).where(*extra))).scalar_one()

    usage = {
        "datasets": await count(Dataset, Dataset.tenant_id == ctx.tenant_id,
                                Dataset.archived.is_(False)),
        "dashboards": await count(Dashboard, Dashboard.tenant_id == ctx.tenant_id,
                                  Dashboard.archived.is_(False)),
        "connections": await count(Connection, Connection.tenant_id == ctx.tenant_id),
        "members": await count(Membership, Membership.tenant_id == ctx.tenant_id),
    }
    events = (await session.execute(
        select(BillingEvent.kind, func.count(), func.sum(BillingEvent.quantity))
        .where(BillingEvent.tenant_id == ctx.tenant_id).group_by(BillingEvent.kind))).all()
    return {"plan_code": code, "limits": limits, "usage": usage,
            "billing_events": [{"kind": k, "count": c, "quantity": float(q or 0)}
                               for k, c, q in events],
            "plans": [{"code": p.code, "name": p.name, "limits": p.limits,
                       "monthly_price_usd": p.monthly_price_usd} for p in plans]}


class PlanChange(BaseModel):
    plan_code: str


@router.post("/billing/plan")
async def change_plan(body: PlanChange, ctx: TenantContext = Depends(require("tenant:manage")),
                      session=Depends(get_session)):
    plan = (await session.execute(
        select(Plan).where(Plan.code == body.plan_code))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(422, "Unknown plan — choose free, starter, or growth")
    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == ctx.tenant_id))).scalar_one()
    tenant.plan_code = plan.code
    await entitlements.record_billing_event(session, ctx.tenant_id, "plan.changed",
                                            plan_code=plan.code)
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="tenant.plan_changed", resource_type="tenant",
                       detail={"plan_code": plan.code})
    await session.commit()
    return {"plan_code": plan.code}


@router.get("/admin/diagnostics")
async def diagnostics(ctx: TenantContext = Depends(require("usage:read")),
                      session=Depends(get_session)):
    """Support-safe operational snapshot: statuses and counts only — no row
    data, no credentials, no message bodies."""
    failed_runs = (await session.execute(select(SyncRun).where(
        SyncRun.tenant_id == ctx.tenant_id, SyncRun.status == "failed")
        .order_by(desc(SyncRun.started_at)).limit(10))).scalars()
    conns = (await session.execute(select(Connection).where(
        Connection.tenant_id == ctx.tenant_id))).scalars()
    outbox = (await session.execute(
        select(EmailOutbox.status, func.count()).where(
            EmailOutbox.tenant_id == ctx.tenant_id).group_by(EmailOutbox.status))).all()
    return {
        "connections": [{"id": str(c.id), "name": c.name, "type": c.connector_type,
                         "status": c.status, "consecutive_failures": c.consecutive_failures,
                         "last_error": c.last_error[:200]} for c in conns],
        "recent_failed_runs": [{"id": str(r.id), "connection_id": str(r.connection_id),
                                "error": r.error[:200],
                                "at": r.started_at.isoformat()} for r in failed_runs],
        "outbox": {status: count for status, count in outbox},
    }
