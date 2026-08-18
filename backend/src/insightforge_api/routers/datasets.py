"""Dataset catalog, uploads (CSV/XLSX through the trust pipeline), preview
with quarantine drill-through, quality trend, semantic measures, alerts,
neutralized CSV export, lineage."""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, text

from .. import audit
from ..deps import TenantContext, get_session, require
from ..models import (
    AlertRule,
    Connection,
    Dataset,
    DatasetRow,
    DQHistory,
    DQResult,
    Measure,
    Workspace,
)
from ..services import entitlements, ingest, narrative, nlq, prepsvc, querysvc
from ..services.formulas import FormulaError, compile_formula
from ..services.reportsvc import neutralize_csv_cell, safe_filename
from .auth import _uuid_or_422

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


async def _dataset_or_404(session, ctx, dataset_id) -> Dataset:
    did = _uuid_or_422(dataset_id, "dataset_id")
    ds = (await session.execute(select(Dataset).where(
        Dataset.id == did, Dataset.tenant_id == ctx.tenant_id,
        Dataset.archived.is_(False)))).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    return ds


def _dataset_out(ds: Dataset, connection_name: str | None = None) -> dict:
    return {"id": str(ds.id), "workspace_id": str(ds.workspace_id), "name": ds.name,
            "source_type": ds.source_type,
            "connection_id": str(ds.connection_id) if ds.connection_id else None,
            "connection_name": connection_name, "schema": ds.schema_def,
            "row_count": ds.row_count, "quarantined_count": ds.quarantined_count,
            "quality_score": ds.quality_score, "profile": ds.profile,
            "ingested_at": ds.ingested_at.isoformat() if ds.ingested_at else None,
            "current_import_id": str(ds.current_import_id) if ds.current_import_id else None}


@router.get("")
async def catalog(ctx: TenantContext = Depends(require("dataset:read")),
                  session=Depends(get_session)):
    rows = (await session.execute(
        select(Dataset, Connection.name)
        .join(Connection, Connection.id == Dataset.connection_id, isouter=True)
        .where(Dataset.tenant_id == ctx.tenant_id, Dataset.archived.is_(False))
        .order_by(desc(Dataset.created_at)))).all()
    return [_dataset_out(ds, cname) for ds, cname in rows]


@router.post("/upload", status_code=201)
async def upload(request: Request, file: UploadFile, workspace_id: str = Query(...),
                 name: str = Query(..., min_length=1, max_length=255),
                 ctx: TenantContext = Depends(require("dataset:create")),
                 session=Depends(get_session)):
    wid = _uuid_or_422(workspace_id, "workspace_id")
    ws = (await session.execute(select(Workspace).where(
        Workspace.id == wid, Workspace.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    await entitlements.enforce_quota(session, ctx.tenant_id, "datasets", Dataset,
                                     (Dataset.tenant_id == ctx.tenant_id)
                                     & Dataset.archived.is_(False))
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 15 MB — split it or use a connector")
    fname = (file.filename or "").lower()
    try:
        if fname.endswith((".xlsx", ".xlsm")):
            headers, rows = ingest.parse_xlsx(content)
        else:
            headers, rows = ingest.parse_csv(content)
        pipeline = ingest.run_pipeline(headers, rows)
    except ingest.IngestError as e:
        raise HTTPException(422, str(e)) from None

    from ..models import uuid7

    ds = Dataset(tenant_id=ctx.tenant_id, workspace_id=wid, name=name, source_type="upload",
                 created_by=ctx.user_id)
    session.add(ds)
    await session.flush()
    import_id = uuid7()
    for bucket, quarantined in ((pipeline["records"], False), (pipeline["quarantined"], True)):
        for rec in bucket:
            session.add(DatasetRow(tenant_id=ctx.tenant_id, dataset_id=ds.id,
                                   import_id=import_id, row_index=rec["row_index"],
                                   data=rec["data"], is_quarantined=quarantined,
                                   quarantine_reason=rec["reason"]))
    for dq in pipeline["dq"]:
        session.add(DQResult(tenant_id=ctx.tenant_id, dataset_id=ds.id, import_id=import_id,
                             rule=dq["rule"], severity=dq["severity"],
                             affected=dq["affected"], detail=dq["detail"]))
    session.add(DQHistory(tenant_id=ctx.tenant_id, dataset_id=ds.id,
                          score=pipeline["quality_score"], row_count=pipeline["row_count"],
                          quarantined_count=pipeline["quarantined_count"]))
    from datetime import datetime, timezone

    ds.schema_def = pipeline["schema"]
    ds.row_count = pipeline["row_count"]
    ds.quarantined_count = pipeline["quarantined_count"]
    ds.quality_score = pipeline["quality_score"]
    ds.profile = pipeline["profile"]
    ds.current_import_id = import_id
    ds.ingested_at = datetime.now(timezone.utc)
    await entitlements.meter(session, ctx.tenant_id, "upload.rows", pipeline["row_count"])
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="dataset.uploaded", resource_type="dataset",
                       resource_id=str(ds.id),
                       detail={"rows": pipeline["row_count"],
                               "quarantined": pipeline["quarantined_count"]},
                       correlation_id=ctx.correlation_id)
    await session.commit()
    return _dataset_out(ds)


@router.get("/{dataset_id}")
async def detail(dataset_id: str, ctx: TenantContext = Depends(require("dataset:read")),
                 session=Depends(get_session)):
    ds = await _dataset_or_404(session, ctx, dataset_id)
    dq = (await session.execute(select(DQResult).where(
        DQResult.dataset_id == ds.id,
        DQResult.import_id == ds.current_import_id))).scalars()
    out = _dataset_out(ds)
    out["dq_results"] = [{"rule": r.rule, "severity": r.severity, "affected": r.affected,
                          "detail": r.detail} for r in dq]
    out["lineage"] = {"source": ds.source_type, "connection_id":
                      str(ds.connection_id) if ds.connection_id else None,
                      "import_id": str(ds.current_import_id) if ds.current_import_id else None,
                      "ingested_at": out["ingested_at"]}
    return out


@router.get("/{dataset_id}/preview")
async def preview(dataset_id: str, limit: int = 50, include_quarantined: bool = False,
                  filters: str | None = None,
                  ctx: TenantContext = Depends(require("dataset:read")),
                  session=Depends(get_session)):
    """Preview / drill-through: `filters` is a JSON array of
    {column, op, value} — the same shape dashboards use, enabling
    "view underlying rows" from any chart segment."""
    ds = await _dataset_or_404(session, ctx, dataset_id)
    parsed = []
    if filters:
        import json as _json
        try:
            parsed = _json.loads(filters)
            assert isinstance(parsed, list)
        except Exception:  # noqa: BLE001
            raise HTTPException(422, "filters must be a JSON array") from None
    return await querysvc.fetch_table(
        session, dataset_id=ds.id, current_import_id=ds.current_import_id,
        dataset_schema=ds.schema_def, limit=limit,
        include_quarantined=include_quarantined, filters=parsed)


@router.get("/{dataset_id}/dq-history")
async def dq_history(dataset_id: str, ctx: TenantContext = Depends(require("dataset:read")),
                     session=Depends(get_session)):
    ds = await _dataset_or_404(session, ctx, dataset_id)
    rows = (await session.execute(select(DQHistory).where(DQHistory.dataset_id == ds.id)
                                  .order_by(DQHistory.recorded_at).limit(200))).scalars()
    return [{"score": h.score, "row_count": h.row_count,
             "quarantined_count": h.quarantined_count,
             "at": h.recorded_at.isoformat()} for h in rows]


@router.patch("/{dataset_id}")
async def archive_or_rename(dataset_id: str, body: dict,
                            ctx: TenantContext = Depends(require("dataset:create")),
                            session=Depends(get_session)):
    ds = await _dataset_or_404(session, ctx, dataset_id)
    if "name" in body:
        ds.name = str(body["name"])[:255]
    if body.get("archived") is True:
        ds.archived = True
        await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                           action="dataset.archived", resource_type="dataset",
                           resource_id=str(ds.id))
    await session.commit()
    return _dataset_out(ds)


@router.get("/{dataset_id}/export.csv")
async def export_csv(dataset_id: str, ctx: TenantContext = Depends(require("dataset:export")),
                     session=Depends(get_session)):
    ds = await _dataset_or_404(session, ctx, dataset_id)
    table = await querysvc.fetch_table(
        session, dataset_id=ds.id, current_import_id=ds.current_import_id,
        dataset_schema=ds.schema_def, limit=querysvc.TABLE_LIMIT)
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="dataset.exported", resource_type="dataset",
                       resource_id=str(ds.id))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(table["columns"])
    for row in table["rows"]:
        writer.writerow([neutralize_csv_cell(row.get(c)) for c in table["columns"]])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{safe_filename(ds.name, "csv")}"'})


