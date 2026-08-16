"""MVP3 P3 commercial: trial lifecycle, invoicing, offboarding + purge."""


import asyncpg
from conftest import ADMIN_DSN, auth, get_workspace, outbox_bodies, register_and_login, upload_csv


async def test_trial_start_convert_and_expiry(client):
    from insightforge_api.scheduler import run_lifecycle_once

    tok = await register_and_login(client)
    r = await client.post("/api/v1/billing/trial", headers=auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "growth"
    # once only
    assert (await client.post("/api/v1/billing/trial",
                              headers=auth(tok))).status_code == 409
    # expiry: rewind trial_ends_at, lifecycle downgrades + emails owner
    conn = await asyncpg.connect(ADMIN_DSN)
    await conn.execute("UPDATE tenants SET trial_ends_at = now() - "
                       "interval '1 hour'")
    await conn.close()
    assert await run_lifecycle_once() >= 1
    summary = (await client.get("/api/v1/billing/summary",
                                headers=auth(tok))).json()
    assert summary["plan_code"] == "free"
    assert any("trial ended" in b.lower() for b in outbox_bodies())
    # conversion path is just the existing plan change
    r = await client.post("/api/v1/billing/plan", headers=auth(tok),
                          json={"plan_code": "starter"})
    assert r.status_code == 200


async def test_invoice_generation_lists_plan_and_usage(client):
    tok = await register_and_login(client)
    await client.post("/api/v1/billing/plan", headers=auth(tok),
                      json={"plan_code": "starter"})
    r = await client.post("/api/v1/billing/invoices/generate",
                          headers=auth(tok))
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["amount_usd"] == 49.0
    assert inv["line_items"][0]["item"].startswith("Starter plan")
    listing = (await client.get("/api/v1/billing/invoices",
                                headers=auth(tok))).json()["invoices"]
    assert len(listing) == 1 and listing[0]["status"] == "issued"
    # tenant isolation
    tok2 = await register_and_login(client, slug="rival", email="o@rival.dev")
    assert (await client.get("/api/v1/billing/invoices",
                             headers=auth(tok2))).json()["invoices"] == []


async def test_offboarding_grace_cancel_and_purge(client):
    from insightforge_api.scheduler import run_lifecycle_once

    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    # wrong slug refused
    r = await client.post("/api/v1/tenants/offboard", headers=auth(tok),
                          json={"confirm_slug": "wrong"})
    assert r.status_code == 422
    r = await client.post("/api/v1/tenants/offboard", headers=auth(tok),
                          json={"confirm_slug": "acme"})
    assert r.status_code == 200 and r.json()["status"] == "offboarding"
    # cancel restores
    r = await client.post("/api/v1/tenants/offboard/cancel", headers=auth(tok))
    assert r.json()["status"] == "active"
    # offboard again, force the grace period past, purge runs
    await client.post("/api/v1/tenants/offboard", headers=auth(tok),
                      json={"confirm_slug": "acme"})
    conn = await asyncpg.connect(ADMIN_DSN)
    await conn.execute("UPDATE tenants SET deletion_due_at = now() - "
                       "interval '1 minute' WHERE slug = 'acme'")
    await conn.close()
    assert await run_lifecycle_once() >= 1
    conn = await asyncpg.connect(ADMIN_DSN)
    left = await conn.fetchval("SELECT count(*) FROM datasets")
    status = await conn.fetchval("SELECT status FROM tenants WHERE slug='acme'")
    await conn.close()
    assert left == 0 and status == "purged"
    assert ds  # (dataset existed before the purge)
