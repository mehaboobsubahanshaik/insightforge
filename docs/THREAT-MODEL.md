# Threat Model (STRIDE-lite, MVP scope)

**Assets**: tenant business data, credentials for customer databases/SaaS,
session tokens, platform secret.

| Threat | Control | Where |
|---|---|---|
| Cross-tenant read (IDOR) | PostgreSQL **RLS on every tenant table**, session GUC `app.tenant_id`; API works as non-superuser `app_user` in prod | `database/migrations/0001…0002`, `backend/src/insightforge_api/db.py`; proven in `tests/test_billing_security.py` by connecting AS `app_user` |
| SQL injection via connector config | identifiers regex-validated **and** quoted; values parameterised; per-type `ALLOWED_CONFIG_KEYS` | `services/connectors/{postgres,mysql}.py`, `__init__.py` |
| SSRF to cloud metadata | `BLOCKED_HOSTS` (169.254.169.254, metadata.google.internal) | both engines |
| Credential theft at rest | per-tenant envelope encryption (Fernet) via vault service; creds never in API responses | `services/vault.py`; asserted in tests |
| Session theft | short-lived JWT access + rotating refresh (hash-stored, RLS-scoped) | `routers/auth.py`, 0002 identity RLS |
| Brute force | login throttling + lockout counters; MFA (TOTP) | `services/security.py` |
| Suspended tenant access | login 403 + middleware check | `routers/auth.py`, `test_new_features.py` |
| Platform console abuse | secret header, counts-only responses, audit events | `routers/platform.py` |
| Request flooding / oversized bodies | request-size guard middleware, upload caps | `main.py` |
| Share-link scraping | random 128-bit tokens, expiry enforced server-side | `routers/dashboards.py` |

Out of MVP scope (documented, not ignored): per-tenant KMS keys, SSO/SAML,
IP allowlists, row-level *user* permissions inside a tenant, DDoS (assumed at
the edge/CDN), backup encryption.