@router.get("/{dataset_id}/export.xlsx")
async def export_xlsx(dataset_id: str,
                      ctx: TenantContext = Depends(require("dataset:export")),
                      session=Depends(get_session)):
    """R4: Excel export with a WATERMARK sheet header — who exported what,
    when, from which tenant. Export leakage becomes attributable."""
    from datetime import datetime, timezone

    from openpyxl import Workbook

    ds = await _dataset_or_404(session, ctx, dataset_id)
    table = await querysvc.fetch_table(
        session, dataset_id=ds.id, current_import_id=ds.current_import_id,
        dataset_schema=ds.schema_def, limit=querysvc.TABLE_LIMIT)
    wb = Workbook()
    sh = wb.active
    sh.title = "data"
    stamp = (f"CONFIDENTIAL · {ds.name} · exported "
             f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} "
             f"· user {ctx.user_id} · tenant {ctx.tenant_id}")
    sh.append([stamp])
    sh.append(table["columns"])
    for row in table["rows"]:
        sh.append([neutralize_csv_cell(row.get(c))
                   for c in table["columns"]])
    sh.oddFooter.center.text = stamp[:250]
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="dataset.exported",
                       resource_type="dataset", resource_id=str(ds.id),
                       detail={"format": "xlsx"})
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument"
                        ".spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="{safe_filename(ds.name, "xlsx")}"'})


@router.get("/{dataset_id}/histogram")
async def histogram(dataset_id: str, column: str, bins: int = 10,
                    ctx: TenantContext = Depends(require("dataset:read")),
                    session=Depends(get_session)):
    """R4 viz data: deterministic equal-width binning for histogram charts
    (renderable via SDK/embed or any client)."""
    from sqlalchemy import text as _t

    ds = await _dataset_or_404(session, ctx, dataset_id)
    if bins < 2 or bins > 50:
        raise HTTPException(422, "bins must be 2..50")
    if column not in {c["name"] for c in ds.schema_def
                      if c["inferred_type"] in ("number", "integer")}:
        raise HTTPException(422, f"'{column}' is not a numeric column")
    rows = (await session.execute(_t(
        "SELECT (data->>:c)::numeric AS v FROM dataset_rows "
        "WHERE dataset_id = :d AND import_id = :i "
        "AND NOT is_quarantined AND data->>:c IS NOT NULL"),
        {"c": column, "d": str(ds.id),
         "i": str(ds.current_import_id)})).scalars().all()
    vals = [float(v) for v in rows]
    if not vals:
        return {"bins": [], "column": column}
    lo, hi = min(vals), max(vals)
    width = (hi - lo) / bins or 1.0
    counts = [0] * bins
    for v in vals:
        idx = min(int((v - lo) / width), bins - 1)
        counts[idx] += 1
    return {"column": column, "min": lo, "max": hi, "bin_width": width,
            "bins": [{"from": round(lo + i * width, 4),
                      "to": round(lo + (i + 1) * width, 4),
                      "count": c} for i, c in enumerate(counts)]}


@router.get("/{dataset_id}/scatter")
async def scatter(dataset_id: str, x: str, y: str, limit: int = 500,
                  ctx: TenantContext = Depends(require("dataset:read")),
                  session=Depends(get_session)):
    """R4 viz data: (x, y) pairs for scatter plots — governed, row-capped."""
    from sqlalchemy import text as _t

    ds = await _dataset_or_404(session, ctx, dataset_id)
    numeric = {c["name"] for c in ds.schema_def
               if c["inferred_type"] in ("number", "integer")}
    if x not in numeric or y not in numeric:
        raise HTTPException(422, "x and y must be numeric columns")
    limit = max(10, min(limit, 2000))
    rows = (await session.execute(_t(
        "SELECT (data->>:x)::numeric, (data->>:y)::numeric FROM dataset_rows "
        "WHERE dataset_id = :d AND import_id = :i AND NOT is_quarantined "
        "AND data->>:x IS NOT NULL AND data->>:y IS NOT NULL "
        "LIMIT :n"),
        {"x": x, "y": y, "d": str(ds.id),
         "i": str(ds.current_import_id), "n": limit})).all()
    return {"x": x, "y": y,
            "points": [[float(a), float(b)] for a, b in rows],
            "capped_at": limit}


