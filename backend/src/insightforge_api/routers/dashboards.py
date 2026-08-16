"""Self-service BI surface: builder CRUD with widget validation, draft →
publish → versions → revert, hydrated data (draft or published snapshot,
global filters, cross-filter), templates, saved personal/shared views,
expiring share links + public viewer, threaded comments with mentions,
scheduled email reports, PDF export."""

import json as _json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, text

from .. import audit
from ..db import tenant_scoped_session
from ..deps import TenantContext, get_session, require
from ..models import (
    Comment,
    Dashboard,
    DashboardVersion,
    DashboardView,
    Dataset,
    Measure,
    Membership,
    ReportSchedule,
    ShareLink,
    User,
    Workspace,
)
from ..security import new_opaque_token, sha256_of
from ..services import entitlements, narrative, querysvc
from ..services.formulas import FormulaError, compile_formula
from ..services.reportsvc import render_dashboard_pdf, safe_filename
from .auth import _uuid_or_422

router = APIRouter(prefix="/api/v1", tags=["dashboards"])

WIDGET_TYPES = {"kpi", "bar", "line", "area", "pie", "donut", "table", "pivot"}
MAX_WIDGETS = 24


async def _validate_widgets(session, ctx, widgets: list) -> list:
    if not isinstance(widgets, list) or len(widgets) > MAX_WIDGETS:
        raise HTTPException(422, f"widgets must be a list of at most {MAX_WIDGETS} items")
    datasets: dict[str, Dataset] = {}
    out = []
    for i, w in enumerate(widgets):
        if not isinstance(w, dict):
            raise HTTPException(422, f"Widget {i + 1} must be an object")
        wtype = w.get("type")
        if wtype not in WIDGET_TYPES:
            raise HTTPException(422, f"Widget {i + 1}: type must be one of "
                                     f"{', '.join(sorted(WIDGET_TYPES))}")
        ds_id = str(w.get("dataset_id", ""))
        if ds_id not in datasets:
            did = _uuid_or_422(ds_id, f"widget {i + 1} dataset_id")
            ds = (await session.execute(select(Dataset).where(
                Dataset.id == did, Dataset.tenant_id == ctx.tenant_id,
                Dataset.archived.is_(False)))).scalar_one_or_none()
            if ds is None:
                raise HTTPException(422, f"Widget {i + 1}: dataset not found")
            datasets[ds_id] = ds
        ds = datasets[ds_id]
        columns = {c["name"] for c in ds.schema_def}
        clean = {"id": w.get("id") or uuid.uuid4().hex[:8], "type": wtype,
                 "title": str(w.get("title", "Untitled"))[:120], "dataset_id": ds_id,
                 "width": w.get("width") if w.get("width") in ("half", "full") else "half"}
        if wtype == "table":
            clean["limit"] = min(int(w.get("limit", 25) or 25), querysvc.TABLE_LIMIT)
        else:
            formula = str(w.get("formula", ""))
            measure_id = w.get("measure_id")
            if measure_id:
                mid = _uuid_or_422(str(measure_id), f"widget {i + 1} measure_id")
                m = (await session.execute(select(Measure).where(
                    Measure.id == mid, Measure.dataset_id == ds.id))).scalar_one_or_none()
                if m is None:
                    raise HTTPException(422, f"Widget {i + 1}: measure not found")
                formula = m.formula
                clean["measure_id"] = str(mid)
            try:
                compile_formula(formula, ds.schema_def)
            except FormulaError as e:
                raise HTTPException(422, f"Widget {i + 1} formula error: {e}") from None
            clean["formula"] = formula
            if wtype in ("bar", "line", "area", "pie", "donut", "pivot"):
                gb = w.get("group_by")
                if gb not in columns:
                    raise HTTPException(422, f"Widget {i + 1}: group_by must be a dataset "
                                             f"column")
                clean["group_by"] = gb
            if wtype == "pivot":
                gb2 = w.get("group_by2")
                if gb2 not in columns or gb2 == clean["group_by"]:
                    raise HTTPException(422, f"Widget {i + 1}: pivot needs a second, "
                                             f"different group_by2 column")
                clean["group_by2"] = gb2
        out.append(clean)
    return out


