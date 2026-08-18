"""MVP6 A4 capstone: the mandate, end to end — agents may observe, rank,
and propose; NOTHING acts without explicit human approval; every step of
the chain is in the audit trail."""

from datetime import date, timedelta

from conftest import auth, get_workspace, register_and_login, upload_csv


async def test_decision_platform_mandate(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    t = date.today()
    csv = ("order_date,region,revenue\n"
           f"{(t - timedelta(days=35)).isoformat()},South,1000\n"
           f"{(t - timedelta(days=5)).isoformat()},South,1600\n"
           f"{(t - timedelta(days=4)).isoformat()},East,300\n")
    ds = await upload_csv(client, tok, ws, name="fin", content=csv)
    # observe -> rank -> propose
    o = (await client.post("/api/v1/agents/orchestrate",
                           headers=auth(tok))).json()
    assert o["ranked_recommendations"]
    p = (await client.post("/api/v1/agents/plans", headers=auth(tok), json={
        "name": "Act on top rec", "steps": ["do the thing"],
        "metric_dataset_id": ds["id"],
        "metric_formula": "sum(revenue)"})).json()
    # THE MANDATE: no outcome without approval
    assert (await client.post(f"/api/v1/agents/plans/{p['id']}/outcome",
                              headers=auth(tok))).status_code == 403
    ap = next(a for a in (await client.get(
        "/api/v1/catalog/approvals", headers=auth(tok))).json()["approvals"]
        if a["kind"] == "action_plan")
    await client.post(f"/api/v1/catalog/approvals/{ap['id']}/decide",
                      headers=auth(tok), json={"decision": "approve"})
    out = (await client.post(f"/api/v1/agents/plans/{p['id']}/outcome",
                             headers=auth(tok))).json()
    assert out["baseline"] == 2900.0
    # the whole chain is auditable
    exp = (await client.get("/api/v1/enterprise/audit/export",
                            headers=auth(tok))).text
    for step in ("ai.orchestrate", "plan.create", "approval.request",
                 "approval.approved", "plan.outcome"):
        assert step in exp, step
