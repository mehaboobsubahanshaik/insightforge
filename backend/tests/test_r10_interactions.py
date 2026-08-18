"""R10: bookmarks, snapshots (parameters + cross-filter + drill-through
pre-existed — verified via the filters param below)."""

import json
import os

from conftest import auth, get_workspace, register_and_login, upload_csv

CSV = "region,amount\nSouth,100\nNorth,50\n"


async def test_parameters_bookmarks_snapshot(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="sales", content=CSV)
    d = (await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "Ten", "widgets": [
            {"type": "kpi", "title": "Spend", "dataset_id": ds["id"],
             "formula": "sum(amount)"}]})).json()
    # parameters: viewer-supplied filters change the data (pre-existing)
    flt = json.dumps([{"column": "region", "op": "eq", "value": "South"}])
    data = (await client.get(f"/api/v1/dashboards/{d['id']}/data",
                             params={"filters": flt},
                             headers=auth(tok))).json()
    assert data["widgets"][0]["value"] == 100
    # bookmarks: save the state, list it back; bad filter shape 422
    r = await client.post(f"/api/v1/dashboards/{d['id']}/bookmarks",
                          headers=auth(tok),
                          json={"name": "South only",
                                "filters": json.loads(flt)})
    assert r.status_code == 201
    marks = (await client.get(f"/api/v1/dashboards/{d['id']}/bookmarks",
                              headers=auth(tok))).json()["bookmarks"]
    assert marks[0]["name"] == "South only"
    r = await client.post(f"/api/v1/dashboards/{d['id']}/bookmarks",
                          headers=auth(tok),
                          json={"name": "bad", "filters": [{"column": "x"}]})
    assert r.status_code == 422
    # snapshot: published required by default; draft view works; file lands
    r = await client.post(f"/api/v1/dashboards/{d['id']}/snapshot",
                          headers=auth(tok))
    assert r.status_code == 404  # never published
    r = await client.post(f"/api/v1/dashboards/{d['id']}/snapshot",
                          headers=auth(tok), params={"view": "draft"})
    assert r.status_code == 201
    snap = r.json()
    path = os.path.join(os.environ.get("OUTBOX_DIR", "/srv/outbox"),
                        snap["file"])
    saved = json.load(open(path))
    assert saved["widgets"][0]["value"] == 150  # values, not just defs
    assert saved["taken_by"]
