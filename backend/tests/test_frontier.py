"""MVP6 A3: causal validity gates, simulation, proactive forecasting,
narratives, private models, AI governance."""

from datetime import date, timedelta

from conftest import auth, get_workspace, register_and_login, upload_csv
from test_notifications import webhook_deliveries


def _did_csv():
    t = date.today()
    rows = []
    for i in range(6):  # pre: parallel flat trends
        d = (t - timedelta(days=12 - i)).isoformat()
        rows += [f"{d},South,100", f"{d},North,80"]
    for i in range(6):  # post: South jumps +50, North stays
        d = (t - timedelta(days=6 - i)).isoformat()
        rows += [f"{d},South,150", f"{d},North,80"]
    return "order_date,region,amount\n" + "\n".join(rows) + "\n"


async def test_causal_valid_and_refusals(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="exp", content=_did_csv())
    cut = (date.today() - timedelta(days=6)).isoformat()
    r = (await client.post("/api/v1/ml/causal", headers=auth(tok), json={
        "dataset_id": ds["id"], "value_column": "amount",
        "date_column": "order_date", "group_column": "region",
        "treated_value": "South", "intervention_date": cut})).json()
    assert r["valid"] and abs(r["estimate"] - 50.0) < 1.0
    assert "parallel-trends" in r["caveat"]
    # thin cells -> refusal, not a number
    tiny = await upload_csv(client, tok, ws, name="tiny",
                            content="order_date,region,amount\n"
                                    f"{cut},South,1\n{cut},North,1\n")
    r = (await client.post("/api/v1/ml/causal", headers=auth(tok), json={
        "dataset_id": tiny["id"], "value_column": "amount",
        "date_column": "order_date", "group_column": "region",
        "treated_value": "South", "intervention_date": cut})).json()
    assert r["valid"] is False and "Not methodologically valid" in r["refusal"]


async def test_simulation_proactive_narrative_private_governance(client):
    from insightforge_api.scheduler import run_proactive_forecasts_once

    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    t = date.today()
    rows = [f"{(t - timedelta(days=10 - i)).isoformat()},South,{100 + i * 50}"
            for i in range(10)]  # steep growth -> breach vs recent mean
    ds = await upload_csv(client, tok, ws, name="grow",
                          content="order_date,region,revenue\n"
                                  + "\n".join(rows) + "\n")
    # simulation: scenario curve = baseline x ratio
    sim = (await client.post("/api/v1/ml/simulate", headers=auth(tok), json={
        "dataset_id": ds["id"], "value_column": "revenue",
        "date_column": "order_date", "horizon": 4,
        "adjustments": [{"column": "region", "value": "South",
                         "factor": 1.1}]})).json()
    assert len(sim["baseline_trajectory"]) == 4
    assert sim["scenario_ratio"] == 1.1
    assert sim["scenario_trajectory"][0] == round(
        sim["baseline_trajectory"][0] * 1.1, 2)
    # proactive forecasting: register model + breach webhook
    await client.post("/api/v1/webhooks", headers=auth(tok), json={
        "name": "fw", "url": "https://ops.example/f",
        "events": ["forecast.breach"]})
    await client.post("/api/v1/ml/models", headers=auth(tok), json={
        "name": "rev", "dataset_id": ds["id"], "value_column": "revenue",
        "date_column": "order_date"})
    assert await run_proactive_forecasts_once() >= 1
    import json as _json

    body = _json.loads(webhook_deliveries()[-1]["body"])
    assert body["event"] == "forecast.breach"
    # automated narrative
    n = (await client.get("/api/v1/agents/narrative", headers=auth(tok))).json()
    assert "agents run" in n["text"] and "human approval" in n["text"]
    # private model + governance report
    r = await client.put("/api/v1/ml/private-model", headers=auth(tok), json={
        "endpoint_url": "https://models.acme.internal/score",
        "model_name": "churn-v2"})
    assert "high" in r.json()["risk_tier"]
    gov = (await client.get("/api/v1/ml/governance", headers=auth(tok))).json()
    assert gov["high_risk_count"] >= 1
    assert any("human" in c for c in gov["controls"])
    names = {m["name"] for m in gov["models"]}
    assert "private:churn-v2" in names and "rev" in names
