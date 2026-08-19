"""R16: annotations, shared collections, scheduled snapshots, bullet +
control charts (threaded comments + PDF reports pre-existed)."""

import glob
import os

from conftest import auth, get_workspace, register_and_login, upload_csv

CSV = ("line,units\nA,100\nB,104\nC,98\nD,102\nE,300\n")  # E out of control


async def test_annotations_collections_snapshot_and_charts(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="prod", content=CSV)
    d = (await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "Ops", "widgets": [
            {"type": "bullet", "title": "Output vs goal",
             "dataset_id": ds["id"], "formula": "sum(units)",
             "target": 800, "max": 1000},
            {"type": "control", "title": "Line stability",
             "dataset_id": ds["id"], "formula": "sum(units)",
             "group_by": "line"}]})).json()
    data = (await client.get(f"/api/v1/dashboards/{d['id']}/data",
                             headers=auth(tok))).json()
    bullet = next(w for w in data["widgets"] if w["type"] == "bullet")
    assert bullet["value"] == 704 and bullet["target"] == 800
    ctl = next(w for w in data["widgets"] if w["type"] == "control")
    assert ctl["control"]["lcl"] < ctl["control"]["mean"] \
        < ctl["control"]["ucl"]
    assert ctl["control"]["out_of_control"] == ["E"]  # spike caught
    # annotation: widget-anchored comment; out-of-range anchor 422
    r = await client.post(f"/api/v1/dashboards/{d['id']}/comments",
                          headers=auth(tok),
                          json={"body": "Line E spiked after retooling",
                                "widget_anchor": 1})
    assert r.status_code == 201
    assert (await client.post(f"/api/v1/dashboards/{d['id']}/comments",
                              headers=auth(tok),
                              json={"body": "x", "widget_anchor": 9}
                              )).status_code == 422
    listing = (await client.get(f"/api/v1/dashboards/{d['id']}/comments",
                                headers=auth(tok))).json()
    assert listing[0]["widget_anchor"] == 1
    # shared collections
    r = (await client.post("/api/v1/collections", headers=auth(tok),
                           json={"name": "Board pack",
                                 "dashboard_ids": [d["id"]]})).json()
    assert r["collections"][0]["name"] == "Board pack"
    got = (await client.get("/api/v1/collections",
                            headers=auth(tok))).json()["collections"]
    assert got[0]["dashboard_ids"] == [d["id"]]
    # scheduled snapshot artifact from the report job
    import asyncpg
    from conftest import ADMIN_DSN

    from insightforge_api.scheduler import run_due_reports_once

    await client.post(f"/api/v1/dashboards/{d['id']}/publish",
                      headers=auth(tok))
    r = await client.post(f"/api/v1/dashboards/{d['id']}/report-schedules",
                          headers=auth(tok), json={
        "recipients": ["boss@acme.dev"], "interval_minutes": 1440})
    assert r.status_code in (200, 201), r.text
    conn = await asyncpg.connect(ADMIN_DSN)
    await conn.execute("UPDATE report_schedules SET next_run_at = now() "
                       "- interval '1 minute'")
    await conn.close()
    before = set(glob.glob(os.path.join(
        os.environ.get("OUTBOX_DIR", "/srv/outbox"), "snapshot-*.json")))
    assert await run_due_reports_once() >= 1
    after = set(glob.glob(os.path.join(
        os.environ.get("OUTBOX_DIR", "/srv/outbox"), "snapshot-*.json")))
    assert len(after - before) == 1  # snapshot rode along with the report
