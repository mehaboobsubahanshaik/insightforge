# MVP3 Verification — Commercial Release

Date: 2026-08-16 · Branch: feat/mvp3 · Suite: 97 tests (95 pg-only + 2 MySQL) · Tag on close: v0.3-mvp3

## Checklist: 34/34 built, all test-covered
- **AI layer (P1)**: governed NLQ + chart suggestions + injection defenses (ADR 0013, test_ai_nlq); executive brief, PoP driver attribution, report summaries, metric explanations (test_ai_narrative); prep suggestions, feedback capture, daily quotas + elapsed_ms (test_ai_prep_feedback); formal eval suite `pytest -m ai_eval` (13 tests) in CI + docs/AI-EVALS.md.
- **Anomaly/trend/forecast**: pre-existing explainable ML, verified in-browser items 5–7.
- **Notifications (P2)**: HMAC webhooks, Slack/Teams formats, anomaly-triggered alerts (test_notifications).
- **Commercial (P3)**: plans UI, 14-day trial + auto-downgrade email, invoices, offboarding grace + tested purge (test_commercial).
- **Ops/compliance (P4)**: public status + heartbeat, support + privacy endpoints (test_ops); RUNBOOKS, INCIDENT-PROCESS (+tabletop), SUPPORT, PRIVACY, SECURITY-HARDENING, DR-VALIDATION (restore drill PASS), SOC2-EVIDENCE, ADMIN-GUIDE.
- **Public API (P5)**: scoped once-shown keys, governed query endpoints, docs/API.md (test_public_api).

## Exit criteria
| Criterion | Status | Evidence |
|---|---|---|
| 3 business scenarios end-to-end | ✅ | test_acceptance_scenarios (signup→insight; exec brief; ops alerted) |
| AI grounded + permission-aware | ✅ | ai_eval suite: injection inert, cross-tenant 404, honesty assertions |
| Load vs defined targets | ✅ | 4-widget/1k-row hydration < 2s; 20 NL asks < 10s (same file) |
| Backup restore tested | ✅ | DR-VALIDATION.md drill PASS |
| Incident/rollback exercised | ✅ | INCIDENT-PROCESS drill log; ROLLBACK-PROCEDURE |
| Deletion/privacy workflows | ✅ | purge test; privacy endpoints |
| Docs (admin/API/legal-privacy) | ✅ | ADMIN-GUIDE, API.md, PRIVACY.md |
| **No open critical security defects** | ❌ **BLOCKED** | SECURITY-HARDENING.md item 1: committed Neon password + JWT secret in git history — **rotation at provider required before tagging**. Three field catches this MVP (greedy explain intent, date-driver bug, public-API tenant filter) all fixed + regression-tested. |

## Tag decision
v0.3-mvp3 may be tagged once the credential rotation is confirmed. Everything else is green.
