"""Partner administration (MVP4 E4): OEM hierarchy, reusable tenant
templates, self-serve child-tenant onboarding.

A partner (any tenant) can create CHILD tenants — full, isolated tenants
whose parent_tenant_id points back. The partner administers lifecycle
(create from template, list with usage, suspend) but can NEVER read child
data: children are ordinary tenants behind their own RLS wall. Onboarding
needs zero platform engineering: create -> owner invite email -> done.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from .. import audit
from ..db import tenant_scoped_session
from ..deps import TenantContext, get_session, require
from ..models import (
    AuditEvent,
    Invitation,
    Tenant,
    TenantTemplate,
    Workspace,
    uuid7,
)
from ..security import new_opaque_token
from ..services import mailer

router = APIRouter(prefix="/api/v1/partner", tags=["partner"])


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    plan_code: str = Field(default="free", pattern="^(free|starter|growth)$")
    theme: dict = Field(default_factory=dict)
    workspaces: list[str] = Field(default_factory=lambda: ["General"])


@router.post("/templates", status_code=201)
async def create_template(body: TemplateIn,
                          ctx: TenantContext = Depends(require("tenant:manage")),
                          session=Depends(get_session)):
    t = TenantTemplate(id=uuid7(), tenant_id=ctx.tenant_id, name=body.name,
                       config=body.model_dump())
    session.add(t)
    await session.commit()
    return {"id": str(t.id), "name": t.name, "config": t.config}


@router.get("/templates")
async def list_templates(ctx: TenantContext = Depends(require("tenant:manage")),
                         session=Depends(get_session)):
    rows = (await session.execute(select(TenantTemplate).where(
        TenantTemplate.tenant_id == ctx.tenant_id))).scalars().all()
    return {"templates": [{"id": str(t.id), "name": t.name,
                           "config": t.config} for t in rows]}


class ChildIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=2, max_length=40,
                      pattern="^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    owner_email: EmailStr
    template_id: str | None = None


@router.post("/tenants", status_code=201)
async def create_child_tenant(body: ChildIn,
                              ctx: TenantContext = Depends(
                                  require("tenant:manage")),
                              session=Depends(get_session)):
    """Self-serve partner onboarding: child tenant + workspaces + themed
    plan from template + owner invitation email — no platform staff."""
    exists = (await session.execute(select(Tenant).where(
        Tenant.slug == body.slug))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "Slug already taken")
    cfg = {"plan_code": "free", "theme": {}, "workspaces": ["General"]}
    if body.template_id:
        tpl = (await session.execute(select(TenantTemplate).where(
            TenantTemplate.id == body.template_id,
            TenantTemplate.tenant_id == ctx.tenant_id))).scalar_one_or_none()
        if tpl is None:
            raise HTTPException(404, "Template not found")
        cfg = {**cfg, **tpl.config}
    child = Tenant(id=uuid7(), slug=body.slug, name=body.name,
                   plan_code=cfg["plan_code"], theme=cfg.get("theme") or {},
                   parent_tenant_id=ctx.tenant_id, status="active")
    session.add(child)
    await session.commit()  # child must exist before its RLS-scoped inserts
    async with tenant_scoped_session(child.id) as cs:
        for ws_name in cfg.get("workspaces") or ["General"]:
            cs.add(Workspace(id=uuid7(), tenant_id=child.id, name=ws_name,
                             created_by=ctx.user_id))
        raw, thash = new_opaque_token()
        cs.add(Invitation(id=uuid7(), tenant_id=child.id,
                          email=str(body.owner_email).lower(),
                          role="tenant_owner", token_hash=thash,
                          expires_at=datetime.now(timezone.utc)
                          + timedelta(days=7), created_by=ctx.user_id))
        await mailer.send(cs, tenant_id=child.id,
                          to_email=str(body.owner_email), kind="invite",
                          subject=f"You've been invited to {body.name}",
                          body=f"Your analytics workspace '{body.name}' is "
                               f"ready. Accept with token: {raw} "
                               f"(org slug: {body.slug}, expires in 7 days).")
        await cs.commit()
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="partner.child_create",
                       resource_type="tenant", resource_id=str(child.id))
    await session.commit()
    return {"id": str(child.id), "slug": child.slug, "plan": child.plan_code,
            "invited": str(body.owner_email),
            "note": "Child is a fully isolated tenant — you administer its "
                    "lifecycle but can never read its data."}


@router.get("/tenants")
async def list_children(ctx: TenantContext = Depends(require("tenant:manage")),
                        session=Depends(get_session)):
    """Partner console data: children + today's embed usage (metered)."""
    kids = (await session.execute(select(Tenant).where(
        Tenant.parent_tenant_id == ctx.tenant_id))).scalars().all()
    out = []
    for k in kids:
        views = (await session.execute(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.tenant_id == k.id,
                AuditEvent.action == "embed.view",
                AuditEvent.created_at >= func.date_trunc("day", func.now()))
        )).scalar_one()
        out.append({"id": str(k.id), "slug": k.slug, "name": k.name,
                    "plan": k.plan_code, "status": k.status,
                    "embed_views_today": views})
    return {"children": out}
