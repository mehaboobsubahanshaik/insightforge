# Public API v1

Auth: create a key in-app (`POST /api/v1/api-keys`, owner/admin) → shown once
as `ifk_<prefix>_<secret>` (only a SHA-256 hash is stored). Send it on every
request as `X-API-Key`. Scopes: `data:read`. Revoke any time; usage audited
as `api.query` with `last_used_at` tracked.

## Endpoints
- `GET /api/v1/public/datasets` — datasets with columns + quality score.
- `POST /api/v1/public/datasets/{id}/query` — body `{"formula": "sum(total)",
  "group_by": "region"}`. Same governed formulas-only path as the UI: an API
  key can never reach raw SQL; every response carries the quality score.
- `GET /api/v1/platform/status` — public health (no key needed).

## Example
```bash
curl -H "X-API-Key: ifk_..." https://host/api/v1/public/datasets
curl -H "X-API-Key: ifk_..." -H "Content-Type: application/json" \
  -d '{"formula":"sum(total)","group_by":"region"}' \
  https://host/api/v1/public/datasets/<id>/query
```

Errors: 401 bad/revoked key · 403 missing scope · 404 not your tenant's
dataset · 422 formula rejected. Rate limiting: plan quotas apply; per-IP
limits tracked as an open item in SECURITY-HARDENING.md.
