# Rollback Procedure

When a deployment goes wrong, there are two independent things that can need
rolling back: **application code** (containers) and **database schema**
(alembic migrations). They have different blast radii — know which one you
are doing before you type anything.

## 0. Decide what kind of bad it is

| Symptom | Rollback needed |
|---|---|
| UI broken, API errors, feature misbehaves — data reads fine | Code only (§1) |
| Migration failed mid-apply; app won't boot on schema mismatch | Schema (§2), then code |
| Bad data written by a bug (wrong values, not wrong schema) | Neither — restore from backup (see BACKUP-RESTORE.md); rolling back code/schema does not un-write rows |

## 1. Code rollback (containers) — safe, do freely

Deployments are `docker compose up --build` from a git checkout, so the
previous version is one checkout away:

```bash
git log --oneline -5            # find the last good commit
git checkout <good-commit-sha>
docker compose up --build -d
```

Verify: `curl localhost:8001/api/v1/health` returns ok, then log in at
`localhost:8000`. Because migrations are **append-only and
backwards-compatible within a release** (Engineering Standards), old code
runs fine against a newer schema — this is why code rollback alone fixes
most incidents.

When fixed forward, return to tip: `git checkout main && docker compose up
--build -d`.

## 2. Schema rollback (alembic) — rare, deliberate

Only for a migration that failed to apply cleanly or must be reverted before
customers write data shaped by it.

```bash
# see where you are
docker compose exec api alembic current
# step back exactly one revision
docker compose exec api alembic downgrade -1
```

Rules:
* Downgrade **one step at a time**; check `alembic current` between steps.
* The up→down→up cycle for every migration is exercised in CI on every push
  (see `.github/workflows/ci.yml`), so the downgrade path is tested code —
  but downgrades that drop columns **destroy the data in those columns**.
  If the migration being reverted created tables/columns that already hold
  customer data, stop and take a backup first (BACKUP-RESTORE.md).
* Never downgrade below the revision the currently-deployed code expects;
  pair a schema rollback with the matching code rollback (§1).

## 3. Rollback drill (do once per release cycle)

1. On a dev stack, note `alembic current` and create a dataset via the UI.
2. `git checkout <previous-tag>` + `docker compose up --build -d` → app
   serves, dataset still visible (code rollback proven).
3. `alembic downgrade -1` then `upgrade head` → app healthy, tests pass
   (schema cycle proven — same thing CI does, rehearsed by hands).
4. Return to tip. Record the date in the ops log / PR description.

## 4. What we deliberately do NOT have yet

No blue-green or canary deploys, no automated rollback triggers — single
compose target, manual rollback, acceptable at internal-alpha scale
(MVP1 customer status). Revisit when there is more than one production
deploy target.