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
