"""MVP3 exit criteria: three end-to-end business scenarios, run as a real
customer would experience them, plus a load sanity check."""

import time
from datetime import date, timedelta

from conftest import auth, get_workspace, register_and_login, upload_csv


async def test_scenario_new_customer_to_first_insight(client):
    """Scenario 1: sign up -> upload messy data -> AI-assisted cleanup ->
    ask a question -> pin to dashboard -> publish."""
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    messy = ("order_date,region,amount\n2026-06-01,south,Rs.100\n"
             "2026-06-02,South,Rs.200\n2026-06-03,North,Rs.50\n")
    ds = await upload_csv(client, tok, ws, name="sales", content=messy)
    sugs = (await client.get(f"/api/v1/datasets/{ds['id']}/prep-suggestions",
                             headers=auth(tok))).json()["suggestions"]
    steps = [{"op": s["op"], "column": s["column"],
              **({"value": s["value"]} if "value" in s else {})} for s in sugs]
    r = await client.post(f"/api/v1/datasets/{ds['id']}/recipe/apply",
                          headers=auth(tok), json={"steps": steps})
    assert r.status_code == 200
    a = (await client.post(f"/api/v1/datasets/{ds['id']}/ask", headers=auth(tok),
                           json={"question": "total amount by region"})).json()
    assert a["answered"] and a["suggested_widget"]["type"] == "bar"
    d = (await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "Sales", "widgets": [
            {"type": "bar", "dataset_id": ds["id"],
             **{k: a["suggested_widget"][k] for k in ("formula", "group_by")}}]}
    )).json()
    r = await client.post(f"/api/v1/dashboards/{d['id']}/publish",
                          headers=auth(tok))
    assert r.status_code == 200


async def test_scenario_monday_morning_executive(client):
    """Scenario 2: exec opens the brief, gets honest PoP narrative with
    drivers; scheduled report would carry the same story."""
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    today = date.today()
    csv = ("order_date,region,amount\n"
           f"{(today - timedelta(days=35)).isoformat()},South,1000\n"
           f"{(today - timedelta(days=5)).isoformat()},South,1500\n"
           f"{(today - timedelta(days=4)).isoformat()},East,500\n")
    ds = await upload_csv(client, tok, ws, name="rev", content=csv)
    d = (await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "Exec", "widgets": [
            {"type": "kpi", "title": "Revenue", "dataset_id": ds["id"],
             "formula": "sum(amount)"},
            {"type": "bar", "dataset_id": ds["id"], "formula": "sum(amount)",
             "group_by": "region"}]})).json()
    b = (await client.get(f"/api/v1/dashboards/{d['id']}/brief",
                          headers=auth(tok))).json()
    s = b["headlines"][0]["sentence"]
    assert "up 100%" in s and "driven by" in s and "East" in s
    assert any("Comparison windows" in n for n in b["notes"])


async def test_scenario_ops_team_gets_alerted(client):
    """Scenario 3: ops wires a Slack webhook + anomaly watch; a spike in
    the data reaches them without anyone opening the app."""
    import json as _json

    from test_distribution import _rewind
    from test_notifications import webhook_deliveries

    from insightforge_api.scheduler import run_due_alerts_once

    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    base = date.today() - timedelta(days=9)
    rows = [f"{(base + timedelta(days=i)).isoformat()},A,100" for i in range(9)]
    rows.append(f"{(base + timedelta(days=9)).isoformat()},A,999")
    ds = await upload_csv(client, tok, ws, name="ops",
                          content="d,c,v\n" + "\n".join(rows) + "\n")
    await client.post("/api/v1/webhooks", headers=auth(tok), json={
        "name": "ops-slack", "url": "https://hooks.slack.com/services/T/B/x",
        "format": "slack", "events": ["anomaly.detected"]})
    r = await client.post(f"/api/v1/datasets/{ds['id']}/alerts",
                          headers=auth(tok),
                          json={"name": "v watch", "formula": "sum(v)",
                                "kind": "anomaly", "date_column": "d",
                                "interval_minutes": 1440, "recipients": []})
    assert r.status_code == 201, r.text
    await _rewind("alert_rules", "next_check_at")
    assert await run_due_alerts_once() == 1
    msg = _json.loads(webhook_deliveries()[-1]["body"])
    assert "999" in msg["text"] and "[InsightForge]" in msg["text"]


async def test_load_sanity_dashboard_hydration(client):
    """Exit criterion 'load tests vs defined targets' — the defined target:
    a published 4-widget dashboard over 1k rows hydrates in < 2s, and 20
    sequential asks stay under 10s total (deterministic AI path)."""
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    rows = "\n".join(f"2026-0{(i % 6) + 1}-15,R{i % 5},{i}" for i in range(1000))
    ds = await upload_csv(client, tok, ws, name="big",
                          content="order_date,region,amount\n" + rows + "\n")
    d = (await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "Load", "widgets": [
            {"type": "kpi", "dataset_id": ds["id"], "formula": "sum(amount)"},
            {"type": "kpi", "dataset_id": ds["id"], "formula": "avg(amount)"},
            {"type": "bar", "dataset_id": ds["id"], "formula": "sum(amount)",
             "group_by": "region"},
            {"type": "table", "dataset_id": ds["id"], "limit": 25}]})).json()
    t0 = time.perf_counter()
    r = await client.get(f"/api/v1/dashboards/{d['id']}/data",
                         headers=auth(tok))
    hydrate_s = time.perf_counter() - t0
    assert r.status_code == 200 and hydrate_s < 2.0, f"hydration {hydrate_s:.2f}s"
    t0 = time.perf_counter()
    for _ in range(20):
        a = (await client.post(f"/api/v1/datasets/{ds['id']}/ask",
                               headers=auth(tok),
                               json={"question": "total amount by region"})).json()
        assert a["answered"]
    asks_s = time.perf_counter() - t0
    assert asks_s < 10.0, f"20 asks took {asks_s:.2f}s"
