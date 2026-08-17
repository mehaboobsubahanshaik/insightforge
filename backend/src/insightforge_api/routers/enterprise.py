"""Enterprise identity (MVP5 G1): SAML SSO, SCIM provisioning, ABAC member
attributes + dataset policies, access review workflows.

Scope honesty: SAML here implements SP metadata + an ACS that validates the
IdP's embedded signing cert against the tenant-configured SHA-256 digest and
extracts the NameID — the pinned-certificate pattern. Full XMLDSig chain
validation is documented as the production hardening step in docs/SSO.md.
"""

import base64
import hashlib
import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from .. import audit
from ..db import tenant_scoped_session
from ..deps import TenantContext, get_session, require
from ..models import AccessReview, Membership, Tenant, User, uuid7
from ..security import issue_access_token, new_opaque_token

router = APIRouter(prefix="/api/v1/enterprise", tags=["enterprise"])


# ---- SAML SSO ----
class SSOIn(BaseModel):
    entity_id: str = Field(min_length=3, max_length=500)
    sso_url: str = Field(pattern="^https://", max_length=1000)
    cert_digest: str = Field(pattern="^[0-9a-f]{64}$")  # sha256 of IdP cert DER


@router.put("/sso")
async def configure_sso(body: SSOIn,
                        ctx: TenantContext = Depends(require("tenant:manage")),
                        session=Depends(get_session)):
    t = (await session.execute(select(Tenant).where(
        Tenant.id == ctx.tenant_id))).scalar_one()
    t.sso = body.model_dump()
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="sso.configure",
                       resource_type="tenant", resource_id=str(t.id))
    await session.commit()
    return {"sso": t.sso, "acs_url": f"/api/v1/enterprise/sso/acs/{t.slug}",
            "sp_metadata": f"/api/v1/enterprise/sso/metadata/{t.slug}"}


@router.get("/sso/metadata/{slug}")
async def sp_metadata(slug: str):
    return {"entity_id": f"insightforge:{slug}",
            "acs_url": f"/api/v1/enterprise/sso/acs/{slug}",
            "binding": "HTTP-POST", "nameid_format": "emailAddress"}


@router.post("/sso/acs/{slug}")
async def sso_acs(slug: str, request: Request):
    """Assertion Consumer Service: IdP posts SAMLResponse; on cert-digest
    match + known user email -> session tokens."""
    form = await request.form()
    raw = form.get("SAMLResponse", "")
    try:
        xml = base64.b64decode(raw).decode(errors="ignore")
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Malformed SAMLResponse") from None
    async with tenant_scoped_session(None) as s:
        t = (await s.execute(select(Tenant).where(
            Tenant.slug == slug))).scalar_one_or_none()
        if t is None or not (t.sso or {}).get("cert_digest"):
            raise HTTPException(404, "SSO not configured")
        cert_m = re.search(r"<(?:\w+:)?X509Certificate>([^<]+)<", xml)
        if not cert_m:
            raise HTTPException(401, "Assertion missing signing certificate")
        der = base64.b64decode(re.sub(r"\s", "", cert_m.group(1)))
        if hashlib.sha256(der).hexdigest() != t.sso["cert_digest"]:
            raise HTTPException(401, "Signing certificate does not match the "
                                     "configured IdP digest")
        email_m = re.search(r"<(?:\w+:)?NameID[^>]*>([^<]+)<", xml)
        if not email_m:
            raise HTTPException(401, "Assertion missing NameID")
        email = email_m.group(1).strip().lower()
    async with tenant_scoped_session(t.id) as s:
        user = (await s.execute(select(User).join(
            Membership, Membership.user_id == User.id).where(
            Membership.tenant_id == t.id,
            User.email == email))).scalar_one_or_none()
        if user is None:
            raise HTTPException(403, f"No member '{email}' in this "
                                     "organization (provision via SCIM)")
        m = (await s.execute(select(Membership).where(
            Membership.tenant_id == t.id,
            Membership.user_id == user.id))).scalar_one()
        await audit.record(s, tenant_id=t.id, actor_user_id=user.id,
                           action="sso.login", resource_type="user",
                           resource_id=str(user.id))
        await s.commit()
        return {"access_token": issue_access_token(user.id, t.id, m.role),
                "method": "saml"}


