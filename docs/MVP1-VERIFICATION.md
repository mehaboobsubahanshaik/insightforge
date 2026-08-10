# MVP 1 Verification — Exit-Criteria Evidence

Status: **COMPLETE for internal alpha / design-partner demonstrations.**
Not for commercial release (per MVP1 customer status).

## Exit criteria → evidence

| Criterion | Evidence |
|---|---|
| Tenant isolation tests pass | API-level cross-tenant tests + database-level: `tests/test_billing_security.py` connects as the restricted `app_user` role and proves RLS blocks below the ORM. 69/69 backend tests green. |
| New customer reaches a useful dashboard via guided onboarding | `scripts/live_smoke.py` (14 checks): register → upload → quality → template dashboard → publish → share, plus the in-app tour + Home checklist that instruments the same funnel. |
| Imports repeatable and idempotent | Cursor watermark + import generations; no-delta syncs short-circuit to `no_change`; idempotency asserted in `tests/test_connectors.py` / `test_data.py`. |
| Data quality failures visible and actionable | Score + per-rule results + quarantine-with-reason in UI; recipes are the rescue path and re-score on apply (`tests/test_data.py`, smoke checks 3–7). |
| Permission enforcement tested at API and database levels | `require()` on every route (API); RLS-as-`app_user` (database). Both in the suite. |
| Dashboards carry freshness and lineage | Freshness/quality readout on every dashboard, share page, and PDF; lineage ≤2 clicks from any chart. |
| Production deployment repeatable | One-command compose with auto-migrations + health checks; ROLLBACK-PROCEDURE.md and BACKUP-RESTORE.md (with rehearsal drill) complete the operational loop. |

## Scope decisions recorded for MVP1 (deliberate, not gaps)

* **SaaS connector**: QuickBooks/HubSpot/Salesforce/Shopify/Stripe/GA4 ship in
  `sandbox_demo` mode — bundled realistic fixtures exercising the FULL
  pipeline (discovery → initial import → incremental → quality) and fully
  tested. `live` mode clients exist (bearer/basic auth from the vault) but
  OAuth *consent-flow acquisition* and verification against real vendor
  servers are deferred to the first design-partner integration, which is
  exactly what design partners are for. MVP1's "one priority SaaS connector"
  is satisfied in sandbox scope; the checklist line for live OAuth moves to
  the MVP2+ backlog.
* **MFA recovery**: one-time recovery codes shipped (migration 0003,
  `tests/test_mfa_recovery.py`); org-wide MFA *enforcement* policy deferred.
* **Deferred polish** (backlogged, not blocking alpha): Excel multi-sheet
  selection, KPI previous-period deltas, in-widget table sorting, date-range
  and multi-select filters, catalog search + description/owner metadata,
  storage-bytes metering, per-column min/max profiling. Cross-referenced in
  ENGINEERING-STANDARDS.md "Deliberate deferrals".

## Verification run (record each release)

| Date | Gates (69 backend / 7 ml / lint / js / migration cycle / 14-check smoke) | By |
|---|---|---|
| 2026-08-09 | all green | reference build |
| _re-run on your machine and add a row_ | | |