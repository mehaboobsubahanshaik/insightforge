# Disaster Recovery Validation

**Procedure under test**: BACKUP-RESTORE.md (pg_dump nightly + restore steps).

**Validation run — 2026-08-16 (sandbox)**: full dump of dev database → restore into empty database → alembic `upgrade head` no-ops (schema matches) → smoke: login, dataset list, dashboard render, row counts equal. Result: PASS. Time to restore: < 10 min at dev size.

**Targets**: RPO = 24h (nightly) — recommend 6h at first paying customer. RTO = 1h.

**Gaps / follow-ups**: restore of the outbox volume is not covered (acceptable: emails are transient); production-scale timing unmeasured until a production-sized dataset exists.

Next validation due: at v0.3-mvp3 tag, then quarterly (see RUNBOOKS.md RB-4).
