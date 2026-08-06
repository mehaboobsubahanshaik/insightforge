# Connector & Data Guide

## The gallery model
The Sources gallery shows **19 platform tiles** driven by
`backend/src/insightforge_api/services/connectors/catalog.py`. Tiles map to
**engines** by wire protocol (ADR 0008):

* **PostgreSQL-wire** (engine `postgres.py`): PostgreSQL, Supabase, Neon,
  Amazon RDS·PostgreSQL, Cloud SQL·PostgreSQL, Azure·PostgreSQL,
  TimescaleDB, CockroachDB — because these *are* PostgreSQL to a client.
  Config: host, port, database, table, cursor_column, `sslmode`
  (prefer/require/disable — cloud platforms want `require`).
* **MySQL-wire** (engine `mysql.py`): MySQL, MariaDB, Amazon RDS·MySQL,
  Cloud SQL·MySQL, Azure·MySQL. Config: same shape, boolean `ssl`.
* **SaaS** (engine `saas.py`): QuickBooks, HubSpot, Salesforce, Shopify,
  Stripe, GA4 — each ships a **sandbox demo** (tick the box in the wizard,
  no credentials needed) that lands realistic typed rows.

Adding a platform whose wire protocol we already speak = **one row in
catalog.py + one test**. The gallery, wizard and connection cards render
from the catalog automatically.

## Sync semantics
* `full` — re-extracts everything into a fresh import generation.
* `incremental` — `WHERE cursor_column > last_cursor ORDER BY cursor_column`
  (numeric-aware comparison), returns `no_change` when nothing new.
* Every run is recorded (`sync_runs`) with rows extracted/loaded and errors;
  connection health rolls up from recent runs.
* Schedules honor plan floors (free: daily, starter: hourly, growth: 15m).

## Safety posture (both DB engines)
* identifiers (database/table/cursor) regex-validated **and** quoted —
  `shop_orders; DROP TABLE x` is rejected at create time (422);
* values only ever bound as parameters;
* metadata endpoints blocked (`169.254.169.254`, `metadata.google.internal`);
* credentials envelope-encrypted per tenant; never returned by any API;
* connection failures return **actionable guidance** — inside Docker,
  `127.0.0.1` is the API container, so the error suggests `postgres`,
  `host.docker.internal`, or your cloud hostname + SSL.

## The trust pipeline (uploads and syncs alike)
parse → **infer types** (integer/number/date/text) → validate rows →
**quarantine** bad ones (never drop) → profile columns → **quality score**
(0–100) → DQ results + history point → lineage hop. **Cleaning recipes**
(trim/case/replace/fill_missing/strip_non_numeric, ≤20 steps) re-run this
pipeline over ALL rows — rescuing quarantined ones — into a new generation.

## Demo sources
`database/seeds/`: `demo_shop.sql` (PG, 15 orders), `demo_shop_mysql.sql`
(MySQL, 12 orders + demo/devpassword), plus `*_more_orders.sql` deltas to
demonstrate incremental sync, and two sample CSVs for uploads.
