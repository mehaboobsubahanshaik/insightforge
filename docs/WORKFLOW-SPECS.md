# Workflow Specifications

## Administration workflows
Invite→role→(review cycle: /enterprise/access-reviews)→revoke ·
Suspend/offboard: platform suspend → tenant offboard → grace → purge
(legal hold suspends purge) · Support: consent grant (time-boxed) or
impersonation (approval kind=impersonation, viewer-capped, dual-audit) ·
Break-glass: owner + reason → token + SIEM-visible audit.

## Billing & entitlement workflows
Trial→plan via POST /billing/plan → entitlements enforce (datasets, rows,
embed views/day, ai/day, report intervals) → meters (embed.view,
ai.question, ai.tokens) → invoice lines → /enterprise/cost-report.
Downgrade honesty: quota checks at creation time; existing objects kept.

## AI interaction flows
Ask: question → parse → governed formula → answer + evidence + freshness
+ confidence → feedback thumbs → eval suite corpus.
Summarize/brief: deterministic grounded text → optional LLM rephrase
(redacted, injection-scanned, metered) → grounded_text ALWAYS attached.
Agent plan: agent → findings+plan → approval queue → approve → act →
baseline captured → outcomes vs baseline → close loop.

## UX flows + states (per §15H)
Onboarding: register → guided tour → upload/connect → auto profile+score →
pack apply → first dashboard < 1h. Connector flow: pick tile → config →
verify creds → schedule → health visible. Prep flow: profile → suggestions
(advisory outliers) → apply recipe → re-score → quarantine rescue.
Builder flow: dataset → widget type (15) → formula/group → filters →
draft → publish → share/embed. Copilot flow: ask box (+🎤) → answer card
w/ evidence → follow-ups.
States: every list ships empty-state copy; loading spinners on fetch;
errors as RFC7807 toasts w/ correlation id; stale = freshness badge;
partial = skipped[] patterns (pack apply, drift report).

## Connector priority matrix (next wave)
| Connector | Demand | Effort | Door | Priority |
|---|---|---|---|---|
| Snowflake / BigQuery | ent data teams | S (SQL adapter) | 2 (creds) | P1 |
| SQL Server / Azure SQL | mid-market | S | 2 | P1 |
| Xero / Zoho CRM | SMB intl | M (OAuth apps) | 2 | P2 |
| Jira / Zendesk | ops packs | M | 2 | P2 |
| Google/Meta Ads | marketing pack | M | 2 | P2 |
| SFTP / object storage | file drops | M | 1/2 | P2 |
| Kafka / Event Hubs | streaming | L | 3 | P3 |

## Dashboard template + KPI inventory
12 industry packs × (3 KPIs + 3-widget starter) — services/industry_packs.py
is the source of truth; this doc indexes it. Chart library: kpi, table,
pivot, bar, line, area, pie, donut, funnel, waterfall, gauge, scatter,
histogram, bullet, control (15). Forecast intervals via insights; geo +
cohort tracked in PRODUCT-BACKLOG.md.
