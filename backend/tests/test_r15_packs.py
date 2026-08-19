"""R15: 12 industry packs (honest apply) + churn/lead scoring."""

from datetime import date, timedelta

from conftest import auth, get_workspace, register_and_login, upload_csv


async def test_pack_catalog_and_honest_apply(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    packs = (await client.get("/api/v1/packs",
                              headers=auth(tok))).json()["packs"]
    assert len(packs) == 12
    assert {p["industry"] for p in packs} >= {
        "sales", "healthcare_admin", "nonprofit", "education",
        "property_management", "logistics"}
    ds = await upload_csv(client, tok, ws, name="crm", content=(
        "region,stage,amount\nSouth,Won,100\nNorth,Open,50\n"))
    r = (await client.post("/api/v1/packs/sales/apply", headers=auth(tok),
                           json={"dataset_id": ds["id"]})).json()
    assert set(r["measures_created"]) == {"Total revenue", "Deals",
                                          "Avg deal size"}
    assert r["dashboard_id"] and r["widgets"] == 3
    data = (await client.get(f"/api/v1/dashboards/{r['dashboard_id']}/data",
                             headers=auth(tok))).json()
    kpi = next(w for w in data["widgets"] if w["type"] == "kpi")
    assert kpi["value"] == 150
    # mismatched pack: skips honestly instead of creating broken objects
    r2 = (await client.post("/api/v1/packs/manufacturing/apply",
                            headers=auth(tok),
                            json={"dataset_id": ds["id"]})).json()
    assert r2["measures_created"] == []
    assert r2["skipped"] and all("needs columns" in s["reason"]
                                 for s in r2["skipped"]
                                 if "kpi" in s or "widget" in s)
    assert (await client.get("/api/v1/packs/astrology",
                             headers=auth(tok))).status_code == 404


async def test_churn_and_lead_scoring(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    t = date.today()
    fresh, stale = (t - timedelta(days=5)), (t - timedelta(days=300))
    csv = ("customer,order_date,amount\n"
           f"acme,{fresh},500\nacme,{fresh},300\n"
           f"ghost,{stale},50\n")
    ds = await upload_csv(client, tok, ws, name="orders", content=csv)
    r = (await client.post("/api/v1/ml/models/score", headers=auth(tok),
                           json={"dataset_id": ds["id"], "kind": "churn",
                                 "entity_column": "customer",
                                 "recency_column": "order_date",
                                 "value_column": "amount"})).json()
    scores = {s["entity"]: s["score"] for s in r["scores"]}
    assert scores["ghost"] > scores["acme"]  # stale customer churnier
    assert "not a trained model" in r["method"]  # honesty label
    lead = (await client.post("/api/v1/ml/models/score",
                              headers=auth(tok),
                              json={"dataset_id": ds["id"], "kind": "lead",
                                    "entity_column": "customer",
                                    "recency_column": "order_date",
                                    "value_column": "amount"})).json()
    lscores = {s["entity"]: s["score"] for s in lead["scores"]}
    assert lscores["acme"] > lscores["ghost"]  # valuable+recent = warm
    bad = await client.post("/api/v1/ml/models/score", headers=auth(tok),
                            json={"dataset_id": ds["id"], "kind": "churn",
                                  "entity_column": "customer",
                                  "recency_column": "amount",
                                  "value_column": "amount"})
    assert bad.status_code == 422
