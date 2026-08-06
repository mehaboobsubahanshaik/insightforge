"""MySQL live connector, platform catalog, cleaning recipes, drill-through
filters, platform operator console."""

import conftest  # noqa: F401 - referenced lazily inside the skipif expression
import pytest
from conftest import ADMIN_DSN, PASSWORD, auth, get_workspace, register_and_login, upload_csv

needs_mysql = pytest.mark.skipif(
    "not conftest.MYSQL_AVAILABLE",
    reason="no MySQL/MariaDB at 127.0.0.1:3306 (see conftest note for a "
           "one-line docker command)")

MYSQL_CONN = {"connector_type": "mariadb", "name": "mysql shop",
              "config": {"host": "127.0.0.1", "port": "3306",
                         "database": "demo_shop_mysql", "table": "shop_orders",
                         "cursor_column": "id"},
              "credentials": {"user": "demo", "password": "devpassword"}}


async def test_catalog_gallery_shape(client):
    tok = await register_and_login(client)
    types = (await client.get("/api/v1/connections/types", headers=auth(tok))).json()
    assert len(types) == 19
    by_type = {t["type"]: t for t in types}
    for alias in ("supabase", "neon", "amazon-rds-postgresql", "cockroachdb"):
        assert by_type[alias]["engine"] == "postgresql"
        assert "sslmode" in by_type[alias]["config_keys"]
    for alias in ("mysql", "mariadb", "cloud-sql-mysql"):
        assert by_type[alias]["engine"] == "mysql"
    assert all({"label", "category", "color", "glyph", "blurb"} <= set(t)
               for t in types)
    assert by_type["stripe"]["supports_sandbox_demo"] is True
    assert by_type["postgresql"]["supports_sandbox_demo"] is False


@needs_mysql
async def test_mysql_live_incremental_cycle(client):
    import aiomysql

    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    body = dict(MYSQL_CONN, workspace_id=ws)
    r = await client.post("/api/v1/connections", headers=auth(tok), json=body)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["label"] == "MariaDB" and r.json()["color"]
    r = await client.post(f"/api/v1/connections/{cid}/sync", headers=auth(tok),
                          json={"mode": "incremental"})
    d = r.json()
    assert d["status"] == "succeeded" and d["rows_loaded"] == 12, d
    r = await client.post(f"/api/v1/connections/{cid}/sync", headers=auth(tok),
                          json={"mode": "incremental"})
    assert r.json()["status"] == "no_change"
    conn = await aiomysql.connect(host="127.0.0.1", port=3306, db="demo_shop_mysql",
                                  user="demo", password="devpassword")
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO shop_orders (order_date, customer, region, product, quantity,"
            " unit_price, total) VALUES ('2026-07-20','Delta Buyer','East','Widget A',"
            "1,49.90,49.90)")
    await conn.commit()
    conn.close()
    r = await client.post(f"/api/v1/connections/{cid}/sync", headers=auth(tok),
                          json={"mode": "incremental"})
    d = r.json()
    assert d["status"] == "succeeded" and d["rows_extracted"] == 1 and d["rows_loaded"] == 13
    conn = await aiomysql.connect(host="127.0.0.1", port=3306, db="demo_shop_mysql",
                                  user="demo", password="devpassword")
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM shop_orders WHERE customer='Delta Buyer'")
    await conn.commit()
    conn.close()