def _dash_out(d: Dashboard) -> dict:
    return {"id": str(d.id), "workspace_id": str(d.workspace_id), "name": d.name,
            "status": d.status, "published_version": d.published_version,
            "widgets": d.widgets, "created_at": d.created_at.isoformat()}


async def _dash_or_404(session, ctx, dashboard_id) -> Dashboard:
    did = _uuid_or_422(dashboard_id, "dashboard_id")
    d = (await session.execute(select(Dashboard).where(
        Dashboard.id == did, Dashboard.tenant_id == ctx.tenant_id,
        Dashboard.archived.is_(False)))).scalar_one_or_none()
    if d is None:
        raise HTTPException(404, "Dashboard not found")
    return d


class DashboardIn(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=255)
    widgets: list = []


@router.get("/dashboards")
async def list_dashboards(ctx: TenantContext = Depends(require("dashboard:read")),
                          session=Depends(get_session)):
    rows = (await session.execute(select(Dashboard).where(
        Dashboard.tenant_id == ctx.tenant_id, Dashboard.archived.is_(False))
        .order_by(desc(Dashboard.created_at)))).scalars()
    return [_dash_out(d) for d in rows]


@router.post("/dashboards", status_code=201)
async def create_dashboard(body: DashboardIn,
                           ctx: TenantContext = Depends(require("dashboard:create")),
                           session=Depends(get_session)):
    wid = _uuid_or_422(body.workspace_id, "workspace_id")
    ws = (await session.execute(select(Workspace).where(
        Workspace.id == wid, Workspace.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    await entitlements.enforce_quota(
        session, ctx.tenant_id, "dashboards", Dashboard,
        (Dashboard.tenant_id == ctx.tenant_id) & Dashboard.archived.is_(False))
    widgets = await _validate_widgets(session, ctx, body.widgets)
    d = Dashboard(tenant_id=ctx.tenant_id, workspace_id=wid, name=body.name,
                  widgets=widgets, created_by=ctx.user_id)
    session.add(d)
    await session.flush()
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="dashboard.created", resource_type="dashboard",
                       resource_id=str(d.id), correlation_id=ctx.correlation_id)
    await session.commit()
    return _dash_out(d)


@router.get("/dashboards/{dashboard_id}")
async def get_dashboard(dashboard_id: str,
                        ctx: TenantContext = Depends(require("dashboard:read")),
                        session=Depends(get_session)):
    return _dash_out(await _dash_or_404(session, ctx, dashboard_id))


class DashboardPatch(BaseModel):
    name: str | None = None
    widgets: list | None = None
    archived: bool | None = None


@router.patch("/dashboards/{dashboard_id}")
async def update_dashboard(dashboard_id: str, body: DashboardPatch,
                           ctx: TenantContext = Depends(require("dashboard:create")),
                           session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    if body.name is not None:
        d.name = body.name[:255]
    if body.widgets is not None:
        d.widgets = await _validate_widgets(session, ctx, body.widgets)
        d.status = "draft"  # edits always land in draft; published snapshot is immutable
    if body.archived is True:
        d.archived = True
    await session.commit()
    return _dash_out(d)


@router.post("/dashboards/{dashboard_id}/publish")
async def publish(dashboard_id: str, ctx: TenantContext = Depends(require("dashboard:create")),
                  session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    if not d.widgets:
        raise HTTPException(422, "Add at least one widget before publishing")
    version = (d.published_version or 0) + 1
    session.add(DashboardVersion(tenant_id=ctx.tenant_id, dashboard_id=d.id, version=version,
                                 widgets=d.widgets, published_by=ctx.user_id))
    d.status = "published"
    d.published_version = version
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="dashboard.published", resource_type="dashboard",
                       resource_id=str(d.id), detail={"version": version})
    await session.commit()
    return {"id": str(d.id), "status": d.status, "published_version": version}


@router.get("/dashboards/{dashboard_id}/versions")
async def versions(dashboard_id: str, ctx: TenantContext = Depends(require("dashboard:read")),
                   session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    rows = (await session.execute(
        select(DashboardVersion, User.display_name)
        .join(User, User.id == DashboardVersion.published_by)
        .where(DashboardVersion.dashboard_id == d.id)
        .order_by(desc(DashboardVersion.version)))).all()
    return [{"version": v.version, "published_by": name, "widget_count": len(v.widgets),
             "at": v.created_at.isoformat()} for v, name in rows]


@router.post("/dashboards/{dashboard_id}/revert")
async def revert(dashboard_id: str, version: int = Query(ge=1),
                 ctx: TenantContext = Depends(require("dashboard:create")),
                 session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    v = (await session.execute(select(DashboardVersion).where(
        DashboardVersion.dashboard_id == d.id,
        DashboardVersion.version == version))).scalar_one_or_none()
    if v is None:
        raise HTTPException(404, f"Version {version} not found")
    d.widgets = v.widgets
    d.status = "draft"  # reverting produces a draft; publish again to release it
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="dashboard.reverted", resource_type="dashboard",
                       resource_id=str(d.id), detail={"to_version": version})
    await session.commit()
    return _dash_out(d)


# ---------------- Hydration ----------------
def _parse_filters(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        filters = _json.loads(raw)
        assert isinstance(filters, list)
        return filters
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "filters must be a JSON array of "
                                 "{column, op, value}") from None


async def _hydrate(session, tenant_id, widgets: list, filters: list[dict]) -> dict:
    ds_cache: dict[str, Dataset] = {}
    out, min_quality, freshness = [], None, None
    for w in widgets:
        ds_id = w["dataset_id"]
        if ds_id not in ds_cache:
            ds_cache[ds_id] = (await session.execute(select(Dataset).where(
                Dataset.id == uuid.UUID(ds_id)))).scalar_one_or_none()
        ds = ds_cache[ds_id]
        item = dict(w)
        if ds is None:
            item["error"] = "Dataset no longer available"
            out.append(item)
            continue
        if ds.quality_score is not None:
            min_quality = ds.quality_score if min_quality is None else min(
                min_quality, ds.quality_score)
        if ds.ingested_at is not None and (freshness is None or ds.ingested_at < freshness):
            freshness = ds.ingested_at
        columns = {c["name"] for c in ds.schema_def}
        applicable = [f for f in filters if f.get("column") in columns]
        try:
            if w["type"] == "table":
                item.update(await querysvc.fetch_table(
                    session, dataset_id=ds.id, current_import_id=ds.current_import_id,
                    dataset_schema=ds.schema_def, filters=applicable,
                    limit=w.get("limit", 25)))
            elif w["type"] == "pivot":
                item.update(await querysvc.execute_formula(
                    session, dataset_id=ds.id, current_import_id=ds.current_import_id,
                    dataset_schema=ds.schema_def, formula=w["formula"],
                    group_by=w["group_by"], group_by2=w["group_by2"], filters=applicable))
            elif w["type"] == "kpi":
                item.update(await querysvc.execute_formula(
                    session, dataset_id=ds.id, current_import_id=ds.current_import_id,
                    dataset_schema=ds.schema_def, formula=w["formula"], filters=applicable))
            else:
                item.update(await querysvc.execute_formula(
                    session, dataset_id=ds.id, current_import_id=ds.current_import_id,
                    dataset_schema=ds.schema_def, formula=w["formula"],
                    group_by=w["group_by"], filters=applicable))
        except querysvc.QueryError as e:
            item["error"] = str(e)
        out.append(item)
    return {"widgets": out, "quality_score": min_quality,
            "freshness": freshness.isoformat() if freshness else None}


@router.get("/dashboards/{dashboard_id}/data")
async def dashboard_data(dashboard_id: str, view: str = "draft",
                         filters: str | None = None,
                         ctx: TenantContext = Depends(require("dashboard:read")),
                         session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    parsed = _parse_filters(filters)
    widgets = d.widgets
    if view == "published":
        if d.published_version is None:
            raise HTTPException(404, "This dashboard has never been published")
        v = (await session.execute(select(DashboardVersion).where(
            DashboardVersion.dashboard_id == d.id,
            DashboardVersion.version == d.published_version))).scalar_one()
        widgets = v.widgets
    elif view != "draft":
        raise HTTPException(422, "view must be draft or published")
    result = await _hydrate(session, ctx.tenant_id, widgets, parsed)
    result.update({"id": str(d.id), "name": d.name, "status": d.status, "view": view})
    return result


# ---------------- Templates ----------------
TEMPLATES = {
    "sales_overview": {
        "name": "Sales overview",
        "description": "Revenue KPI, revenue by category, trend over time, top rows",
        "requires": {"value_column": "numeric", "category_column": "text"},
    },
    "finance_cashflow": {
        "name": "Finance & cash flow",
        "description": "Total in, average transaction, by-category breakdown, pivot",
        "requires": {"value_column": "numeric", "category_column": "text"},
    },
}


@router.get("/dashboard-templates")
async def list_templates(ctx: TenantContext = Depends(require("dashboard:read"))):
    return [{"key": k, **v} for k, v in TEMPLATES.items()]


class TemplateApply(BaseModel):
    workspace_id: str
    dataset_id: str
    value_column: str
    category_column: str
    date_column: str | None = None
    name: str | None = None


@router.post("/dashboard-templates/{key}/apply", status_code=201)
async def apply_template(key: str, body: TemplateApply,
                         ctx: TenantContext = Depends(require("dashboard:create")),
                         session=Depends(get_session)):
    if key not in TEMPLATES:
        raise HTTPException(404, "Template not found")
    ds_id = body.dataset_id
    did = _uuid_or_422(ds_id, "dataset_id")
    ds = (await session.execute(select(Dataset).where(
        Dataset.id == did, Dataset.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    columns = {c["name"] for c in ds.schema_def}
    for col in (body.value_column, body.category_column):
        if col not in columns:
            raise HTTPException(422, f"Column {col!r} is not in this dataset")
    v, c = body.value_column, body.category_column
    date_col = body.date_column if body.date_column in columns else c
    if key == "sales_overview":
        widgets = [
            {"type": "kpi", "title": "Total revenue", "formula": f"sum({v})"},
            {"type": "kpi", "title": "Transactions", "formula": "count()"},
            {"type": "bar", "title": f"Revenue by {c}", "formula": f"sum({v})",
             "group_by": c},
            {"type": "line", "title": "Trend", "formula": f"sum({v})",
             "group_by": date_col, "width": "full"},
            {"type": "table", "title": "Latest rows", "limit": 15, "width": "full"},
        ]
        name = body.name or f"Sales overview — {ds.name}"
    else:
        widgets = [
            {"type": "kpi", "title": "Total inflow", "formula": f"sum({v})"},
            {"type": "kpi", "title": "Average transaction",
             "formula": f"sum({v}) / count()"},
            {"type": "donut", "title": f"By {c}", "formula": f"sum({v})", "group_by": c},
            {"type": "pivot", "title": f"{c} × {date_col}", "formula": f"sum({v})",
             "group_by": c, "group_by2": date_col, "width": "full"},
        ]
        name = body.name or f"Cash flow — {ds.name}"
    for w in widgets:
        w["dataset_id"] = ds_id
    await entitlements.enforce_quota(
        session, ctx.tenant_id, "dashboards", Dashboard,
        (Dashboard.tenant_id == ctx.tenant_id) & Dashboard.archived.is_(False))
    validated = await _validate_widgets(session, ctx, widgets)
    d = Dashboard(tenant_id=ctx.tenant_id, workspace_id=ds.workspace_id, name=name,
                  widgets=validated, created_by=ctx.user_id)
    session.add(d)
    await session.flush()
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="dashboard.from_template", resource_type="dashboard",
                       resource_id=str(d.id), detail={"template": key})
    await session.commit()
    return _dash_out(d)


# ---------------- Saved views ----------------
class ViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    filters: list = []
    shared: bool = False


@router.get("/dashboards/{dashboard_id}/views")
async def list_views(dashboard_id: str, ctx: TenantContext = Depends(require("dashboard:read")),
                     session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    rows = (await session.execute(select(DashboardView).where(
        DashboardView.dashboard_id == d.id, DashboardView.archived.is_(False))
        .order_by(DashboardView.created_at))).scalars()
    return [{"id": str(v.id), "name": v.name, "filters": v.filters, "shared": v.shared,
             "mine": v.created_by == ctx.user_id}
            for v in rows if v.shared or v.created_by == ctx.user_id]


@router.post("/dashboards/{dashboard_id}/views", status_code=201)
async def save_view(dashboard_id: str, body: ViewIn,
                    ctx: TenantContext = Depends(require("dashboard:read")),
                    session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    v = DashboardView(tenant_id=ctx.tenant_id, dashboard_id=d.id, name=body.name,
                      filters=body.filters, shared=body.shared, created_by=ctx.user_id)
    session.add(v)
    await session.flush()
    await session.commit()
    return {"id": str(v.id), "name": v.name, "shared": v.shared}


@router.patch("/dashboards/{dashboard_id}/views/{view_id}")
async def archive_view(dashboard_id: str, view_id: str, body: dict,
                       ctx: TenantContext = Depends(require("dashboard:read")),
                       session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    vid = _uuid_or_422(view_id, "view_id")
    v = (await session.execute(select(DashboardView).where(
        DashboardView.id == vid,
        DashboardView.dashboard_id == d.id))).scalar_one_or_none()
    if v is None or (v.created_by != ctx.user_id and ctx.role not in
                     ("tenant_owner", "tenant_admin")):
        raise HTTPException(404, "View not found")
    if body.get("archived") is True:
        v.archived = True
    if "shared" in body:
        v.shared = bool(body["shared"])
    await session.commit()
    return {"id": str(v.id), "archived": v.archived, "shared": v.shared}


# ---------------- Share links ----------------
class ShareIn(BaseModel):
    expires_in_hours: int = Field(default=72, ge=1, le=24 * 90)


@router.post("/dashboards/{dashboard_id}/share", status_code=201)
async def create_share(dashboard_id: str, body: ShareIn, request: Request,
                       ctx: TenantContext = Depends(require("dashboard:create")),
                       session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    if d.published_version is None:
        raise HTTPException(422, "Publish the dashboard before sharing — links only ever "
                                 "expose the published snapshot")
    raw, token_hash = new_opaque_token()
    link = ShareLink(tenant_id=ctx.tenant_id, dashboard_id=d.id, token_hash=token_hash,
                     expires_at=datetime.now(timezone.utc) + timedelta(
                         hours=body.expires_in_hours),
                     created_by=ctx.user_id)
    session.add(link)
    await session.flush()
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="share.created", resource_type="dashboard",
                       resource_id=str(d.id))
    base = str(request.base_url).rstrip("/")
    await session.commit()
    return {"share_id": str(link.id), "token": raw,
            "url": f"{base}/share.html?token={raw}",
            "expires_at": link.expires_at.isoformat()}


@router.get("/dashboards/{dashboard_id}/shares")
async def list_shares(dashboard_id: str,
                      ctx: TenantContext = Depends(require("dashboard:read")),
                      session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    rows = (await session.execute(select(ShareLink).where(ShareLink.dashboard_id == d.id)
                                  .order_by(desc(ShareLink.created_at)))).scalars()
    return [{"id": str(link.id), "revoked": link.revoked,
             "expires_at": link.expires_at.isoformat(),
             "expired": link.expires_at < datetime.now(timezone.utc)} for link in rows]


@router.post("/shares/{share_id}/revoke")
async def revoke_share(share_id: str, ctx: TenantContext = Depends(require("dashboard:create")),
                       session=Depends(get_session)):
    sid = _uuid_or_422(share_id, "share_id")
    link = (await session.execute(select(ShareLink).where(
        ShareLink.id == sid, ShareLink.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if link is None:
        raise HTTPException(404, "Share link not found")
    link.revoked = True
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="share.revoked", resource_type="share", resource_id=str(sid))
    await session.commit()
    return {"id": str(sid), "revoked": True}


@router.get("/public/dashboards/{token}")
async def public_dashboard(token: str):
    """Unauthenticated read-only viewer. Two-step RLS: the token-hash arm
    reveals only the matching share_links row; then a tenant-scoped session
    hydrates the PUBLISHED snapshot only. Draft content is never reachable."""
    token_hash = sha256_of(token)
    from ..db import session_factory

    async with session_factory()() as s:
        async with s.begin():
            await s.execute(text("SELECT set_config('app.share_token_hash', :h, true)"),
                            {"h": token_hash})
            link = (await s.execute(select(ShareLink).where(
                ShareLink.token_hash == token_hash))).scalar_one_or_none()
            if link is None or link.revoked:
                raise HTTPException(404, "This link is invalid or has been revoked")
            if link.expires_at < datetime.now(timezone.utc):
                raise HTTPException(410, "This link has expired — ask for a new one")
            tenant_id, dashboard_id = link.tenant_id, link.dashboard_id
    async with tenant_scoped_session(tenant_id) as s:
        d = (await s.execute(select(Dashboard).where(
            Dashboard.id == dashboard_id))).scalar_one_or_none()
        if d is None or d.archived or d.published_version is None:
            raise HTTPException(404, "Dashboard is no longer available")
        v = (await s.execute(select(DashboardVersion).where(
            DashboardVersion.dashboard_id == d.id,
            DashboardVersion.version == d.published_version))).scalar_one()
        result = await _hydrate(s, tenant_id, v.widgets, [])
        result.update({"name": d.name, "published_version": d.published_version,
                       "read_only": True})
        return result


# ---------------- Threaded comments ----------------
class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    parent_id: str | None = None
    mentions: list[str] = []


@router.get("/dashboards/{dashboard_id}/comments")
async def list_comments(dashboard_id: str,
                        ctx: TenantContext = Depends(require("dashboard:read")),
                        session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    rows = (await session.execute(
        select(Comment, User.display_name).join(User, User.id == Comment.author_id)
        .where(Comment.dashboard_id == d.id).order_by(Comment.created_at))).all()
    return [{"id": str(c.id), "author": name, "body": c.body,
             "parent_id": str(c.parent_id) if c.parent_id else None,
             "mentions": c.mentions, "at": c.created_at.isoformat()} for c, name in rows]


@router.post("/dashboards/{dashboard_id}/comments", status_code=201)
async def add_comment(dashboard_id: str, body: CommentIn,
                      ctx: TenantContext = Depends(require("dashboard:read")),
                      session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    parent_id = None
    if body.parent_id:
        pid = _uuid_or_422(body.parent_id, "parent_id")
        parent = (await session.execute(select(Comment).where(
            Comment.id == pid, Comment.dashboard_id == d.id))).scalar_one_or_none()
        if parent is None:
            raise HTTPException(404, "Parent comment not found")
        parent_id = pid
    valid_mentions = []
    for email in body.mentions[:10]:
        member = (await session.execute(
            select(User).join(Membership, Membership.user_id == User.id)
            .where(Membership.tenant_id == ctx.tenant_id,
                   User.email == email.lower()))).scalar_one_or_none()
        if member is None:
            raise HTTPException(422, f"@{email} is not a member of this organization")
        valid_mentions.append(member.email)
    c = Comment(tenant_id=ctx.tenant_id, dashboard_id=d.id, author_id=ctx.user_id,
                parent_id=parent_id, body=body.body, mentions=valid_mentions)
    session.add(c)
    await session.flush()
    if valid_mentions:
        from ..services import mailer

        author = (await session.execute(
            select(User).where(User.id == ctx.user_id))).scalar_one()
        for email in valid_mentions:
            await mailer.send(session, tenant_id=ctx.tenant_id, to_email=email,
                              kind="mention",
                              subject=f"{author.display_name} mentioned you on '{d.name}'",
                              body=f"{author.display_name} wrote:\n\n{body.body}\n\n"
                                   f"Open the dashboard in InsightForge to reply.")
    await session.commit()
    return {"id": str(c.id), "parent_id": str(parent_id) if parent_id else None}


# ---------------- Scheduled reports ----------------
class ReportIn(BaseModel):
    recipients: list[str] = Field(min_length=1)
    interval_minutes: int = Field(default=1440, ge=1)


@router.get("/dashboards/{dashboard_id}/report-schedules")
async def list_reports(dashboard_id: str,
                       ctx: TenantContext = Depends(require("dashboard:read")),
                       session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    rows = (await session.execute(select(ReportSchedule).where(
        ReportSchedule.dashboard_id == d.id))).scalars()
    return [{"id": str(r.id), "recipients": r.recipients,
             "interval_minutes": r.interval_minutes, "enabled": r.enabled,
             "last_status": r.last_status,
             "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
             "next_run_at": r.next_run_at.isoformat()} for r in rows]


@router.post("/dashboards/{dashboard_id}/report-schedules", status_code=201)
async def create_report(dashboard_id: str, body: ReportIn,
                        ctx: TenantContext = Depends(require("dashboard:create")),
                        session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    if d.published_version is None:
        raise HTTPException(422, "Publish the dashboard first — reports send the published "
                                 "snapshot")
    await entitlements.enforce_quota(session, ctx.tenant_id, "reports", ReportSchedule,
                                     ReportSchedule.tenant_id == ctx.tenant_id)
    await entitlements.enforce_min_interval(session, ctx.tenant_id, body.interval_minutes)
    r = ReportSchedule(tenant_id=ctx.tenant_id, dashboard_id=d.id,
                       recipients=[e.lower() for e in body.recipients[:20]],
                       interval_minutes=body.interval_minutes, created_by=ctx.user_id)
    session.add(r)
    await session.flush()
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="report.scheduled", resource_type="dashboard",
                       resource_id=str(d.id))
    await session.commit()
    return {"id": str(r.id), "next_run_at": r.next_run_at.isoformat()}


@router.patch("/report-schedules/{schedule_id}")
async def toggle_report(schedule_id: str, body: dict,
                        ctx: TenantContext = Depends(require("dashboard:create")),
                        session=Depends(get_session)):
    sid = _uuid_or_422(schedule_id, "schedule_id")
    r = (await session.execute(select(ReportSchedule).where(
        ReportSchedule.id == sid,
        ReportSchedule.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if r is None:
        raise HTTPException(404, "Report schedule not found")
    if "enabled" in body:
        r.enabled = bool(body["enabled"])
    await session.commit()
    return {"id": str(r.id), "enabled": r.enabled}


@router.get("/dashboards/{dashboard_id}/export.pdf")
async def export_pdf(dashboard_id: str, view: str = "published",
                     ctx: TenantContext = Depends(require("dashboard:read")),
                     session=Depends(get_session)):
    d = await _dash_or_404(session, ctx, dashboard_id)
    widgets = d.widgets
    if view == "published":
        if d.published_version is None:
            raise HTTPException(404, "Publish first, or export with ?view=draft")
        v = (await session.execute(select(DashboardVersion).where(
            DashboardVersion.dashboard_id == d.id,
            DashboardVersion.version == d.published_version))).scalar_one()
        widgets = v.widgets
    hydrated = await _hydrate(session, ctx.tenant_id, widgets, [])
    hydrated["name"] = d.name
    pdf = render_dashboard_pdf(hydrated)
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="dashboard.exported_pdf", resource_type="dashboard",
                       resource_id=str(d.id))
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{safe_filename(d.name, "pdf")}"'})


@router.get("/dashboards/{dashboard_id}/brief")
async def executive_brief(dashboard_id: str,
                          ctx: TenantContext = Depends(require("dashboard:read")),
                          session=Depends(get_session)):
    """MVP3: executive brief — deterministic period-over-period narrative with
    driver attribution, composed from this dashboard's own governed widgets."""
    d = await _dash_or_404(session, ctx, dashboard_id)
    ds_by_id = {}
    for w in d.widgets:
        if w["dataset_id"] not in ds_by_id:
            ds_by_id[w["dataset_id"]] = (await session.execute(select(Dataset).where(
                Dataset.id == uuid.UUID(w["dataset_id"]),
                Dataset.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    brief = await narrative.executive_brief(session, d.name, d.widgets, ds_by_id)
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="ai.brief", resource_type="dashboard",
                       resource_id=str(d.id))
    await session.commit()
    return brief
