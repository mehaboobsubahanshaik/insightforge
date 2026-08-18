"""Semantic layer completion (R11): tenant semantic model (hierarchies,
subject areas, virtual relationships), virtual-join queries (no
materialization), measure units + versioning + validation tests."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from .. import audit
from ..deps import TenantContext, get_session, require
from ..models import Dataset, Measure, Tenant
from ..services import querysvc
from ..services.formulas import FormulaError, compile_formula

router = APIRouter(prefix="/api/v1/semantic", tags=["semantic"])


class Hierarchy(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    dataset_id: str
    levels: list[str] = Field(min_length=2, max_length=6)


class Relationship(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    left_dataset_id: str
    left_key: str
    right_dataset_id: str
    right_key: str


class SubjectArea(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    dataset_ids: list[str] = Field(min_length=1, max_length=50)


class ModelIn(BaseModel):
    hierarchies: list[Hierarchy] = Field(default_factory=list, max_length=20)
    relationships: list[Relationship] = Field(default_factory=list,
                                              max_length=20)
    subject_areas: list[SubjectArea] = Field(default_factory=list,
                                             max_length=20)


async def _ds(session, ctx, ds_id):
    ds = (await session.execute(select(Dataset).where(
        Dataset.id == ds_id,
        Dataset.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ds is None:
        raise HTTPException(422, f"Dataset {ds_id} not found")
    return ds


@router.put("/model")
async def set_model(body: ModelIn,
                    ctx: TenantContext = Depends(require("tenant:manage")),
                    session=Depends(get_session)):
    """The tenant's semantic model — columns validated against real
    schemas at write time so the model can never drift silently."""
    for h in body.hierarchies:
        ds = await _ds(session, ctx, h.dataset_id)
        cols = {c["name"] for c in ds.schema_def}
        missing = set(h.levels) - cols
        if missing:
            raise HTTPException(422, f"Hierarchy '{h.name}': columns "
                                     f"{sorted(missing)} not on dataset")
    for r in body.relationships:
        left = await _ds(session, ctx, r.left_dataset_id)
        right = await _ds(session, ctx, r.right_dataset_id)
        if r.left_key not in {c["name"] for c in left.schema_def} or \
                r.right_key not in {c["name"] for c in right.schema_def}:
            raise HTTPException(422, f"Relationship '{r.name}': keys must "
                                     "exist on their datasets")
    for sa in body.subject_areas:
        for did in sa.dataset_ids:
            await _ds(session, ctx, did)
    t = (await session.execute(select(Tenant).where(
        Tenant.id == ctx.tenant_id))).scalar_one()
    t.features = {**(t.features or {}),
                  "semantic_model": body.model_dump()}
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="semantic.model",
                       resource_type="tenant", resource_id=str(t.id))
    await session.commit()
    return {"semantic_model": t.features["semantic_model"]}


@router.get("/model")
async def get_model(ctx: TenantContext = Depends(require("dataset:read")),
                    session=Depends(get_session)):
    t = (await session.execute(select(Tenant).where(
        Tenant.id == ctx.tenant_id))).scalar_one()
    return {"semantic_model": (t.features or {}).get("semantic_model", {})}


class VJQueryIn(BaseModel):
    relationship: str
    value_column: str  # numeric, on the LEFT dataset
    group_by: str      # column on the RIGHT dataset


@router.post("/query")
async def virtual_join_query(body: VJQueryIn,
                             ctx: TenantContext = Depends(
                                 require("dataset:read")),
                             session=Depends(get_session)):
    """R11: query ACROSS a defined relationship at runtime — no
    materialized copy; the join lives in the semantic model."""
    t = (await session.execute(select(Tenant).where(
        Tenant.id == ctx.tenant_id))).scalar_one()
    rels = ((t.features or {}).get("semantic_model") or {}).get(
        "relationships", [])
    rel = next((r for r in rels if r["name"] == body.relationship), None)
    if rel is None:
        raise HTTPException(404, f"Relationship '{body.relationship}' not "
                                 "in the semantic model")
    left = await _ds(session, ctx, rel["left_dataset_id"])
    right = await _ds(session, ctx, rel["right_dataset_id"])
    lnum = {c["name"] for c in left.schema_def
            if c["inferred_type"] in ("number", "integer")}
    if body.value_column not in lnum:
        raise HTTPException(422, "value_column must be numeric on the "
                                 "left dataset")
    if body.group_by not in {c["name"] for c in right.schema_def}:
        raise HTTPException(422, "group_by must be a right-dataset column")
    rows = (await session.execute(text(
        "SELECT r.data->>:gb AS g, sum((l.data->>:vc)::numeric) AS v "
        "FROM dataset_rows l JOIN dataset_rows r "
        "ON l.data->>:lk = r.data->>:rk "
        "AND r.dataset_id = :rd AND r.import_id = :ri "
        "AND NOT r.is_quarantined "
        "WHERE l.dataset_id = :ld AND l.import_id = :li "
        "AND NOT l.is_quarantined GROUP BY 1 ORDER BY 2 DESC LIMIT 100"),
        {"gb": body.group_by, "vc": body.value_column,
         "lk": rel["left_key"], "rk": rel["right_key"],
         "rd": str(right.id), "ri": str(right.current_import_id),
         "ld": str(left.id), "li": str(left.current_import_id)})).all()
    return {"relationship": body.relationship,
            "groups": [{"group": g, "value": float(v)} for g, v in rows],
            "method": "runtime virtual join — nothing materialized"}


class MeasureUpdateIn(BaseModel):
    formula: str | None = Field(default=None, max_length=500)
    unit: str | None = Field(default=None, max_length=24)
    description: str | None = Field(default=None, max_length=500)


@router.put("/measures/{measure_id}")
async def update_measure(measure_id: str, body: MeasureUpdateIn,
                         ctx: TenantContext = Depends(
                             require("measure:create")),
                         session=Depends(get_session)):
    """R11 metric versioning: formula changes append the OLD definition to
    the version history — auditable metric evolution, certification reset."""
    import copy as _copy

    m = (await session.execute(select(Measure).where(
        Measure.id == measure_id,
        Measure.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Measure not found")
    if body.formula and body.formula != m.formula:
        ds = await _ds(session, ctx, m.dataset_id)
        try:
            compile_formula(body.formula, ds.schema_def)
        except FormulaError as e:
            raise HTTPException(422, f"Formula error: {e}") from None
        versions = _copy.deepcopy(m.versions or [])
        versions.append({"formula": m.formula,
                         "replaced_at":
                         datetime.now(timezone.utc).isoformat(),
                         "replaced_by": str(ctx.user_id)})
        m.versions = versions
        m.formula = body.formula
        m.certified = False  # re-certify after change (via approvals)
    if body.unit is not None:
        m.unit = body.unit
    if body.description is not None:
        m.description = body.description
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="measure.update",
                       resource_type="measure", resource_id=str(m.id))
    await session.commit()
    return {"id": str(m.id), "formula": m.formula, "unit": m.unit,
            "certified": m.certified, "versions": len(m.versions or [])}


class ValidateIn(BaseModel):
    min: float | None = None
    max: float | None = None


@router.post("/measures/{measure_id}/validate")
async def validate_measure(measure_id: str, body: ValidateIn,
                           ctx: TenantContext = Depends(
                               require("dataset:read")),
                           session=Depends(get_session)):
    """R11 metric validation test: run the measure now, assert bounds —
    the semantic layer's unit test."""
    if body.min is None and body.max is None:
        raise HTTPException(422, "Provide min and/or max")
    m = (await session.execute(select(Measure).where(
        Measure.id == measure_id,
        Measure.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Measure not found")
    ds = await _ds(session, ctx, m.dataset_id)
    value = (await querysvc.execute_formula(
        session, dataset_id=ds.id, current_import_id=ds.current_import_id,
        dataset_schema=ds.schema_def, formula=m.formula,
        filters=[]))["value"]
    ok = ((body.min is None or (value is not None and value >= body.min))
          and (body.max is None or (value is not None and value <= body.max)))
    return {"measure": m.name, "value": value, "unit": m.unit,
            "bounds": body.model_dump(), "passed": ok,
            "verdict": "within bounds" if ok else
            "FAILED — investigate before trusting this metric"}