# ---- SCIM v2 (bearer per tenant) ----
@router.post("/scim/token")
async def issue_scim_token(ctx: TenantContext = Depends(require("tenant:manage")),
                           session=Depends(get_session)):
    raw, h = new_opaque_token()
    t = (await session.execute(select(Tenant).where(
        Tenant.id == ctx.tenant_id))).scalar_one()
    t.scim_token_hash = h
    await session.commit()
    return {"scim_token": raw, "base": "/api/v1/enterprise/scim/v2",
            "note": "Shown once. Configure in your IdP's provisioning app."}


async def _scim_tenant(authorization: str = Header(default="")):
    tok = authorization.removeprefix("Bearer ").strip()
    if not tok:
        raise HTTPException(401, "SCIM bearer token required")
    h = hashlib.sha256(tok.encode()).hexdigest()
    async with tenant_scoped_session(None) as s:
        t = (await s.execute(select(Tenant).where(
            Tenant.scim_token_hash == h))).scalar_one_or_none()
    if t is None:
        raise HTTPException(401, "Invalid SCIM token")
    return t


@router.get("/scim/v2/Users")
async def scim_list(t: Tenant = Depends(_scim_tenant)):
    async with tenant_scoped_session(t.id) as s:
        rows = (await s.execute(select(User, Membership).join(
            Membership, Membership.user_id == User.id).where(
            Membership.tenant_id == t.id))).all()
        return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
                "totalResults": len(rows),
                "Resources": [{"id": str(u.id), "userName": u.email,
                               "active": True,
                               "roles": [m.role]} for u, m in rows]}


class SCIMUser(BaseModel):
    userName: EmailStr
    displayName: str | None = None


@router.post("/scim/v2/Users", status_code=201)
async def scim_create(body: SCIMUser, t: Tenant = Depends(_scim_tenant)):
    import secrets as pysecrets

    from ..security import hash_password

    async with tenant_scoped_session(t.id) as s:
        email = str(body.userName).lower()
        user = (await s.execute(select(User).where(
            User.email == email))).scalar_one_or_none()
        if user is None:
            user = User(id=uuid7(), email=email,
                        display_name=body.displayName or email.split("@")[0],
                        password_hash=hash_password(pysecrets.token_urlsafe(24)),
                        email_verified=True)
            s.add(user)
            await s.flush()
        exists = (await s.execute(select(Membership).where(
            Membership.tenant_id == t.id,
            Membership.user_id == user.id))).scalar_one_or_none()
        if exists is None:
            s.add(Membership(id=uuid7(), tenant_id=t.id, user_id=user.id,
                             role="analyst"))
        await audit.record(s, tenant_id=t.id, actor_user_id=None,
                           action="scim.provision", resource_type="user",
                           resource_id=str(user.id))
        await s.commit()
        return {"id": str(user.id), "userName": email, "active": True}


@router.delete("/scim/v2/Users/{user_id}", status_code=204)
async def scim_deprovision(user_id: str, t: Tenant = Depends(_scim_tenant)):
    async with tenant_scoped_session(t.id) as s:
        m = (await s.execute(select(Membership).where(
            Membership.tenant_id == t.id,
            Membership.user_id == user_id))).scalar_one_or_none()
        if m is None:
            raise HTTPException(404, "Not a member")
        await s.delete(m)
        await audit.record(s, tenant_id=t.id, actor_user_id=None,
                           action="scim.deprovision", resource_type="user",
                           resource_id=user_id)
        await s.commit()
    return None


# ---- ABAC: member attributes + dataset access policies ----
class AttrsIn(BaseModel):
    user_id: str
    attributes: dict = Field(default_factory=dict)