# ---------------- AI insights (ml/ package) ----------------
@router.get("/{dataset_id}/insights")
async def insights(dataset_id: str, value_column: str, date_column: str,
                   horizon: int = 6,
                   ctx: TenantContext = Depends(require("dataset:read")),
                   session=Depends(get_session)):
    """Forecast + anomaly detection over a governed dataset series.

    Aggregates `value_column` (sum) per `date_column`, ordered, from the
    current import's clean rows — the same trust boundary every widget uses —
    then runs the insightforge_ml models. Facts, forecasts and anomalies are
    labelled distinctly so the UI can present them honestly.
    """
    from insightforge_ml import detect_anomalies, forecast_series

    ds = await _dataset_or_404(session, ctx, dataset_id)
    cols = {c["name"]: c["inferred_type"] for c in ds.schema_def}
    if value_column not in cols or cols[value_column] not in ("number", "integer"):
        raise HTTPException(422, f"value_column must be a numeric column "
                                 f"(got {value_column!r})")
    if date_column not in cols:
        raise HTTPException(422, f"date_column {date_column!r} is not in this dataset")
    rows_q = (await session.execute(select(DatasetRow).where(
        DatasetRow.dataset_id == ds.id,
        DatasetRow.import_id == ds.current_import_id,
        DatasetRow.is_quarantined.is_(False)))).scalars().all()
    buckets: dict[str, float] = {}
    for r in rows_q:
        key = str(r.data.get(date_column, "") or "")
        try:
            val = float(str(r.data.get(value_column, "") or "").replace(",", ""))
        except ValueError:
            continue
        if key:
            buckets[key] = buckets.get(key, 0.0) + val
    labels = sorted(buckets)
    series = [round(buckets[k], 4) for k in labels]
    out = {"dataset_id": str(ds.id), "value_column": value_column,
           "date_column": date_column, "series": [
               {"label": k, "value": v} for k, v in zip(labels, series)],
           "freshness": ds.ingested_at.isoformat(),
           "quality_score": ds.quality_score}
    try:
        out["forecast"] = forecast_series(series, horizon=horizon)
    except ValueError as e:
        out["forecast"] = {"error": str(e)}
    try:
        out["anomalies"] = detect_anomalies(series, labels=labels)
    except ValueError as e:
        out["anomalies"] = {"error": str(e)}
    return out


# ---------------- Cleaning recipes ----------------
class RecipeIn(BaseModel):
    steps: list


@router.get("/{dataset_id}/recipe")
async def get_recipe(dataset_id: str, ctx: TenantContext = Depends(require("dataset:read")),
                     session=Depends(get_session)):
    ds = await _dataset_or_404(session, ctx, dataset_id)
    return {"steps": ds.recipe,
            "ops": sorted(ingest.RECIPE_OPS)}


@router.post("/{dataset_id}/recipe/apply")
async def apply_recipe(dataset_id: str, body: RecipeIn,
                       ctx: TenantContext = Depends(require("dataset:create")),
                       session=Depends(get_session)):
    """Apply cleaning steps to ALL rows of the current import (including
    quarantined ones — cleaning is how you rescue them), then re-run the full
    trust pipeline into a new generation: types re-inferred, DQ re-scored,
    lineage advanced. The recipe is saved on the dataset."""
    ds = await _dataset_or_404(session, ctx, dataset_id)
    headers = [c["name"] for c in ds.schema_def]
    try:
        steps = ingest.validate_recipe(body.steps, headers)
    except ingest.IngestError as e:
        raise HTTPException(422, str(e)) from None
    rows_q = (await session.execute(select(DatasetRow).where(
        DatasetRow.dataset_id == ds.id,
        DatasetRow.import_id == ds.current_import_id)
        .order_by(DatasetRow.row_index))).scalars().all()
    raw = [[str(r.data.get(h, "") or "") for h in headers] for r in rows_q]
    cleaned = ingest.apply_recipe(headers, raw, steps)
    pipeline = ingest.run_pipeline(headers, cleaned)

    from ..models import uuid7
    import_id = uuid7()
    for bucket, quarantined in ((pipeline["records"], False),
                                (pipeline["quarantined"], True)):
        for rec in bucket:
            session.add(DatasetRow(tenant_id=ctx.tenant_id, dataset_id=ds.id,
                                   import_id=import_id, row_index=rec["row_index"],
                                   data=rec["data"], is_quarantined=quarantined,
                                   quarantine_reason=rec["reason"]))
    for dq in pipeline["dq"]:
        session.add(DQResult(tenant_id=ctx.tenant_id, dataset_id=ds.id,
                             import_id=import_id, rule=dq["rule"],
                             severity=dq["severity"], affected=dq["affected"],
                             detail=dq["detail"]))
    session.add(DQHistory(tenant_id=ctx.tenant_id, dataset_id=ds.id,
                          score=pipeline["quality_score"],
                          row_count=pipeline["row_count"],
                          quarantined_count=pipeline["quarantined_count"]))
    from datetime import datetime, timezone
    ds.schema_def = pipeline["schema"]
    ds.row_count = pipeline["row_count"]
    ds.quarantined_count = pipeline["quarantined_count"]
    ds.quality_score = pipeline["quality_score"]
    ds.profile = pipeline["profile"]
    ds.recipe = steps
    ds.current_import_id = import_id
    ds.ingested_at = datetime.now(timezone.utc)
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="dataset.recipe_applied", resource_type="dataset",
                       resource_id=str(ds.id), detail={"steps": len(steps)})
    await session.commit()
    return _dataset_out(ds)


# ---------------- Semantic layer: governed measures ----------------
class MeasureIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    formula: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=500)
    certified: bool = False


@router.get("/{dataset_id}/measures")
async def list_measures(dataset_id: str, ctx: TenantContext = Depends(require("dataset:read")),
                        session=Depends(get_session)):
    ds = await _dataset_or_404(session, ctx, dataset_id)
    rows = (await session.execute(select(Measure).where(Measure.dataset_id == ds.id)
                                  .order_by(Measure.created_at))).scalars()
    return [{"id": str(m.id), "name": m.name, "formula": m.formula,
             "description": m.description, "certified": m.certified} for m in rows]


