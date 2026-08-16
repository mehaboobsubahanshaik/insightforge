"""Narrative layer (MVP3 chapter 2): grounded numbers -> honest English.

Every sentence here is a deterministic template filled from the SAME
computations the widgets run (execute_formula over governed columns), so the
prose inherits the platform guarantees: it cannot state a number it did not
compute, and every brief names its comparison windows and data health.
No LLM in this path — see ADR 0013's honesty rule.
"""

from __future__ import annotations

from datetime import date, timedelta

from . import querysvc

POP_DAYS = 30          # period-over-period window
MAX_DRIVERS = 3        # named movers per direction
DRIVER_MIN_SHARE = .05  # ignore movers under 5% of the total change


def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if a >= 10_000:
        return f"{v / 1_000:.1f}k"
    if a == int(a):
        return f"{int(v):,}"
    return f"{v:,.2f}"


def _pct(cur: float, prev: float) -> str:
    if prev == 0:
        return "from zero" if cur else "flat at zero"
    p = (cur - prev) / abs(prev) * 100
    word = "up" if p > 0 else "down" if p < 0 else "flat"
    return f"{word} {abs(p):.0f}%" if word != "flat" else "flat"


def windows(today: date | None = None, days: int = POP_DAYS):
    today = today or date.today()
    cur_start = today - timedelta(days=days - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return ((cur_start.isoformat(), today.isoformat()),
            (prev_start.isoformat(), prev_end.isoformat()))


def _win_filters(date_col: str, win: tuple[str, str]) -> list[dict]:
    return [{"column": date_col, "op": "date_gte", "value": win[0]},
            {"column": date_col, "op": "date_lte", "value": win[1]}]


async def pop_kpi(session, ds, formula: str, date_col: str,
                  driver_col: str | None, today: date | None = None) -> dict:
    """Current vs previous window for a formula, with per-group driver deltas."""
    cur_w, prev_w = windows(today)
    kw = dict(dataset_id=ds.id, current_import_id=ds.current_import_id,
              dataset_schema=ds.schema_def, formula=formula)
    cur = (await querysvc.execute_formula(
        session, **kw, filters=_win_filters(date_col, cur_w)))["value"] or 0.0
    prev = (await querysvc.execute_formula(
        session, **kw, filters=_win_filters(date_col, prev_w)))["value"] or 0.0
    drivers = []
    if driver_col:
        gcur = {g["group"]: g["value"] for g in (await querysvc.execute_formula(
            session, **kw, group_by=driver_col,
            filters=_win_filters(date_col, cur_w)))["groups"]}
        gprev = {g["group"]: g["value"] for g in (await querysvc.execute_formula(
            session, **kw, group_by=driver_col,
            filters=_win_filters(date_col, prev_w)))["groups"]}
        for key in set(gcur) | set(gprev):
            d = (gcur.get(key, 0) or 0) - (gprev.get(key, 0) or 0)
            if d:
                drivers.append({"group": key, "delta": d})
        drivers.sort(key=lambda x: -abs(x["delta"]))
    return {"current": cur, "previous": prev, "change": cur - prev,
            "pct": _pct(cur, prev), "drivers": drivers,
            "windows": {"current": cur_w, "previous": prev_w}}


def driver_sentence(change: float, drivers: list[dict],
                    driver_col: str) -> str:
    if not drivers or change == 0:
        return ""
    total = abs(change)
    with_ = [d for d in drivers if (d["delta"] > 0) == (change > 0)
             and abs(d["delta"]) / total >= DRIVER_MIN_SHARE][:MAX_DRIVERS]
    against = [d for d in drivers if (d["delta"] > 0) != (change > 0)
               and abs(d["delta"]) / total >= DRIVER_MIN_SHARE][:MAX_DRIVERS]
    bits = []
    if with_:
        bits.append("driven by " + ", ".join(
            f"{d['group']} ({'+' if d['delta'] > 0 else '−'}{_fmt(abs(d['delta']))})"
            for d in with_))
    if against:
        bits.append("partly offset by " + ", ".join(
            f"{d['group']} ({'+' if d['delta'] > 0 else '−'}{_fmt(abs(d['delta']))})"
            for d in against))
    return f" Across {driver_col}: " + "; ".join(bits) + "."


async def executive_brief(session, dashboard_name: str, widgets: list,
                          ds_by_id: dict, today: date | None = None) -> dict:
    """Compose the brief from a dashboard's own widgets. Honest by scope:
    KPIs without a date column are reported as-is (no fake comparison)."""
    headlines, notes = [], []
    seen: set[str] = set()
    # a driver must be a category: only text-typed group_by columns qualify
    # (a line chart grouped by order_date must never drive attribution)
    grouped_cols: dict = {}
    for w in widgets:
        gb = w.get("group_by")
        ds = ds_by_id.get(w["dataset_id"])
        if not gb or ds is None:
            continue
        gtype = next((c["inferred_type"] for c in ds.schema_def
                      if c["name"] == gb), None)
        if gtype == "text":
            grouped_cols.setdefault(w["dataset_id"], gb)
    for w in widgets:
        if w["type"] != "kpi":
            continue
        ds = ds_by_id.get(w["dataset_id"])
        if ds is None:
            continue
        key = f'{w["dataset_id"]}:{w["formula"]}'
        if key in seen:
            continue
        seen.add(key)
        date_cols = [c["name"] for c in ds.schema_def
                     if c["inferred_type"] in ("date", "timestamp")]
        title = w.get("title") or w["formula"]
        if not date_cols:
            val = (await querysvc.execute_formula(
                session, dataset_id=ds.id,
                current_import_id=ds.current_import_id,
                dataset_schema=ds.schema_def, formula=w["formula"],
                filters=[]))["value"]
            headlines.append({
                "title": title, "current": val, "pct": None,
                "sentence": f"{title}: {_fmt(val)} (all time — no date column "
                            "to compare periods)."})
            continue
        driver = grouped_cols.get(w["dataset_id"]) or next(
            (c["name"] for c in ds.schema_def
             if c["inferred_type"] == "text"
             and not c["name"].lower().endswith("id")), None)
        pop = await pop_kpi(session, ds, w["formula"], date_cols[0],
                            driver, today)
        sent = (f"{title}: {_fmt(pop['current'])}, {pop['pct']} vs the prior "
                f"{POP_DAYS} days ({_fmt(pop['previous'])})."
                + driver_sentence(pop["change"], pop["drivers"], driver or ""))
        if pop["current"] == 0 and pop["previous"]:
            sent += (" No rows fall in the current window — the data itself "
                     "may be stale; check the source's sync schedule.")
        headlines.append({"title": title, **pop, "sentence": sent})
    quality = [ds.quality_score for ds in ds_by_id.values()
               if ds and ds.quality_score is not None]
    quarantined = sum(ds.quarantined_count or 0
                      for ds in ds_by_id.values() if ds)
    if quality:
        notes.append(f"Data health: lowest quality score {min(quality)}/100"
                     + (f"; {quarantined} rows quarantined (excluded from "
                        "every number above)." if quarantined else "."))
    cur_w, prev_w = windows(today)
    notes.append(f"Comparison windows: {cur_w[0]} to {cur_w[1]} vs "
                 f"{prev_w[0]} to {prev_w[1]}. Every figure is computed from "
                 "governed data — nothing in this brief is generated text "
                 "without a number behind it.")
    text = "\n".join([f"Executive brief — {dashboard_name}", ""]
                     + [h["sentence"] for h in headlines] + [""] + notes)
    return {"dashboard": dashboard_name, "headlines": headlines,
            "notes": notes, "text": text}


def explain_formula(formula: str, schema: list[dict], measures: list[dict],
                    row_count: int, quarantined: int) -> dict:
    """Deterministic explanation of a formula/measure — what it computes,
    over which columns and rows, and its governance status."""
    import re as _re

    verbs = {"sum": "adds up", "avg": "averages", "min": "takes the minimum of",
             "max": "takes the maximum of", "count": "counts rows",
             "count_distinct": "counts the distinct values of"}
    types = {c["name"]: c["inferred_type"] for c in schema}
    parts = []
    for func, col in _re.findall(r"([a-z_]+)\(\s*([A-Za-z_][A-Za-z0-9_]*)?\s*\)",
                                 formula):
        if func not in verbs:
            continue
        if col:
            parts.append(f"{verbs[func]} the '{col}' column "
                         f"({types.get(col, 'unknown')})")
        else:
            parts.append(verbs[func])
    ops = [o for o in "+-*/" if o in formula]
    combo = (" and combines them with "
             + "/".join({"+": "addition", "-": "subtraction",
                         "*": "multiplication", "/": "division (zero-safe)"}[o]
                        for o in ops) if ops else "")
    matching = next((m for m in measures if m["formula"] == formula), None)
    governance = (f"This is the certified measure '{matching['name']}' — the "
                  "governed definition every dashboard shares."
                  if matching and matching.get("certified") else
                  f"This matches the measure '{matching['name']}' (not yet "
                  "certified)." if matching else
                  "This is an ad-hoc formula (not a saved measure).")
    scope = (f"It runs over the {row_count:,} clean rows of the current "
             f"import{f'; {quarantined} quarantined rows are excluded' if quarantined else ''}.")
    text = (f"'{formula}' " + (", ".join(parts) if parts else "computes a value")
            + combo + ". " + scope + " " + governance)
    return {"formula": formula, "text": text,
            "certified_measure": matching["name"]
            if matching and matching.get("certified") else None}
