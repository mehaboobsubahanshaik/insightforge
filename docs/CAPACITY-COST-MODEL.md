# Capacity & Cost Model (assumption-driven; validate with load tests)
Unit assumptions: avg tenant 5 datasets × 100k rows (~1.5KB/row JSONB)
≈ 750MB incl indexes → ~$0.15/tenant/mo storage on managed PG.
Compute: 2vCPU/4GB api pod ≈ 200 concurrent light users; scheduler
negligible until ~1k tenants (jobs are per-cycle linear scans — first
optimization target: due-job indexes, already present).
AI: deterministic = $0. LLM path: metered per call (ai.tokens events) —
price plans above observed token cost.
Cost guardrails in product: dataset/row caps, embed_views_per_day,
ai daily quotas, rate limits, 500k union cap, 2M join-pair cap.
Scale triggers: >5M rows/tenant → DuckDB read path; >50 req/s sustained →
second api instance + shared idempotency/rate store (Redis);
audit table > 50M rows → Timescale/partitioning.