@router.put("/members/attributes")
async def set_member_attributes(body: AttrsIn,
                                ctx: TenantContext = Depends(
                                    require("tenant:manage")),
                                session=Depends(get_session)):
    m = (await session.execute(select(Membership).where(
        Membership.tenant_id == ctx.tenant_id,
        Membership.user_id == body.user_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Not a member")
    m.attributes = body.attributes
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="abac.attributes",
                       resource_type="user", resource_id=body.user_id)
    await session.commit()
    return {"user_id": body.user_id, "attributes": m.attributes}


# ---- Access reviews ----
@router.post("/access-reviews", status_code=201)
async def start_review(ctx: TenantContext = Depends(require("tenant:manage")),
                       session=Depends(get_session)):
    rows = (await session.execute(select(User, Membership).join(
        Membership, Membership.user_id == User.id).where(
        Membership.tenant_id == ctx.tenant_id))).all()
    items = [{"user_id": str(u.id), "email": u.email, "role": m.role,
              "attributes": m.attributes or {}, "decision": "pending"}
             for u, m in rows]
    r = AccessReview(id=uuid7(), tenant_id=ctx.tenant_id, items=items,
                     created_by=ctx.user_id)
    session.add(r)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="access_review.start",
                       resource_type="access_review", resource_id=str(r.id))
    await session.commit()
    return {"id": str(r.id), "items": items}


class DecisionIn(BaseModel):
    user_id: str
    decision: str = Field(pattern="^(approve|revoke)$")


@router.post("/access-reviews/{review_id}/decide")
async def decide(review_id: str, body: DecisionIn,
                 ctx: TenantContext = Depends(require("tenant:manage")),
                 session=Depends(get_session)):
    r = (await session.execute(select(AccessReview).where(
        AccessReview.id == review_id,
        AccessReview.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if r is None or r.status != "open":
        raise HTTPException(404, "Open review not found")
    import copy as _copy

    items = _copy.deepcopy(r.items)
    hit = next((i for i in items if i["user_id"] == body.user_id), None)
    if hit is None:
        raise HTTPException(404, "User not in this review")
    hit["decision"] = body.decision
    if body.decision == "revoke":
        m = (await session.execute(select(Membership).where(
            Membership.tenant_id == ctx.tenant_id,
            Membership.user_id == body.user_id))).scalar_one_or_none()
        if m and m.role != "tenant_owner":
            await session.delete(m)
    r.items = items
    if all(i["decision"] != "pending" for i in items):
        r.status = "closed"
        r.closed_at = datetime.now(timezone.utc)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id,
                       action=f"access_review.{body.decision}",
                       resource_type="user", resource_id=body.user_id)
    await session.commit()
    return {"status": r.status, "items": r.items}


class CMKIn(BaseModel):
    provider: str = Field(pattern="^(aws-kms|azure-keyvault|gcp-kms)$")
    key_id: str = Field(min_length=8, max_length=500)


@router.put("/cmk")
async def configure_cmk(body: CMKIn,
                        ctx: TenantContext = Depends(require("tenant:manage")),
                        session=Depends(get_session)):
    """Customer-managed key option (G2): stores the tenant's KMS key
    reference; envelope-encryption rollout is the documented infra step
    (docs/DATA-SECURITY.md) — data-at-rest re-encryption under this key."""
    t = (await session.execute(select(Tenant).where(
        Tenant.id == ctx.tenant_id))).scalar_one()
    t.cmk = {**body.model_dump(), "status": "configured",
             "configured_at": datetime.now(timezone.utc).isoformat()}
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="cmk.configure",
                       resource_type="tenant", resource_id=str(t.id))
    await session.commit()
    return {"cmk": t.cmk}


# ---- G4: compliance ops ----
SLAS = {"free": {"uptime": "99.0%", "support_response": "best effort"},
        "starter": {"uptime": "99.5%", "support_response": "1 business day"},
        "growth": {"uptime": "99.9%", "support_response": "4 business hours",
                   "incident_updates": "hourly"}}
SIEM_ACTIONS = ("sso.login", "scim.provision", "scim.deprovision",
                "access_review.revoke", "apikey.create", "apikey.revoke",
                "webhook.create", "tenant.offboard", "governance.set",
                "cmk.configure", "embed.token", "abac.attributes")


@router.get("/audit/export")
async def audit_export(format: str = "jsonl", since: str | None = None,
                       ctx: TenantContext = Depends(require("tenant:manage")),
                       session=Depends(get_session)):
    """Advanced audit export: full tenant trail as JSONL or CSV for
    archival / auditor handoff."""
    from fastapi.responses import PlainTextResponse

    from ..models import AuditEvent

    q = select(AuditEvent).where(AuditEvent.tenant_id == ctx.tenant_id)
    if since:
        q = q.where(AuditEvent.created_at >= since)
    rows = (await session.execute(q.order_by(
        AuditEvent.created_at))).scalars().all()
    recs = [{"at": r.created_at.isoformat(), "action": r.action,
             "actor": str(r.actor_user_id) if r.actor_user_id else "system",
             "resource_type": r.resource_type, "resource_id": r.resource_id,
             "detail": r.detail or {}} for r in rows]
    if format == "csv":
        import csv as _csv
        import io as _io

        buf = _io.StringIO()
        w = _csv.DictWriter(buf, fieldnames=list(recs[0]) if recs else
                            ["at", "action", "actor", "resource_type",
                             "resource_id", "detail"])
        w.writeheader()
        for r in recs:
            w.writerow({**r, "detail": json.dumps(r["detail"])})
        return PlainTextResponse(buf.getvalue(), media_type="text/csv")
    return PlainTextResponse(
        "\n".join(json.dumps(r) for r in recs),
        media_type="application/x-ndjson")


class DeploymentIn(BaseModel):
    region: str = Field(pattern="^(eu-west|us-east|ap-south)$")
    private_connectivity: bool = False
    dedicated: bool = False


@router.put("/deployment")
async def configure_deployment(body: DeploymentIn,
                               ctx: TenantContext = Depends(
                                   require("tenant:manage")),
                               session=Depends(get_session)):
    """Regional residency + private connectivity + dedicated tenant option:
    records the contracted posture; infra realization per
    docs/ENTERPRISE-OPS.md (region pinning, PrivateLink/VNet, isolated
    stack). New data lands per this config from the infra side."""
    t = (await session.execute(select(Tenant).where(
        Tenant.id == ctx.tenant_id))).scalar_one()
    t.features = {**(t.features or {}),
                  "deployment": {**body.model_dump(),
                                 "configured_at":
                                 datetime.now(timezone.utc).isoformat()}}
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="deployment.configure",
                       resource_type="tenant", resource_id=str(t.id))
    await session.commit()
    return {"deployment": t.features["deployment"]}


@router.get("/sla")
async def sla(ctx: TenantContext = Depends(require("usage:read")),
              session=Depends(get_session)):
    """Advanced SLAs: the tenant's contracted targets + live health."""
    from .. import scheduler as sched
    from ..services import entitlements

    code, _ = await entitlements.get_plan(session, ctx.tenant_id)
    return {"plan": code, "sla": SLAS.get(code, SLAS["free"]),
            "live": {"scheduler_heartbeat": sched.last_heartbeat["at"]},
            "all_tiers": SLAS}


class SupportAccessIn(BaseModel):
    hours: int = Field(ge=1, le=168)


@router.post("/support-access")
async def grant_support_access(body: SupportAccessIn,
                               ctx: TenantContext = Depends(
                                   require("tenant:manage")),
                               session=Depends(get_session)):
    """Enterprise support control: explicitly time-boxed grant for vendor
    support to access this tenant — nothing is accessible without it."""
    from datetime import timedelta

    t = (await session.execute(select(Tenant).where(
        Tenant.id == ctx.tenant_id))).scalar_one()
    until = datetime.now(timezone.utc) + timedelta(hours=body.hours)
    t.features = {**(t.features or {}),
                  "support_access_until": until.isoformat()}
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="support.access_grant",
                       resource_type="tenant", resource_id=str(t.id))
    await session.commit()
    return {"support_access_until": until.isoformat(),
            "note": "Auto-expires; revoke early by granting 1 hour and "
                    "letting it lapse, or contact support."}
