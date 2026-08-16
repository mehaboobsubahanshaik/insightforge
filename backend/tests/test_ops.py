"""MVP3 P4 ops: status visibility, support workflow, privacy requests."""

from conftest import auth, outbox_bodies, register_and_login


async def test_public_status_endpoint(client):
    r = await client.get("/api/v1/platform/status")  # no auth
    assert r.status_code == 200
    body = r.json()
    assert body["database"] == "ok" and body["status"] == "operational"
    assert "scheduler_heartbeat" in body


async def test_support_and_privacy_requests(client):
    tok = await register_and_login(client)
    r = await client.post("/api/v1/support", headers=auth(tok),
                          json={"subject": "Dashboard question",
                                "message": "How do I share a view?"})
    assert r.status_code == 201 and r.json()["received"]
    assert any("[support] Dashboard question" in b for b in outbox_bodies())

    r = await client.post("/api/v1/privacy-request", headers=auth(tok),
                          json={"kind": "export"})
    assert r.status_code == 201 and r.json()["kind"] == "export"
    assert any("[privacy] export request" in b for b in outbox_bodies())
    # bad kind rejected
    r = await client.post("/api/v1/privacy-request", headers=auth(tok),
                          json={"kind": "forget-me"})
    assert r.status_code == 422
