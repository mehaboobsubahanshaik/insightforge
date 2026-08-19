# API Catalog (live spec: /docs OpenAPI)
Routers: auth(+sessions) · tenants(theme/domain/semantics/me) · workspaces ·
connections(+rotate) · datasets(upload csv/xlsx/json/xml, prep ops, join/
union, governance, pii, drift, alerts+lifecycle, measures, ask, exports,
histogram/scatter, timeseries, issues) · dashboards(+bookmarks/snapshot) ·
embed(tokens/data/query/widgets) · public_api(ifk_ keys) · webhooks · ai
(feedback/provider/summarize) · agents(+plans/orchestrate/narrative) ·
catalog(glossary/lineage/impact/approvals) · enterprise(sso/scim/abac/
reviews/cmk/audit-export/deployment/sla/support/legal-hold/flags/cost/
break-glass/impersonate) · mlops(models/causal/simulate/what-if/scenarios/
root-cause/azure/private/governance) · semantic(model/query/measures) ·
partner(templates/tenants) · platform(status/admin).
Standards: bearer auth; role scopes via require(); RFC7807 problems +
correlation ids; rate limit 300/min (env); Idempotency-Key on POST;
security headers; cursor pagination where lists grow.
