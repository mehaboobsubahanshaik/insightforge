"""MVP5 G5: model registry+monitoring, what-if, scenarios, root-cause,
Azure ML config."""

from datetime import date, timedelta

from conftest import auth, get_workspace, register_and_login, upload_csv


def _csv():
    today = date.today()
    rows = []
    for i in range(10):
        d = (today - timedelta(days=40 - i)).isoformat()   # prev window
        rows.append(f"{d},South,Widget,100")
    for i in range(10):
        d = (today - timedelta(days=10 - i)).isoformat()   # current window
        rows.append(f"{d},South,Widget,{200 if i < 9 else 210}")
        rows.append(f"{d},North,Gadget,50")
    return "order_date,region,product,amount\n" + "\n".join(rows) + "\n"


async def test_registry_monitoring_whatif_scenarios_rootcause_azure(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="sales", content=_csv())
    # register forecast model -> baseline metrics
    r = await client.post("/api/v1/ml/models", headers=auth(tok), json={
        "name": "daily revenue", "dataset_id": ds["id"],
        "value_column": "amount", "date_column": "order_date"})
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    assert "mae" in r.json()["metrics"]["baseline"]
    # monitoring: evaluate on same data -> no drift
    ev = (await client.post(f"/api/v1/ml/models/{mid}/evaluate",
                            headers=auth(tok))).json()
    assert ev["drift"] is False
    listing = (await client.get("/api/v1/ml/models", headers=auth(tok))).json()
    assert listing["models"][0]["evaluated_at"]

    # what-if: baseline known; +20% on South
    total = sum(100 for _ in range(10)) + sum(200 for _ in range(9)) + 210 \
        + sum(50 for _ in range(10))
    south = 10 * 100 + 9 * 200 + 210
    wi = (await client.post("/api/v1/ml/what-if", headers=auth(tok), json={
        "dataset_id": ds["id"], "value_column": "amount",
        "adjustments": [{"column": "region", "value": "South",
                         "factor": 1.2}]})).json()
    assert wi["baseline"] == total
    assert abs(wi["adjusted"] - (total + south * 0.2)) < 0.01
    # scenario: save + run reproduces
    sc = (await client.post("/api/v1/ml/scenarios", headers=auth(tok), json={
        "name": "South +20%", "dataset_id": ds["id"],
        "value_column": "amount",
        "adjustments": [{"column": "region", "value": "South",
                         "factor": 1.2}]})).json()
    run = (await client.post(f"/api/v1/ml/scenarios/{sc['id']}/run",
                             headers=auth(tok))).json()
    assert run["adjusted"] == wi["adjusted"] and run["name"] == "South +20%"

    # root-cause: South/Widget drove the PoP jump; region & product agree
    rc = (await client.post("/api/v1/ml/root-cause", headers=auth(tok), json={
        "dataset_id": ds["id"], "value_column": "amount",
        "date_column": "order_date",
        "dimensions": ["region", "product"]})).json()
    assert "explains" in rc["prime_suspect"]
    assert rc["findings"][0]["top_segment"]["group"] in ("South", "Widget")
    assert rc["workflow"][0].startswith("detect")

    # Azure ML config: registered as external model; bad URL 422
    r = await client.put("/api/v1/ml/azure", headers=auth(tok), json={
        "workspace_url": "https://westeurope.api.azureml.net",
        "endpoint_name": "churn-scorer"})
    assert r.status_code == 200
    kinds = {m["kind"] for m in (await client.get(
        "/api/v1/ml/models", headers=auth(tok))).json()["models"]}
    assert "external" in kinds
    assert (await client.put("/api/v1/ml/azure", headers=auth(tok), json={
        "workspace_url": "https://evil.example.com",
        "endpoint_name": "x"})).status_code == 422
