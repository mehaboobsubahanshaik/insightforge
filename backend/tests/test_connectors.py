"""Connector framework: PostgreSQL end-to-end incremental sync, SaaS sandbox
demos, security validation, schema drift, plan floors."""

from conftest import ADMIN_DSN, PG_HOST, auth, get_workspace, register_and_login

PG_CONFIG = {"host": PG_HOST, "port": "5432", "database": "demo_shop",
             "table": "shop_orders", "cursor_column": "id"}
PG_CREDS = {"user": "postgres", "password": "devpassword"}


async def make_pg_connection(client, tok, name="shop"):
    ws = await get_workspace(client, tok)
    r = await client.post("/api/v1/connections", headers=auth(tok), json={
        "workspace_id": ws, "name": name, "connector_type": "postgresql",
        "config": PG_CONFIG, "credentials": PG_CREDS})
    assert r.status_code == 201, r.text
    return r.json()


async def test_postgres_full_incremental_cycle(client):
    import asyncpg

    tok = await register_and_login(client)
    conn = await make_pg_connection(client, tok)
    # 1) first sync loads everything
    r = await client.post(f"/api/v1/connections/{conn['id']}/sync", headers=auth(tok),
                          json={"mode": "incremental"})
    body = r.json()
    assert body["status"] == "succeeded" and body["rows_loaded"] == 15
    ds_id = body["dataset_id"]
    # 2) nothing new -> no_change short-circuit
    r = await client.post(f"/api/v1/connections/{conn['id']}/sync", headers=auth(tok),
                          json={"mode": "incremental"})
    assert r.json()["status"] == "no_change"
    # 3) source grows by one row -> only the delta is extracted
    src = await asyncpg.connect(ADMIN_DSN.replace("/insightforge", "/demo_shop"))
    await src.execute(
        "INSERT INTO shop_orders (order_date, customer, region, product, quantity, "
        "unit_price, total) VALUES ('2026-07-15','Test Co','South','Widget A',1,49.90,49.90)")
    await src.close()
    r = await client.post(f"/api/v1/connections/{conn['id']}/sync", headers=auth(tok),
                          json={"mode": "incremental"})
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["rows_extracted"] == 1 and body["rows_loaded"] == 16
    ds = (await client.get(f"/api/v1/datasets/{ds_id}", headers=auth(tok))).json()
    assert ds["row_count"] == 16
    runs = (await client.get(f"/api/v1/connections/{conn['id']}/runs",
                             headers=auth(tok))).json()
    assert [x["status"] for x in runs] == ["succeeded", "no_change", "succeeded"]
    # cleanup the extra source row for other tests
    src = await asyncpg.connect(ADMIN_DSN.replace("/insightforge", "/demo_shop"))
    await src.execute("DELETE FROM shop_orders WHERE customer = 'Test Co'")
    await src.close()


