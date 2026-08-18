# MVP5 Verification — Advanced Analytics & Enterprise Governance

Date: 2026-08-17 · Branch: suhan · Suite: 114 tests · Migrations: 0011–0014

## Features: 28/28, all test-covered
- **G1 identity**: SAML SSO (pinned-cert ACS; XMLDSig chain = documented hardening), SCIM v2 lifecycle, ABAC member attributes, access reviews with real revocation. test_enterprise_identity.
- **G2 data security**: column-level security (403 names the classification), advanced row policies (role/attribute-matched mandatory filters), classification labels, retention purge job, CMK config (envelope rollout documented). test_data_security.
- **G3 governance catalog**: aggregated catalog, glossary (unique terms, stewards, column links), full lineage (upstream→object→downstream), certification only via approval workflow, impact analysis with severity. test_catalog.
- **G4 compliance ops**: audit export (JSONL/CSV/since), SIEM streaming (cursor'd exactly-once to signed webhooks), deployment posture (residency/private/dedicated — infra realization documented), per-plan SLAs + live heartbeat, time-boxed support access. test_compliance_ops.
- **G5 advanced analytics**: forecast model registry with baseline metrics, drift monitoring (>50% MAE growth), deterministic what-if, saved scenarios, multi-dimension root-cause workflow with concentration ranking, Azure ML external-model config (scoring wiring documented, never faked). test_advanced_analytics.
- **G6 capstone**: SCIM→ABAC→governance→approval→governed answer→audit export in one journey. test_mvp5_capstone.

## Honest scope register
External-dependency features (SAML XMLDSig, CMK envelope encryption, region
pinning/PrivateLink/dedicated stacks, Azure ML scoring calls) ship as:
real app-side config + validation + enforcement where the app can enforce,
with the infra step documented — consistent with MVP4's custom-domain
pattern. Nothing is simulated as if live.

## Carried risks
1. Neon credential rotation STILL unconfirmed (register since MVP2).
2. main branch lags: MVP4 + MVP5 both live only on suhan until merged.

## Tag decision
v0.5-mvp5 after merge to main (may land alongside v0.4-mvp4).
