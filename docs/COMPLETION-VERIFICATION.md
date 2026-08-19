# Completion Arc Verification (R1–R6)

Date: 2026-08-18 · Branch: suhan · Suite: 153 tests · Migrations: 0001–0016 · Migrations: 0001–0015

| Phase | Delivered | Evidence |
|---|---|---|
| R1 | PII detection (suggest-only), security headers, CI supply-chain (gitleaks/SBOM/Trivy), ADRs, threat model, gap register | test_r1_security |
| R2 | Generic REST + Google-Sheets connectors, JSON upload, connector SDK doc (vendor connectors pre-existed from MVP2) | test_r2_connectors |
| R3 | LLM provider abstraction: grounded-only prompting, PII redaction pre-egress, token/latency metering, deterministic fallback (ADR-003) | test_r3_llm |
| R4 | Watermarked xlsx export, histogram + scatter data endpoints | test_r4_exports_viz |
| R5 | Cross-dataset join/pivot/derive via trust pipeline, fiscal calendars, time grains, tenant-managed currency conversion | test_r5_semantics |
| R7 | union, favorites, embedded-builder API (edit-scoped tokens), relative/freshness/DQ alerts, Holt-Winters seasonality, rate limiting + idempotency | test_r7_completion |
| R8 | 14-role catalog, prompt-injection source scan (blocks egress, falls back grounded), unpivot/split/merge, docs pack (NFR targets, storage evaluation, diagrams, product brief) | test_r8_completion |
| R9 | funnel/waterfall/gauge/scatter/histogram end-to-end | test_r9_viz |
| R10 | bookmarks, snapshots, print stylesheet, presentation mode (cross-filter/drill-through/parameters pre-existed) | test_r10_interactions |
| R11 | semantic model, virtual joins, metric versioning+units+validation | test_r11_semantic |
| R12 | JIT, break-glass, gated impersonation, session revocation, XML (defusedxml) | test_r12_identity |
| R13 | legal hold, flags, cost report, credential rotation, drift report, outlier advisory | test_r13_ops |
| R14 | full docs suite (matrix, backlog, catalogs, FMEA, capacity, observability, release notes) | this doc |
| R6 | 9-role catalog with scoped permissions, alert ack/quiet-hours/escalation (once-only), data-issue reporting into approvals | test_r6_completion |

## Remaining honest gaps (docs/GAP-REGISTER.md governs)
- Bucket A partial: frontend renderers for funnel/waterfall/heatmap/gauge/
  pivot/cohort/geo (data endpoints exist); print stylesheet for PDF.
- Bucket B (config+docs, external creds needed): vendor OAuth live use,
  live LLM key, SMS, Azure infra, XMLDSig, CMK envelope, pentest/DAST.
- Bucket C (deliberate roadmap): Next.js rebuild, Timescale/Redis/Kafka,
  Temporal, OpenTelemetry, microservice extraction.
- Immortal: Neon credential rotation (gitleaks will flag it in history —
  that is the tool working).
