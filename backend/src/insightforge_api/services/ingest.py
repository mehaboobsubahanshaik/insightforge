"""Trust pipeline: parse -> infer types -> profile -> quality rules ->
quarantine -> score. Runs identically for uploads and connector syncs so
every dataset earns the same quality evidence."""

import csv
import io
import re

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].*)?$")
NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
INT_RE = re.compile(r"^-?\d+$")
MAX_UPLOAD_ROWS = 50000


class IngestError(ValueError):
    pass


def parse_csv(content: bytes) -> tuple[list[str], list[list[str]]]:
    try:
        textio = io.StringIO(content.decode("utf-8-sig"))
    except UnicodeDecodeError as e:
        raise IngestError("File is not valid UTF-8 text") from e
    reader = csv.reader(textio)
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        raise IngestError("File needs a header row and at least one data row")
    return _normalize(rows[0]), rows[1 : MAX_UPLOAD_ROWS + 1]


def parse_xlsx(content: bytes) -> tuple[list[str], list[list[str]]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = [["" if c is None else str(c) for c in row]
            for row in ws.iter_rows(values_only=True)]
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        raise IngestError("Sheet needs a header row and at least one data row")
    return _normalize(rows[0]), rows[1 : MAX_UPLOAD_ROWS + 1]


def _normalize(header: list[str]) -> list[str]:
    out, seen = [], set()
    for i, h in enumerate(header):
        name = re.sub(r"[^a-z0-9_]", "_", (h or f"column_{i+1}").strip().lower())[:63]
        name = name or f"column_{i+1}"
        base, n = name, 2
        while name in seen:
            name, n = f"{base}_{n}", n + 1
        seen.add(name)
        out.append(name)
    return out


def infer_type(values: list[str]) -> str:
    nonempty = [v for v in values if v.strip() != ""]
    if not nonempty:
        return "text"
    sample = nonempty[:500]
    # Majority typing with an outlier allowance: at least 90% must conform,
    # but small files may carry one bad value (it lands in quarantine as
    # R003 rather than silently downgrading the whole column to text).
    allowed_bad = max(1, len(sample) // 10)
    for kind, rx in (("integer", INT_RE), ("number", NUM_RE), ("date", DATE_RE)):
        conform = sum(1 for v in sample if rx.match(v.strip()))
        if conform * 2 > len(sample) and conform >= len(sample) - allowed_bad:
            return kind
    return "text"


def run_pipeline(headers: list[str], raw_rows: list[list[str]]) -> dict:
    width = len(headers)
    rows = [(r + [""] * width)[:width] for r in raw_rows]
    types = [infer_type([r[i] for r in rows]) for i in range(width)]
    schema = [{"name": h, "inferred_type": t} for h, t in zip(headers, types)]

    checkers = {"integer": INT_RE, "number": NUM_RE, "date": DATE_RE}
    records, quarantined, seen_keys = [], [], set()
    missing_by_col = dict.fromkeys(headers, 0)
    dup_count = nonconform_count = 0
    for idx, row in enumerate(rows):
        reason = ""
        for i, cell in enumerate(row):
            if cell.strip() == "":
                missing_by_col[headers[i]] += 1
        key = tuple(row)
        if key in seen_keys:
            dup_count += 1
            reason = "R002: duplicate row"
        else:
            seen_keys.add(key)
        if not reason:
            for i, cell in enumerate(row):
                rx = checkers.get(types[i])
                if cell.strip() != "" and rx and not rx.match(cell.strip()):
                    nonconform_count += 1
                    reason = f"R003: '{headers[i]}' expected {types[i]}, got {cell.strip()[:40]!r}"
                    break
        data = {h: (row[i].strip() if row[i].strip() != "" else None)
                for i, h in enumerate(headers)}
        (quarantined if reason else records).append(
            {"row_index": idx, "data": data, "reason": reason})

    total = len(rows) or 1
    missing_cells = sum(missing_by_col.values())
    missing_ratio = missing_cells / (total * width)
    score = max(0, round(100 - 40 * missing_ratio - 30 * (dup_count / total)
                         - 30 * (nonconform_count / total)))
    profile = {
        "columns": {h: {"missing": missing_by_col[h],
                        "distinct": len({r[i] for r in rows}),
                        "type": types[i]}
                    for i, h in enumerate(headers)},
        "missing_cells": missing_cells,
        "duplicate_rows": dup_count,
        "nonconforming_values": nonconform_count,
    }
    dq = [
        {"rule": "R001", "severity": "warn" if missing_cells else "pass",
         "affected": missing_cells, "detail": {"by_column": missing_by_col}},
        {"rule": "R002", "severity": "warn" if dup_count else "pass",
         "affected": dup_count, "detail": {}},
        {"rule": "R003", "severity": "warn" if nonconform_count else "pass",
         "affected": nonconform_count, "detail": {}},
    ]
    return {"schema": schema, "records": records, "quarantined": quarantined,
            "row_count": len(records), "quarantined_count": len(quarantined),
            "quality_score": score, "profile": profile, "dq": dq}


# ---------------- Cleaning recipes ----------------
_NUMERIC_IN_TEXT = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
RECIPE_OPS = {"trim", "uppercase", "lowercase", "replace", "fill_missing",
              "strip_non_numeric"}


def validate_recipe(steps: list, headers: list[str]) -> list[dict]:
    if not isinstance(steps, list) or len(steps) > 20:
        raise IngestError("A recipe is a list of at most 20 steps")
    clean = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or step.get("op") not in RECIPE_OPS:
            raise IngestError(
                f"Step {i + 1}: op must be one of {', '.join(sorted(RECIPE_OPS))}")
        column = step.get("column")
        if column not in headers:
            raise IngestError(f"Step {i + 1}: column {column!r} is not in this dataset")
        out = {"op": step["op"], "column": column}
        if step["op"] == "replace":
            out["find"] = str(step.get("find", ""))[:200]
            out["replace"] = str(step.get("replace", ""))[:200]
            if not out["find"]:
                raise IngestError(f"Step {i + 1}: replace needs a non-empty 'find'")
        if step["op"] == "fill_missing":
            out["value"] = str(step.get("value", ""))[:200]
        clean.append(out)
    return clean


def apply_recipe(headers: list[str], rows: list[list[str]], steps: list[dict]):
    """Apply cleaning steps to raw string rows; returns new rows."""
    idx = {h: i for i, h in enumerate(headers)}
    out = [list(r) for r in rows]
    for step in steps:
        i = idx[step["column"]]
        op = step["op"]
        for row in out:
            v = row[i]
            if op == "trim":
                row[i] = v.strip()
            elif op == "uppercase":
                row[i] = v.upper()
            elif op == "lowercase":
                row[i] = v.lower()
            elif op == "replace":
                row[i] = v.replace(step["find"], step["replace"])
            elif op == "fill_missing":
                row[i] = step["value"] if v.strip() == "" else v
            elif op == "strip_non_numeric":
                m = _NUMERIC_IN_TEXT.search(v)
                row[i] = m.group(0).replace(",", "") if m else v
    return out
