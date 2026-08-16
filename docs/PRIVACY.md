# Privacy & Data Deletion Workflows

**Data residency**: tenant data lives in the platform Postgres, isolated by row-level security; uploads are parsed then discarded (rows stored, file not retained).

**Individual requests** (`POST /api/v1/privacy-request`, audited):
- *export*: user-scoped data compiled and delivered within 30 days.
- *delete*: account + personal identifiers removed/anonymized within 30 days, unless retention is legally required; audit rows are retained but reference IDs only.

**Organization deletion**: self-serve offboarding → 30-day grace (reversible) → automated purge of all tenant rows (verified by test), tenant marked `purged`.

**Breach notification**: affected tenants informed without undue delay after confirmation (Sev-1 incident path), including scope, mitigation, and recommended actions.

**Subprocessors**: hosting + email provider (when SMTP configured). No analytics trackers in the product.
