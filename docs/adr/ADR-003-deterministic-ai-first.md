# ADR-003: Deterministic analytics engine before LLM
Status: accepted (MVP3). NLQ/narratives/agents are deterministic pipelines
over the governed query layer — explainable, quota'd, audited, eval-tested.
Rationale: trust + zero AI cost + no injection surface. Path: R3 adds an
LLM provider abstraction behind the SAME guardrails; deterministic engine
remains the fallback and the grounding.