@router.post("/{dataset_id}/measures", status_code=201)
async def create_measure(dataset_id: str, body: MeasureIn,
                         ctx: TenantContext = Depends(require("measure:create")),
                         session=Depends(get_session)):
    ds = await _dataset_or_404(session, ctx, dataset_id)
    try:
        compile_formula(body.formula, ds.schema_def)
    except FormulaError as e:
        raise HTTPException(422, f"Formula error: {e}") from None
    m = Measure(tenant_id=ctx.tenant_id, dataset_id=ds.id, name=body.name,
                formula=body.formula, description=body.description,
                certified=body.certified, created_by=ctx.user_id)
    session.add(m)
    await session.flush()
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="measure.created", resource_type="measure", resource_id=str(m.id),
                       detail={"formula": body.formula})
    await session.commit()
    return {"id": str(m.id), "name": m.name, "formula": m.formula, "certified": m.certified}


@router.get("/{dataset_id}/measures/{measure_id}/result")
async def measure_result(dataset_id: str, measure_id: str, group_by: str | None = None,
                         ctx: TenantContext = Depends(require("dataset:read")),
                         session=Depends(get_session)):
    ds = await _dataset_or_404(session, ctx, dataset_id)
    mid = _uuid_or_422(measure_id, "measure_id")
    m = (await session.execute(select(Measure).where(
        Measure.id == mid, Measure.dataset_id == ds.id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Measure not found")
    try:
        return await querysvc.execute_formula(
            session, dataset_id=ds.id, current_import_id=ds.current_import_id,
            dataset_schema=ds.schema_def, formula=m.formula, group_by=group_by)
    except querysvc.QueryError as e:
        raise HTTPException(422, str(e)) from None


# ---------------- Threshold alerts ----------------
class AlertIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    formula: str = Field(min_length=1, max_length=500)
    kind: str = Field(default="threshold", pattern="^(threshold|anomaly)$")
    operator: str = "gt"           # threshold rules only
    threshold: float = 0.0         # threshold rules only
    date_column: str | None = None  # anomaly rules only
    interval_minutes: int = Field(default=60, ge=1)
    recipients: list[str] = []


@router.get("/{dataset_id}/alerts")
async def list_alerts(dataset_id: str, ctx: TenantContext = Depends(require("dataset:read")),
                      session=Depends(get_session)):
    ds = await _dataset_or_404(session, ctx, dataset_id)
    rows = (await session.execute(select(AlertRule).where(
        AlertRule.dataset_id == ds.id))).scalars()
    return [{"id": str(a.id), "name": a.name, "formula": a.formula, "operator": a.operator,
             "threshold": a.threshold, "interval_minutes": a.interval_minutes,
             "enabled": a.enabled, "last_state": a.last_state,
             "recipients": a.recipients} for a in rows]


@router.post("/{dataset_id}/alerts", status_code=201)
async def create_alert(dataset_id: str, body: AlertIn,
                       ctx: TenantContext = Depends(require("measure:create")),
                       session=Depends(get_session)):
    if body.kind == "threshold" and body.operator not in ("gt", "gte", "lt", "lte"):
        raise HTTPException(422, "operator must be gt, gte, lt, or lte")
    ds = await _dataset_or_404(session, ctx, dataset_id)
    if body.kind == "anomaly":
        date_cols = [c["name"] for c in ds.schema_def
                     if c["inferred_type"] in ("date", "timestamp")]
        if body.date_column not in date_cols:
            available = ", ".join(date_cols) or "none — this dataset has no date column"
            raise HTTPException(
                422, "Anomaly alerts need a date column to aggregate by; "
                     f"available: {available}")
    try:
        compile_formula(body.formula, ds.schema_def)
    except FormulaError as e:
        raise HTTPException(422, f"Formula error: {e}") from None
    await entitlements.enforce_quota(session, ctx.tenant_id, "alerts", AlertRule,
                                     AlertRule.tenant_id == ctx.tenant_id)
    await entitlements.enforce_min_interval(session, ctx.tenant_id, body.interval_minutes)
    rule = AlertRule(tenant_id=ctx.tenant_id, dataset_id=ds.id, name=body.name,
                     formula=body.formula, operator=body.operator, threshold=body.threshold,
                     kind=body.kind, date_column=body.date_column,
                     interval_minutes=body.interval_minutes, recipients=body.recipients,
                     created_by=ctx.user_id)
    session.add(rule)
    await session.flush()
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="alert.created", resource_type="alert", resource_id=str(rule.id))
    await session.commit()
    return {"id": str(rule.id), "name": rule.name}


@router.patch("/{dataset_id}/alerts/{alert_id}")
async def toggle_alert(dataset_id: str, alert_id: str, body: dict,
                       ctx: TenantContext = Depends(require("measure:create")),
                       session=Depends(get_session)):
    ds = await _dataset_or_404(session, ctx, dataset_id)
    aid = _uuid_or_422(alert_id, "alert_id")
    rule = (await session.execute(select(AlertRule).where(
        AlertRule.id == aid, AlertRule.dataset_id == ds.id))).scalar_one_or_none()
    if rule is None:
        raise HTTPException(404, "Alert not found")
    if "enabled" in body:
        rule.enabled = bool(body["enabled"])
    await session.commit()
    return {"id": str(rule.id), "enabled": rule.enabled}


# ---------------------------------------------------------------------------
# MVP3: governed natural-language questions (ADR 0013)
# ---------------------------------------------------------------------------

class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=nlq.MAX_QUESTION_LEN)


@router.get("/{dataset_id}/prep-suggestions")
async def prep_suggestions(dataset_id: str,
                           ctx: TenantContext = Depends(require("dataset:read")),
                           session=Depends(get_session)):
    """MVP3: AI-assisted data preparation — diagnosed from this dataset's own
    values and quarantine; every suggestion is one click from applied."""
    ds = await _dataset_or_404(session, ctx, dataset_id)
    suggestions = await prepsvc.suggest(session, ds)
    return {"suggestions": suggestions,
            "note": ("Each suggestion names its evidence. Applying uses the "
                     "same recipe engine as manual cleaning and re-scores the "
                     "dataset.") if suggestions else
                    "Nothing to suggest — this dataset already looks clean."}


class JoinIn(BaseModel):
    left_id: str
    right_id: str
    left_key: str
    right_key: str
    name: str = Field(min_length=1, max_length=255)
    how: str = Field(default="inner", pattern="^(inner|left)$")


async def _rows_of(session, ds) -> list[dict]:
    from sqlalchemy import text as _t

    rows = (await session.execute(_t(
        "SELECT data FROM dataset_rows WHERE dataset_id = :d "
        "AND import_id = :i AND NOT is_quarantined"),
        {"d": str(ds.id), "i": str(ds.current_import_id)})).scalars().all()
    return list(rows)


async def _materialize(request, session, ctx, workspace_id, name,
                       headers, dicts):
    """R5: turn derived rows into a NEW dataset through the SAME trust
    pipeline (typing, quality, quarantine, lineage) via the CSV path."""
    import csv as _csv
    import io as _io

    from starlette.datastructures import UploadFile as _SUF

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(headers)
    for d in dicts:
        w.writerow(["" if d.get(h) is None else str(d.get(h))
                    for h in headers])
    f = _SUF(filename=name + ".csv",
             file=_io.BytesIO(buf.getvalue().encode()))
    return await upload(request=request, file=f, workspace_id=workspace_id,
                        name=name, ctx=ctx, session=session)


@router.post("/join", status_code=201)
async def join_datasets(request: Request, body: JoinIn,
                        ctx: TenantContext = Depends(require("dataset:create")),
                        session=Depends(get_session)):
    """R5: governed cross-dataset join -> a new dataset. Right columns are
    prefixed on collision; provenance in the description."""
    left = await _dataset_or_404(session, ctx, body.left_id)
    right = await _dataset_or_404(session, ctx, body.right_id)
    lcols = {c["name"] for c in left.schema_def}
    rcols = {c["name"] for c in right.schema_def}
    if body.left_key not in lcols or body.right_key not in rcols:
        raise HTTPException(422, "Join keys must exist in their datasets")
    lrows, rrows = await _rows_of(session, left), await _rows_of(session, right)
    if len(lrows) * max(len(rrows), 1) > 2_000_000:
        raise HTTPException(422, "Join too large (cap 2M row pairs)")
    index: dict = {}
    for r in rrows:
        index.setdefault(str(r.get(body.right_key)), []).append(r)
    rename = {c: (c if c not in lcols or c == body.right_key
                  else f"{right.name}_{c}") for c in rcols}
    headers = list(lcols) + [rename[c] for c in rcols if c != body.right_key]
    out = []
    for lrow in lrows:
        matches = index.get(str(lrow.get(body.left_key)), [])
        if not matches and body.how == "left":
            out.append(dict(lrow))
        for m in matches:
            merged = dict(lrow)
            for c in rcols:
                if c != body.right_key:
                    merged[rename[c]] = m.get(c)
            out.append(merged)
    ds = await _materialize(request, session, ctx, str(left.workspace_id),
                            body.name, headers, out)
    return ds


class UnionIn(BaseModel):
    left_id: str
    right_id: str
    name: str = Field(min_length=1, max_length=255)


@router.post("/union", status_code=201)
async def union_datasets(request: Request, body: UnionIn,
                         ctx: TenantContext = Depends(require("dataset:create")),
                         session=Depends(get_session)):
    """R7: stack two datasets -> new dataset via the trust pipeline.
    Columns are the ordered union; missing values are empty (typing and
    quality judge the result honestly)."""
    left = await _dataset_or_404(session, ctx, body.left_id)
    right = await _dataset_or_404(session, ctx, body.right_id)
    headers = [c["name"] for c in left.schema_def]
    headers += [c["name"] for c in right.schema_def
                if c["name"] not in headers]
    rows = (await _rows_of(session, left)) + (await _rows_of(session, right))
    if len(rows) > 500_000:
        raise HTTPException(422, "Union too large (cap 500k rows)")
    return await _materialize(request, session, ctx,
                              str(left.workspace_id), body.name,
                              headers, rows)


class PivotIn(BaseModel):
    index: str
    columns: str
    value: str
    name: str = Field(min_length=1, max_length=255)


@router.post("/{dataset_id}/pivot", status_code=201)
async def pivot_dataset(request: Request, dataset_id: str, body: PivotIn,
                        ctx: TenantContext = Depends(require("dataset:create")),
                        session=Depends(get_session)):
    """R5: cross-tab (sum) -> new dataset. index rows x columns values."""
    ds = await _dataset_or_404(session, ctx, dataset_id)
    names = {c["name"] for c in ds.schema_def}
    if {body.index, body.columns, body.value} - names:
        raise HTTPException(422, "index/columns/value must be columns")
    rows = await _rows_of(session, ds)
    col_vals = sorted({str(r.get(body.columns)) for r in rows})[:50]
    table: dict = {}
    for r in rows:
        key = str(r.get(body.index))
        cell = str(r.get(body.columns))
        try:
            v = float(r.get(body.value) or 0)
        except (TypeError, ValueError):
            continue
        table.setdefault(key, dict.fromkeys(col_vals, 0.0))
        if cell in table[key]:
            table[key][cell] += v
    headers = [body.index] + col_vals
    out = [{body.index: k, **{c: round(v, 4) for c, v in cells.items()}}
           for k, cells in sorted(table.items())]
    return await _materialize(request, session, ctx, str(ds.workspace_id),
                              body.name, headers, out)


class UnpivotIn(BaseModel):
    id_column: str
    value_columns: list[str] = Field(min_length=2, max_length=30)
    name: str = Field(min_length=1, max_length=255)


@router.post("/{dataset_id}/unpivot", status_code=201)
async def unpivot_dataset(request: Request, dataset_id: str, body: UnpivotIn,
                          ctx: TenantContext = Depends(
                              require("dataset:create")),
                          session=Depends(get_session)):
    """R8: wide -> long. Each value column becomes (metric, value) rows."""
    ds = await _dataset_or_404(session, ctx, dataset_id)
    names = {c["name"] for c in ds.schema_def}
    if {body.id_column, *body.value_columns} - names:
        raise HTTPException(422, "All columns must exist on the dataset")
    rows = await _rows_of(session, ds)
    out = [{body.id_column: r.get(body.id_column), "metric": vc,
            "value": r.get(vc)} for r in rows for vc in body.value_columns]
    return await _materialize(request, session, ctx, str(ds.workspace_id),
                              body.name, [body.id_column, "metric", "value"],
                              out)


class SplitIn(BaseModel):
    column: str
    delimiter: str = Field(min_length=1, max_length=5)
    into: list[str] = Field(min_length=2, max_length=6)
    name: str = Field(min_length=1, max_length=255)


@router.post("/{dataset_id}/split-column", status_code=201)
async def split_column(request: Request, dataset_id: str, body: SplitIn,
                       ctx: TenantContext = Depends(require("dataset:create")),
                       session=Depends(get_session)):
    """R8: split one column into parts by delimiter -> new dataset."""
    ds = await _dataset_or_404(session, ctx, dataset_id)
    if body.column not in {c["name"] for c in ds.schema_def}:
        raise HTTPException(422, f"'{body.column}' not on dataset")
    rows = await _rows_of(session, ds)
    headers = [c["name"] for c in ds.schema_def] + body.into
    out = []
    for r in rows:
        d = dict(r)
        parts = str(r.get(body.column) or "").split(body.delimiter)
        for i, col in enumerate(body.into):
            d[col] = parts[i].strip() if i < len(parts) else ""
        out.append(d)
    return await _materialize(request, session, ctx, str(ds.workspace_id),
                              body.name, headers, out)


class MergeIn(BaseModel):
    columns: list[str] = Field(min_length=2, max_length=6)
    delimiter: str = Field(default=" ", max_length=5)
    into: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=255)


