"""Embedded analytics core (MVP4 E1): signed embed tokens + customer-aware
row filtering + embed audit.

Security model:
- Tokens are HMAC-SHA256-signed JWTs using a per-tenant embed secret; the
  vendor mints them SERVER-SIDE for each end-customer session.
- Customer awareness: the token carries mandatory filters (e.g.
  customer_id = 42) which are appended to EVERY widget query — the embedded
  viewer cannot see, remove, or widen them. No filters, no data.
- Only PUBLISHED dashboards can be embedded; every view is audited as
  embed.view with the customer label.
"""

import base64
import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import audit
from ..db import tenant_scoped_session
from ..deps import TenantContext, get_session, require
from ..models import Dashboard, DashboardVersion, Tenant
from .dashboards import _hydrate

router = APIRouter(prefix="/api/v1/embed", tags=["embed"])


def _b64(d: bytes) -> str:
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(secret: str, payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(),
                        hashlib.sha256).digest())
    return f"{body}.{sig}"


def _verify(secret: str, token: str) -> dict:
    try:
        body, sig = token.split(".")
        expect = _b64(hmac.new(secret.encode(), body.encode(),
                               hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            raise ValueError("bad signature")
        payload = json.loads(_unb64(body))
        if payload["exp"] < time.time():
            raise ValueError("expired")
        return payload
    except ValueError as e:
        raise HTTPException(401, f"Invalid embed token: {e}") from None
    except Exception:  # noqa: BLE001
        raise HTTPException(401, "Invalid embed token") from None


class TokenIn(BaseModel):
    dashboard_id: str
    customer_label: str = Field(min_length=1, max_length=120)
    filters: list[dict] = Field(min_length=1)  # customer awareness is mandatory
    expires_minutes: int = Field(default=60, ge=1, le=1440)


@router.post("/tokens", status_code=201)
async def mint_token(body: TokenIn,
                     ctx: TenantContext = Depends(require("dashboard:read")),
                     session=Depends(get_session)):
    import secrets as pysecrets

    d = (await session.execute(select(Dashboard).where(
        Dashboard.id == body.dashboard_id,
        Dashboard.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if d is None:
        raise HTTPException(404, "Dashboard not found")
    if not d.published_version:
        raise HTTPException(422, "Publish the dashboard before embedding")
    for f in body.filters:
        if not {"column", "op", "value"} <= set(f):
            raise HTTPException(422, "Each filter needs column/op/value")
    tenant = (await session.execute(select(Tenant).where(
        Tenant.id == ctx.tenant_id))).scalar_one()
    if not tenant.embed_secret:
        tenant.embed_secret = pysecrets.token_hex(24)
    payload = {"t": str(ctx.tenant_id), "d": str(d.id),
               "c": body.customer_label, "f": body.filters,
               "exp": int(time.time()) + body.expires_minutes * 60}
    token = _sign(tenant.embed_secret, payload)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="embed.token",
                       resource_type="dashboard", resource_id=str(d.id))
    await session.commit()
    return {"token": token, "expires_in": body.expires_minutes * 60,
            "note": "Mint tokens server-side per end-customer session; the "
                    "filters travel inside the signature and cannot be "
                    "altered by the viewer."}


@router.get("/{token}/data")
async def embed_data(token: str):
    """Public: no session auth — the signed token IS the authorization."""
    try:
        tenant_id = json.loads(_unb64(token.split(".")[0]))["t"]
    except Exception:  # noqa: BLE001
        raise HTTPException(401, "Invalid embed token") from None
    async with tenant_scoped_session(tenant_id) as s:
        tenant = (await s.execute(select(Tenant).where(
            Tenant.id == tenant_id))).scalar_one_or_none()
        if tenant is None or not tenant.embed_secret:
            raise HTTPException(401, "Invalid embed token")
        payload = _verify(tenant.embed_secret, token)
        d = (await s.execute(select(Dashboard).where(
            Dashboard.id == payload["d"],
            Dashboard.tenant_id == tenant.id))).scalar_one_or_none()
        if d is None or not d.published_version:
            raise HTTPException(404, "Dashboard not available")
        ver = (await s.execute(select(DashboardVersion).where(
            DashboardVersion.dashboard_id == d.id,
            DashboardVersion.version == d.published_version))).scalar_one()
        hydrated = await _hydrate(s, tenant.id, ver.widgets, payload["f"])
        hydrated["name"] = d.name
        hydrated["customer"] = payload["c"]
        hydrated["theme"] = tenant.theme or {}
        from sqlalchemy import func as _f

        from ..models import AuditEvent
        from ..services import entitlements as _ent

        _, limits = await _ent.get_plan(s, tenant.id)
        limit = (limits or {}).get("embed_views_per_day")
        if limit:
            today = (await s.execute(
                select(_f.count()).select_from(AuditEvent).where(
                    AuditEvent.tenant_id == tenant.id,
                    AuditEvent.action == "embed.view",
                    AuditEvent.created_at >= _f.date_trunc(
                        "day", _f.now())))).scalar_one()
            if today >= limit:
                raise HTTPException(
                    429, f"Daily embed view limit reached ({limit} on this "
                         "plan). Resets at midnight UTC; upgrading raises it.")
        await _ent.record_billing_event(s, tenant.id, "embed.view")
        await audit.record(s, tenant_id=tenant.id, actor_user_id=None,
                           action="embed.view", resource_type="dashboard",
                           resource_id=str(d.id),
                           detail={"customer": payload["c"]})
        await s.commit()
        return hydrated


@router.get("/{token}/query")
async def embed_query(token: str, formula: str, group_by: str | None = None):
    """Headless analytics (MVP4 E2): one governed query under the token's
    mandatory customer filters — data without the viewer, for vendors
    rendering their own charts. Same rules: signed token is the auth, the
    filters cannot be escaped, formulas never SQL."""
    from ..models import Dataset
    from ..services import querysvc

    try:
        tenant_id = json.loads(_unb64(token.split(".")[0]))["t"]
    except Exception:  # noqa: BLE001
        raise HTTPException(401, "Invalid embed token") from None
    async with tenant_scoped_session(tenant_id) as s:
        tenant = (await s.execute(select(Tenant).where(
            Tenant.id == tenant_id))).scalar_one_or_none()
        if tenant is None or not tenant.embed_secret:
            raise HTTPException(401, "Invalid embed token")
        payload = _verify(tenant.embed_secret, token)
        d = (await s.execute(select(Dashboard).where(
            Dashboard.id == payload["d"],
            Dashboard.tenant_id == tenant.id))).scalar_one_or_none()
        if d is None or not d.published_version:
            raise HTTPException(404, "Dashboard not available")
        ver = (await s.execute(select(DashboardVersion).where(
            DashboardVersion.dashboard_id == d.id,
            DashboardVersion.version == d.published_version))).scalar_one()
        ds_ids = {w["dataset_id"] for w in ver.widgets}
        results = []
        for ds_id in ds_ids:
            ds = (await s.execute(select(Dataset).where(
                Dataset.id == ds_id))).scalar_one_or_none()
            if ds is None:
                continue
            try:
                r = await querysvc.execute_formula(
                    s, dataset_id=ds.id, current_import_id=ds.current_import_id,
                    dataset_schema=ds.schema_def, formula=formula,
                    group_by=group_by, filters=payload["f"])
                results.append({"dataset": ds.name, **r})
            except querysvc.QueryError:
                continue
        if not results:
            raise HTTPException(422, "Formula not computable on this "
                                     "dashboard's datasets")
        await audit.record(s, tenant_id=tenant.id, actor_user_id=None,
                           action="embed.query", resource_type="dashboard",
                           resource_id=str(d.id),
                           detail={"customer": payload["c"]})
        await s.commit()
        return {"customer": payload["c"], "results": results}
