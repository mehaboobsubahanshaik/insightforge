# Backup & Restore Procedure

## What must be protected (in priority order)

| Asset | Where it lives | Backup mechanism |
|---|---|---|
| Tenant business data, users, dashboards | PostgreSQL (Neon in prod) | §1 + §2 |
| `APP_ENCRYPTION_KEY` + `JWT_SECRET` | `.env` (never in git) | §3 — **without the encryption key, every stored connector credential is permanently unreadable, even with a perfect DB backup** |
| Application code, migrations, seeds | git (GitHub remote) | already backed up by being pushed |
| Containers/images | rebuilt from git by `docker compose up --build` | nothing to back up |
| Email outbox files | `outbox/` volume | disposable — not backed up |

## 1. Continuous backup (Neon, automatic)

Neon keeps a continuous history of the database. Restoring to any moment
inside the retention window (check: Neon console → project → Settings →
Storage / History retention; default 24h on free, longer on paid):

1. Neon console → **Branches** → **Restore** (or "Create branch" →
   "From timestamp").
2. Pick the branch (`main`/production) and the timestamp just **before** the
   incident.
3. Neon creates a new branch with the data as of that moment — the live
   branch is untouched, so this is safe to do while investigating.
4. To make it the active database: point `DATABASE_URL` in `.env` at the
   new branch's pooled host, restart the API, verify (§4), then retire the
   damaged branch.

This is the primary restore path for "bad data written by a bug" incidents
(see ROLLBACK-PROCEDURE.md §0).

## 2. Weekly offline backup (pg_dump, manual until scheduled)

Point-in-time history lives inside Neon; a `pg_dump` file is the backup that
survives account problems, region incidents, or provider migration.

```bash
# from the repo root; reads the same URL the app uses, direct (non -pooler) host
pg_dump "postgresql://USER:PASSWORD@YOUR-HOST.REGION.aws.neon.tech/DBNAME?sslmode=require" \
  --format=custom --file=backups/insightforge-$(date +%Y%m%d).dump
```

* Use the **direct** host (without `-pooler`) and `sslmode=require` —
  pg_dump speaks libpq, unlike the app's asyncpg URL.
* Store dumps **outside the repo** (never commit them: they contain tenant
  data) — an encrypted drive or private object storage. Keep 4 weekly dumps.
* Local dev equivalent:
  `docker compose exec insightforge pg_dump -U postgres -Fc insightforge > backups/dev.dump`

## 3. Secrets backup

`.env` is deliberately outside git, so it has **no** automatic backup. Copy
`APP_ENCRYPTION_KEY`, `JWT_SECRET`, and the current `DATABASE_URL` into the
team password manager **now** and whenever they rotate. Losing the
encryption key = every tenant must re-enter every connector credential
(data survives; connections' stored passwords do not).

## 4. Restore rehearsal (run once now, then each release cycle)

Restores are only real if rehearsed. This drill restores a dump into a
scratch database and proves the app runs on it — production untouched.

1. Take a fresh dump (§2).
2. Restore into the local Docker Postgres as a scratch DB:
```bash
   docker compose exec insightforge createdb -U postgres restore_drill
   docker compose exec -T insightforge pg_restore -U postgres \
     -d restore_drill --no-owner < backups/insightforge-YYYYMMDD.dump
```
3. Point a **local** API at it: in `.env` set
   `DATABASE_URL=postgresql+asyncpg://postgres:devpassword@127.0.0.1:5432/restore_drill`,
   start the API, log in with a real account from the dump.
4. Verification checklist — all four must pass:
   * login succeeds (users + auth tables restored)
   * a dataset opens with rows and its quality score (data + DQ restored)
   * a dashboard hydrates (analytics path restored)
   * Sources → a connection shows **without** re-entering credentials
     (proves the backed-up `APP_ENCRYPTION_KEY` matches the restored data)
5. Drop the scratch DB, restore local `.env`:
   `docker compose exec insightforge dropdb -U postgres restore_drill`
6. Record the drill date at the bottom of this file.

## Drill log

| Date | Dump file | Performed by | All 4 checks passed? |
|---|---|---|---|
| _run the first drill and record it here_ | | | |