"""R15: industry solution packs — list, inspect, and honestly apply."""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .. import audit
from ..deps import TenantContext, get_session, require
from ..models import Dashboard, Dataset, Measure, uuid7
from ..services.industry_packs import PACKS

router = APIRouter(prefix="/api/v1/packs", tags=["packs"])


@router.get("")
async def list_packs(ctx: TenantContext = Depends(require("dataset:read"))):
    return {"packs": [{"industry": k, "label": v["label"],
                       "kpis": len(v["kpis"]),
                       "connectors": v["connectors"]}
                      for k, v in PACKS.items()]}


@router.get("/{industry}")
async def get_pack(industry: str,
                   ctx: TenantContext = Depends(require("dataset:read"))):
    if industry not in PACKS:
        raise HTTPException(404, f"Unknown pack; known: {sorted(PACKS)}")
    p = PACKS[industry]
    return {"industry": industry, **p,
            "kpis": [{"name": n, "formula": f, "unit": u}
                     for n, f, u in p["kpis"]],
            "widgets": [{"type": t, "title": ti, "formula": f,
                         "group_by": g} for t, ti, f, g in p["widgets"]]}


def _cols_of(formula: str) -> set[str]:
    return set(re.findall(r"[a-z_][a-z0-9_]*", formula or "")) - {
        "sum", "count", "avg", "min", "max"}


class ApplyIn(BaseModel):
    dataset_id: str


@router.post("/{industry}/apply", status_code=201)
async def apply_pack(industry: str, body: ApplyIn,
                     ctx: TenantContext = Depends(require("dashboard:create")),
                     session=Depends(get_session)):
    """Create the pack's measures + a starter dashboard against a real
    dataset — only pieces whose columns exist; the rest reported skipped."""
    if industry not in PACKS:
        raise HTTPException(404, f"Unknown pack; known: {sorted(PACKS)}")
    pack = PACKS[industry]
    ds = (await session.execute(select(Dataset).where(
        Dataset.id == body.dataset_id,
        Dataset.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    cols = {c["name"] for c in ds.schema_def}
    numeric = {c["name"] for c in ds.schema_def
               if c["inferred_type"] in ("number", "integer")}
    created_measures, skipped = [], []
    existing = {m.name for m in (await session.execute(select(Measure).where(
        Measure.dataset_id == ds.id))).scalars().all()}
    for name, formula, unit in pack["kpis"]:
        missing = _cols_of(formula) - cols
        if missing:
            skipped.append({"kpi": name,
                            "reason": f"needs columns {sorted(missing)}"})
            continue
        if name in existing:
            skipped.append({"kpi": name, "reason": "already exists"})
            continue
        session.add(Measure(id=uuid7(), tenant_id=ctx.tenant_id,
                            dataset_id=ds.id, name=name, formula=formula,
                            unit=unit, created_by=ctx.user_id,
                            description=f"{pack['label']} pack KPI"))
        created_measures.append(name)
    await session.flush()  # surface measure conflicts before dashboard
    widgets = []
    for wtype, title, formula, group in pack["widgets"]:
        if wtype == "histogram":
            if group in numeric:
                widgets.append({"type": "histogram", "title": title,
                                "dataset_id": str(ds.id),
                                "x_column": group, "bins": 10})
            else:
                skipped.append({"widget": title,
                                "reason": f"needs numeric column {group}"})
            continue
        need = _cols_of(formula) | ({group} if group else set())
        missing = need - cols
        if missing:
            skipped.append({"widget": title,
                            "reason": f"needs columns {sorted(missing)}"})
            continue
        w = {"type": wtype, "title": title, "dataset_id": str(ds.id),
             "formula": formula}
        if group:
            w["group_by"] = group
        widgets.append(w)
    dash_id = None
    if widgets:
        d = Dashboard(id=uuid7(), tenant_id=ctx.tenant_id,
                      workspace_id=ds.workspace_id,
                      name=f"{pack['label']} starter",
                      widgets=widgets, created_by=ctx.user_id)
        session.add(d)
        dash_id = str(d.id)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="pack.apply",
                       resource_type="dataset", resource_id=str(ds.id),
                       detail={"industry": industry,
                               "measures": len(created_measures),
                               "widgets": len(widgets)})
    await session.commit()
    return {"industry": industry, "measures_created": created_measures,
            "dashboard_id": dash_id, "widgets": len(widgets),
            "skipped": skipped,
            "dq_focus": pack["dq_focus"],
            "recommendations": pack["recommendations"]}
