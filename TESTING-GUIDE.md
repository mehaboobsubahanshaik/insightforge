# Testing Guide

## Quick start

```bash
pip install -e ./ml -e "./backend[dev]"
cd backend && python -m pytest -q     # 66 passed
cd ../ml  && python -m pytest -q      # 7 passed
```

The harness **self-provisions everything it needs**: it truncates the app
tables, recreates the `demo_shop` PostgreSQL source (15 rows), and — when a
MySQL/MariaDB server is listening on 127.0.0.1:3306 with the demo user — the
`demo_shop_mysql` source (12 rows). On dev sandboxes it will even try to
start stopped local services.

## Suites (backend/tests/)

| File | Proves |
|---|---|
| `test_auth.py` | register→login→MFA→refresh rotation→reset; roles & invitations; workspaces |
| `test_billing_security.py` | **RLS from the attacker's seat** (connects as restricted `app_user`), vault encryption, entitlements, audit, meters |
| `test_data.py` | trust pipeline: inference, scoring, quarantine, lineage, export |
| `test_connectors.py` | PostgreSQL live sync + guards; SaaS sandboxes; schedules |
| `test_dashboards.py` | templates, widgets, formulas, filters, publish/versions |
| `test_distribution.py` | share links, comments+mentions, reports, alerts, scheduler |
| `test_new_features.py` | 19-tile catalog, **MySQL live incremental**, recipes, drill-through, ops console, docker-hint errors |
| `test_ml_insights.py` | `/insights`: forecast continues trends, spike detection, validation, tenant isolation |

`ml/tests/test_ml.py` — model unit tests: linear-trend recovery, band
widening √h, spike/drop/drift behavior, gap handling.

## MySQL-dependent tests
Skip locally with a printed one-line docker command when no server is
present; **fail hard in CI** via `REQUIRE_MYSQL=1` so a misconfigured runner
can't silently skip coverage. Local server setup:
`mysql -u root < database/seeds/demo_shop_mysql.sql`.

## Lint & static checks

```bash
cd backend && python -m ruff check src tests ../ml ../scripts
node --check frontend/src/js/*.js
```

## Migration cycle check

```bash
cd backend
python -m alembic downgrade base && python -m alembic upgrade head
```

## Performance smoke (headline numbers on a dev laptop)

```bash
cd backend && python -m uvicorn --app-dir src insightforge_api.main:app --port 8000 &
python ../scripts/perf_smoke.py
# 50k-row upload + full pipeline:  ~5s
# dashboard hydration p50:         ~120ms
# 10 concurrent hydrations:        <2s
# preview 50 rows:                 ~25ms
```

## Conventions
* Tests are API-level (httpx against the ASGI app) — they exercise auth,
  RLS, and serialization exactly as a browser would.
* Fixed seeds and fixed CSV fixtures: numbers in assertions are exact.
* Every test gets a truncated database; the session provisions sources once.
