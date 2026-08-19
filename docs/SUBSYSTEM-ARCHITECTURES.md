# Subsystem Architecture Diagrams

## Security architecture
```mermaid
graph LR
REQ[Request] --> RL[rate limit + idempotency] --> AUTHN[JWT / X-API-Key / embed sig / magic link]
AUTHN --> RBAC[require scope - 14 roles] --> ABAC[attrs + row/col policies]
ABAC --> RLS[(Postgres RLS per tenant)]
RLS --> AUD[audit trail] --> SIEM[SIEM stream + exports]
UP[Uploads] --> NEUT[csv neutralize + defusedxml + size caps]
```

## AI architecture
```mermaid
graph LR
Q[Question/agent task] --> NLQ[deterministic parser] --> GOV[governed formula engine + RLS]
GOV --> GT[grounded text + evidence]
GT -->|optional| INJ{injection scan} -->|clean| RED[redact PII] --> LLM[provider abstraction]
INJ -->|hostile| FB[deterministic fallback + audit]
LLM --> METER[tokens/latency metering]
GT --> PLAN[action plans] --> APPR[human approval] --> OUT[closed-loop outcomes]
```

## Ingestion architecture
```mermaid
graph LR
SRC[files: csv/xlsx/json/xml/parquet · DBs · SaaS · REST/Sheets] --> EXT[extract: cursors, full refresh, retries]
EXT --> TYPE[type inference] --> DQ[quality rules R001-R011]
DQ -->|clean| ROWS[(dataset_rows + import lineage)]
DQ -->|invalid| QUAR[(quarantine + reason)]
ROWS --> HEALTH[freshness/quality alerts + drift report]
```

## Semantic architecture
```mermaid
graph LR
DS[(datasets)] --> MEAS[measures: formula+unit+versions+certification]
DS --> MODEL[semantic model: hierarchies, relationships, subject areas]
MODEL --> VJ[virtual join queries - runtime SQL]
TEN[tenant semantics: fiscal + FX] --> TS[timeseries grains]
MEAS --> VAL[validation tests min/max]
MEAS --> GLOSS[glossary + lineage + impact + approvals]
```

## Embedded architecture
```mermaid
graph LR
VENDOR[Vendor app] --> MINT[mint signed token: dashboard+customer+filters+scope IN signature]
MINT --> IFR[embed.html/SDKs] --> DATA[/embed data+query/]
MINT -->|scope=edit| EDIT[/embed widgets PUT/]
DATA --> RLSF[filters enforced server-side] --> METERQ[embed.view metering + audit w/ customer label]
PARENT[OEM parent] --> CHILD[child tenants + templates + quotas]
```

## Component diagram (control plane)
```mermaid
graph TB
main[main.py factory + middleware] --> R1[routers: auth tenants workspaces connections datasets dashboards embed public_api webhooks ai agents catalog enterprise mlops semantic packs platform]
R1 --> SV[services: querysvc formulas ingest prepsvc datasec llm narrative notify mailer vault agents connectors/* industry_packs pii]
SV --> ML[ml pkg: forecast anomaly holt-winters]
main --> SCHED[scheduler: syncs reports alerts escalations health lifecycle forecasts]
```
