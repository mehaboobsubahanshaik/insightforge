# AI Evaluation Suite

How InsightForge evaluates its AI layer — and why the evaluation is ordinary
pytest rather than a separate LLM-judging harness.

## Run it

```bash
# just the AI evals (10+ tests)
python -m pytest -m ai_eval -q
# everything
python -m pytest -q
```

CI runs the eval suite as a named step on every push, so an AI regression
fails the build like any other bug.

## What is asserted, by risk

| Risk | Assertion | Test |
|---|---|---|
| Hallucination | Answers carry exact computed values; unanswerable questions refuse with alternatives | `test_ai_nlq.py` |
| Prompt injection (direct) | Hostile instruction text yields grounded refusal; data survives | `test_ai_nlq.py::test_honest_refusal_and_injection_is_inert` |
| SQL injection | Question text never reaches SQL; DROP TABLE payloads are inert strings | same |
| Permission escape | Another tenant asking about a dataset gets 404 (RLS + scoped lookup) | same |
| Wrong-column grounding | Measures outrank columns; single-numeric datasets default correctly | `test_ai_nlq.py` |
| Narrative dishonesty | Brief states exact windows; empty windows say "may be stale"; datasets without dates get no fake comparison | `test_ai_narrative.py` |
| Nonsense attribution | Drivers must be text-typed categories — a date-grouped widget cannot drive attribution (field bug, now a regression test) | `test_ai_narrative.py::test_drivers_never_use_date_columns...` |
| Bad prep advice | Suggestions require observed evidence (sampled values, quarantine reasons) and must be applyable + improving | `test_ai_prep_feedback.py` |
| Cost runaway | Per-plan daily question quota returns 429; latency measured per answer (`elapsed_ms`) | `test_ai_prep_feedback.py::test_ai_question_quota_enforced` |

## Why deterministic evals suffice today

The AI layer is a deterministic parser + template narrator over governed
computations (ADR 0013): identical input yields identical output, so evals
are exact assertions, not statistical samples. Hallucination is prevented by
construction — prose is filled from computed numbers only.

## The feedback loop

Every AI surface carries 👍/👎 (stored in `ai_feedback`, tenant-scoped,
listable by admins at `GET /api/v1/ai/feedback`). Field reports become
regression tests — two already have: the "total by region" single-column
default, and the date-column driver bug found in a production report email.

## When an LLM adapter arrives

The optional LLM planner slot (off by default) must ship with: the same eval
suite passing unchanged, plus sampled-output evals for the new probabilistic
surface, injection red-team cases (direct + data-borne), the existing quota
mechanism as its budget control, and `elapsed_ms` monitoring. The rule stays:
models emit formulas/plans, never SQL, and every claim traces to a computation.
