"""Tenant administration: members, invitations, roles, activity feed,
notifications, billing & usage, plan changes, diagnostics."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
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
    Invoice,
    Membership,
    Plan,
    SyncRun,
    Tenant,
    User,
    uuid7,
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


@router.post("/billing/trial")
async def start_trial(ctx: TenantContext = Depends(require("tenant:manage")),
                      session=Depends(get_session)):
    """14-day Growth trial — once per tenant. Converting = choosing a plan
    (POST /billing/plan) any time; unconverted trials fall back to free."""
    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == ctx.tenant_id))).scalar_one()
    if (tenant.features or {}).get("trial_used"):
        raise HTTPException(409, "The trial has already been used for this "
                                 "organization.")
    tenant.features = {**(tenant.features or {}), "trial_used": True}
    tenant.plan_code = "growth"
    tenant.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=14)
    await entitlements.record_billing_event(session, ctx.tenant_id,
                                            "trial.started")
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="billing.trial",
                       resource_type="tenant", resource_id=str(tenant.id))
    await session.commit()
    return {"plan": "growth", "trial_ends_at": tenant.trial_ends_at.isoformat(),
            "note": "Growth features unlocked for 14 days. Pick a plan before "
                    "it ends to keep them — otherwise the organization "
                    "returns to free automatically (nothing is deleted)."}


@router.get("/billing/invoices")
async def list_invoices(ctx: TenantContext = Depends(require("tenant:manage")),
                        session=Depends(get_session)):
    rows = (await session.execute(select(Invoice).where(
        Invoice.tenant_id == ctx.tenant_id).order_by(
        Invoice.period_start.desc()))).scalars().all()
    return {"invoices": [{
        "id": str(i.id), "period_start": str(i.period_start),
        "period_end": str(i.period_end), "plan": i.plan_code,
        "amount_usd": float(i.amount_usd), "line_items": i.line_items,
        "status": i.status, "issued_at": i.issued_at.isoformat()}
        for i in rows]}


@router.post("/billing/invoices/generate", status_code=201)
async def generate_invoice(ctx: TenantContext = Depends(require("tenant:manage")),
                           session=Depends(get_session)):
    """Issue an invoice for the current month to date: plan base price plus
    an informational usage summary from the metered billing events."""
    from sqlalchemy import func

    from ..models import BillingEvent

    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == ctx.tenant_id))).scalar_one()
    plan = (await session.execute(
        select(Plan).where(Plan.code == tenant.plan_code))).scalar_one()
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage = (await session.execute(
        select(BillingEvent.kind, func.count()).where(
            BillingEvent.tenant_id == ctx.tenant_id,
            BillingEvent.created_at >= start).group_by(
            BillingEvent.kind))).all()
    items = [{"item": f"{plan.name} plan (monthly)",
              "amount_usd": float(plan.monthly_price_usd)}]
    items += [{"item": f"usage: {k}", "count": c, "amount_usd": 0.0}
              for k, c in usage]
    inv = Invoice(id=uuid7(), tenant_id=ctx.tenant_id,
                  period_start=start.replace(tzinfo=None),
                  period_end=now.replace(tzinfo=None),
                  plan_code=plan.code,
                  amount_usd=float(plan.monthly_price_usd), line_items=items)
    session.add(inv)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="billing.invoice",
                       resource_type="invoice", resource_id=str(inv.id))
    await session.commit()
    return {"id": str(inv.id), "amount_usd": float(inv.amount_usd),
            "line_items": items}


class OffboardIn(BaseModel):
    confirm_slug: str


@router.post("/tenants/offboard")
async def offboard(body: OffboardIn,
                   ctx: TenantContext = Depends(require("tenant:manage")),
                   session=Depends(get_session)):
    """Offboarding: 30-day grace, then the scheduler purges tenant data.
    Reversible until the purge runs (POST /offboard/cancel)."""
    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == ctx.tenant_id))).scalar_one()
    if body.confirm_slug != tenant.slug:
        raise HTTPException(422, f"Type the organization slug "
                                 f"('{tenant.slug}') to confirm offboarding.")
    tenant.status = "offboarding"
    tenant.deletion_due_at = datetime.now(timezone.utc) + timedelta(days=30)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="tenant.offboard",
                       resource_type="tenant", resource_id=str(tenant.id))
    await session.commit()
    return {"status": "offboarding",
            "deletion_due_at": tenant.deletion_due_at.isoformat(),
            "note": "Data will be purged after the grace period. Export "
                    "datasets via each dataset's Export CSV until then; "
                    "cancel any time before the purge."}


@router.post("/tenants/offboard/cancel")
async def cancel_offboard(ctx: TenantContext = Depends(require("tenant:manage")),
                          session=Depends(get_session)):
    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == ctx.tenant_id))).scalar_one()
    tenant.status = "active"
    tenant.deletion_due_at = None
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id,
                       action="tenant.offboard_cancel",
                       resource_type="tenant", resource_id=str(tenant.id))
    await session.commit()
    return {"status": "active", "note": "Offboarding cancelled."}


class SupportIn(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    message: str = Field(min_length=3, max_length=5000)


@router.post("/support", status_code=201)
async def support_request(body: SupportIn,
                          ctx: TenantContext = Depends(require("dataset:read")),
                          session=Depends(get_session)):
    """Support workflow entry point (docs/SUPPORT.md): recorded, audited,
    routed to the support inbox."""
    import os as _os

    to = _os.environ.get("SUPPORT_EMAIL", "support@insightforge.dev")
    await mailer.send(session, tenant_id=ctx.tenant_id, to_email=to,
                      kind="support", subject=f"[support] {body.subject}",
                      body=f"tenant={ctx.tenant_id} user={ctx.user_id}\n\n"
                           + body.message)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="support.request",
                       resource_type="support", resource_id=str(ctx.user_id))
    await session.commit()
    return {"received": True, "note": "Logged and routed to support — "
            "acknowledgement within one business day (docs/SUPPORT.md)."}


class PrivacyIn(BaseModel):
    kind: str = Field(pattern="^(export|delete)$")
    details: str | None = Field(default=None, max_length=2000)


@router.post("/privacy-request", status_code=201)
async def privacy_request(body: PrivacyIn,
                          ctx: TenantContext = Depends(require("dataset:read")),
                          session=Depends(get_session)):
    """Individual privacy requests (export/delete my data), audited and
    routed per docs/PRIVACY.md. Org-level deletion is self-serve via
    offboarding."""
    import os as _os

    to = _os.environ.get("SUPPORT_EMAIL", "support@insightforge.dev")
    await mailer.send(session, tenant_id=ctx.tenant_id, to_email=to,
                      kind="privacy", subject=f"[privacy] {body.kind} request",
                      body=f"tenant={ctx.tenant_id} user={ctx.user_id}\n"
                           f"kind={body.kind}\n{body.details or ''}")
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id,
                       action=f"privacy.{body.kind}",
                       resource_type="privacy", resource_id=str(ctx.user_id))
    await session.commit()
    return {"received": True, "kind": body.kind,
            "note": "Recorded; fulfilment per docs/PRIVACY.md (30-day SLA)."}


class ThemeIn(BaseModel):
    brand_name: str | None = Field(default=None, max_length=80)
    accent: str | None = Field(default=None, pattern="^#[0-9a-fA-F]{6}$")
    background: str | None = Field(default=None, pattern="^#[0-9a-fA-F]{6}$")
    foreground: str | None = Field(default=None, pattern="^#[0-9a-fA-F]{6}$")
    locale: str | None = Field(default=None, pattern="^(en|es|fr|de|hi)$")
    white_label: bool | None = None  # hides "Powered by InsightForge"


@router.patch("/tenants/theme")
async def set_theme(body: ThemeIn,
                    ctx: TenantContext = Depends(require("tenant:manage")),
                    session=Depends(get_session)):
    """White-label theme (MVP4 E3): applied to every embed of this tenant."""
    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == ctx.tenant_id))).scalar_one()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    tenant.theme = {**(tenant.theme or {}), **updates}
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="tenant.theme",
                       resource_type="tenant", resource_id=str(tenant.id))
    await session.commit()
    return {"theme": tenant.theme}


class DomainIn(BaseModel):
    domain: str = Field(pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?"
                                r"(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$",
                        max_length=255)


@router.post("/tenants/custom-domain")
async def set_custom_domain(body: DomainIn,
                            ctx: TenantContext = Depends(require("tenant:manage")),
                            session=Depends(get_session)):
    """Custom domain (MVP4 E3): stored + uniqueness-enforced; DNS/TLS steps
    in docs/WHITE-LABEL.md (CNAME -> platform, cert via proxy)."""
    from sqlalchemy.exc import IntegrityError

    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == ctx.tenant_id))).scalar_one()
    tenant.custom_domain = body.domain
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(409, "Domain already claimed by another "
                                 "organization") from None
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="tenant.domain",
                       resource_type="tenant", resource_id=str(tenant.id))
    await session.commit()
    return {"custom_domain": tenant.custom_domain,
            "next_steps": "Point a CNAME at the platform host; embeds and "
                          "portals will serve under it (docs/WHITE-LABEL.md)."}
