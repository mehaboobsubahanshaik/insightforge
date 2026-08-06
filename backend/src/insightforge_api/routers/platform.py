"""Platform operator console (cross-tenant). NOT part of the tenant product:
guarded by a platform secret header, intended for InsightForge staff. Uses
the superuser-capable app session but only ever returns statuses and counts
— never row data or credentials."""

import os

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import func, select

from ..db import session_factory
from ..models import Connection, Dashboard, Dataset, Membership, SyncRun, Tenant

router = APIRouter(prefix="/api/v1/platform", tags=["platform-ops"])


def _check(secret: str | None):
    expected = os.environ.get("PLATFORM_ADMIN_SECRET", "platform-dev-secret")
    if not secret or secret != expected:
        raise HTTPException(401, "Platform secret required")


@router.get("/tenants")
async def list_tenants(x_platform_secret: str | None = Header(default=None)):
    _check(x_platform_secret)
    async with session_factory()() as s:
        tenants = (await s.execute(select(Tenant).order_by(Tenant.created_at))).scalars().all()

        async def count(model, cond):
            return (await s.execute(
                select(func.count()).select_from(model).where(cond))).scalar_one()

        out = []
        for t in tenants:
            out.append({
                "id": str(t.id), "slug": t.slug, "name": t.name, "status": t.status,
                "plan_code": t.plan_code, "created_at": t.created_at.isoformat(),
                "members": await count(Membership, Membership.tenant_id == t.id),
                "datasets": await count(Dataset, (Dataset.tenant_id == t.id)
                                        & Dataset.archived.is_(False)),
                "dashboards": await count(Dashboard, (Dashboard.tenant_id == t.id)
                                          & Dashboard.archived.is_(False)),
                "connections": await count(Connection, Connection.tenant_id == t.id),
                "failed_runs": await count(SyncRun, (SyncRun.tenant_id == t.id)
                                           & (SyncRun.status == "failed")),
            })
        return out


@router.post("/tenants/{tenant_id}/status")
async def set_tenant_status(tenant_id: str, body: dict,
                            x_platform_secret: str | None = Header(default=None)):
    _check(x_platform_secret)
    status = body.get("status")
    if status not in ("active", "suspended"):
        raise HTTPException(422, "status must be active or suspended")
    import uuid

    try:
        tid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(422, "tenant_id must be a UUID") from None
    async with session_factory()() as s:
        async with s.begin():
            tenant = (await s.execute(
                select(Tenant).where(Tenant.id == tid))).scalar_one_or_none()
            if tenant is None:
                raise HTTPException(404, "Tenant not found")
            tenant.status = status
            from .. import audit

            await audit.record(s, tenant_id=tid, actor_user_id=None,
                               action=f"tenant.{status}", resource_type="tenant",
                               resource_id=str(tid), detail={"by": "platform-operator"})
    return {"id": tenant_id, "status": status}
