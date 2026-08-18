"""R9: funnel/waterfall/gauge/scatter/histogram widgets — validation +
hydration shapes."""

from conftest import auth, get_workspace, register_and_login, upload_csv

CSV = ("stage,region,amount,cost\n"
       "Visit,South,1000,10\nSignup,South,400,20\nTrial,North,150,30\n"
       "Paid,East,60,40\n")


async def test_new_widget_types_validate_and_hydrate(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="funnelds", content=CSV)
    widgets = [
        {"type": "funnel", "title": "Journey", "dataset_id": ds["id"],
         "formula": "sum(amount)", "group_by": "stage"},
        {"type": "waterfall", "title": "Bridge", "dataset_id": ds["id"],
         "formula": "sum(amount)", "group_by": "region"},
        {"type": "gauge", "title": "Total", "dataset_id": ds["id"],
         "formula": "sum(amount)", "max": 2000},
        {"type": "scatter", "title": "A vs C", "dataset_id": ds["id"],
         "x_column": "amount", "y_column": "cost"},
        {"type": "histogram", "title": "Dist", "dataset_id": ds["id"],
         "x_column": "amount", "bins": 4},
    ]
    d = (await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "Viz9", "widgets": widgets}))
    assert d.status_code == 201, d.text
    did = d.json()["id"]
    data = (await client.get(f"/api/v1/dashboards/{did}/data",
                             headers=auth(tok))).json()
    by = {w["type"]: w for w in data["widgets"]}
    assert {g["group"] for g in by["funnel"]["groups"]} == \
        {"Visit", "Signup", "Trial", "Paid"}
    assert by["gauge"]["value"] == 1610 and by["gauge"]["max"] == 2000
    assert len(by["scatter"]["points"]) == 4
    assert [1000.0, 10.0] in by["scatter"]["points"]
    bins = by["histogram"]["bins"]
    assert len(bins) == 4 and sum(b["count"] for b in bins) == 4
    # validation: scatter same column, histogram non-numeric -> 422
    r = await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "bad", "widgets": [
            {"type": "scatter", "dataset_id": ds["id"],
             "x_column": "amount", "y_column": "amount"}]})
    assert r.status_code == 422
    r = await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "bad2", "widgets": [
            {"type": "histogram", "dataset_id": ds["id"],
             "x_column": "stage"}]})
    assert r.status_code == 422
