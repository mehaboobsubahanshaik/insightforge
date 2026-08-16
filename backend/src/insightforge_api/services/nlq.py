"""Governed natural-language questions (MVP3, ADR 0013).

Deterministic semantic parser: a question is matched against the dataset's
OWN schema and the tenant's OWN certified measures, and compiled into a plan
for the existing formula engine — the single allow-listed path to SQL.

Properties by construction (the checklist's hard requirements):
* grounded — every number comes from execute_formula over governed columns
  and measures; the parser cannot invent data it cannot name
* permission-aware — plans execute through the same tenant-scoped session
  and dataset lookup as every widget; RLS applies underneath
* injection-proof — question text is never concatenated anywhere; it only
  SELECTS from allow-lists (columns, measures, ops) or travels as bind values
* honest — unanswerable questions return what CAN be asked, not a guess

An LLM planner can later slot in ahead of this parser (emitting the same
plan shape, validated by the same allow-lists); it is deliberately absent
from the default path. See docs/adr/0013-governed-nlq.md.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

MAX_QUESTION_LEN = 300

_AGGS = [
    (("how many", "number of", "count of", "count"), "count"),
    (("average", "avg", "mean"), "avg"),
    (("total", "sum of", "sum", "overall"), "sum"),
    (("highest", "maximum", "max", "largest", "biggest"), "max"),
    (("lowest", "minimum", "min", "smallest"), "min"),
    (("unique", "distinct"), "count_distinct"),
]
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_TOP_RE = re.compile(r"\btop\s+(\d{1,2})\b")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def _phrases(name: str) -> list[str]:
    """Column 'unit_price' matches as 'unit_price', 'unit price', and simple
    plurals ('regions' -> region) — people ask about 'products', not 'product'."""
    base = [name.lower(), name.lower().replace("_", " ")]
    return base + [b + "s" for b in base if not b.endswith("s")]


def _find_named(q: str, names: list[str]) -> tuple[str | None, str]:
    """Longest matching name (schema/measure) present in q; returns
    (canonical_name, q_without_that_phrase)."""
    best, best_phrase = None, ""
    for name in names:
        for ph in _phrases(name):
            if len(ph) > len(best_phrase) and re.search(rf"\b{re.escape(ph)}\b", q):
                best, best_phrase = name, ph
    if best is None:
        return None, q
    return best, re.sub(rf"\b{re.escape(best_phrase)}\b", " ", q, count=1)


def _date_range(q: str, today: date) -> tuple[str | None, str | None, str, str]:
    """Recognise a time phrase; returns (start_iso, end_iso, label, q_rest)."""
    def month_span(y: int, m: int) -> tuple[str, str]:
        last = calendar.monthrange(y, m)[1]
        return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last:02d}"

    m = re.search(r"\blast (\d{1,3}) days\b", q)
    if m:
        n = int(m.group(1))
        return ((today - timedelta(days=n)).isoformat(), today.isoformat(),
                f"last {n} days", q.replace(m.group(0), " "))
    if "this month" in q:
        s, e = month_span(today.year, today.month)
        return s, e, "this month", q.replace("this month", " ")
    if "last month" in q:
        y, mo = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        s, e = month_span(y, mo)
        return s, e, "last month", q.replace("last month", " ")
    if "this year" in q:
        return (f"{today.year}-01-01", f"{today.year}-12-31", "this year",
                q.replace("this year", " "))
    if "last year" in q:
        y = today.year - 1
        return f"{y}-01-01", f"{y}-12-31", "last year", q.replace("last year", " ")
    for name, num in _MONTHS.items():
        if re.search(rf"\b{name}\b", q):
            ym = _YEAR_RE.search(q)
            y = int(ym.group(1)) if ym else today.year
            s, e = month_span(y, num)
            rest = re.sub(rf"\b{name}\b", " ", q)
            if ym:
                rest = rest.replace(ym.group(1), " ")
            return s, e, f"{name.title()} {y}", rest
    return None, None, "", q


def parse_question(question: str, schema: list[dict],
                   measures: list[dict], today: date | None = None) -> dict:
    """Compile a question into an execution plan, or an honest refusal.

    Returns {"ok": True, plan...} or {"ok": False, "reason", "answerable"}.
    Plan: {formula, group_by?, filters[], top_n?, description, confidence,
           used: {measure?|column?, aggregation, group_by?, time?, where?}}
    """
    today = today or date.today()
    if not question or len(question) > MAX_QUESTION_LEN:
        return _refuse("Ask a question up to 300 characters.", schema, measures)
    q = " " + _norm(question) + " "

    # explanation intent: "explain revenue", "what does unit_price mean".
    # Fires ONLY when the remainder is exactly one known name — "what is the
    # total total" is a computation, not a definition request.
    em = re.match(r"^\s*(?:explain|define|what does|what is)\s+(.+?)"
                  r"(?:\s+mean)?\s*$", q.strip())
    if em:
        remainder = re.sub(r"^(?:the|a|an)\s+", "", em.group(1).strip())
        names = [m["name"] for m in measures] + [c["name"] for c in schema]
        target = next((n for n in names
                       if remainder in _phrases(n)), None)
        if target:
            return {"ok": True, "explain": target}

    numeric = [c["name"] for c in schema
               if c["inferred_type"] in ("number", "integer")]
    date_cols = [c["name"] for c in schema
                 if c["inferred_type"] in ("date", "timestamp")]
    all_cols = [c["name"] for c in schema]
    used: dict = {}
    filters: list[dict] = []
    parts: list[str] = []

    top_n = None
    m = _TOP_RE.search(q)
    if m:
        top_n = max(1, min(int(m.group(1)), 50))
        q = q.replace(m.group(0), " ")

    start, end, tlabel, q = _date_range(q, today)
    if start:
        if not date_cols:
            return _refuse(
                f"This dataset has no date column, so '{tlabel}' cannot be "
                "answered.", schema, measures)
        dcol = date_cols[0]
        filters += [{"column": dcol, "op": "date_gte", "value": start},
                    {"column": dcol, "op": "date_lte", "value": end}]
        used["time"] = f"{dcol} in {tlabel}"
        parts.append(f"in {tlabel}")

    # aggregation words
    agg, agg_word = None, None
    for words, name in _AGGS:
        for w in words:
            if f" {w} " in q or q.strip().startswith(w):
                agg, agg_word = name, w
                q = q.replace(w, " ", 1)
                break
        if agg:
            break

    # certified measures outrank raw columns (that's what governed means)
    measure_names = [mm["name"] for mm in measures]
    mname, q = _find_named(q, measure_names)
    if mname is not None:
        mdef = next(mm for mm in measures if mm["name"] == mname)
        formula = mdef["formula"]
        used["measure"] = mname
        parts.insert(0, f"measure '{mname}'")
    else:
        col, q = _find_named(q, numeric)
        if col is None and agg_word:
            # 'total by region': the aggregation word IS the column's name
            col = next((c for c in numeric if agg_word in _phrases(c)), None)
        if col is None and agg in ("sum", "avg", "min", "max") and len(numeric) == 1:
            # only one numeric column exists — "total by region" can only
            # mean that column; defaulting is grounded, not guessing
            col = numeric[0]
        if col is not None and agg in (None, "count"):
            agg = agg or "sum"
        if agg == "count" and col is None:
            formula = "count()"
            parts.insert(0, "count of rows")
            used["aggregation"] = "count"
        elif col is not None:
            agg = agg or "sum"
            formula = (f"count_distinct({col})" if agg == "count_distinct"
                       else f"{agg}({col})")
            used["aggregation"], used["column"] = agg, col
            parts.insert(0, f"{agg} of {col}")
        elif agg == "count":
            formula = "count()"
            parts.insert(0, "count of rows")
            used["aggregation"] = "count"
        else:
            return _refuse(
                "Could not find a measure or numeric column to compute.",
                schema, measures)

    # group by / per / for each <column>
    group_by = None
    m = re.search(r"\b(?:by|per|for each|across)\s+(\w[\w ]*)", q)
    if m:
        cand, _ = _find_named(" " + m.group(1) + " ", all_cols)
        if cand:
            group_by = cand
            used["group_by"] = cand
            parts.append(f"by {cand}")
            q = q.replace(m.group(0), " ", 1)
    if group_by is None and top_n:
        cand, q2 = _find_named(q, [c for c in all_cols if c not in numeric])
        if cand:
            group_by, q = cand, q2
            used["group_by"] = cand
            parts.append(f"top {top_n} {cand}")

    # where <col> is <value> / <col> = value / in <TextValue>
    m = re.search(r"\b(?:where|with)\s+(\w[\w ]*?)\s+(?:is|equals|=)\s+([\w .-]+)", q)
    if m:
        cand, _ = _find_named(" " + m.group(1) + " ", all_cols)
        if cand:
            val = m.group(2).strip()
            filters.append({"column": cand, "op": "eq", "value": val})
            used["where"] = f"{cand} = {val}"
            parts.append(f"where {cand} is {val}")
            q = q.replace(m.group(0), " ", 1)
    else:
        m = re.search(r"\b(?:in|for)\s+([a-z][\w-]*)\b", q)
        if m and group_by is None or (m and m.group(1) not in
                                      [p for c in all_cols for p in _phrases(c)]):
            pass  # bare "in <value>" is resolved by the endpoint against data
    bare = re.search(r"\b(?:in|for)\s+([a-z][\w-]*)\b", q)
    bare_value = bare.group(1) if bare and bare.group(1) not in (
        "the", "a", "of", "all", "each") else None

    desc = "Computed " + ", ".join(parts) if parts else "Computed value"
    confidence = "high" if not bare_value else "medium"
    return {"ok": True, "formula": formula, "group_by": group_by,
            "filters": filters, "top_n": top_n, "bare_value": bare_value,
            "description": desc, "confidence": confidence, "used": used}


def _refuse(reason: str, schema: list[dict], measures: list[dict]) -> dict:
    numeric = [c["name"] for c in schema
               if c["inferred_type"] in ("number", "integer")]
    cats = [c["name"] for c in schema if c["inferred_type"] == "text"
            and not re.search(r"(^|_)id$", c["name"].lower())]
    examples = []
    if measures:
        examples.append(f"{measures[0]['name']}" +
                        (f" by {cats[0]}" if cats else ""))
    if numeric:
        examples.append(f"total {numeric[0].replace('_', ' ')}" +
                        (f" by {cats[0]}" if cats else ""))
        examples.append(f"average {numeric[0].replace('_', ' ')} last month")
    examples.append("how many rows this year")
    return {"ok": False, "reason": reason,
            "answerable": {
                "measures": [m["name"] for m in measures],
                "numeric_columns": numeric,
                "group_by_columns": cats,
                "examples": examples[:4]}}


def suggest_widget(plan: dict, dataset_id: str, question: str,
                   date_grouped: bool) -> dict:
    """Chart suggestion derived from the grounded plan (never from vibes)."""
    if plan.get("group_by") is None:
        wtype = "kpi"
    elif date_grouped:
        wtype = "line"
    elif plan.get("top_n"):
        wtype = "bar"
    else:
        wtype = "bar"
    return {"type": wtype, "title": question.strip()[:80].rstrip("?") or "Answer",
            "dataset_id": dataset_id, "formula": plan["formula"],
            **({"group_by": plan["group_by"]} if plan.get("group_by") else {})}
