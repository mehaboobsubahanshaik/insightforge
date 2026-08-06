# RUN-EVERYTHING — zero-assumptions walkthrough (Windows / macOS / Linux)

This is the "I just cloned it, make it work" runbook. Pick ONE path.

## Path 1 — Docker Desktop (every OS, easiest)

1. Install Docker Desktop and start it (whale icon steady).
2. In a terminal (PowerShell is fine):
   ```
   cd insightforge
   docker compose up --build
   ```
   First run downloads images and builds — a few minutes. You're ready when
   the log shows `insightforge-api` printing `Application startup complete`.
3. Open **http://localhost:8000** → "New org" tab → register. The tour starts.
4. API docs: http://localhost:8001/docs · Ops console:
   http://localhost:8000/ops.html (secret `platform-dev-secret`).
5. Demo source for the connector walkthrough (bundled Postgres container):
   ```
   docker exec -i insightforge psql -U postgres < database/seeds/demo_shop.sql
   ```
   In the wizard use host **postgres**, db `demo_shop`, table `shop_orders`,
   cursor `id`, sslmode `disable`, user `postgres` / `devpassword`.
6. Dev emails: `docker exec insightforge-api ls /srv/outbox` (invite/reset
   tokens are inside the .eml files).
7. Reset everything: `docker compose down -v` (wipes data volumes).

### Windows notes
* If ports 8000/8001/5432 are taken, edit the left side of `ports:` in
  docker-compose.yml (e.g. `"18000:80"`).
* WSL2 backend recommended (Docker Desktop default). No other setup needed.
* Line endings: the repo is LF; Git for Windows with default settings is fine.

## Path 2 — no Docker (local Python + PostgreSQL)

1. Install Python 3.12+ and PostgreSQL 16 (remember the postgres password;
   guides assume `devpassword`).
2. ```
   cd insightforge
   pip install -e ./ml -e "./backend[dev]"
   ```
3. Create the database (PowerShell):
   ```
   & "C:\Program Files\PostgreSQL\16\bin\psql" -U postgres -c "CREATE DATABASE insightforge;"
   ```
4. ```
   set DATABASE_URL=postgresql+asyncpg://postgres:devpassword@127.0.0.1:5432/insightforge   # PowerShell: $env:DATABASE_URL="..."
   cd backend
   python -m alembic upgrade head
   python -m uvicorn --app-dir src insightforge_api.main:app --port 8000
   ```
5. Open http://localhost:8000 — the API serves the frontend folder directly
   in this mode. (Use host `127.0.0.1` in the connector wizard here.)

## Running the tests (either path)

```
pip install -e ./ml -e "./backend[dev]"
cd backend
python -m pytest -q          # 66 passed (MySQL tests auto-skip without a local server)
cd ../ml
python -m pytest -q          # 7 passed
```
Want the MySQL tests too? Easiest server:
```
docker run -d --name if-test-mariadb -e MYSQL_ROOT_PASSWORD=root ^
  -e MYSQL_DATABASE=demo_shop_mysql -e MYSQL_USER=demo -e MYSQL_PASSWORD=devpassword ^
  -p 3306:3306 mariadb:10.11
```
(then rerun pytest — the harness seeds the 12 demo rows itself).

## If something misbehaves
* **"Connection test failed … connection refused" in the wizard** — read the
  message: inside Docker use host `postgres` or `host.docker.internal`.
* **Web loads but API calls fail (Path 2)** — DATABASE_URL not set in the
  same terminal, or migrations not applied.
* **Port already allocated (Docker)** — another stack is on 8000/8001/5432;
  change the published ports.
* **Tests: "REQUIRE_MYSQL=1 but no usable MySQL"** — that's CI-only
  strictness; locally just unset REQUIRE_MYSQL and they skip politely.
