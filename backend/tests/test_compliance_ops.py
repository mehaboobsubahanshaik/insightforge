"""MVP5 G4: audit exports, SIEM streaming, deployment posture, SLAs,
support access controls."""

import json

from conftest import auth, register_and_login
from test_notifications import webhook_deliveries


async def test_audit_export_jsonl_and_csv(client):
    tok = await register_and_login(client)
    await client.put("/api/v1/enterprise/cmk", headers=auth(tok), json={
        "provider": "aws-kms", "key_id": "arn:aws:kms:eu:1:key/a"})
    r = await client.get("/api/v1/enterprise/audit/export", headers=auth(tok))
    lines = [json.loads(line) for line in r.text.strip().split("\n")]
    assert any(rec["action"] == "cmk.configure" for rec in lines)
    r = await client.get("/api/v1/enterprise/audit/export?format=csv",
                         headers=auth(tok))
    assert r.headers["content-type"].startswith("text/csv")
    assert "cmk.configure" in r.text


async def test_siem_streams_security_events_once(client):
    from insightforge_api.scheduler import run_siem_once

    tok = await register_and_login(client)
    await client.post("/api/v1/webhooks", headers=auth(tok), json={
        "name": "SIEM", "url": "https://siem.example/ingest",
        "events": ["siem.audit"]})
    # generate security-relevant events
    await client.put("/api/v1/enterprise/cmk", headers=auth(tok), json={
        "provider": "aws-kms", "key_id": "arn:aws:kms:eu:1:key/a"})
    shipped = await run_siem_once()
    assert shipped >= 2  # webhook.create + cmk.configure at minimum
    body = json.loads(webhook_deliveries()[-1]["body"])
    assert body["event"] == "siem.audit"
    actions = [e["action"] for e in body["payload"]["events"]]
    assert "cmk.configure" in actions
    # cursor: second run ships nothing new
    assert await run_siem_once() == 0


async def test_deployment_sla_support_access(client):
    tok = await register_and_login(client)
    r = await client.put("/api/v1/enterprise/deployment", headers=auth(tok),
                         json={"region": "eu-west",
                               "private_connectivity": True,
                               "dedicated": True})
    assert r.json()["deployment"]["region"] == "eu-west"
    assert (await client.put("/api/v1/enterprise/deployment",
                             headers=auth(tok),
                             json={"region": "moon-base"})).status_code == 422
    sla = (await client.get("/api/v1/enterprise/sla",
                            headers=auth(tok))).json()
    assert sla["plan"] == "free" and sla["sla"]["uptime"] == "99.0%"
    assert "growth" in sla["all_tiers"]
    r = await client.post("/api/v1/enterprise/support-access",
                          headers=auth(tok), json={"hours": 24})
    assert "support_access_until" in r.json()
    assert (await client.post("/api/v1/enterprise/support-access",
                              headers=auth(tok),
                              json={"hours": 500})).status_code == 422
