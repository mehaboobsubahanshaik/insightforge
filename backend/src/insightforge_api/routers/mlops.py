"""Advanced analytics (MVP5 G5): forecast model management + registry +
monitoring, what-if analysis, scenario planning, root-cause workflow,
Azure ML config. All deterministic/explainable per house rules."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import audit
from ..deps import TenantContext, get_session, require
from ..models import Dataset, MLModel, Tenant, uuid7
from ..services import narrative, querysvc

router = APIRouter(prefix="/api/v1/ml", tags=["ml-ops"])


async def _series(session, ds, value_col: str, date_col: str) -> list[float]:
    r = await querysvc.execute_formula(
        session, dataset_id=ds.id, current_import_id=ds.current_import_id,
        dataset_schema=ds.schema_def, formula=f"sum({value_col})",
        group_by=date_col, filters=[])
    groups = sorted((g for g in r["groups"] if g["group"] is not None),
                    key=lambda g: str(g["group"]))
    return [float(g["value"] or 0) for g in groups]


def _fit_metrics(series: list[float]) -> dict:
    from insightforge_ml import forecast_series

    if len(series) < 5:
        raise HTTPException(422, "Need at least 5 points to fit")
    f = forecast_series(series, horizon=1)
    return {"points": len(series),
            "mae": round(f.get("residual_std", 0.0), 4),
            "level": round(f["points"][0]["forecast"], 2)}


class ModelIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    dataset_id: str
    value_column: str
    date_column: str


@router.post("/models", status_code=201)
async def register_model(body: ModelIn,
                         ctx: TenantContext = Depends(require("dataset:read")),
                         session=Depends(get_session)):
    """Forecast model management: fit on the dataset's daily series, store
    config + backtest MAE as the monitoring baseline."""
    ds = (await session.execute(select(Dataset).where(
        Dataset.id == body.dataset_id,
        Dataset.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    series = await _series(session, ds, body.value_column, body.date_column)
    metrics = _fit_metrics(series)
    m = MLModel(id=uuid7(), tenant_id=ctx.tenant_id, name=body.name,
                kind="forecast", dataset_id=ds.id,
                config={"value_column": body.value_column,
                        "date_column": body.date_column},
                metrics={"baseline": metrics})
    session.add(m)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="ml.register",
                       resource_type="ml_model", resource_id=str(m.id))
    await session.commit()
    return {"id": str(m.id), "metrics": m.metrics}


@router.get("/models")
async def list_models(ctx: TenantContext = Depends(require("dataset:read")),
                      session=Depends(get_session)):
    rows = (await session.execute(select(MLModel).where(
        MLModel.tenant_id == ctx.tenant_id))).scalars().all()
    return {"models": [{"id": str(m.id), "name": m.name, "kind": m.kind,
                        "status": m.status, "metrics": m.metrics,
                        "evaluated_at": m.evaluated_at.isoformat()
                        if m.evaluated_at else None} for m in rows]}


@router.post("/models/{model_id}/evaluate")
async def evaluate_model(model_id: str,
                         ctx: TenantContext = Depends(require("dataset:read")),
                         session=Depends(get_session)):
    """Model monitoring: refit on current data, compare MAE to the baseline;
    drift flagged when error grows >50%."""
    m = (await session.execute(select(MLModel).where(
        MLModel.id == model_id, MLModel.tenant_id == ctx.tenant_id,
        MLModel.kind == "forecast"))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Model not found")
    ds = (await session.execute(select(Dataset).where(
        Dataset.id == m.dataset_id))).scalar_one()
    series = await _series(session, ds, m.config["value_column"],
                           m.config["date_column"])
    current = _fit_metrics(series)
    base_mae = m.metrics.get("baseline", {}).get("mae", 0) or 1e-9
    drift = current["mae"] > base_mae * 1.5 and current["mae"] > 1e-6
    m.metrics = {**m.metrics, "latest": current, "drift": drift}
    m.evaluated_at = datetime.now(timezone.utc)
    await session.commit()
    return {"metrics": m.metrics, "drift": drift}


# ---- what-if + scenarios ----
class Adjustment(BaseModel):
    column: str
    value: str
    factor: float = Field(gt=0, le=100)


class WhatIfIn(BaseModel):
    dataset_id: str
    value_column: str
    adjustments: list[Adjustment] = Field(min_length=1, max_length=10)


async def _what_if(session, ctx, body: WhatIfIn) -> dict:
    ds = (await session.execute(select(Dataset).where(
        Dataset.id == body.dataset_id,
        Dataset.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    kw = dict(dataset_id=ds.id, current_import_id=ds.current_import_id,
              dataset_schema=ds.schema_def,
              formula=f"sum({body.value_column})")
    baseline = (await querysvc.execute_formula(
        session, **kw, filters=[]))["value"] or 0.0
    adjusted, parts = baseline, []
    for adj in body.adjustments:
        seg = (await querysvc.execute_formula(
            session, **kw, filters=[{"column": adj.column, "op": "eq",
                                     "value": adj.value}]))["value"] or 0.0
        delta = seg * (adj.factor - 1)
        adjusted += delta
        parts.append({"segment": f"{adj.column}={adj.value}",
                      "segment_value": seg, "factor": adj.factor,
                      "delta": round(delta, 2)})
    return {"baseline": baseline, "adjusted": round(adjusted, 2),
            "change_pct": round((adjusted - baseline) / baseline * 100, 1)
            if baseline else None,
            "parts": parts,
            "method": "deterministic segment reweighting — every number "
                      "recomputable by hand"}


@router.post("/what-if")
async def what_if(body: WhatIfIn,
                  ctx: TenantContext = Depends(require("dataset:read")),
                  session=Depends(get_session)):
    return await _what_if(session, ctx, body)


class ScenarioIn(WhatIfIn):
    name: str = Field(min_length=1, max_length=120)


@router.post("/scenarios", status_code=201)
async def save_scenario(body: ScenarioIn,
                        ctx: TenantContext = Depends(require("dataset:read")),
                        session=Depends(get_session)):
    m = MLModel(id=uuid7(), tenant_id=ctx.tenant_id, name=body.name,
                kind="scenario", dataset_id=body.dataset_id,
                config=body.model_dump(exclude={"name"}))
    session.add(m)
    await session.commit()
    return {"id": str(m.id), "name": body.name}


@router.post("/scenarios/{scenario_id}/run")
async def run_scenario(scenario_id: str,
                       ctx: TenantContext = Depends(require("dataset:read")),
                       session=Depends(get_session)):
    m = (await session.execute(select(MLModel).where(
        MLModel.id == scenario_id, MLModel.tenant_id == ctx.tenant_id,
        MLModel.kind == "scenario"))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Scenario not found")
    return {"name": m.name,
            **(await _what_if(session, ctx, WhatIfIn(**m.config)))}


# ---- root-cause workflow ----
class RootCauseIn(BaseModel):
    dataset_id: str
    value_column: str
    date_column: str
    dimensions: list[str] = Field(min_length=1, max_length=5)


@router.post("/root-cause")
async def root_cause(body: RootCauseIn,
                     ctx: TenantContext = Depends(require("dataset:read")),
                     session=Depends(get_session)):
    """Root-cause workflow: period-over-period change attributed across
    EVERY requested dimension; the dimension with the most concentrated
    single-segment delta is the prime suspect."""
    ds = (await session.execute(select(Dataset).where(
        Dataset.id == body.dataset_id,
        Dataset.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    findings = []
    for dim in body.dimensions:
        pop = await narrative.pop_kpi(session, ds,
                                      f"sum({body.value_column})",
                                      body.date_column, dim)
        top = pop["drivers"][0] if pop["drivers"] else None
        findings.append({"dimension": dim, "change": pop["change"],
                         "top_segment": top,
                         "concentration": round(abs(top["delta"])
                                                / abs(pop["change"]), 3)
                         if top and pop["change"] else 0})
    findings.sort(key=lambda f: -f["concentration"])
    prime = findings[0] if findings else None
    return {"workflow": ["detect period-over-period change",
                         "attribute across each dimension",
                         "rank by concentration of the change"],
            "findings": findings,
            "prime_suspect": (f"{prime['dimension']}="
                              f"{prime['top_segment']['group']} explains "
                              f"{prime['concentration'] * 100:.0f}% of the "
                              "change") if prime and prime["top_segment"]
            else "no dominant driver found",
            "windows": (await narrative.pop_kpi(
                session, ds, f"sum({body.value_column})",
                body.date_column, None))["windows"]}


# ---- Azure ML config (external model registry) ----
class AzureIn(BaseModel):
    workspace_url: str = Field(pattern="^https://.+\\.azureml\\.net",
                               max_length=500)
    endpoint_name: str = Field(min_length=1, max_length=200)


@router.put("/azure")
async def configure_azure(body: AzureIn,
                          ctx: TenantContext = Depends(require("tenant:manage")),
                          session=Depends(get_session)):
    """Azure ML integration: registers the external scoring endpoint as an
    'external' model. Invocation wiring (managed identity + scoring call)
    is the documented deployment step — external calls are never faked."""
    t = (await session.execute(select(Tenant).where(
        Tenant.id == ctx.tenant_id))).scalar_one()
    t.features = {**(t.features or {}), "azure_ml": body.model_dump()}
    m = MLModel(id=uuid7(), tenant_id=ctx.tenant_id,
                name=f"azure:{body.endpoint_name}", kind="external",
                config=body.model_dump(),
                metrics={"status": "configured, not yet invoked"})
    session.add(m)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="ml.azure_configure",
                       resource_type="ml_model", resource_id=str(m.id))
    await session.commit()
    return {"registered": str(m.id), "azure_ml": t.features["azure_ml"]}
