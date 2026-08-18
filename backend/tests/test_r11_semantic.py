"""R11: semantic model, virtual joins, measure versioning + validation."""

from conftest import auth, get_workspace, register_and_login, upload_csv

ORDERS = ("order_id,customer_id,amount\n1,c1,100\n2,c2,200\n3,c1,300\n")
CUSTOMERS = ("customer_id,segment,country\nc1,Enterprise,IN\nc2,SMB,US\n")


async def test_semantic_model_and_virtual_join(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    orders = await upload_csv(client, tok, ws, name="orders", content=ORDERS)
    cust = await upload_csv(client, tok, ws, name="customers",
                            content=CUSTOMERS)
    model = {"hierarchies": [{"name": "Geo", "dataset_id": cust["id"],
                              "levels": ["country", "segment"]}],
             "relationships": [{"name": "orders->customers",
                                "left_dataset_id": orders["id"],
                                "left_key": "customer_id",
                                "right_dataset_id": cust["id"],
                                "right_key": "customer_id"}],
             "subject_areas": [{"name": "Sales",
                                "dataset_ids": [orders["id"], cust["id"]]}]}
    r = await client.put("/api/v1/semantic/model", headers=auth(tok),
                         json=model)
    assert r.status_code == 200
    # bad hierarchy column -> 422 (model can't drift from real schemas)
    bad = {**model, "hierarchies": [{"name": "X", "dataset_id": cust["id"],
                                     "levels": ["country", "ghost"]}]}
    assert (await client.put("/api/v1/semantic/model", headers=auth(tok),
                             json=bad)).status_code == 422
    # virtual join: sum orders.amount grouped by customers.segment — no copy
    q = (await client.post("/api/v1/semantic/query", headers=auth(tok), json={
        "relationship": "orders->customers", "value_column": "amount",
        "group_by": "segment"})).json()
    assert {g["group"]: g["value"] for g in q["groups"]} == \
        {"Enterprise": 400.0, "SMB": 200.0}
    assert "nothing materialized" in q["method"]
    assert (await client.post("/api/v1/semantic/query", headers=auth(tok),
                              json={"relationship": "nope",
                                    "value_column": "amount",
                                    "group_by": "segment"})).status_code == 404


async def test_measure_versioning_units_validation(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="orders", content=ORDERS)
    m = (await client.post(f"/api/v1/datasets/{ds['id']}/measures",
                           headers=auth(tok), json={
        "name": "Revenue", "formula": "sum(amount)"})).json()
    r = (await client.put(f"/api/v1/semantic/measures/{m['id']}",
                          headers=auth(tok),
                          json={"formula": "sum(amount)/count()",
                                "unit": "INR"})).json()
    assert r["versions"] == 1 and r["unit"] == "INR"
    assert r["certified"] is False  # change resets certification
    # bad formula rejected, history unchanged
    bad = await client.put(f"/api/v1/semantic/measures/{m['id']}",
                           headers=auth(tok),
                           json={"formula": "sum(ghost)"})
    assert bad.status_code == 422
    # validation test: avg 200 within [100,300]; fails at min 500
    ok = (await client.post(f"/api/v1/semantic/measures/{m['id']}/validate",
                            headers=auth(tok),
                            json={"min": 100, "max": 300})).json()
    assert ok["passed"] is True and ok["value"] == 200
    fail = (await client.post(f"/api/v1/semantic/measures/{m['id']}/validate",
                              headers=auth(tok), json={"min": 500})).json()
    assert fail["passed"] is False and "FAILED" in fail["verdict"]
