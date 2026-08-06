"""Governed query execution: the single chokepoint through which every chart,
KPI, pivot, alert, and export reads data. Filter operators are allow-listed
constant templates; only the current import generation and non-quarantined
rows are ever visible."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .formulas import FormulaError, compile_formula

FILTER_OPS = {
    "eq": "data->>:{c} = :{v}",
    "neq": "data->>:{c} IS DISTINCT FROM :{v}",
    "gt": "(data->>:{c})::numeric > (:{v})::numeric",
    "gte": "(data->>:{c})::numeric >= (:{v})::numeric",
    "lt": "(data->>:{c})::numeric < (:{v})::numeric",
    "lte": "(data->>:{c})::numeric <= (:{v})::numeric",
    "contains": "data->>:{c} ILIKE '%' || :{v} || '%'",
}
GROUP_LIMIT = 50
TABLE_LIMIT = 200
MAX_FILTERS = 10


class QueryError(ValueError):
    pass


def _compile_filters(filters: list[dict], columns: set[str]) -> tuple[str, dict]:
    if len(filters) > MAX_FILTERS:
        raise QueryError(f"At most {MAX_FILTERS} filters allowed")
    clauses, params = [], {}
    for i, f in enumerate(filters):
        col, op, value = f.get("column"), f.get("op", "eq"), f.get("value")
        if col not in columns:
            raise QueryError(f"Unknown filter column {col!r}")
        if op not in FILTER_OPS:
            raise QueryError(f"Unknown filter op {op!r}; allowed: {', '.join(sorted(FILTER_OPS))}")
        cn, vn = f"flc{i}", f"flv{i}"
        clauses.append("AND " + FILTER_OPS[op].format(c=cn, v=vn))
        params[cn] = col
        params[vn] = str(value)
    return " ".join(clauses), params


_BASE = ("FROM dataset_rows WHERE dataset_id = :did AND NOT is_quarantined "
         "AND import_id IS NOT DISTINCT FROM :imp")


async def execute_formula(
    session: AsyncSession, *, dataset_id: uuid.UUID, current_import_id,
    dataset_schema: list[dict], formula: str, group_by: str | None = None,
    group_by2: str | None = None, filters: list[dict] | None = None,
) -> dict:
    columns = {c["name"] for c in dataset_schema}
    try:
        agg_sql, params = compile_formula(formula, dataset_schema)
        fsql, fparams = _compile_filters(filters or [], columns)
    except FormulaError as e:
        raise QueryError(str(e)) from None
    params.update(fparams)
    params.update({"did": str(dataset_id),
                   "imp": str(current_import_id) if current_import_id else None})
    for g in (group_by, group_by2):
        if g is not None and g not in columns:
            raise QueryError(f"Unknown group-by column {g!r}")
    if group_by is None:
        sql = f"SELECT {agg_sql} AS value {_BASE} {fsql}"  # noqa: S608 - allow-listed fragments only
        row = (await session.execute(text(sql), params)).one()
        return {"value": float(row.value) if row.value is not None else None}
    if group_by2 is None:
        params["gcol"] = group_by
        sql = (f"SELECT COALESCE(data->>:gcol,'(none)') AS grp, {agg_sql} AS value "  # noqa: S608
               f"{_BASE} {fsql} GROUP BY 1 ORDER BY 2 DESC NULLS LAST LIMIT {GROUP_LIMIT}")
        rows = (await session.execute(text(sql), params)).all()
        return {"groups": [{"group": r.grp, "value": float(r.value or 0)} for r in rows]}
    params["gcol"], params["gcol2"] = group_by, group_by2
    sql = (f"SELECT COALESCE(data->>:gcol,'(none)') AS r, "  # noqa: S608
           f"COALESCE(data->>:gcol2,'(none)') AS c, {agg_sql} AS value "
           f"{_BASE} {fsql} GROUP BY 1, 2 ORDER BY 1, 2 LIMIT {GROUP_LIMIT * 10}")
    rows = (await session.execute(text(sql), params)).all()
    row_keys = sorted({r.r for r in rows})
    col_keys = sorted({r.c for r in rows})
    cells = {(r.r, r.c): float(r.value or 0) for r in rows}
    return {"pivot": {"rows": row_keys, "cols": col_keys,
                      "cells": [[cells.get((rk, ck)) for ck in col_keys] for rk in row_keys]}}


async def fetch_table(
    session: AsyncSession, *, dataset_id: uuid.UUID, current_import_id,
    dataset_schema: list[dict], filters: list[dict] | None = None, limit: int = 50,
    include_quarantined: bool = False,
) -> dict:
    columns = {c["name"] for c in dataset_schema}
    fsql, params = _compile_filters(filters or [], columns)
    params.update({"did": str(dataset_id),
                   "imp": str(current_import_id) if current_import_id else None})
    limit = max(1, min(int(limit), TABLE_LIMIT))
    quarantine = "" if include_quarantined else "AND NOT is_quarantined"
    sql = (f"SELECT data, is_quarantined, quarantine_reason FROM dataset_rows "  # noqa: S608
           f"WHERE dataset_id = :did {quarantine} AND import_id IS NOT DISTINCT FROM :imp "
           f"{fsql} ORDER BY row_index LIMIT {limit}")
    rows = (await session.execute(text(sql), params)).all()
    return {"columns": [c["name"] for c in dataset_schema],
            "rows": [r.data for r in rows],
            "quarantine": [{"reason": r.quarantine_reason, **r.data}
                           for r in rows if r.is_quarantined]}
