"""Test harness. Runs against the local `insightforge` database via the
superuser DSN (migrations already applied); truncates all mutable tables
between tests. RLS depth is separately proven in test_billing_security by
connecting as the restricted app_user role."""

import asyncio
import os
import pathlib
import re

import asyncpg
import httpx
import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:devpassword@127.0.0.1:5432/insightforge")
os.environ["DISABLE_SCHEDULER"] = "1"
import tempfile

OUTBOX_DIR = pathlib.Path(tempfile.gettempdir()) / "if_test_outbox"
os.environ["MAIL_OUTBOX_DIR"] = str(OUTBOX_DIR)
os.environ.pop("SMTP_HOST", None)

ADMIN_DSN = "postgresql://postgres:devpassword@127.0.0.1:5432/insightforge"
PASSWORD = "correct-horse-battery"
TABLES = [
    "audit_events", "meter_readings", "billing_events", "email_outbox", "alert_events",
    "alert_rules", "report_schedules", "share_links", "comments", "dashboard_views",
    "dashboard_versions", "dashboards", "measures", "sync_runs", "sync_schedules",
    "connections", "dq_history", "dq_results", "dataset_rows", "datasets", "workspaces",
    "invitations", "memberships", "tenants", "refresh_tokens", "users",
]

CLEAN_CSV = (
    "order_date,region,product,quantity,total\n"
    "2026-06-01,South,Widget A,10,499.00\n"
    "2026-06-02,North,Widget B,5,600.00\n"
    "2026-06-03,South,Widget A,8,399.20\n"
    "2026-06-04,South,Widget C,3,896.70\n"
    "2026-06-05,East,Widget B,2,247.42\n"
)  # sum(total)=2642.32; South=1794.90


def _ensure_service(port: int, start_cmd: list[str]):
    """Best-effort: start a local backing service if it isn't listening
    (dev sandboxes stop services between runs). No-op when unavailable."""
    import socket
    import subprocess

    with socket.socket() as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return
    try:
        subprocess.run(start_cmd, capture_output=True, timeout=30, check=False)  # noqa: S603 - fixed dev-service commands
    except Exception:  # noqa: BLE001, S110 - best effort only
        pass


def _port_open(port: int) -> bool:
    import socket

    with socket.socket() as s:
        s.settimeout(0.7)
        return s.connect_ex(("127.0.0.1", port)) == 0


MYSQL_AVAILABLE = False

PG_ROWS = [
    ("2026-06-01", "Asha Retail", "South", "Widget A", 10, 49.90, 499.00),
    ("2026-06-03", "Bimal Traders", "North", "Widget B", 5, 120.00, 600.00),
    ("2026-06-05", "Chetan & Co", "South", "Widget A", 8, 49.90, 399.20),
    ("2026-06-08", "Devi Stores", None, "Widget C", 3, 210.00, 630.00),
    ("2026-06-10", "Asha Retail", "South", "Widget B", 2, 120.00, 240.00),
    ("2026-06-12", "Eshan Mart", "West", "Widget A", 12, 49.90, 598.80),
    ("2026-06-15", "Farhan Goods", "East", "Widget C", 6, 210.00, 1260.00),
    ("2026-06-18", "Bimal Traders", "North", "Widget A", 4, 49.90, 199.60),
    ("2026-06-20", "Gita Supplies", None, "Widget B", 7, 120.00, 840.00),
    ("2026-06-22", "Chetan & Co", "South", "Widget C", 2, 210.00, 420.00),
    ("2026-06-25", "Asha Retail", "South", "Widget A", 15, 49.90, 748.50),
    ("2026-06-27", "Eshan Mart", "West", "Widget B", 3, 120.00, 360.00),
    ("2026-06-29", "Devi Stores", "North", "Widget A", 9, 49.90, 449.10),
    ("2026-07-02", "Farhan Goods", "East", "Widget B", 4, 120.00, 480.00),
    ("2026-07-05", "Gita Supplies", "West", "Widget C", 5, 210.00, 1050.00),
]

DDL = ("(id {serial} PRIMARY KEY, order_date date NOT NULL, "
       "customer varchar(120) NOT NULL, region varchar(40), "
       "product varchar(80) NOT NULL, quantity int NOT NULL, "
       "unit_price decimal(10,2) NOT NULL, total decimal(12,2) NOT NULL)")


async def _seed_pg_demo_shop():
    """demo_shop with exactly 15 rows — recreated every session so connector
    tests are deterministic on any machine (local, CI, fresh clone)."""
    sysconn = await asyncpg.connect(ADMIN_DSN.rsplit("/", 1)[0] + "/postgres")
    if not await sysconn.fetchval("SELECT 1 FROM pg_database WHERE datname='demo_shop'"):
        await sysconn.execute("CREATE DATABASE demo_shop")
    await sysconn.close()
    conn = await asyncpg.connect(ADMIN_DSN.rsplit("/", 1)[0] + "/demo_shop")
    await conn.execute("DROP TABLE IF EXISTS shop_orders")
    await conn.execute("CREATE TABLE shop_orders " + DDL.format(serial="serial"))
    from datetime import date

    rows = [(date.fromisoformat(r[0]), *r[1:]) for r in PG_ROWS]
    await conn.executemany(
        "INSERT INTO shop_orders (order_date, customer, region, product, quantity,"
        " unit_price, total) VALUES ($1, $2, $3, $4, $5, $6, $7)", rows)
    await conn.close()


