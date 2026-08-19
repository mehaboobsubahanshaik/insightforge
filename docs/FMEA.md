# Failure-Mode Analysis (top modes)
| Failure | Effect | Detection | Mitigation | Residual |
|---|---|---|---|---|
| Postgres down | full outage | /status, heartbeat | managed HA in prod | RTO per NFR doc |
| Scheduler death | alerts/reports stop | heartbeat staleness on /status + SLA endpoint | restart; jobs idempotent+cursor'd | single-instance today |
| Bad migration | boot failure | CI migration cycle test | downgrade fns; backups | manual drill |
| Webhook target down | events undelivered | delivery failures logged | retries; outbox mode | no DLQ for runs |
| LLM provider outage | rephrase fails | httpx errors | deterministic fallback ALWAYS | none — by design |
| Hostile data → LLM | prompt injection | R8 scanner | egress blocked, grounded served, audited | marker list evolves |
| Embed token leak | customer data view | expiry+audit trail | short TTLs; secret rotation (once-set note) | vendor hygiene |
| Quota bypass attempt | cost abuse | 429s + metering | plan enforcement tested | — |
| Tenant flood | noisy neighbor | rate limiter, caps | dedicated posture (G4) | shared-DB ceiling |
