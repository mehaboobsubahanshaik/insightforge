# Operational Runbooks

## RB-1 Service down / degraded
1. `GET /api/v1/platform/status` — database + scheduler heartbeat.
2. `docker compose ps` then `docker compose logs api --tail 100`.
3. DB down → restart postgres service; verify status returns `operational`.
4. Heartbeat stale (>60s) → `docker compose restart api` (scheduler runs in-process).
5. Not recovered in 15 min → declare incident (INCIDENT-PROCESS.md).

## RB-2 Failed connector syncs
1. Sources page → connection shows failure count + last error (backoff is automatic, owner emailed after 3).
2. Fix upstream credentials/network → "Sync now"; success resets the streak.

## RB-3 Report/alert not delivered
1. `SELECT last_status FROM report_schedules` — `retrying` = auto-retry in 10 min.
2. Outbox mode: check MAIL_OUTBOX_DIR .eml files; SMTP mode: check SMTP_HOST creds.
3. Webhook deliveries: Settings → Webhooks shows per-hook `last_status`.

## RB-4 Restore from backup
Follow BACKUP-RESTORE.md (tested procedure + drill log). RPO: last backup; RTO target: 1h.

## RB-5 Roll back a bad deploy
Follow ROLLBACK-PROCEDURE.md — images are tagged per release; DB migrations are append-only so N-1 code runs against N schema.

## RB-6 Tenant purge verification
After offboarding grace: `SELECT status FROM tenants WHERE slug='X'` = `purged`; spot-check `SELECT count(*) FROM datasets WHERE tenant_id='...'` = 0.