async def _seed_mysql_demo_shop():
    """demo_shop_mysql with exactly 12 rows via the demo user. The database +
    user must exist (local: seed/demo_shop_mysql.sql as root; CI: created by
    the mariadb service container env)."""
    import aiomysql

    conn = await aiomysql.connect(host="127.0.0.1", port=3306, db="demo_shop_mysql",
                                  user="demo", password="devpassword")
    async with conn.cursor() as cur:
        await cur.execute("DROP TABLE IF EXISTS shop_orders")
        await cur.execute("CREATE TABLE shop_orders "
                          + DDL.format(serial="int AUTO_INCREMENT"))
        await cur.executemany(
            "INSERT INTO shop_orders (order_date, customer, region, product,"
            " quantity, unit_price, total) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            PG_ROWS[:12])
    await conn.commit()
    conn.close()


@pytest.fixture(scope="session", autouse=True)
def _provision():
    _ensure_service(5432, ["pg_ctlcluster", "16", "main", "start"])
    _ensure_service(3306, ["service", "mariadb", "start"])

    async def setup():
        conn = await asyncpg.connect(ADMIN_DSN)
        await conn.execute(f"TRUNCATE {', '.join(TABLES)} CASCADE")
        await conn.close()
        await _seed_pg_demo_shop()
        global MYSQL_AVAILABLE
        if _port_open(3306):
            try:
                await _seed_mysql_demo_shop()
                MYSQL_AVAILABLE = True
            except Exception as e:  # noqa: BLE001
                print(f"WARNING: MySQL reachable but demo source not provisioned"
                      f" ({e}); run seed/demo_shop_mysql.sql as root first.")
        if os.environ.get("REQUIRE_MYSQL") == "1" and not MYSQL_AVAILABLE:
            raise RuntimeError("REQUIRE_MYSQL=1 but no usable MySQL/MariaDB "
                               "at 127.0.0.1:3306 — refusing to skip in CI")
        if not MYSQL_AVAILABLE:
            print("NOTE: no MySQL/MariaDB at 127.0.0.1:3306 — MySQL connector "
                  "tests will be SKIPPED. Quick start:  docker run -d --name "
                  "if-test-mariadb -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE="
                  "demo_shop_mysql -e MYSQL_USER=demo -e MYSQL_PASSWORD="
                  "devpassword -p 3306:3306 mariadb:10.11")
    asyncio.run(setup())
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)

@pytest.fixture(autouse=True)
async def _clean_db():
    conn = await asyncpg.connect(ADMIN_DSN)
    await conn.execute(f"TRUNCATE {', '.join(TABLES)} CASCADE")
    await conn.close()
    for f in OUTBOX_DIR.glob("*"):
        f.unlink()
    yield
    # The app engine is lru_cached; dispose it on THIS test's loop and clear
    # the cache so the next test (new loop) builds a fresh engine.
    from insightforge_api import db

    await db.engine().dispose()
    db.engine.cache_clear()
    db.session_factory.cache_clear()


@pytest.fixture
async def client():
    from insightforge_api.main import create_app

    app = create_app(with_scheduler=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def register_and_login(client, slug="acme", email="owner@acme.dev",
                             name="Acme Inc") -> dict:
    r = await client.post("/api/v1/auth/register", json={
        "tenant_name": name, "tenant_slug": slug, "email": email,
        "password": PASSWORD, "display_name": "Owner"})
    assert r.status_code == 201, r.text
    return r.json()


def auth(token_bundle) -> dict:
    return {"Authorization": f"Bearer {token_bundle['access_token']}"}


async def get_workspace(client, tok) -> str:
    r = await client.get("/api/v1/workspaces", headers=auth(tok))
    return r.json()[0]["id"]


async def upload_csv(client, tok, ws_id, name="orders", content=CLEAN_CSV) -> dict:
    r = await client.post(
        f"/api/v1/datasets/upload?workspace_id={ws_id}&name={name}",
        headers=auth(tok), files={"file": (f"{name}.csv", content.encode(), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()


def outbox_bodies() -> list[str]:
    return [p.read_text() for p in sorted(OUTBOX_DIR.glob("*.eml"))]


def token_from_outbox(pattern: str) -> str:
    for body in reversed(outbox_bodies()):
        m = re.search(pattern, body)
        if m:
            return m.group(1).strip()
    raise AssertionError(f"no outbox mail matched {pattern!r}")
