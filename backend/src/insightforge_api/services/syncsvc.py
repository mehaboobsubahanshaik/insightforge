"""Connector sync orchestration. Append-only import generations: each load
writes rows under a new import_id and flips datasets.current_import_id
atomically — history is never destroyed, reloads are idempotent, and an
incremental extract with no delta short-circuits to `no_change`."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Connection, Dataset, DatasetRow, DQHistory, DQResult, SyncRun, uuid7
from . import entitlements
from .connectors import REGISTRY
from .ingest import run_pipeline
from .vault import decrypt_credentials


async def run_sync(session: AsyncSession, connection: Connection, *,
                   actor_user_id: uuid.UUID, mode: str = "incremental",
                   trigger: str = "manual") -> SyncRun:
    run = SyncRun(tenant_id=connection.tenant_id, connection_id=connection.id,
                  mode=mode, trigger=trigger, status="failed")
    session.add(run)
    await session.flush()
    connector = REGISTRY[connection.connector_type]
    credentials = decrypt_credentials(connection.credentials_enc)
    cursor = None if mode == "full_refresh" else connection.sync_cursor
    try:
        result = await connector.extract(connection.config, credentials, cursor)
    except Exception as e:
        run.status = "failed"
        run.error = str(e)[:1000]
        run.finished_at = datetime.now(timezone.utc)
        raise
    run.rows_extracted = len(result.rows)

    dataset = (await session.execute(
        select(Dataset).where(Dataset.connection_id == connection.id))).scalar_one_or_none()

    if mode == "incremental" and dataset is not None and not result.rows:
        run.status = "no_change"
        run.dataset_id = dataset.id
        run.finished_at = datetime.now(timezone.utc)
        return run

    if dataset is not None and mode == "incremental" and result.headers:
        existing = [c["name"] for c in dataset.schema_def]
        if existing and existing != result.headers:
            run.status = "failed"
            run.error = (f"Schema drift detected: source now returns {result.headers}, "
                         f"dataset expects {existing}. Run a full refresh to re-baseline.")
            run.finished_at = datetime.now(timezone.utc)
            return run

    # Merge: incremental = prior generation rows + delta, reprocessed as a whole
    prior_rows: list[list[str]] = []
    headers = result.headers
    if dataset is not None and mode == "incremental" and dataset.current_import_id:
        headers = [c["name"] for c in dataset.schema_def] or result.headers
        db_rows = (await session.execute(
            text("SELECT data FROM dataset_rows WHERE dataset_id = :d "
                 "AND import_id = :i AND NOT is_quarantined ORDER BY row_index"),
            {"d": str(dataset.id), "i": str(dataset.current_import_id)})).all()
        prior_rows = [["" if r.data.get(h) is None else str(r.data.get(h)) for h in headers]
                      for r in db_rows]
    merged = prior_rows + result.rows
    pipeline = run_pipeline(headers, merged)

    if dataset is None:
        dataset = Dataset(tenant_id=connection.tenant_id, workspace_id=connection.workspace_id,
                          name=f"{connection.name} data", source_type="connector",
                          connection_id=connection.id, created_by=actor_user_id)
        session.add(dataset)
        await session.flush()

    import_id = uuid7()
    for bucket, quarantined in ((pipeline["records"], False), (pipeline["quarantined"], True)):
        for rec in bucket:
            session.add(DatasetRow(
                tenant_id=connection.tenant_id, dataset_id=dataset.id, import_id=import_id,
                row_index=rec["row_index"], data=rec["data"], is_quarantined=quarantined,
                quarantine_reason=rec["reason"]))
    for dq in pipeline["dq"]:
        session.add(DQResult(tenant_id=connection.tenant_id, dataset_id=dataset.id,
                             import_id=import_id, rule=dq["rule"], severity=dq["severity"],
                             affected=dq["affected"], detail=dq["detail"]))
    session.add(DQHistory(tenant_id=connection.tenant_id, dataset_id=dataset.id,
                          score=pipeline["quality_score"], row_count=pipeline["row_count"],
                          quarantined_count=pipeline["quarantined_count"]))
    dataset.schema_def = pipeline["schema"]
    dataset.row_count = pipeline["row_count"]
    dataset.quarantined_count = pipeline["quarantined_count"]
    dataset.quality_score = pipeline["quality_score"]
    dataset.profile = pipeline["profile"]
    dataset.current_import_id = import_id
    dataset.ingested_at = datetime.now(timezone.utc)

    connection.sync_cursor = result.cursor
    connection.last_sync_at = datetime.now(timezone.utc)
    run.dataset_id = dataset.id
    run.rows_loaded = pipeline["row_count"]
    run.status = "succeeded"
    run.finished_at = datetime.now(timezone.utc)
    await entitlements.meter(session, connection.tenant_id, "sync.rows",
                             pipeline["row_count"])
    return run
