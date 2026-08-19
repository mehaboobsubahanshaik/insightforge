# Observability Design
Today: structured logs w/ correlation_id per request (RFC7807 echoes it);
audit trail as business-event log; scheduler heartbeat on /status + /sla;
sync health per connection; drift + latency in ml governance; token/latency
per LLM call in audit detail.
Deploy layer (documented, not in compose): ship logs to any collector;
alert on: heartbeat stale >60s, 5xx rate >1%, p95 breach vs NFR-TARGETS,
webhook failure streaks, siem.audit delivery lag.
Next (Bucket C): OpenTelemetry traces once multi-service; RED dashboards.
