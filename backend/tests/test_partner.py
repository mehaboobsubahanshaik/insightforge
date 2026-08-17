"""MVP4 E4: OEM hierarchy, templates, embedded entitlements, usage metering,
partner onboarding without platform engineering."""

import asyncpg
from conftest import ADMIN_DSN, auth, get_workspace, outbox_bodies, register_and_login, upload_csv


async def test_partner_onboards_child_from_template(client):
    tok = await register_and_login(client)  # the partner (acme)
    r = await client.post("/api/v1/partner/templates", headers=auth(tok), json={
        "name": "MSP starter", "plan_code": "starter",
        "theme": {"brand_name": "PartnerBI", "white_label": True},
        "workspaces": ["Ops", "Finance"]})
    tpl = r.json()
    r = await client.post("/api/v1/partner/tenants", headers=auth(tok), json={
        "name": "Client One", "slug": "client-one",
        "owner_email": "boss@clientone.dev", "template_id": tpl["id"]})
    assert r.status_code == 201, r.text
    child = r.json()
    assert child["plan"] == "starter" and child["invited"] == "boss@clientone.dev"
    assert any("invited to Client One" in b for b in outbox_bodies())
    kids = (await client.get("/api/v1/partner/tenants",
                             headers=auth(tok))).json()["children"]
    assert kids[0]["slug"] == "client-one"
    assert kids[0]["embed_views_today"] == 0
    # duplicate slug refused; foreign template refused
    assert (await client.post("/api/v1/partner/tenants", headers=auth(tok),
                              json={"name": "X", "slug": "client-one",
                                    "owner_email": "a@b.dev"})).status_code == 409
    tok2 = await register_and_login(client, slug="rival", email="o@rival.dev")
    r = await client.post("/api/v1/partner/tenants", headers=auth(tok2), json={
        "name": "Steal", "slug": "steal-one", "owner_email": "a@b.dev",
        "template_id": tpl["id"]})
    assert r.status_code == 404  # template invisible across tenants


async def test_embed_views_metered_and_limited(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="usage",
                          content="customer,amount\nc1,10\nc2,20\n")
    d = (await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "V", "widgets": [
            {"type": "kpi", "dataset_id": ds["id"],
             "formula": "sum(amount)"}]})).json()
    await client.post(f"/api/v1/dashboards/{d['id']}/publish", headers=auth(tok))
    t = (await client.post("/api/v1/embed/tokens", headers=auth(tok), json={
        "dashboard_id": d["id"], "customer_label": "C1",
        "filters": [{"column": "customer", "op": "eq",
                     "value": "c1"}]})).json()["token"]
    conn = await asyncpg.connect(ADMIN_DSN)
    await conn.execute("UPDATE plans SET limits = limits || "
                       "'{\"embed_views_per_day\": 3}' WHERE code = 'free'")
    await conn.close()
    try:
        for _ in range(3):
            assert (await client.get(f"/api/v1/embed/{t}/data")).status_code == 200
        r = await client.get(f"/api/v1/embed/{t}/data")
        assert r.status_code == 429  # embedded entitlement enforced
        conn = await asyncpg.connect(ADMIN_DSN)
        metered = await conn.fetchval(
            "SELECT count(*) FROM billing_events WHERE kind='embed.view'")
        await conn.close()
        assert metered == 3  # exit criterion: usage accurately metered
    finally:
        conn = await asyncpg.connect(ADMIN_DSN)
        await conn.execute("UPDATE plans SET limits = limits || "
                           "'{\"embed_views_per_day\": 500}' WHERE code='free'")
        await conn.close()


async def test_capstone_parent_cannot_reach_child_data(client):
    """E5 exit evidence: the OEM wall. A partner administers a child's
    lifecycle but cannot mint embed tokens for the child's dashboards,
    list its datasets, or query its data — 404s everywhere."""
    tok = await register_and_login(client)
    r = await client.post("/api/v1/partner/tenants", headers=auth(tok), json={
        "name": "Walled Client", "slug": "walled",
        "owner_email": "o@walled.dev"})
    child_id = r.json()["id"]
    # partner's session sees no child datasets/dashboards
    assert (await client.get("/api/v1/datasets",
                             headers=auth(tok))).json() == []
    # partner cannot mint a token against a fabricated child dashboard id
    r = await client.post("/api/v1/embed/tokens", headers=auth(tok), json={
        "dashboard_id": child_id, "customer_label": "x",
        "filters": [{"column": "c", "op": "eq", "value": "1"}]})
    assert r.status_code == 404
