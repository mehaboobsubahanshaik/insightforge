@"
# MVP 2 Verification — Exit-Criteria Evidence

Status: **COMPLETE for controlled pilots with selected SMB design partners.**
Not for broad commercial launch (per MVP2 customer status).

## Exit criteria -> evidence

| Criterion | Evidence |
|---|---|
| Nontechnical users can build governed dashboards | Template apply + drag-reorder builder + governed formulas/measures; cross-filter by clicking any segment; drill-through to rows; saved personal/team views. Exercised by scripts/live_smoke.py and the dashboards test suite. |
| Scheduled refresh and report distribution are reliable | Scheduler tests cover: report PDF delivery + billing event, quota, alert fire-once/recover/refire, sync failure backoff + heal, owner notification at 3-failure streak (once per streak), report quick-retry (retrying -> failed -> sent). tests/test_distribution.py: 6 tests. |
| Connector failures are diagnosable | Actionable error messages (docker-networking guidance tested), per-run history with rows/status/error, per-connection health + consecutive_failures in UI, ops console failure counts, owner email on persistent failure. |
| Quotas and billing events are measured | Server-side entitlements at create+schedule time; plan.changed/report.sent billing events; daily meter_readings; asserted in tests/test_billing_security.py + test_distribution.py. |
| Customer onboarding documentation exists | docs/CUSTOMER-ONBOARDING.md — customer-facing first-30-minutes walkthrough; every claim maps to a tested feature. |
| Support staff have safe operational tooling | Platform ops console: secret-gated, counts-only (no tenant data), suspension flow tested; /admin/diagnostics asserted to never leak credentials. |
| Security and performance tests pass | Full suite green in the compose environment: 69 passed, 2 skipped (MySQL tests, absent by design in compose; fail-hard in CI). Perf reference: 50k-row upload + pipeline 5.9s, hydration p50 111ms, 10 concurrent hydrations 1.8s. |

## Scope decisions recorded for MVP2 (deliberate, not gaps)

* Additional connectors (QuickBooks/HubSpot/Salesforce/Shopify/Stripe/GA4)
  ship in sandbox_demo mode, fully pipeline-tested; live OAuth consent flow
  is deferred to the first design-partner integration (carried from
  MVP1-VERIFICATION, unchanged).
* Billing integration is the event stream (plans, billing_events, meters) a
  payment provider attaches to; no gateway yet by design.
* Usage analytics = tenant usage vs limits + meters + activity/audit feeds;
  a product-analytics event stream is backlogged.

## Known open items (tracked, not hidden)

* A real database credential remains in the tracked .env.example and git
  history (remediation guided, deferred by decision on 2026-08-10). Until the
  Neon password reset is confirmed and the template sanitized, this is the
  outstanding security finding for any pilot review.

## Verification runs

| Date | Environment | Result | By |
|---|---|---|---|
| 2026-08-10 | docker compose (in-container suite) | 69 passed, 2 skipped | project team |
"@ | Set-Content -Encoding utf8 docs\MVP2-VERIFICATION.md

findstr /c:"69 passed" docs\MVP2-VERIFICATION.md