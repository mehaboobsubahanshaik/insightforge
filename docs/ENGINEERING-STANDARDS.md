# Engineering Standards

* **Layout law**: features map to files (see FILE-MAP.md). New capability =
  new/edited file on an existing row, or a new row — never a re-shuffle.
* **Python**: ruff-clean (rules in backend/pyproject.toml), type-hinted
  services, async end-to-end. No raw SQL outside migrations and the two
  wire-protocol engines (where identifiers are validated + quoted).
* **Tests define behavior**: every feature lands with API-level tests;
  security properties (RLS, vault, entitlements) are tested from the
  attacker's seat (`test_billing_security.py` connects as the restricted
  role). MySQL-dependent tests skip locally when no server is present and
  fail-hard in CI (`REQUIRE_MYSQL=1`).
* **Migrations are append-only** from 0002 onward; 0002 is deliberately
  idempotent to converge early dev databases (see its docstring).
* **Frontend**: no framework by decision (ADR 0012): ES2020, per-feature
  files with banner comments, `node --check` clean, all rendering through
  `esc()`; state in one `S` object; every network call through `api()`.
* **Errors**: RFC7807 problem+json with correlation IDs; connector failures
  return actionable guidance (the docker-networking hint is a product
  feature, not a log line).
* **Copy tone**: numbers are always accompanied by their evidence
  (freshness/quality/governed) — in UI, PDFs, share pages and alert emails.

## Deliberate deferrals & conventions (documented, not forgotten)
* **Redis**: provisioned in compose (`insightforge-redis`, `REDIS_URL` already
  injected) but consumed by no code path yet — it is reserved for the queue
  and cache work in backlog items 5 and 9's evolution. Removing it would make
  those land as infra changes; keeping it makes them pure code changes.
* **Metrics & tracing**: current observability = structured logs with
  correlation IDs (returned as `X-Correlation-Id`), `/api/v1/health`, and the
  immutable audit trail. Prometheus `/metrics` and OpenTelemetry tracing are
  deferred until there is more than one deploy target to observe; the
  correlation-ID middleware in `main.py` is the future span anchor.
* **Pagination**: v1 list endpoints use server-capped `limit` parameters
  (audit 500, activity 100, preview 200) rather than offset/cursor paging —
  SMB tenant list sizes make cursors premature. The convention when needed:
  `?limit=&after=<id>` keyset paging, added per-endpoint without breaking
  existing callers.
* **Dark mode**: the design system is deliberately light-only ("premium
  daylight" palette in `theme.css`). The first build shipped dark and tested
  poorly against the trust-telemetry color coding; tokens are structured so a
  `[data-theme=dark]` override block is additive if that decision reverses.
* **Demo seeding**: there is no demo-tenant seeder by design — registration
  IS the seeder (it provisions tenant, workspace, plan, owner in one call),
  and the demo *business* data lives in `database/seeds/` for connectors to
  pull. A scripted walkthrough tenant would drift from the wizard's reality.