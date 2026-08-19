# MVP Matrix (§15C) + Client-Segment Matrix (§15D)

| MVP | Objective | Functional scope | AI scope | Security scope | Customer readiness | Exit evidence | Complexity | Top risk |
|---|---|---|---|---|---|---|---|---|
| 1 | trusted data->dashboard | ingest, DQ, quarantine, dashboards, NLQ v1 | deterministic NLQ | RLS, RBAC, audit | internal alpha | isolation+idempotency tests | M | data trust |
| 2 | team self-service | builder, sharing, alerts, schedules, connectors | – | roles, quotas | design partners | builder+delivery tests | M | connector quality |
| 3 | commercial | AI layer, billing, lifecycle, public API, ops docs | briefs/prep/evals | hardening, privacy | GA gate — blocked on P0+load+DAST | eval suite + accept tests | L | release readiness |
| 4 | embedded/OEM | embeds, SDKs, white-label, partners, metering | – | signed scoped tokens | vendors | forged-filter tests | M | cross-customer leak |
| 5 | enterprise gov | SSO/SCIM/ABAC, col/row sec, catalog, SIEM, CMK posture | what-if/root-cause | reviews, exports | regulated (post-audit) | attack-shaped tests | L | infra realization |
| 6 | decision platform | 6 agents, plans, outcomes, causal, simulate | grounded agents | approval mandate | premium | 403-before-approval test | L | trust in actions |
| R1-18 | completion arc | see COMPLETION-VERIFICATION | scoring, seasonality | identity+ops closure | – | 158 tests | XL | scope honesty |

| Segment | Size | Pains | Connectors | Dashboards | AI needs | Plan | Min MVP |
|---|---|---|---|---|---|---|---|
| Small biz | 10-100 | spreadsheet chaos | uploads, Sheets, QuickBooks | packs: sales/finance | ask + weekly brief | free/starter | 3 |
| Medium biz | 100-1000 | conflicting KPIs | +CRM, Shopify, GA4, DBs | cross-dept + certified | drivers, alerts, forecasts | growth | 3 |
| SaaS vendor | any | build-vs-buy analytics | REST + their DB | embedded per-customer | headless + narratives | growth/ent | 4 |
| MSP | any | many orgs | per-client mix | templates via OEM | briefs per client | partner | 4 |
| Enterprise dept | 1000+ | governance | DBs + SSO | certified + reviewed | governed only | enterprise | 5 |