@router.post("/{dataset_id}/merge-columns", status_code=201)
async def merge_columns(request: Request, dataset_id: str, body: MergeIn,
                        ctx: TenantContext = Depends(require("dataset:create")),
                        session=Depends(get_session)):
    """R8: concatenate columns into one -> new dataset."""
    ds = await _dataset_or_404(session, ctx, dataset_id)
    names = {c["name"] for c in ds.schema_def}
    if set(body.columns) - names:
        raise HTTPException(422, "All columns must exist on the dataset")
    rows = await _rows_of(session, ds)
    headers = [c["name"] for c in ds.schema_def] + [body.into]
    out = []
    for r in rows:
        d = dict(r)
        d[body.into] = body.delimiter.join(
            str(r.get(c) or "").strip() for c in body.columns).strip()
        out.append(d)
    return await _materialize(request, session, ctx, str(ds.workspace_id),
                              body.name, headers, out)


class DeriveIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    column: str = Field(min_length=1, max_length=120)
    left: str
    op: str = Field(pattern="^[-+*/]$")
    right: str  # column name or numeric constant


@router.post("/{dataset_id}/derive", status_code=201)
async def derive_column(request: Request, dataset_id: str, body: DeriveIn,
                        ctx: TenantContext = Depends(require("dataset:create")),
                        session=Depends(get_session)):
    """R5 formula column: left <op> right (column or constant) -> new
    dataset with the derived column. Deterministic, no eval()."""
    ds = await _dataset_or_404(session, ctx, dataset_id)
    numeric = {c["name"] for c in ds.schema_def
               if c["inferred_type"] in ("number", "integer")}
    if body.left not in numeric:
        raise HTTPException(422, f"'{body.left}' must be numeric")
    const = None
    if body.right not in numeric:
        try:
            const = float(body.right)
        except ValueError:
            raise HTTPException(422, f"'{body.right}' is neither a numeric "
                                     "column nor a constant") from None
    rows = await _rows_of(session, ds)
    headers = [c["name"] for c in ds.schema_def] + [body.column]
    out = []
    for r in rows:
        d = dict(r)
        try:
            a = float(r.get(body.left) or 0)
            b = const if const is not None else float(r.get(body.right) or 0)
            v = (a + b if body.op == "+" else a - b if body.op == "-"
                 else a * b if body.op == "*" else (a / b if b else None))
            d[body.column] = "" if v is None else round(v, 6)
        except (TypeError, ValueError):
            d[body.column] = ""
        out.append(d)
    return await _materialize(request, session, ctx, str(ds.workspace_id),
                              body.name, headers, out)