@needs_mysql
async def test_mysql_guards(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    bad = dict(MYSQL_CONN, workspace_id=ws, name="inj")
    bad["config"] = dict(bad["config"], table="shop_orders; DROP TABLE x")
    r = await client.post("/api/v1/connections", headers=auth(tok), json=bad)
    assert r.status_code == 422
    bad = dict(MYSQL_CONN, workspace_id=ws, name="ssrf")
    bad["config"] = dict(bad["config"], host="169.254.169.254")
    r = await client.post("/api/v1/connections", headers=auth(tok), json=bad)
    assert r.status_code == 422
    bad = dict(MYSQL_CONN, workspace_id=ws, name="badcreds")
    bad["credentials"] = {"user": "demo", "password": "wrong"}
    r = await client.post("/api/v1/connections", headers=auth(tok), json=bad)
    assert r.status_code == 422


async def test_pg_alias_platform_works(client):
    """A 'supabase' tile is a real PostgreSQL connection under the hood."""
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    r = await client.post("/api/v1/connections", headers=auth(tok), json={
        "workspace_id": ws, "name": "via supabase tile", "connector_type": "supabase",
        "config": {"host": "127.0.0.1", "port": "5432", "database": "demo_shop",
                   "table": "shop_orders", "cursor_column": "id", "sslmode": "disable"},
        "credentials": {"user": "postgres", "password": "devpassword"}})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    r = await client.post(f"/api/v1/connections/{cid}/sync", headers=auth(tok),
                          json={"mode": "incremental"})
    assert r.json()["status"] == "succeeded" and r.json()["rows_loaded"] == 15


DIRTY = (
    "order_date, Customer Name ,region,amount\n"
    "2026-06-01,  asha retail  ,south,Rs.499.00\n"
    "2026-06-02,bimal traders,,Rs.600.00\n"
    "2026-06-03,chetan co,south,Rs.399.20\n"
)


async def test_cleaning_recipe_rescues_rows(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="messy", content=DIRTY)
    types = {c["name"]: c["inferred_type"] for c in ds["schema"]}
    assert types["amount"] == "text"
    r = await client.get(f"/api/v1/datasets/{ds['id']}/recipe", headers=auth(tok))
    assert "strip_non_numeric" in r.json()["ops"]
    r = await client.post(f"/api/v1/datasets/{ds['id']}/recipe/apply", headers=auth(tok),
                          json={"steps": [{"op": "explode", "column": "amount"}]})
    assert r.status_code == 422
    r = await client.post(f"/api/v1/datasets/{ds['id']}/recipe/apply", headers=auth(tok),
                          json={"steps": [
                              {"op": "strip_non_numeric", "column": "amount"},
                              {"op": "trim", "column": "customer_name"},
                              {"op": "uppercase", "column": "region"},
                              {"op": "fill_missing", "column": "region",
                               "value": "UNKNOWN"},
                          ]})
    assert r.status_code == 200, r.text
    cleaned = r.json()
    types = {c["name"]: c["inferred_type"] for c in cleaned["schema"]}
    assert types["amount"] == "number"
    prev = (await client.get(f"/api/v1/datasets/{ds['id']}/preview",
                             headers=auth(tok))).json()
    regions = {row["region"] for row in prev["rows"]}
    assert regions == {"SOUTH", "UNKNOWN"}
    customers = {row["customer_name"] for row in prev["rows"]}
    assert "asha retail" in customers
    hist = (await client.get(f"/api/v1/datasets/{ds['id']}/dq-history",
                             headers=auth(tok))).json()
    assert len(hist) == 2


async def test_drill_through_preview_filters(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    filt = '[{"column":"region","op":"eq","value":"South"}]'
    r = await client.get(f"/api/v1/datasets/{ds['id']}/preview?filters={filt}",
                         headers=auth(tok))
    rows = r.json()["rows"]
    assert len(rows) == 3 and all(row["region"] == "South" for row in rows)
    r = await client.get(f"/api/v1/datasets/{ds['id']}/preview?filters=not-json",
                         headers=auth(tok))
    assert r.status_code == 422


async def test_platform_operator_console(client):
    await register_and_login(client)
    r = await client.get("/api/v1/platform/tenants")
    assert r.status_code == 401
    r = await client.get("/api/v1/platform/tenants",
                         headers={"X-Platform-Secret": "wrong"})
    assert r.status_code == 401
    hdr = {"X-Platform-Secret": "platform-dev-secret"}
    tenants = (await client.get("/api/v1/platform/tenants", headers=hdr)).json()
    mine = next(t for t in tenants if t["slug"] == "acme")
    assert mine["status"] == "active" and mine["members"] == 1
    r = await client.post(f"/api/v1/platform/tenants/{mine['id']}/status",
                          headers=hdr, json={"status": "suspended"})
    assert r.json()["status"] == "suspended"
    r = await client.post("/api/v1/auth/login",
                          json={"email": "owner@acme.dev", "password": PASSWORD})
    assert r.status_code == 403
    await client.post(f"/api/v1/platform/tenants/{mine['id']}/status",
                      headers=hdr, json={"status": "active"})
    r = await client.post("/api/v1/auth/login",
                          json={"email": "owner@acme.dev", "password": PASSWORD})
    assert r.status_code == 200
    import json as _json
    assert "devpassword" not in _json.dumps(tenants)
    assert ADMIN_DSN


async def test_connection_refused_gives_docker_guidance(client):
    """Errno 111 must return an actionable message, not a bare errno."""
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    r = await client.post("/api/v1/connections", headers=auth(tok), json={
        "workspace_id": ws, "name": "dead", "connector_type": "postgresql",
        "config": {"host": "127.0.0.1", "port": "59999", "database": "x",
                   "table": "y", "sslmode": "disable"},
        "credentials": {"user": "u", "password": "p"}})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "Connection test failed" in detail
    assert "host.docker.internal" in detail and "postgres" in detail
