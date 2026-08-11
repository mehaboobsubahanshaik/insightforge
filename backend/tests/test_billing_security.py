"""Plans & quotas, metering, billing events, RLS depth proof via the
restricted app_user role, problem-details contract, ops endpoints."""

import asyncpg
import pytest
from conftest import (
    ADMIN_DSN,
    PASSWORD,
    PG_HOST,
    auth,
    get_workspace,
    register_and_login,
    upload_csv,
)

APP_DSN = f"postgresql://app_user:app_dev_password@{PG_HOST}:5432/insightforge"


async def test_dataset_quota_and_archive_frees_slot(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ids = []
    for i in range(3):  # free plan allows 3 datasets
        ids.append((await upload_csv(client, tok, ws, name=f"d{i}"))["id"])
    r = await client.post(f"/api/v1/datasets/upload?workspace_id={ws}&name=d3",
                          headers=auth(tok),
                          files={"file": ("d3.csv", b"a,b\n1,2\n", "text/csv")})
    assert r.status_code == 403
    assert "free plan" in r.json()["detail"]
    # archiving one frees the slot
    r = await client.patch(f"/api/v1/datasets/{ids[0]}", headers=auth(tok),
                           json={"archived": True})
    assert r.status_code == 200
    r = await client.post(f"/api/v1/datasets/upload?workspace_id={ws}&name=d3",
                          headers=auth(tok),
                          files={"file": ("d3.csv", b"a,b\n1,2\n", "text/csv")})
    assert r.status_code == 201


async def test_plan_switch_owner_only_and_billing_summary(client):
    tok = await register_and_login(client)
    # invite an admin — admins manage members but must NOT manage billing
    r = await client.post("/api/v1/members/invitations", headers=auth(tok),
                          json={"email": "admin@acme.dev", "role": "tenant_admin"})
    assert r.status_code == 201
    from conftest import token_from_outbox
    invite_token = token_from_outbox(r"token:\n(\S+)")
    r = await client.post("/api/v1/auth/invitations/accept",
                          json={"token": invite_token, "password": PASSWORD,
                                "display_name": "Admin"})
    assert r.status_code == 200
    admin_tok = r.json()

    r = await client.post("/api/v1/billing/plan", headers=auth(admin_tok),
                          json={"plan_code": "growth"})
    assert r.status_code == 403  # tenant:manage is owner-only

    r = await client.post("/api/v1/billing/plan", headers=auth(tok),
                          json={"plan_code": "growth"})
    assert r.status_code == 200 and r.json()["plan_code"] == "growth"
    r = await client.post("/api/v1/billing/plan", headers=auth(tok),
                          json={"plan_code": "platinum"})
    assert r.status_code == 422

    r = await client.get("/api/v1/billing/summary", headers=auth(tok))
    body = r.json()
    assert body["plan_code"] == "growth"
    assert body["usage"]["members"] == 2
    assert {p["code"] for p in body["plans"]} == {"free", "starter", "growth"}
    assert any(e["kind"] == "plan.changed" for e in body["billing_events"])


async def test_upload_meters_usage(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    await upload_csv(client, tok, ws)
    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        rows = await conn.fetch("SELECT meter, value FROM meter_readings")
    finally:
        await conn.close()
    assert any(m == "upload.rows" and v == 5 for m, v in rows)


async def test_rls_depth_app_user_sees_nothing_without_guc(client):
    """The real enforcement layer: connect as the restricted role the API
    uses in production posture. Without GUCs armed, zero rows are visible;
    DELETE is denied outright by grants."""
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    await upload_csv(client, tok, ws)
    conn = await asyncpg.connect(APP_DSN)
    try:
        for table in ("tenants", "users", "datasets", "dataset_rows", "dashboards"):
            count = await conn.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608
            assert count == 0, f"{table}: app_user saw {count} rows without tenant GUC"
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("DELETE FROM datasets")
        # and with the WRONG tenant armed, still nothing
        await conn.execute("SELECT set_config('app.tenant_id', gen_random_uuid()::text, false)")
        assert await conn.fetchval("SELECT count(*) FROM datasets") == 0
    finally:
        await conn.close()


async def test_rls_correct_tenant_guc_reveals_rows(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    await upload_csv(client, tok, ws)
    conn = await asyncpg.connect(APP_DSN)
    try:
        await conn.execute("SELECT set_config('app.tenant_id', $1, false)", tok["tenant_id"])
        assert await conn.fetchval("SELECT count(*) FROM datasets") == 1
        assert await conn.fetchval("SELECT count(*) FROM dataset_rows") == 5
    finally:
        await conn.close()


async def test_problem_details_contract(client):
    tok = await register_and_login(client)
    r = await client.get("/api/v1/datasets/not-a-uuid", headers=auth(tok))
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == 422 and "title" in body and "detail" in body
    assert r.headers.get("content-type", "").startswith("application/problem+json")
    assert r.headers.get("x-correlation-id")
    # a supplied correlation id is echoed back
    r = await client.get("/api/v1/auth/me", headers={**auth(tok),
                                                    "X-Correlation-Id": "trace-me-123"})
    assert r.headers["x-correlation-id"] == "trace-me-123"


async def test_ops_endpoints_and_diagnostics_secret_free(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    r = await client.get("/api/v1/ready")
    assert r.status_code == 200 and r.json()["database"] == "ok"
    r = await client.get("/openapi.json")
    assert r.status_code == 200 and r.json()["info"]["version"] == "1.0.0"

    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    # create a pg connection so credentials exist in the vault
    r = await client.post("/api/v1/connections", headers=auth(tok), json={
        "workspace_id": ws, "name": "Shop DB", "connector_type": "postgresql",
        "config": {"host": PG_HOST, "port": 5432, "database": "demo_shop",
                   "table": "shop_orders", "cursor_column": "id"},
        "credentials": {"user": "postgres", "password": "devpassword"}})
    assert r.status_code == 201, r.text
    r = await client.get("/api/v1/admin/diagnostics", headers=auth(tok))
    assert r.status_code == 200
    assert "devpassword" not in r.text  # never leak credentials in support output


async def test_tenants_current_and_suspension(client):
    tok = await register_and_login(client)
    r = await client.get("/api/v1/tenants/current", headers=auth(tok))
    body = r.json()
    assert body["slug"] == "acme" and body["plan_code"] == "free"
    assert body["limits"]["datasets"] == 3
    # suspend via admin backdoor (support action), then login is refused
    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        await conn.execute("UPDATE tenants SET status='suspended' WHERE slug='acme'")
    finally:
        await conn.close()
    r = await client.post("/api/v1/auth/login",
                          json={"email": "owner@acme.dev", "password": PASSWORD})
    assert r.status_code == 403
    assert "suspended" in r.json()["detail"]