@router.get("/{dataset_id}/timeseries")
async def timeseries(dataset_id: str, value: str, date: str,
                     grain: str = "month", currency_to: str | None = None,
                     ctx: TenantContext = Depends(require("dataset:read")),
                     session=Depends(get_session)):
    """R5 time grains + fiscal calendar + currency conversion in one
    governed endpoint. grain: day|week|month|quarter|fiscal_quarter.
    Fiscal year start + currency rates come from tenant semantics."""
    from sqlalchemy import text as _t

    ds = await _dataset_or_404(session, ctx, dataset_id)
    numeric = {c["name"] for c in ds.schema_def
               if c["inferred_type"] in ("number", "integer")}
    dates = {c["name"] for c in ds.schema_def
             if c["inferred_type"] in ("date", "timestamp")}
    if value not in numeric or date not in dates:
        raise HTTPException(422, "value must be numeric, date must be a "
                                 "date column")
    if grain not in ("day", "week", "month", "quarter", "fiscal_quarter"):
        raise HTTPException(422, "grain: day|week|month|quarter|"
                                 "fiscal_quarter")
    from ..models import Tenant as _T

    tenant = (await session.execute(select(_T).where(
        _T.id == ctx.tenant_id))).scalar_one()
    sem = (tenant.features or {}).get("semantics", {})
    fy_start = int(sem.get("fiscal_year_start_month", 1))
    rate = 1.0
    if currency_to:
        rates = (sem.get("currency") or {}).get("rates") or {}
        base = (sem.get("currency") or {}).get("base", "")
        if currency_to == base:
            rate = 1.0
        elif currency_to in rates:
            rate = float(rates[currency_to])
        else:
            raise HTTPException(422, f"No rate for {currency_to}; set it "
                                     "via PUT /tenants/semantics")
    sql_grain = "month" if grain in ("quarter", "fiscal_quarter") else grain
    rows = (await session.execute(_t(
        "SELECT date_trunc(:g, (data->>:dc)::date)::date AS p, "
        "sum((data->>:vc)::numeric) AS v FROM dataset_rows "
        "WHERE dataset_id = :d AND import_id = :i AND NOT is_quarantined "
        "AND data->>:dc IS NOT NULL AND data->>:vc IS NOT NULL "
        "GROUP BY 1 ORDER BY 1"),
        {"g": sql_grain, "dc": date, "vc": value, "d": str(ds.id),
         "i": str(ds.current_import_id)})).all()
    if grain in ("quarter", "fiscal_quarter"):
        agg: dict = {}
        for p, v in rows:
            if grain == "quarter":
                label = f"{p.year}-Q{(p.month - 1) // 3 + 1}"
            else:
                shifted = (p.month - fy_start + 12) % 12
                fy = p.year + (1 if p.month >= fy_start and fy_start > 1
                               else 0)
                label = f"FY{fy}-Q{shifted // 3 + 1}"
            agg[label] = agg.get(label, 0.0) + float(v)
        points = [{"period": k, "value": round(v * rate, 2)}
                  for k, v in sorted(agg.items())]
    else:
        points = [{"period": p.isoformat(),
                   "value": round(float(v) * rate, 2)} for p, v in rows]
    return {"grain": grain, "fiscal_year_start_month": fy_start,
            "currency": currency_to, "rate_applied": rate, "points": points}


