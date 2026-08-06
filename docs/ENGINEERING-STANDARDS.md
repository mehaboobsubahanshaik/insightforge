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
