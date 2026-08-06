"""Connector lifecycle: create (allow-listed config, vaulted credentials,
live connection test), manual sync, schedules with plan floor, health, runs."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from .. import audit
from ..deps import TenantContext, get_session, require
from ..models import Connection, Dataset, SyncRun, SyncSchedule, Workspace
from ..services import entitlements, syncsvc
from ..services.connectors import ALLOWED_CONFIG_KEYS, CATALOG, REGISTRY
from ..services.vault import encrypt_credentials
from .auth import _uuid_or_422

router = APIRouter(prefix="/api/v1/connections", tags=["connections"])


class ConnectionIn(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=255)
    connector_type: str
    config: dict = {}
    credentials: dict = {}


_DOCKER_HINT = (
    " — nothing is listening at that host/port from where the API runs. "
    "If InsightForge runs in Docker, 127.0.0.1/localhost points at the API "
    "container itself: use host 'postgres' for the bundled database, "
    "'host.docker.internal' for a database on your machine, or your cloud "
    "provider's hostname (with SSL). If running locally, check the database "
    "is started and the port is right (pg_isready / mysqladmin ping)."
)


def _friendly_conn_error(e: Exception) -> str:
    msg = str(e)[:300]
    text = f"Connection test failed: {msg}"
    if "Connection refused" in msg or "Errno 111" in msg or "10061" in msg:
        text += _DOCKER_HINT
    return text


def _connection_out(c: Connection, schedule: SyncSchedule | None = None) -> dict:
    health = "healthy"
    if c.consecutive_failures >= 3:
        health = "failing"
    elif c.consecutive_failures > 0:
        health = "degraded"
    from ..services.connectors import BY_TYPE

    meta = BY_TYPE.get(c.connector_type, {})
    return {"id": str(c.id), "workspace_id": str(c.workspace_id), "name": c.name,
            "connector_type": c.connector_type, "label": meta.get("label", c.connector_type),
            "color": meta.get("color", "#64748B"), "glyph": meta.get("glyph", "??"),
            "config": c.config, "status": c.status,
            "health": health, "sync_cursor": c.sync_cursor,
            "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
            "consecutive_failures": c.consecutive_failures,
            "last_error": c.last_error[:300],
            "schedule": ({"interval_minutes": schedule.interval_minutes,
                          "enabled": schedule.enabled,
                          "next_run_at": schedule.next_run_at.isoformat()}
                         if schedule else None)}


@router.get("/types")
async def connector_types(ctx: TenantContext = Depends(require("connection:read"))):
    """The data-source gallery: every live platform tile with its engine,
    category, brand-free color/glyph, and allowed config keys."""
    return [{**c, "config_keys": sorted(ALLOWED_CONFIG_KEYS[c["type"]]),
             "supports_sandbox_demo": "sandbox_demo" in ALLOWED_CONFIG_KEYS[c["type"]]}
            for c in CATALOG]


@router.get("")
async def list_connections(ctx: TenantContext = Depends(require("connection:read")),
                           session=Depends(get_session)):
    rows = (await session.execute(
        select(Connection, SyncSchedule)
        .join(SyncSchedule, SyncSchedule.connection_id == Connection.id, isouter=True)
        .where(Connection.tenant_id == ctx.tenant_id)
        .order_by(Connection.created_at))).all()
    return [_connection_out(c, s) for c, s in rows]


@router.post("", status_code=201)
async def create_connection(body: ConnectionIn,
                            ctx: TenantContext = Depends(require("connection:manage")),
                            session=Depends(get_session)):
    if body.connector_type not in REGISTRY:
        raise HTTPException(422, f"Unknown connector type; available: {', '.join(REGISTRY)}")
    wid = _uuid_or_422(body.workspace_id, "workspace_id")
    ws = (await session.execute(select(Workspace).where(
        Workspace.id == wid, Workspace.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    allowed = ALLOWED_CONFIG_KEYS[body.connector_type]
    unknown = set(body.config) - allowed
    if unknown:
        raise HTTPException(422, f"Unknown config keys: {', '.join(sorted(unknown))}; "
                                 f"allowed: {', '.join(sorted(allowed))}")
    await entitlements.enforce_quota(session, ctx.tenant_id, "connections", Connection,
                                     Connection.tenant_id == ctx.tenant_id)
    try:
        await REGISTRY[body.connector_type].test_connection(body.config, body.credentials)
    except Exception as e:
        raise HTTPException(422, _friendly_conn_error(e)) from None
    conn = Connection(tenant_id=ctx.tenant_id, workspace_id=wid, name=body.name,
                      connector_type=body.connector_type, config=body.config,
                      credentials_enc=encrypt_credentials(body.credentials),
                      created_by=ctx.user_id)
    session.add(conn)
    await session.flush()
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="connection.created", resource_type="connection",
                       resource_id=str(conn.id), detail={"type": body.connector_type},
                       correlation_id=ctx.correlation_id)
    await session.commit()
    return _connection_out(conn)


async def _connection_or_404(session, ctx, connection_id) -> Connection:
    cid = _uuid_or_422(connection_id, "connection_id")
    conn = (await session.execute(select(Connection).where(
        Connection.id == cid,
        Connection.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if conn is None:
        raise HTTPException(404, "Connection not found")
    return conn


@router.post("/{connection_id}/test")
async def test_existing(connection_id: str,
                        ctx: TenantContext = Depends(require("connection:manage")),
                        session=Depends(get_session)):
    from ..services.vault import decrypt_credentials

    conn = await _connection_or_404(session, ctx, connection_id)
    try:
        await REGISTRY[conn.connector_type].test_connection(
            conn.config, decrypt_credentials(conn.credentials_enc))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(422, _friendly_conn_error(e)) from None


class SyncIn(BaseModel):
    mode: str = "incremental"


@router.post("/{connection_id}/sync")
async def sync_now(connection_id: str, body: SyncIn,
                   ctx: TenantContext = Depends(require("connection:manage")),
                   session=Depends(get_session)):
    if body.mode not in ("incremental", "full_refresh"):
        raise HTTPException(422, "mode must be incremental or full_refresh")
    conn = await _connection_or_404(session, ctx, connection_id)
    try:
        run = await syncsvc.run_sync(session, conn, actor_user_id=ctx.user_id,
                                     mode=body.mode, trigger="manual")
    except Exception as e:
        conn.consecutive_failures += 1
        conn.last_error = str(e)[:1000]
        await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                           action="sync.failed", resource_type="connection",
                           resource_id=str(conn.id))
        raise HTTPException(502, f"Sync failed: {str(e)[:300]}") from None
    if run.status == "failed":
        conn.consecutive_failures += 1
        conn.last_error = run.error
        return {"run_id": str(run.id), "status": run.status, "error": run.error}
    conn.consecutive_failures = 0
    conn.last_error = ""
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="sync.completed", resource_type="connection",
                       resource_id=str(conn.id),
                       detail={"status": run.status, "rows_loaded": run.rows_loaded})
    return {"run_id": str(run.id), "status": run.status,
            "rows_extracted": run.rows_extracted, "rows_loaded": run.rows_loaded,
            "dataset_id": str(run.dataset_id) if run.dataset_id else None}


class ScheduleIn(BaseModel):
    interval_minutes: int = Field(ge=1)
    enabled: bool = True


@router.put("/{connection_id}/schedule")
async def set_schedule(connection_id: str, body: ScheduleIn,
                       ctx: TenantContext = Depends(require("connection:manage")),
                       session=Depends(get_session)):
    conn = await _connection_or_404(session, ctx, connection_id)  # ownership BEFORE quota
    await entitlements.enforce_min_interval(session, ctx.tenant_id, body.interval_minutes)
    schedule = (await session.execute(select(SyncSchedule).where(
        SyncSchedule.connection_id == conn.id))).scalar_one_or_none()
    if schedule is None:
        schedule = SyncSchedule(tenant_id=ctx.tenant_id, connection_id=conn.id)
        session.add(schedule)
    schedule.interval_minutes = body.interval_minutes
    schedule.enabled = body.enabled
    schedule.next_run_at = datetime.now(timezone.utc) + timedelta(
        minutes=body.interval_minutes)
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="schedule.updated", resource_type="connection",
                       resource_id=str(conn.id),
                       detail={"interval_minutes": body.interval_minutes,
                               "enabled": body.enabled})
    return {"connection_id": str(conn.id), "interval_minutes": schedule.interval_minutes,
            "enabled": schedule.enabled, "next_run_at": schedule.next_run_at.isoformat()}


@router.get("/{connection_id}/runs")
async def run_history(connection_id: str, limit: int = 30,
                      ctx: TenantContext = Depends(require("connection:read")),
                      session=Depends(get_session)):
    conn = await _connection_or_404(session, ctx, connection_id)
    rows = (await session.execute(select(SyncRun).where(SyncRun.connection_id == conn.id)
                                  .order_by(desc(SyncRun.started_at))
                                  .limit(min(max(limit, 1), 100)))).scalars()
    return [{"id": str(r.id), "mode": r.mode, "trigger": r.trigger, "status": r.status,
             "rows_extracted": r.rows_extracted, "rows_loaded": r.rows_loaded,
             "error": r.error[:300], "started_at": r.started_at.isoformat(),
             "finished_at": r.finished_at.isoformat() if r.finished_at else None}
            for r in rows]


@router.get("/{connection_id}/dataset")
async def linked_dataset(connection_id: str,
                         ctx: TenantContext = Depends(require("dataset:read")),
                         session=Depends(get_session)):
    conn = await _connection_or_404(session, ctx, connection_id)
    ds = (await session.execute(select(Dataset).where(
        Dataset.connection_id == conn.id))).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "No dataset yet — run a sync first")
    return {"dataset_id": str(ds.id), "name": ds.name}