@router.post("/upload-json", status_code=201)
async def upload_json(request: Request, file: UploadFile,
                      workspace_id: str = Query(...),
                      name: str = Query(..., min_length=1, max_length=255),
                      ctx: TenantContext = Depends(require("dataset:create")),
                      session=Depends(get_session)):
    """R2: JSON upload — an array of flat objects (or {records: [...]}).
    Converted to tabular form and fed through the SAME trust pipeline as
    CSV (typing, quality, quarantine, scoring)."""
    import csv as _csv
    import io as _io
    import json as _json

    from starlette.datastructures import UploadFile as _SUF

    from ..services.connectors.generic import records_to_result

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Upload too large")
    try:
        payload = _json.loads(raw)
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "File is not valid JSON") from None
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list) or not records:
        raise HTTPException(422, 'Expected a JSON array of objects '
                                 '(or {"records": [...]})')
    res = records_to_result(records, None, None)
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(res.headers)
    w.writerows(res.rows)
    csv_file = _SUF(filename=(name or "data") + ".csv",
                    file=_io.BytesIO(buf.getvalue().encode()))
    return await upload(request=request, file=csv_file,
                        workspace_id=workspace_id, name=name,
                        ctx=ctx, session=session)


class AlertLifecycleIn(BaseModel):
    quiet_start: str | None = Field(default=None,
                                    pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    quiet_end: str | None = Field(default=None,
                                  pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    escalate_after_minutes: int | None = Field(default=None, ge=5, le=1440)
    escalate_to: str | None = None


@router.put("/{dataset_id}/alerts/{rule_id}/lifecycle")
async def set_alert_lifecycle(dataset_id: str, rule_id: str,
                              body: AlertLifecycleIn,
                              ctx: TenantContext = Depends(
                                  require("dataset:create")),
                              session=Depends(get_session)):
    """R6: quiet hours (UTC) + escalation policy per alert rule."""
    from ..models import AlertRule

    rule = (await session.execute(select(AlertRule).where(
        AlertRule.id == rule_id, AlertRule.tenant_id == ctx.tenant_id,
        AlertRule.dataset_id == dataset_id))).scalar_one_or_none()
    if rule is None:
        raise HTTPException(404, "Alert rule not found")
    rule.lifecycle = {k: v for k, v in body.model_dump().items()
                      if v is not None}
    await session.commit()
    return {"lifecycle": rule.lifecycle}


@router.post("/{dataset_id}/alerts/{rule_id}/ack")
async def ack_alert(dataset_id: str, rule_id: str,
                    ctx: TenantContext = Depends(require("dataset:read")),
                    session=Depends(get_session)):
    """R6: acknowledge the latest firing — stops escalation, audited."""
    from ..models import AlertEvent

    ev = (await session.execute(select(AlertEvent).where(
        AlertEvent.rule_id == rule_id,
        AlertEvent.tenant_id == ctx.tenant_id).order_by(
        AlertEvent.fired_at.desc()))).scalars().first()
    if ev is None:
        raise HTTPException(404, "No firings to acknowledge")
    if ev.acked_at is None:
        from datetime import datetime, timezone

        ev.acked_at = datetime.now(timezone.utc)
        ev.acked_by = ctx.user_id
        await audit.record(session, tenant_id=ctx.tenant_id,
                           actor_user_id=ctx.user_id, action="alert.ack",
                           resource_type="alert", resource_id=str(rule_id))
        await session.commit()
    return {"acked_at": ev.acked_at.isoformat(), "by": str(ev.acked_by)}


class IssueIn(BaseModel):
    description: str = Field(min_length=5, max_length=2000)


@router.post("/{dataset_id}/issues", status_code=201)
async def report_data_issue(dataset_id: str, body: IssueIn,
                            ctx: TenantContext = Depends(
                                require("dataset:read")),
                            session=Depends(get_session)):
    """R6 collaboration: anyone who can read can flag a data issue; it
    lands in the approvals queue for admins to resolve."""
    from ..models import Approval, uuid7

    ds = await _dataset_or_404(session, ctx, dataset_id)
    a = Approval(id=uuid7(), tenant_id=ctx.tenant_id, kind="data_issue",
                 subject_id=str(ds.id), note=body.description,
                 requested_by=ctx.user_id)
    session.add(a)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="issue.report",
                       resource_type="dataset", resource_id=str(ds.id))
    await session.commit()
    return {"id": str(a.id), "status": "pending",
            "note": "Visible in the approvals queue (kind: data_issue)."}


@router.post("/{dataset_id}/pii-scan")
async def pii_scan(dataset_id: str,
                   ctx: TenantContext = Depends(require("tenant:manage")),
                   session=Depends(get_session)):
    """R1: scan sampled values per text column; SUGGEST classification —
    apply via PUT /governance after human review."""
    from sqlalchemy import text as _t

    from ..services import pii

    ds = await _dataset_or_404(session, ctx, dataset_id)
    found = {}
    for col in ds.schema_def:
        if col["inferred_type"] != "text":
            continue
        rows = (await session.execute(_t(
            "SELECT data->>:c FROM dataset_rows WHERE dataset_id = :d "
            "AND import_id = :i LIMIT 200"),
            {"c": col["name"], "d": str(ds.id),
             "i": str(ds.current_import_id)})).scalars().all()
        kind = pii.scan_column(rows)
        if kind:
            found[col["name"]] = kind
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="pii.scan",
                       resource_type="dataset", resource_id=str(ds.id))
    await session.commit()
    return {"detected": found,
            "suggested_governance": {"classification":
                                     {c: "pii" for c in found}},
            "note": "Nothing applied automatically — review and PUT "
                    "/governance to classify, then column_policy to "
                    "restrict."}


