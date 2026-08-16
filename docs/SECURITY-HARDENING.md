# Security Hardening Pass — MVP3

## Verified in place (each with enforcing tests)
- Tenant isolation: Postgres RLS on every tenant table incl. new ai_feedback, webhooks, invoices; API 404s cross-tenant probes.
- AuthN/Z: bcrypt passwords, JWT + refresh rotation, MFA + one-time recovery codes, RBAC permission checks per route.
- Injection: formulas-only SQL path (bind params, allow-listed ops); NLQ never emits SQL; CSV export cell neutralization; hostile-input tests.
- Webhooks: HMAC-SHA256 signatures, secrets shown once, delivery failures isolated.
- Quotas/limits: plan limits, AI daily quotas, request body cap (20 MB), scheduler backoff.
- Audit: every sensitive action recorded with actor + correlation id.

## Known open items (blocking "no critical defects" exit criterion)
1. **CRITICAL — committed credentials**: a real Neon password and JWT secret exist in `.env.example` in git history. Rotation at the provider is the only fix; not yet confirmed done. Owner: repo owner. This MUST be resolved before v0.3-mvp3.
2. Rate limiting is per-quota, not per-IP; acceptable at current scale, revisit at public API GA.

## Review cadence
Hardening checklist re-walked at every MVP close; pip-audit runs in CI on every push.
