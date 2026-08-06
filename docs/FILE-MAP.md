# InsightForge — Feature ↔ File Map

**The rule this repo is built around: adding to a feature means editing the
files on its row — never restructuring folders.** Each frontend file opens
with a banner comment saying what belongs in it.

## Top-level layout

| Folder | Owns | Container |
|---|---|---|
| `frontend/` | Everything the browser loads (HTML/CSS/JS) | `insightforge-web` (nginx) |
| `backend/`  | FastAPI app: routers, services, connectors, tests | `insightforge-api` |
| `database/` | Schema migrations + demo seed data | applied by `insightforge-api` on boot |
| `ml/`       | Forecasting & anomaly models (own package + tests) | installed into `insightforge-api` |
| `docs/`     | Product, architecture and decision records | — |
| `scripts/`  | Operational scripts (perf smoke) | — |

## Feature rows

| Feature | Frontend file | Backend file(s) | Tests |
|---|---|---|---|
| Login / register / MFA / password reset | `frontend/src/js/core.js` | `backend/src/insightforge_api/routers/auth.py`, `services/security.py` | `backend/tests/test_auth.py` |
| Sessions, API client, loading animation, toasts | `frontend/src/js/core.js` | `backend/src/insightforge_api/main.py` (middleware) | `backend/tests/test_auth.py` |
| **Workspaces (project folders)** | `frontend/src/js/core.js` (switcher, manager modal) | `backend/src/insightforge_api/routers/workspaces.py` | `backend/tests/test_auth.py` |
| Navigation, Home, onboarding tour | `frontend/src/js/home-tour.js` | — | — |
| Connector gallery + wizard + sync | `frontend/src/js/sources.js` | `routers/connections.py`, `services/connectors/catalog.py` | `backend/tests/test_connectors.py`, `test_new_features.py` |
| A new database/SaaS platform tile | `frontend/src/js/sources.js` (only if custom fields) | `services/connectors/catalog.py` (+ engine in `connectors/` if a new wire protocol) | `backend/tests/test_new_features.py` |
| PostgreSQL-wire engine | — | `services/connectors/postgres.py` | `test_connectors.py` |
| MySQL-wire engine | — | `services/connectors/mysql.py` | `test_new_features.py` |
| SaaS engines (QuickBooks…GA4) | — | `services/connectors/saas.py` | `test_connectors.py` |
| CSV/Excel upload + trust pipeline | `frontend/src/js/sources.js` (modal) | `routers/datasets.py`, `services/ingest.py` | `test_data.py` |
| Type inference / quality scoring / quarantine | — | `services/ingest.py` | `test_data.py` |
| Cleaning recipes | `frontend/src/js/datasets.js` | `services/ingest.py` (`RECIPE_OPS`), `routers/datasets.py` | `test_new_features.py` |
| Dataset views, preview, drill chips, lineage | `frontend/src/js/datasets.js` | `routers/datasets.py`, `services/querysvc.py` | `test_data.py` |
| **AI insights (forecast + anomalies)** | `frontend/src/js/datasets.js` | `routers/datasets.py` (`/insights`) → **`ml/insightforge_ml/forecast.py`, `anomaly.py`** | `ml/tests/test_ml.py`, `backend/tests/test_ml_insights.py` |
| Dashboards: list/builder/widgets/charts | `frontend/src/js/dashboards.js` | `routers/dashboards.py`, `services/querysvc.py` | `test_dashboards.py` |
| Governed formulas | `frontend/src/js/dashboards.js` (input only) | `services/formulas.py` | `test_dashboards.py` |
| Cross-filter + drill-through | `frontend/src/js/dashboards.js` | `services/querysvc.py` (filters) | `test_dashboards.py`, `test_new_features.py` |
| Publish / versions / restore | `frontend/src/js/dashboards.js` | `routers/dashboards.py` | `test_dashboards.py` |
| Comments + @mentions | `frontend/src/js/dashboards.js` | `routers/dashboards.py`, `services/mailer.py` | `test_distribution.py` |
| Share links + public snapshot page | `frontend/src/share.html` | `routers/dashboards.py` (`/share`) | `test_distribution.py` |
| Scheduled PDF reports | `frontend/src/js/admin.js` | `routers/dashboards.py` (reports), `services/reportsvc.py`, `scheduler.py` | `test_distribution.py` |
| Threshold alerts | `frontend/src/js/admin.js` | `routers/dashboards.py` (alerts), `scheduler.py` | `test_distribution.py` |
| Members, roles, invitations | `frontend/src/js/admin.js` | `routers/tenants.py`, `authz.py` | `test_auth.py` |
| Audit trail (Activity) | `frontend/src/js/admin.js` | `audit.py` (writers everywhere) | `test_billing_security.py` |
| Billing, plans, usage meters | `frontend/src/js/admin.js` | `routers/tenants.py`, `services/entitlements.py` | `test_billing_security.py` |
| Platform operator console | `frontend/src/ops.html` | `routers/platform.py` | `test_new_features.py` |
| Theme / colors / typography | `frontend/src/css/theme.css` | — | — |
| Schema change | — | new file in `database/migrations/versions/` (+ `models.py`) | `alembic upgrade head` in CI |
| Demo/source seed data | — | `database/seeds/*.sql` | used by `backend/tests/conftest.py` |

## Worked examples

* **"Add a `snowflake` tile"** → one entry in `services/connectors/catalog.py`
  (engine `postgresql` if using their PG-compatible endpoint) + one test in
  `test_new_features.py`. Zero frontend edits — the gallery renders from the catalog.
* **"Add a `median` aggregation"** → `services/querysvc.py` (agg map) +
  dropdown option in `frontend/src/js/dashboards.js` + a `test_dashboards.py` case.
* **"Change the forecast model"** → `ml/insightforge_ml/forecast.py` only;
  keep the `forecast_series()` return shape and nothing else moves
  (see `docs/adr/0011-ml-stdlib-first.md`).
* **"New cleaning op `round_numbers`"** → `services/ingest.py`
  (`RECIPE_OPS` + one branch in `apply_recipe`) + label in
  `frontend/src/js/datasets.js` `OPMETA` + a `test_new_features.py` case.
