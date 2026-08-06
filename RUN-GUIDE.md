# Run Guide

## A. Docker (recommended — one command)

```bash
docker compose up --build
```

* Web app: http://localhost:8000 (nginx `insightforge-web`)
* API + docs: http://localhost:8001/docs (`insightforge-api`)
* Postgres: localhost:5432, db `insightforge`, postgres/devpassword
  (container name `insightforge`, data persists in volume `insightforge_pgdata`)
* Migrations run automatically every boot (idempotent).
* Dev emails (invites, resets, reports, alerts) land in the
  `insightforge_outbox` volume as `.eml` files:
  `docker exec insightforge-api ls /srv/outbox`

Stop with Ctrl-C; `docker compose down` removes containers (volumes persist);
`docker compose down -v` wipes data.

### Connecting your own database from the wizard
Inside Docker, `127.0.0.1` is the API container itself. Use:
* `postgres` — the bundled PostgreSQL (try db `insightforge`… or better,
  seed the demo source below);
* `host.docker.internal` — a database running on your machine;
* your cloud hostname (Supabase/Neon/RDS…) with SSL `require`.
The wizard shows this hint, and connection errors repeat it.

## B. Single-process dev (no Docker)

```bash
# prerequisites: Python 3.12, PostgreSQL 16 running locally
pip install -e ./ml -e "./backend[dev]"
createdb insightforge   # or via psql
export DATABASE_URL=postgresql+asyncpg://postgres:devpassword@127.0.0.1:5432/insightforge
cd backend
python -m alembic upgrade head
python -m uvicorn --app-dir src insightforge_api.main:app --reload --port 8000
```

Open http://localhost:8000 — in this mode the API also serves the
`frontend/` folder directly, so the whole product works from one process.

## C. Demo source databases (for the connector walkthrough)

```bash
# PostgreSQL demo (15 orders) — tests recreate this automatically too:
psql -U postgres -f database/seeds/demo_shop.sql
# MySQL/MariaDB demo (12 orders + demo/devpassword user):
mysql -u root < database/seeds/demo_shop_mysql.sql
# later, to demonstrate incremental sync picking up exactly the delta:
psql -U postgres -d demo_shop -f database/seeds/demo_shop_more_orders.sql
mysql -u root < database/seeds/demo_shop_mysql_more_orders.sql
```

## D. Platform operator console
http://localhost:8000/ops.html — secret `platform-dev-secret` (override with
env `PLATFORM_ADMIN_SECRET` on `insightforge-api`). Suspend/reactivate
tenants; suspended tenants get 403 at login.

## E. First-run walkthrough (5 minutes)
1. Register an organization → the tour starts automatically.
2. Sources → pick the **PostgreSQL** tile → host `postgres` (Docker) or
   `127.0.0.1`, db `demo_shop`, table `shop_orders`, cursor `id`, sslmode
   `disable` → Test → Create: 15 rows land, typed and scored.
3. Open the dataset → **✨ AI insights** → value `total`, over `order_date`.
4. Dashboards → From template → Sales overview → map `total` / `region` /
   `order_date` → click a bar → **Filter dashboard** or **View underlying rows**.
5. Publish → Share → open the link in a private window.
6. Settings → Manage alerts → sum(total) < 100000 → watch Activity.
