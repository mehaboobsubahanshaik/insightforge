"""MVP6 A1: domain agents ground or refuse; DQ agent recommends real fixes;
agent APIs audited + quota-metered."""

from datetime import date, timedelta

from conftest import auth, get_workspace, register_and_login, upload_csv


def _finance_csv():
    t = date.today()
    rows = [f"{(t - timedelta(days=35)).isoformat()},South,1000",
            f"{(t - timedelta(days=5)).isoformat()},South,1600",
            f"{(t - timedelta(days=4)).isoformat()},East,300"]
    return "order_date,region,revenue\n" + "\n".join(rows) + "\n"


async def test_agents_ground_refuse_recommend(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    await upload_csv(client, tok, ws, name="fin", content=_finance_csv())
    listing = (await client.get("/api/v1/agents", headers=auth(tok))).json()
    assert len(listing["agents"]) == 6
    assert "human approval" in listing["agents"][0]["action_policy"]
    # finance agent: grounded finding + driver-based recommendation
    r = (await client.post("/api/v1/agents/finance/run",
                           headers=auth(tok))).json()
    assert r["grounded"] and "fin.revenue" in r["analyzed"]
    assert any(f["severity"] == "high" for f in r["findings"])
    assert any("South" in rec["action"] for rec in r["recommendations"])
    # marketing agent: no campaign columns -> honest refusal
    r = (await client.post("/api/v1/agents/marketing/run",
                           headers=auth(tok))).json()
    assert r["grounded"] is False and "refusing" in r["message"]
    # data-quality agent recommends applyable fixes on messy data
    await upload_csv(client, tok, ws, name="messy",
                     content="region,amount\nsouth,Rs.10\nSouth,Rs.20\n")
    r = (await client.post("/api/v1/agents/data_quality/run",
                           headers=auth(tok))).json()
    assert any("uppercase" in rec["action"] or
               "strip_non_numeric" in rec["action"]
               for rec in r["recommendations"])
    assert "never modify data" in r["note"]
    # unknown agent 404; runs audited as ai.agent
    assert (await client.post("/api/v1/agents/skynet/run",
                              headers=auth(tok))).status_code == 404
    acts = (await client.get("/api/v1/audit", headers=auth(tok))).json()
    items = acts if isinstance(acts, list) else acts.get("events", [])
    assert any(a["action"] == "ai.agent" for a in items)
