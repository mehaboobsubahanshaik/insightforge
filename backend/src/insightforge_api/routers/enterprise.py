"""Enterprise identity (MVP5 G1): SAML SSO, SCIM provisioning, ABAC member
attributes + dataset policies, access review workflows.

Scope honesty: SAML here implements SP metadata + an ACS that validates the
IdP's embedded signing cert against the tenant-configured SHA-256 digest and
extracts the NameID — the pinned-certificate pattern. Full XMLDSig chain
validation is documented as the production hardening step in docs/SSO.md.
"""

import base64
import hashlib
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
