"""Workspace administration."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import audit
from ..deps import TenantContext, get_session, require
from ..models import Workspace
from .auth import _uuid_or_422

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


@router.get("")
async def list_workspaces(ctx: TenantContext = Depends(require("dataset:read")),
                          session=Depends(get_session)):
    rows = (await session.execute(select(Workspace).where(
        Workspace.tenant_id == ctx.tenant_id, Workspace.archived.is_(False))
        .order_by(Workspace.created_at))).scalars()
    return [{"id": str(w.id), "name": w.name} for w in rows]


@router.post("", status_code=201)
async def create_workspace(body: WorkspaceIn,
                           ctx: TenantContext = Depends(require("workspace:manage")),
                           session=Depends(get_session)):
    ws = Workspace(tenant_id=ctx.tenant_id, name=body.name, created_by=ctx.user_id)
    session.add(ws)
    await session.flush()
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="workspace.created", resource_type="workspace",
                       resource_id=str(ws.id))
    await session.commit()
    return {"id": str(ws.id), "name": ws.name}


@router.patch("/{workspace_id}")
async def rename_or_archive(workspace_id: str, body: dict,
                            ctx: TenantContext = Depends(require("workspace:manage")),
                            session=Depends(get_session)):
    wid = _uuid_or_422(workspace_id, "workspace_id")
    ws = (await session.execute(select(Workspace).where(
        Workspace.id == wid, Workspace.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    if "name" in body:
        ws.name = str(body["name"])[:255]
    if body.get("archived") is True:
        ws.archived = True
    await session.commit()
    return {"id": str(ws.id), "name": ws.name, "archived": ws.archived}
