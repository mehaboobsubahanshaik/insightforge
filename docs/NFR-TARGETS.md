# Non-Functional Requirement Targets

| Target | MVP tier | Enterprise tier | Measured by |
|---|---|---|---|
| Control-plane availability | 99.0%/mo | 99.9%/mo | /platform/status + heartbeat |
| API p95 (reads) | < 500 ms | < 250 ms | correlation-id logs |
| API p95 (queries/ask) | < 2 s | < 1 s | audit latency fields |
| Dashboard load | < 3 s | < 1.5 s | frontend timing |
| Query row cap | 50k rows | 50k rows | querysvc limits |
| Data freshness | per-dataset SLA (governance.alerts) | same + alerting | health job |
| RTO / RPO | 4 h / 24 h | 1 h / 1 h | DR-VALIDATION drills |
| Backup frequency / restore test | daily / quarterly | daily / monthly | RUNBOOKS |
| Cross-tenant leakage | 0, ever | 0, ever | attack-shaped test suite |
| AI cost/request | metered (ai.tokens) | + per-plan caps | billing_events |
| Rate limits | 300 req/min/principal | negotiated | R7 limiter |
Load-test scripts (k6/locust) remain an open engineering item (gap register).
