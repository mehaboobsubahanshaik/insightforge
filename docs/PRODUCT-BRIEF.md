# Product Brief — personas, pricing hypothesis, risk register

## Personas
- Owner-operator "Priya" (30-person retailer): spreadsheets + Shopify;
  needs first dashboard in an afternoon. KPI: time-to-first-dashboard.
- Ops analyst "Daniel" (300-person services firm): builds governed
  dashboards, schedules reports, chases data quality.
- Vendor PM "Sana" (SaaS company): embeds customer-facing analytics via
  SDK; cares about isolation proof and white-labeling.
- IT/compliance "Rafael" (enterprise dept): SSO/SCIM, reviews, exports,
  SIEM, residency posture.

## Pricing hypothesis (validate with pilots)
free: 3 datasets, 500 embed views/day, AI-capped · starter: teams +
schedules + 10k views · growth: quotas up, SLAs, SSO/SCIM, partner/OEM ·
enterprise (sales-led): dedicated posture, CMK, private models.
Usage meters already in billing_events: embed.view, ai.question, ai.tokens.

## Risk register (top)
1. Neon credential in git history — rotate (open since MVP2).
2. Postgres analytical ceiling — see STORAGE-EVALUATION migration path.
3. Single-process scheduler/limiter/idempotency — shared store before
   multi-instance deploy.
4. Vendor connectors need customer OAuth — sandbox_demo until then.
5. LLM live path unexercised until a key exists (mock-tested).
6. No load-test suite yet — before commercial claims on NFR targets.
