"""AI-assisted data preparation suggestions (MVP3 chapter 3).

Deterministic diagnosis: samples the dataset's own values and quarantine to
propose recipe steps THE PLATFORM CAN ALREADY APPLY — every suggestion is an
{op, column} pair for services/ingest.RECIPE_OPS, one click from fixed.
Same honesty contract as the rest of the AI layer: each suggestion names its
evidence, and no suggestion is emitted without observed data behind it.
"""

from __future__ import annotations

import re

from sqlalchemy import text

SAMPLE = 200          # distinct values examined per text column
NUMERICISH = re.compile(r"^\s*[^0-9\-+]{0,3}\s*-?[\d,]+(\.\d+)?\s*[^0-9]{0,3}\s*$")
MIN_EVIDENCE = 2      # a single odd value is noise, not a pattern


async def _sample_values(session, ds, column: str) -> list[str]:
    rows = await session.execute(text(
        "SELECT DISTINCT data->>:c AS v FROM dataset_rows "
        "WHERE dataset_id = :d AND import_id = :i AND NOT is_quarantined "
        "AND data->>:c IS NOT NULL LIMIT :n"),
        {"c": column, "d": str(ds.id), "i": str(ds.current_import_id),
         "n": SAMPLE})
    return [r.v for r in rows]


async def suggest(session, ds) -> list[dict]:
    """Ranked, apply-ready suggestions with evidence and expected effect."""
    out: list[dict] = []
    profile = (ds.profile or {}).get("columns", {})  # {col: {missing: n, ...}}

    for col in ds.schema_def:
        name, ctype = col["name"], col["inferred_type"]
        missing = (profile.get(name) or {}).get("missing", 0)
        if missing:
            out.append({
                "op": "fill_missing", "column": name, "value": "UNKNOWN",
                "reason": f"{missing} rows have no value for '{name}'",
                "effect": "fills blanks so grouping and filters stop "
                          "splitting into an invisible empty bucket",
                "severity": missing})
        if ctype != "text":
            continue
        values = await _sample_values(session, ds, name)
        if not values:
            continue
        padded = [v for v in values if v != v.strip()]
        if len(padded) >= MIN_EVIDENCE:
            out.append({
                "op": "trim", "column": name,
                "reason": f"{len(padded)} of {len(values)} sampled values "
                          f"carry leading/trailing spaces (e.g. '{padded[0]}')",
                "effect": "' South' and 'South' merge into one category",
                "severity": len(padded) * 3})
        lowered: dict[str, set] = {}
        for v in values:
            lowered.setdefault(v.strip().lower(), set()).add(v.strip())
        case_clashes = {k: vs for k, vs in lowered.items() if len(vs) > 1}
        if case_clashes:
            example = sorted(next(iter(case_clashes.values())))
            out.append({
                "op": "uppercase", "column": name,
                "reason": f"{len(case_clashes)} values differ only by casing "
                          f"(e.g. {' vs '.join(repr(e) for e in example[:2])})",
                "effect": "casing variants collapse into one category",
                "severity": len(case_clashes) * 4})
        numericish = [v for v in values if NUMERICISH.match(v)]
        if len(values) >= MIN_EVIDENCE and len(numericish) >= .9 * len(values):
            out.append({
                "op": "strip_non_numeric", "column": name,
                "reason": f"'{name}' inferred as text but "
                          f"{len(numericish)}/{len(values)} sampled values "
                          f"look numeric (e.g. '{numericish[0]}')",
                "effect": "column becomes aggregatable — sums, averages and "
                          "KPIs unlock",
                "severity": 100})

    # quarantine-driven: reasons name the columns that trap rows
    if ds.quarantined_count:
        rows = await session.execute(text(
            "SELECT quarantine_reason AS r, count(*) AS n FROM dataset_rows "
            "WHERE dataset_id = :d AND import_id = :i AND is_quarantined "
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 5"),
            {"d": str(ds.id), "i": str(ds.current_import_id)})
        for r in rows:
            if not r.r:
                continue
            m = re.search(r"'([^']+)' expected (?:number|integer)", r.r)
            colname = m.group(1) if m else None
            ctype = next((c["inferred_type"] for c in ds.schema_def
                          if c["name"] == colname), None)
            if colname and ctype in ("number", "integer"):
                out.append({
                    "op": "strip_non_numeric", "column": colname,
                    "reason": f"{r.n} quarantined rows: {r.r}",
                    "effect": f"rescues up to {r.n} rows back into the "
                              "clean set and re-scores the dataset",
                    "severity": 90 + r.n})

    # dedupe (same op+column suggested twice keeps the stronger evidence)
    # R13 advisory: numeric outliers (|z| > 3) via live SQL stats —
    # flagged for review, never auto-removed.
    from sqlalchemy import text as _t

    for col in ds.schema_def:
        if col["inferred_type"] not in ("number", "integer"):
            continue
        row = (await session.execute(_t(
            "SELECT avg((data->>:c)::numeric), "
            "stddev_samp((data->>:c)::numeric) FROM dataset_rows "
            "WHERE dataset_id = :d AND import_id = :i "
            "AND NOT is_quarantined AND data->>:c IS NOT NULL"),
            {"c": col["name"], "d": str(ds.id),
             "i": str(ds.current_import_id)})).one()
        mean, std = row
        if mean is None or not std:
            continue
        n = (await session.execute(_t(
            "SELECT count(*) FROM dataset_rows WHERE dataset_id = :d "
            "AND import_id = :i AND NOT is_quarantined "
            "AND data->>:c IS NOT NULL "
            "AND abs(((data->>:c)::numeric - :m) / :s) > 3"),
            {"d": str(ds.id), "i": str(ds.current_import_id),
             "c": col["name"], "m": float(mean),
             "s": float(std)})).scalar_one()
        if n:
            out.append({"op": "review_outliers", "column": col["name"],
                        "advisory": True, "severity": 1,
                        "reason": f"{n} value(s) beyond 3 standard "
                                  f"deviations (mean {float(mean):,.1f}, "
                                  f"std {float(std):,.1f})",
                        "effect": "review flagged rows — outliers are "
                                  "never auto-removed"})

    seen: dict[tuple, dict] = {}
    for sug in out:
        key = (sug["op"], sug["column"])
        if key not in seen or sug["severity"] > seen[key]["severity"]:
            seen[key] = sug
    ranked = sorted(seen.values(), key=lambda x: -x["severity"])
    for sug in ranked:
        sug.pop("severity", None)
    return ranked
