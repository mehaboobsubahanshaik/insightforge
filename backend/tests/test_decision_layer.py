"""MVP6 A2: orchestration+ranking, action plans, approval gate,
closed-loop outcomes. The mandate test lives here: no outcome without
human approval."""

from datetime import date, timedelta

from conftest import auth, get_workspace, register_and_login, upload_csv


async def test_orchestrate_plan_approve_closed_loop(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    t = date.today()
    csv = ("order_date,region,revenue\n"
           f"{(t - timedelta(days=35)).isoformat()},South,1000\n"
           f"{(t - timedelta(days=5)).isoformat()},South,1600\n"
           f"{(t - timedelta(days=4)).isoformat()},East,300\n")
    ds = await upload_csv(client, tok, ws, name="fin", content=csv)
    # orchestration: all agents run, recs ranked by impact x confidence
    o = (await client.post("/api/v1/agents/orchestrate",
                           headers=auth(tok))).json()
    assert set(o["agents_run"]) >= {"finance", "data_quality"}
    assert o["grounded"]["finance"] is True
    recs = o["ranked_recommendations"]
    assert recs and all(recs[i]["score"] >= recs[i + 1]["score"]
                        for i in range(len(recs) - 1))
    # plan from the top rec -> pending + approval auto-opened
    p = (await client.post("/api/v1/agents/plans", headers=auth(tok), json={
        "name": "Boost East", "steps": ["Review East pricing",
                                        "Launch East promo"],
        "metric_dataset_id": ds["id"],
        "metric_formula": "sum(revenue)"})).json()
    assert p["status"] == "pending"
    # MANDATE: outcome refused while unapproved
    r = await client.post(f"/api/v1/agents/plans/{p['id']}/outcome",
                          headers=auth(tok))
    assert r.status_code == 403 and "human-approved" in r.json()["detail"]
    # human approves -> baseline captured at approval time
    approvals = (await client.get("/api/v1/catalog/approvals",
                                  headers=auth(tok))).json()["approvals"]
    ap = next(a for a in approvals if a["kind"] == "action_plan")
    await client.post(f"/api/v1/catalog/approvals/{ap['id']}/decide",
                      headers=auth(tok), json={"decision": "approve"})
    plans = (await client.get("/api/v1/agents/plans",
                              headers=auth(tok))).json()["plans"]
    assert plans[0]["status"] == "approved"
    assert plans[0]["metrics"]["baseline"] == 2900.0
    # world changes in place; the closed loop measures the delta honestly
    import asyncpg
    from conftest import ADMIN_DSN

    conn = await asyncpg.connect(ADMIN_DSN)
    await conn.execute("DELETE FROM dataset_rows WHERE data->>'region'='East'")
    await conn.close()
    out = (await client.post(f"/api/v1/agents/plans/{p['id']}/outcome",
                             headers=auth(tok))).json()
    assert out["baseline"] == 2900.0 and out["outcome"] == 2600.0
    assert out["delta"] == -300.0 and out["verdict"] == "declined"
