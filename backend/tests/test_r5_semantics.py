"""R5: joins, pivot, formula columns, time grains, fiscal calendar,
currency conversion."""

from conftest import auth, get_workspace, register_and_login, upload_csv

ORDERS = ("order_id,customer_id,order_date,amount\n"
          "1,c1,2026-03-10,100\n2,c2,2026-04-05,200\n3,c1,2026-07-20,300\n")
CUSTOMERS = "customer_id,segment\nc1,Enterprise\nc2,SMB\n"


async def test_join_pivot_derive(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    await client.post("/api/v1/billing/plan", headers=auth(tok),
                      json={"plan_code": "growth"})  # room for derived sets
    left = await upload_csv(client, tok, ws, name="orders", content=ORDERS)
    right = await upload_csv(client, tok, ws, name="customers",
                             content=CUSTOMERS)
    j = (await client.post("/api/v1/datasets/join", headers=auth(tok), json={
        "left_id": left["id"], "right_id": right["id"],
        "left_key": "customer_id", "right_key": "customer_id",
        "name": "orders-enriched", "how": "inner"})).json()
    assert j["row_count"] == 3
    a = (await client.post(f"/api/v1/datasets/{j['id']}/ask",
                           headers=auth(tok),
                           json={"question": "total amount by segment"})).json()
    groups = {g["group"]: g["value"] for g in a["answer"]["groups"]}
    assert groups == {"Enterprise": 400.0, "SMB": 200.0}  # join correct
    p = (await client.post(f"/api/v1/datasets/{j['id']}/pivot",
                           headers=auth(tok), json={
        "index": "segment", "columns": "customer_id", "value": "amount",
        "name": "seg-pivot"})).json()
    assert p["row_count"] == 2
    d = (await client.post(f"/api/v1/datasets/{left['id']}/derive",
                           headers=auth(tok), json={
        "name": "orders-taxed", "column": "with_tax",
        "left": "amount", "op": "*", "right": "1.18"})).json()
    a = (await client.post(f"/api/v1/datasets/{d['id']}/ask",
                           headers=auth(tok),
                           json={"question": "total with_tax"})).json()
    assert abs(a["answer"]["value"] - 708.0) < 0.01  # 600 * 1.18
    r = await client.post(f"/api/v1/datasets/{left['id']}/derive",
                          headers=auth(tok), json={
        "name": "x", "column": "bad", "left": "amount", "op": "*",
        "right": "customer_id"})
    assert r.status_code == 422


async def test_timeseries_grains_fiscal_currency(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="orders", content=ORDERS)
    await client.put("/api/v1/tenants/semantics", headers=auth(tok), json={
        "fiscal_year_start_month": 4,
        "currency": {"base": "INR", "rates": {"USD": 0.012}}})
    m = (await client.get(f"/api/v1/datasets/{ds['id']}/timeseries",
                          params={"value": "amount", "date": "order_date",
                                  "grain": "month"},
                          headers=auth(tok))).json()
    assert m["points"][0] == {"period": "2026-03-01", "value": 100.0}
    q = (await client.get(f"/api/v1/datasets/{ds['id']}/timeseries",
                          params={"value": "amount", "date": "order_date",
                                  "grain": "fiscal_quarter"},
                          headers=auth(tok))).json()
    pts = {p["period"]: p["value"] for p in q["points"]}
    # FY starts April: Mar-2026 -> FY2026-Q4; Apr -> FY2027-Q1; Jul -> Q2
    assert pts == {"FY2026-Q4": 100.0, "FY2027-Q1": 200.0,
                   "FY2027-Q2": 300.0}
    c = (await client.get(f"/api/v1/datasets/{ds['id']}/timeseries",
                          params={"value": "amount", "date": "order_date",
                                  "grain": "month", "currency_to": "USD"},
                          headers=auth(tok))).json()
    assert c["points"][0]["value"] == 1.2  # 100 INR * 0.012
    r = await client.get(f"/api/v1/datasets/{ds['id']}/timeseries",
                         params={"value": "amount", "date": "order_date",
                                 "currency_to": "EUR"}, headers=auth(tok))
    assert r.status_code == 422  # no invented FX rates
