# ADR 0013 — Natural-language questions via a deterministic governed parser

Status: accepted (MVP3). Context: the MVP3 checklist demands NL questions
that are grounded, permission-aware, injection-resistant, cheap, and
evaluable. Decision: the default NL path is a deterministic semantic parser
(`services/nlq.py`) that compiles questions into plans for the existing
formula engine — the same allow-listed path every widget uses.

Why not an LLM first: an LLM in the answer path reintroduces every risk the
checklist asks us to defend against (hallucination, prompt injection, cost,
latency) and then requires an eval suite to police it. A parser over the
governed semantic layer has those properties by construction: it can only
name columns/measures that exist, values travel as bind parameters, RLS
applies underneath, latency is milliseconds, cost is zero, and the "eval
suite" is ordinary pytest (`tests/test_ai_nlq.py`).

The LLM seam: `parse_question` returns a plan dict; a future LLM planner may
emit the same shape and MUST pass through the same allow-list validation
before execution ("models emit formulas, never SQL" — formulas.py). It is
off by default and out of MVP3's default path.

Honesty rule: unanswerable questions return `answered: false` with what CAN
be asked (measures, columns, examples) — never a guess. Every answer carries
description, confidence, freshness and quality score.
