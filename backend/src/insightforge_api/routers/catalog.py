"""Governance catalog (MVP5 G3): advanced catalog, business glossary, full
lineage, certified datasets, impact analysis, approval workflows."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import audit
from ..deps import TenantContext, get_session, require
from ..models import (
    AlertRule,
    Approval,
    Dashboard,
    Dataset,
    GlossaryTerm,
    Measure,
    ReportSchedule,
    uuid7,
)

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


async def _downstream(session, ctx, ds: Dataset) -> dict:
    dashes = (await session.execute(select(Dashboard).where(
        Dashboard.tenant_id == ctx.tenant_id))).scalars().all()
    using = [{"id": str(d.id), "name": d.name, "published":
              bool(d.published_version),
              "widgets": sum(1 for w in d.widgets
                             if w.get("dataset_id") == str(ds.id))}
             for d in dashes
             if any(w.get("dataset_id") == str(ds.id) for w in d.widgets)]
    measures = (await session.execute(select(Measure).where(
        Measure.dataset_id == ds.id))).scalars().all()
    alerts = (await session.execute(select(AlertRule).where(
        AlertRule.dataset_id == ds.id))).scalars().all()
    reports = (await session.execute(select(ReportSchedule).where(
        ReportSchedule.tenant_id == ctx.tenant_id))).scalars().all()
    report_hits = [r for r in reports
                   if str(r.dashboard_id) in {d["id"] for d in using}]
    return {"dashboards": using,
            "measures": [{"name": m.name, "certified": m.certified}
                         for m in measures],
            "alerts": [a.name for a in alerts],
            "report_schedules": len(report_hits)}


@router.get("")
async def catalog(ctx: TenantContext = Depends(require("dataset:read")),
                  session=Depends(get_session)):
    """Advanced catalog: every dataset with governance labels, certification,
    glossary coverage, and usage summary in one view."""
    dss = (await session.execute(select(Dataset).where(
        Dataset.tenant_id == ctx.tenant_id,
        Dataset.archived.is_(False)))).scalars().all()
    terms = (await session.execute(select(GlossaryTerm).where(
        GlossaryTerm.tenant_id == ctx.tenant_id))).scalars().all()
    linked = {link["dataset_id"] for t in terms for link in t.links}
    out = []
    for ds in dss:
        gov = ds.governance or {}
        down = await _downstream(session, ctx, ds)
        out.append({
            "id": str(ds.id), "name": ds.name, "rows": ds.row_count,
            "quality_score": ds.quality_score,
            "certified": bool(gov.get("certified")),
            "classification": gov.get("classification") or {},
            "glossary_covered": str(ds.id) in linked,
            "used_by_dashboards": len(down["dashboards"]),
            "certified_measures": sum(1 for m in down["measures"]
                                      if m["certified"])})
    return {"datasets": out, "glossary_terms": len(terms)}


# ---- glossary ----
class TermIn(BaseModel):
    term: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1)
    steward: str = ""
    links: list[dict] = Field(default_factory=list)  # {dataset_id, column}


@router.post("/glossary", status_code=201)
async def add_term(body: TermIn,
                   ctx: TenantContext = Depends(require("tenant:manage")),
                   session=Depends(get_session)):
    t = GlossaryTerm(id=uuid7(), tenant_id=ctx.tenant_id, **body.model_dump())
    session.add(t)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="glossary.add",
                       resource_type="glossary", resource_id=body.term)
    await session.commit()
    return {"id": str(t.id), "term": t.term}


@router.get("/glossary")
async def list_terms(ctx: TenantContext = Depends(require("dataset:read")),
                     session=Depends(get_session)):
    rows = (await session.execute(select(GlossaryTerm).where(
        GlossaryTerm.tenant_id == ctx.tenant_id).order_by(
        GlossaryTerm.term))).scalars().all()
    return {"terms": [{"id": str(t.id), "term": t.term,
                       "definition": t.definition, "steward": t.steward,
                       "links": t.links} for t in rows]}


# ---- full lineage + impact ----
@router.get("/lineage/{dataset_id}")
async def full_lineage(dataset_id: str,
                       ctx: TenantContext = Depends(require("dataset:read")),
                       session=Depends(get_session)):
    ds = (await session.execute(select(Dataset).where(
        Dataset.id == dataset_id,
        Dataset.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    down = await _downstream(session, ctx, ds)
    return {"upstream": {"source": ds.source_type,
                         "connection_id": str(ds.connection_id)
                         if ds.connection_id else None,
                         "ingested_at": ds.ingested_at.isoformat()
                         if ds.ingested_at else None},
            "object": {"id": str(ds.id), "name": ds.name,
                       "certified": bool((ds.governance or {}).get("certified"))},
            "downstream": down}


@router.get("/impact/{dataset_id}")
async def impact_analysis(dataset_id: str,
                          ctx: TenantContext = Depends(require("dataset:read")),
                          session=Depends(get_session)):
    """What breaks if this dataset changes: named dependents + severity."""
    ds = (await session.execute(select(Dataset).where(
        Dataset.id == dataset_id,
        Dataset.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    down = await _downstream(session, ctx, ds)
    published = [d for d in down["dashboards"] if d["published"]]
    severity = ("high" if published or down["report_schedules"]
                else "medium" if down["dashboards"] or down["alerts"]
                else "low")
    return {"dataset": ds.name, "severity": severity,
            "summary": f"{len(down['dashboards'])} dashboard(s) "
                       f"({len(published)} published), "
                       f"{len(down['measures'])} measure(s), "
                       f"{len(down['alerts'])} alert(s), "
                       f"{down['report_schedules']} report schedule(s) "
                       "depend on this dataset.",
            "dependents": down}


# ---- certification via approval workflow ----
class ApprovalIn(BaseModel):
    kind: str = Field(pattern="^(certify_dataset)$")
    subject_id: str
    note: str = ""


@router.post("/approvals", status_code=201)
async def request_approval(body: ApprovalIn,
                           ctx: TenantContext = Depends(require("dataset:read")),
                           session=Depends(get_session)):
    a = Approval(id=uuid7(), tenant_id=ctx.tenant_id, kind=body.kind,
                 subject_id=body.subject_id, note=body.note,
                 requested_by=ctx.user_id)
    session.add(a)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="approval.request",
                       resource_type=body.kind, resource_id=body.subject_id)
    await session.commit()
    return {"id": str(a.id), "status": "pending"}


@router.get("/approvals")
async def list_approvals(ctx: TenantContext = Depends(require("tenant:manage")),
                         session=Depends(get_session)):
    rows = (await session.execute(select(Approval).where(
        Approval.tenant_id == ctx.tenant_id).order_by(
        Approval.created_at.desc()))).scalars().all()
    return {"approvals": [{"id": str(a.id), "kind": a.kind,
                           "subject_id": a.subject_id, "note": a.note,
                           "status": a.status} for a in rows]}


class DecideIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


@router.post("/approvals/{approval_id}/decide")
async def decide_approval(approval_id: str, body: DecideIn,
                          ctx: TenantContext = Depends(require("tenant:manage")),
                          session=Depends(get_session)):
    a = (await session.execute(select(Approval).where(
        Approval.id == approval_id,
        Approval.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if a is None or a.status != "pending":
        raise HTTPException(404, "Pending approval not found")
    a.status = "approved" if body.decision == "approve" else "rejected"
    a.decided_by = ctx.user_id
    a.decided_at = datetime.now(timezone.utc)
    if a.status == "approved" and a.kind == "certify_dataset":
        ds = (await session.execute(select(Dataset).where(
            Dataset.id == a.subject_id,
            Dataset.tenant_id == ctx.tenant_id))).scalar_one_or_none()
        if ds is not None:
            ds.governance = {**(ds.governance or {}), "certified": True}
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id,
                       action=f"approval.{a.status}",
                       resource_type=a.kind, resource_id=a.subject_id)
    await session.commit()
    return {"status": a.status}
