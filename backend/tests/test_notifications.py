"""MVP3 P2 notifications: webhook CRUD + HMAC-signed delivery,
Slack formatting, scheduler event emission, anomaly-triggered alerts."""

import hashlib
import hmac
import json
from datetime import date, timedelta

from conftest import OUTBOX_DIR, auth, get_workspace, register_and_login, upload_csv
from test_distribution import _rewind


def webhook_deliveries() -> list[dict]:
    return [json.loads(p.read_text())
            for p in sorted(OUTBOX_DIR.glob("*.webhook.json"),
                            key=lambda p: p.stat().st_mtime_ns)]


async def test_webhook_crud_signature_and_slack_format(client):
    tok = await register_and_login(client)
    r = await client.post("/api/v1/webhooks", headers=auth(tok), json={
        "name": "Ops generic", "url": "https://ops.example/hook",
        "events": ["alert.triggered", "sync.failed"]})
    assert r.status_code == 201, r.text
    created = r.json()
    secret = created["secret"]
    assert len(secret) == 48 and "shown only once" in created["note"]

    listing = (await client.get("/api/v1/webhooks", headers=auth(tok))).json()
    assert listing["webhooks"][0]["name"] == "Ops generic"
    assert "secret" not in listing["webhooks"][0]  # never listed again
    assert set(listing["available_events"]) >= {"anomaly.detected", "report.sent"}

    # test delivery -> outbox file with verifiable HMAC
    hook_id = created["id"]
    r = await client.post(f"/api/v1/webhooks/{hook_id}/test", headers=auth(tok))
    assert r.json()["delivered"] == 1
    d = webhook_deliveries()[-1]
    body = d["body"].encode()
    expect = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert d["headers"]["X-InsightForge-Signature"] == expect
    assert json.loads(d["body"])["event"] == "alert.triggered"

    # slack format posts {"text": ...}
    r = await client.post("/api/v1/webhooks", headers=auth(tok), json={
        "name": "Slack", "url": "https://hooks.slack.com/services/T/B/x",
        "format": "slack", "events": ["alert.triggered"]})
    sid = r.json()["id"]
    await client.post(f"/api/v1/webhooks/{sid}/test", headers=auth(tok))
    slack_body = json.loads(webhook_deliveries()[-1]["body"])
    assert set(slack_body) == {"text"} and "[InsightForge]" in slack_body["text"]

    # unknown event rejected; other tenant sees nothing
    r = await client.post("/api/v1/webhooks", headers=auth(tok), json={
        "name": "x", "url": "https://a.example/h", "events": ["nope"]})
    assert r.status_code == 422
    tok2 = await register_and_login(client, slug="rival", email="o@rival.dev")
    assert (await client.get("/api/v1/webhooks",
                             headers=auth(tok2))).json()["webhooks"] == []


async def test_threshold_alert_fires_webhook_event(client):
    from insightforge_api.scheduler import run_due_alerts_once

    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)  # default CSV has amounts
    await client.post("/api/v1/webhooks", headers=auth(tok), json={
        "name": "Ops", "url": "https://ops.example/hook", "format": "teams",
        "events": ["alert.triggered"]})
    r = await client.post(f"/api/v1/datasets/{ds['id']}/alerts",
                          headers=auth(tok),
                          json={"name": "Total floor", "formula": "sum(total)",
                                "operator": "gt", "threshold": 1,
                                "interval_minutes": 1440, "recipients": []})
    assert r.status_code == 201, r.text
    await _rewind("alert_rules", "next_check_at")
    assert await run_due_alerts_once() == 1
    last = json.loads(webhook_deliveries()[-1]["body"])
    assert "Alert 'Total floor'" in last["text"]  # teams format


async def test_anomaly_alert_fires_on_latest_day_spike(client):
    from insightforge_api.scheduler import run_due_alerts_once

    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    base = date.today() - timedelta(days=9)
    rows = [f"{(base + timedelta(days=i)).isoformat()},South,100" for i in range(9)]
    rows.append(f"{(base + timedelta(days=9)).isoformat()},South,950")  # spike today
    csv = "order_date,region,amount\n" + "\n".join(rows) + "\n"
    ds = await upload_csv(client, tok, ws, name="spiky", content=csv)
    await client.post("/api/v1/webhooks", headers=auth(tok), json={
        "name": "Anoms", "url": "https://ops.example/anoms",
        "events": ["anomaly.detected"]})
    r = await client.post(f"/api/v1/datasets/{ds['id']}/alerts",
                          headers=auth(tok),
                          json={"name": "Revenue anomaly watch",
                                "formula": "sum(amount)", "kind": "anomaly",
                                "date_column": "order_date", "interval_minutes": 1440,
                                "recipients": ["ops@acme.dev"]})
    assert r.status_code == 201, r.text
    await _rewind("alert_rules", "next_check_at")
    assert await run_due_alerts_once() == 1  # fires on the spike
    last = json.loads(webhook_deliveries()[-1]["body"])
    assert last["event"] == "anomaly.detected"
    assert "950" in last["payload"]["message"]
    assert "spike" in last["payload"]["message"]
    # state machine: same anomaly does not re-fire
    await _rewind("alert_rules", "next_check_at")
    assert await run_due_alerts_once() == 0

    # a dataset without an anomaly never fires
    flat = "order_date,region,amount\n" + "\n".join(
        f"{(base + timedelta(days=i)).isoformat()},South,100"
        for i in range(10)) + "\n"
    ds2 = await upload_csv(client, tok, ws, name="flat", content=flat)
    r = await client.post(f"/api/v1/datasets/{ds2['id']}/alerts",
                          headers=auth(tok),
                          json={"name": "Flat watch", "formula": "sum(amount)",
                                "kind": "anomaly", "date_column": "order_date",
                                "interval_minutes": 1440, "recipients": []})
    await _rewind("alert_rules", "next_check_at")
    assert await run_due_alerts_once() == 0

    # validation: anomaly alerts demand a real date column
    r = await client.post(f"/api/v1/datasets/{ds['id']}/alerts",
                          headers=auth(tok),
                          json={"name": "bad", "formula": "sum(amount)",
                                "kind": "anomaly", "date_column": "region",
                                "interval_minutes": 1440})
    assert r.status_code == 422
