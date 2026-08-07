# InsightForge — Vision & Personas

## One-liner
The trustworthy BI platform for small and mid-sized businesses: connect the
tools you already run, and get dashboards where **every number carries its
evidence** — freshness, quality score, and lineage.

## The wedge
Incumbent SMB BI (Zoho Analytics et al.) optimises for *count of charts*.
InsightForge optimises for *confidence per chart*. SMB owner-operators don't
lack charts; they lack the confidence to act on them, because data arrives
dirty, stale, and unexplained. Our differentiators, in priority order:
1. **Trust telemetry everywhere** — the FRESHNESS · QUALITY · GOVERNED
   readout follows every dashboard, dataset and shared snapshot.
2. **The trust pipeline is the product** — typing, profiling, DQ scoring,
   quarantine (never silent row drops), cleaning recipes with re-scoring.
3. **Governed self-service** — drag-drop building with formulas constrained
   to a governed semantic layer; no SQL escape hatches that rot.
4. **Honest AI** — forecasts and anomalies are computed by explainable
   models, labelled apart from facts, with confidence bands that widen.

## Personas
* **Owner-operator Priya** (48-person distributor): wants Monday-morning
  answers. Uses templates, checklist, scheduled PDF reports. Never writes SQL.
* **Ops analyst Arjun** (her one "data person"): connects MySQL/Postgres,
  fixes dirty columns with recipes, watches quarantine counts, sets alerts.
* **Fractional CFO Meera** (external): views published snapshots via expiring
  share links; comments with @mentions; never sees drafts or raw rows.
* **Platform operator (us)**: the ops console (`/ops.html`) — tenant health,
  suspension, failed-run counts; statuses and counts only, never tenant data.

## Product principles
1. Every number can explain itself (lineage in ≤2 clicks).
2. Never silently drop a row — quarantine and show the count.
3. Multi-tenancy is a database property (RLS), not an application habit.
4. Workspaces mirror how SMBs think: one project's documents in one place.
5. Boring, explainable models before clever, opaque ones.
## Success metrics (MVP horizon)
* **Activation**: % of new tenants reaching a published dashboard in ≤ 1 day
  (the checklist on Home instruments exactly this funnel).
* **Trust engagement**: % of weekly-active tenants that open lineage or the
  quarantine view — proves the differentiator is used, not decorative.
* **Data health**: median dataset quality score after first recipe ≥ 90.
* **Retention proxy**: tenants with ≥ 1 scheduled report or alert (recurring
  value delivery) — target 40% of paying tenants.
* **Expansion lever**: % of Starter tenants hitting the sync-interval floor
  (the designed upgrade trigger to Growth).