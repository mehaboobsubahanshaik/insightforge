# MVP4 Verification — Embedded Analytics & White-Label

Date: 2026-08-17 · Branch: suhan · Suite: 103 tests · Migrations: 0008–0010

## Features: 18/18, all test-covered
- **E1 Embedding core**: signed HMAC embed tokens (once-set per-tenant secret), public viewer serving published snapshots only, customer-aware mandatory filters inside the signature, embed audit (embed.token/view/query with customer label). test_embed.
- **E2 SDKs**: JS SDK (embed + headless query), React SDK (component + hook), headless API `GET /embed/{token}/query`, docs/SDK.md + /sdk/example.html sample.
- **E3 White-label**: theme endpoint (hex/locale-validated, white_label flag), custom domains (unique, workflow in docs/WHITE-LABEL.md), /portal.html multi-dashboard portals, viewer i18n (en/es/fr/de/hi), embed a11y (lang, roles, aria, iframe titles) + WCAG checklist.
- **E4 OEM/partner**: parent_tenant_id hierarchy, tenant templates (plan+theme+workspaces), partner admin console endpoints, embed_views_per_day entitlements (429), per-view usage metering into billing_events → invoice lines. test_partner.

## Exit criteria
| Criterion | Status | Evidence |
|---|---|---|
| No cross-customer exposure in embeds | ✅ | forged-filter token → 401; c1/c2 slices disjoint (viewer + headless); capstone: parent cannot reach child data (404s) |
| SDK docs and samples complete | ✅ | docs/SDK.md (3 integration levels), sdk/example.html works end-to-end |
| Usage accurately metered | ✅ | 3 views → exactly 3 billing_events rows (test), partner console shows live counts |
| Theming + custom-domain workflows production-ready | ✅ | validated endpoints + documented DNS/TLS workflow; theme applied live to embeds |
| Partner onboarding without platform engineering | ✅ | template → child tenant → workspaces → owner invite email, one API call (test) |

## Notes
- Custom-domain TLS termination is an infra step (documented), not app code.
- Carried risk: Neon credential rotation (MVP3 register) still pending confirmation.
- v0.4-mvp4 tag after merge to main.