async def test_bad_credentials_rejected_at_create(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    r = await client.post("/api/v1/connections", headers=auth(tok), json={
        "workspace_id": ws, "name": "bad", "connector_type": "postgresql",
        "config": PG_CONFIG, "credentials": {"user": "postgres", "password": "wrong"}})
    assert r.status_code == 422 and "test failed" in r.json()["detail"].lower()


async def test_ssrf_identifier_and_config_validation(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    r = await client.post("/api/v1/connections", headers=auth(tok), json={
        "workspace_id": ws, "name": "meta", "connector_type": "postgresql",
        "config": {**PG_CONFIG, "host": "169.254.169.254"}, "credentials": PG_CREDS})
    assert r.status_code == 422
    r = await client.post("/api/v1/connections", headers=auth(tok), json={
        "workspace_id": ws, "name": "inj", "connector_type": "postgresql",
        "config": {**PG_CONFIG, "table": "shop_orders; DROP TABLE x"},
        "credentials": PG_CREDS})
    assert r.status_code == 422
    r = await client.post("/api/v1/connections", headers=auth(tok), json={
        "workspace_id": ws, "name": "cfg", "connector_type": "stripe",
        "config": {"sandbox_demo": True, "evil_key": "x"}, "credentials": {}})
    assert r.status_code == 422 and "evil_key" in r.json()["detail"]


async def test_all_saas_sandbox_demos_sync(client):
    tok = await register_and_login(client)
    await client.post("/api/v1/billing/plan", headers=auth(tok),
                      json={"plan_code": "growth"})  # room for 6 connections
    ws = await get_workspace(client, tok)
    for ctype in ("quickbooks", "hubspot", "salesforce", "shopify", "stripe", "ga4"):
        r = await client.post("/api/v1/connections", headers=auth(tok), json={
            "workspace_id": ws, "name": f"demo-{ctype}", "connector_type": ctype,
            "config": {"sandbox_demo": True}, "credentials": {}})
        assert r.status_code == 201, (ctype, r.text)
        cid = r.json()["id"]
        r = await client.post(f"/api/v1/connections/{cid}/sync", headers=auth(tok),
                              json={"mode": "incremental"})
        body = r.json()
        assert body["status"] == "succeeded" and body["rows_loaded"] >= 10, (ctype, body)
        r = await client.post(f"/api/v1/connections/{cid}/sync", headers=auth(tok),
                              json={"mode": "incremental"})
        assert r.json()["status"] == "no_change", ctype
    assert len((await client.get("/api/v1/datasets", headers=auth(tok))).json()) == 6


async def test_schema_drift_detected(client):
    import asyncpg

    tok = await register_and_login(client)
    conn = await make_pg_connection(client, tok)
    r = await client.post(f"/api/v1/connections/{conn['id']}/sync", headers=auth(tok),
                          json={"mode": "incremental"})
    ds_id = r.json()["dataset_id"]
    # simulate the source having had a different shape: mutate the stored schema
    admin = await asyncpg.connect(ADMIN_DSN)
    await admin.execute(
        "UPDATE datasets SET schema_def = '[{\"name\": \"other_col\", "
        "\"inferred_type\": \"text\"}]'::jsonb WHERE id = $1", __import__("uuid").UUID(ds_id))
    await admin.execute("UPDATE connections SET sync_cursor = '0' WHERE id = $1",
                        __import__("uuid").UUID(conn["id"]))
    await admin.close()
    r = await client.post(f"/api/v1/connections/{conn['id']}/sync", headers=auth(tok),
                          json={"mode": "incremental"})
    body = r.json()
    assert body["status"] == "failed" and "Schema drift" in body["error"]
    conns = (await client.get("/api/v1/connections", headers=auth(tok))).json()
    assert conns[0]["consecutive_failures"] == 1 and conns[0]["health"] == "degraded"
    # full refresh re-baselines
    r = await client.post(f"/api/v1/connections/{conn['id']}/sync", headers=auth(tok),
                          json={"mode": "full_refresh"})
    assert r.json()["status"] == "succeeded"


async def test_schedule_plan_floor(client):
    tok = await register_and_login(client)
    conn = await make_pg_connection(client, tok)
    r = await client.put(f"/api/v1/connections/{conn['id']}/schedule", headers=auth(tok),
                         json={"interval_minutes": 15})
    assert r.status_code == 403 and "free plan" in r.json()["detail"]
    r = await client.put(f"/api/v1/connections/{conn['id']}/schedule", headers=auth(tok),
                         json={"interval_minutes": 1440})
    assert r.status_code == 200
    await client.post("/api/v1/billing/plan", headers=auth(tok),
                      json={"plan_code": "growth"})
    r = await client.put(f"/api/v1/connections/{conn['id']}/schedule", headers=auth(tok),
                         json={"interval_minutes": 15})
    assert r.status_code == 200


async def test_connection_quota(client):
    tok = await register_and_login(client)  # free: 1 connection
    await make_pg_connection(client, tok, name="one")
    ws = await get_workspace(client, tok)
    r = await client.post("/api/v1/connections", headers=auth(tok), json={
        "workspace_id": ws, "name": "two", "connector_type": "stripe",
        "config": {"sandbox_demo": True}, "credentials": {}})
    assert r.status_code == 403 and "Plan limit" in r.json()["detail"]