@router.put("/{dataset_id}/governance")
async def set_governance(dataset_id: str, body: dict,
                         ctx: TenantContext = Depends(require("tenant:manage")),
                         session=Depends(get_session)):
    """G2: classification, column_policy, row_policies, retention — stored
    per dataset, enforced on every read surface."""
    ds = await _dataset_or_404(session, ctx, dataset_id)
    allowed_keys = {"classification", "column_policy", "row_policies",
                    "retention"}
    bad = set(body) - allowed_keys
    if bad:
        raise HTTPException(422, f"Unknown governance keys {sorted(bad)}; "
                                 f"allowed: {sorted(allowed_keys)}")
    ret = body.get("retention")
    if ret and (ret.get("column") not in
                [c["name"] for c in ds.schema_def
                 if c["inferred_type"] in ("date", "timestamp")]
                or not isinstance(ret.get("days"), int) or ret["days"] < 1):
        raise HTTPException(422, "retention needs a date column + days >= 1")
    ds.governance = {**(ds.governance or {}), **body}
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="governance.set",
                       resource_type="dataset", resource_id=str(ds.id))
    await session.commit()
    return {"governance": ds.governance}


@router.get("/{dataset_id}/governance")
async def get_governance(dataset_id: str,
                         ctx: TenantContext = Depends(require("dataset:read")),
                         session=Depends(get_session)):
    ds = await _dataset_or_404(session, ctx, dataset_id)
    return {"governance": ds.governance or {}}


@router.post("/{dataset_id}/ask")
async def ask_question(dataset_id: str, body: AskIn,
                       ctx: TenantContext = Depends(require("dataset:read")),
                       session=Depends(get_session)):
    """Answer a natural-language question, grounded in this dataset's schema
    and the tenant's certified measures. Deterministic parsing (no LLM in the
    default path): the question can only select from allow-listed columns,
    measures and filter ops — see services/nlq.py for the security argument."""
    import time as _time

    started = _time.perf_counter()
    ds = await _dataset_or_404(session, ctx, dataset_id)
    await entitlements.enforce_ai_quota(session, ctx.tenant_id)
    measures = [{"name": m.name, "formula": m.formula, "certified": m.certified}
                for m in (await session.execute(select(Measure).where(
                    Measure.dataset_id == ds.id,
                    Measure.tenant_id == ctx.tenant_id))).scalars()]
    plan = nlq.parse_question(body.question, ds.schema_def, measures)
    if plan.get("explain"):
        target = plan["explain"]
        m = next((mm for mm in measures if mm["name"] == target), None)
        if m:
            exp = narrative.explain_formula(m["formula"], ds.schema_def,
                                            measures, ds.row_count or 0,
                                            ds.quarantined_count or 0)
            exp["text"] = f"'{target}': " + exp["text"]
        else:
            col = next(c for c in ds.schema_def if c["name"] == target)
            exp = {"formula": None, "certified_measure": None,
                   "text": (f"'{target}' is a {col['inferred_type']} column of "
                            f"this dataset ({ds.row_count or 0:,} clean rows). "
                            "Ask e.g. "
                            + (f"'total {target} by month'." if col["inferred_type"]
                               in ("number", "integer") else
                               f"'total by {target}'."))}
        return {"grounded": True, "answered": True, "explanation": exp,
                "confidence": "high", "quality_score": ds.quality_score,
                "freshness": ds.ingested_at.isoformat() if ds.ingested_at else None}
    if not plan["ok"]:
        return {"grounded": True, "answered": False, "reason": plan["reason"],
                "answerable": plan["answerable"]}

    # a bare "in <value>" phrase is resolved against real data, never guessed:
    # probe allow-listed text columns for a case-insensitive exact value match.
    if plan.get("bare_value") and not any(
            f["op"] == "eq" for f in plan["filters"]):
        text_cols = [c["name"] for c in ds.schema_def
                     if c["inferred_type"] == "text"]
        for col in text_cols:
            probe = await session.execute(text(
                "SELECT data->>:c AS v FROM dataset_rows "
                "WHERE dataset_id = :did AND import_id = :imp "
                "AND NOT is_quarantined AND lower(data->>:c) = lower(:val) "
                "LIMIT 1"), {"c": col, "did": str(ds.id),
                             "imp": str(ds.current_import_id),
                             "val": plan["bare_value"]})
            row = probe.first()
            if row:
                plan["filters"].append({"column": col, "op": "eq",
                                        "value": row.v})
                plan["description"] += f" where {col} is {row.v}"
                plan["used"]["where"] = f"{col} = {row.v}"
                plan["confidence"] = "high"
                break

    import re as _re

    from ..models import Membership as _M
    from ..services import datasec

    mem = (await session.execute(select(_M).where(
        _M.tenant_id == ctx.tenant_id,
        _M.user_id == ctx.user_id))).scalar_one_or_none()
    role = mem.role if mem else "viewer"
    referenced = _re.findall(r"[a-z_][a-z0-9_]*", plan["formula"]) + (
        [plan["group_by"]] if plan.get("group_by") else [])
    known = {c["name"] for c in ds.schema_def}
    datasec.check_columns(ds.governance or {}, role,
                          [c for c in referenced if c in known])
    mandatory = datasec.row_filters(ds.governance or {}, role,
                                    (mem.attributes if mem else {}) or {})
    try:
        result = await querysvc.execute_formula(
            session, dataset_id=ds.id, current_import_id=ds.current_import_id,
            dataset_schema=ds.schema_def, formula=plan["formula"],
            group_by=plan["group_by"],
            filters=(plan["filters"] or []) + mandatory)
    except querysvc.QueryError as e:
        raise HTTPException(422, str(e)) from None
    if plan.get("top_n") and "groups" in result:
        result["groups"] = result["groups"][: plan["top_n"]]

    date_cols = {c["name"] for c in ds.schema_def
                 if c["inferred_type"] in ("date", "timestamp")}
    widget = nlq.suggest_widget(plan, str(ds.id), body.question,
                                plan.get("group_by") in date_cols)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="ai.question",
                       resource_type="dataset", resource_id=str(ds.id))
    await session.commit()  # audit persists even though this is a read
    return {"grounded": True, "answered": True, "answer": result,
            "elapsed_ms": round((_time.perf_counter() - started) * 1000, 1),
            "description": plan["description"],
            "confidence": plan["confidence"], "used": plan["used"],
            "freshness": ds.ingested_at.isoformat() if ds.ingested_at else None,
            "quality_score": ds.quality_score,
            "suggested_widget": widget}
