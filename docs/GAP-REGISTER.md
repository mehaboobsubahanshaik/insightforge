# Gap Register — repo vs. master product prompt

## Bucket A — CLOSED through R14 (see COMPLETION-VERIFICATION.md)
R1–R14 delivered: security, connectors framework, LLM abstraction, exports,
semantics, roles, alert lifecycle, viz types, interactions, identity, ops,
docs. Remaining Bucket-A items (small, tracked in PRODUCT-BACKLOG.md):
geo + cohort renderers, custom visuals, reference-data mapping, GraphQL
source, webhooks-as-source (append-ingest design), formal dead-letter queue,
service-account creation flow, enrichment. (bullet/control/annotations/
collections/snapshots/per-key-usage/Parquet/passwordless closed R15-R17;
threaded comments + PDF reports discovered pre-existing.)

## (superseded) original Bucket A plan
R1 security completion (this phase) · R2 connector framework (generic
REST/JSON/Sheets-CSV) · R3 LLM provider abstraction (env-keyed, deterministic
fallback, redaction + cost tracking) · R4 viz breadth + Excel/print export +
watermarks · R5 joins/union, fiscal calendars, currency, time grains, prep
pivot/formula columns · R6 full role catalog, alert lifecycle
(ack/escalation/dedup/quiet hours), favorites/activity/issue reporting.

## Bucket B: external-dependency — config + wiring + docs, never simulated
Vendor OAuth connectors (QuickBooks/Salesforce/HubSpot/Shopify/Stripe/GA…),
live LLM provider calls (abstraction ships in R3; key = customer's), SMS
(Twilio), Azure cloud deployment (AKS/Container Apps, Key Vault, Front Door,
Entra), SAML XMLDSig chain, CMK envelope encryption, region pinning /
PrivateLink / dedicated stacks, Azure ML scoring, DAST + independent pentest,
SOC2/ISO audits. Pattern: real config endpoints + validation + docs
(established in MVP4/5).

## Bucket C: rewrite-class — roadmap decisions, not patches
Next.js/TypeScript/Tailwind frontend rebuild · TimescaleDB / Redis / Kafka /
analytical-warehouse adoption · Temporal workers · OpenTelemetry tracing ·
microservice extraction. Each would destabilize the tested core; adopt
deliberately with migration plans, not bolt on.

## Standing risks
Neon credential rotation (open since MVP2, flagged in every verification
doc). main lags suhan until the grand merge.
