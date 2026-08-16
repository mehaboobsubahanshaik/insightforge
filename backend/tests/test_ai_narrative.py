"""MVP3 chapter 2: executive brief, PoP driver attribution, metric
explanations, and the narrative riding scheduled report emails."""

from datetime import date, timedelta

import pytest
from conftest import auth, get_workspace, outbox_bodies, register_and_login, upload_csv

pytestmark = pytest.mark.ai_eval


def _pop_csv() -> str:
    """Two 30-day windows with known deltas.
    Previous window: South 1000, North 500 (total 1500).
    Current window:  South 1600, North 450, East 250 (total 2300).
    Change +800: driven by South (+600) and East (+250), offset by North (−50)."""
    today = date.today()
    cur = (today - timedelta(days=5)).isoformat()
    prev = (today - timedelta(days=35)).isoformat()
    rows = [
        (prev, "South", 1000), (prev, "North", 500),
        (cur, "South", 1600), (cur, "North", 450), (cur, "East", 250),
    ]
    return ("order_date,region,amount\n"
            + "\n".join(f"{d},{r},{a}" for d, r, a in rows) + "\n")


async def _dash_with_kpi(client, tok, ds):
    r = await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ds["workspace_id"], "name": "Exec view", "widgets": [
            {"type": "kpi", "title": "Revenue", "dataset_id": ds["id"],
             "formula": "sum(amount)"},
            {"type": "bar", "title": "By region", "dataset_id": ds["id"],
             "formula": "sum(amount)", "group_by": "region"}]})
    assert r.status_code == 201, r.text
    return r.json()


async def test_brief_pop_and_driver_attribution(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="sales", content=_pop_csv())
    d = await _dash_with_kpi(client, tok, ds)
    r = await client.get(f"/api/v1/dashboards/{d['id']}/brief", headers=auth(tok))
    assert r.status_code == 200, r.text
    b = r.json()
    h = b["headlines"][0]
    assert h["current"] == 2300 and h["previous"] == 1500
    assert h["pct"] == "up 53%"
    s = h["sentence"]
    # drivers ordered by magnitude, offsets named, small movers welcome
    assert "driven by South (+600)" in s and "East (+250)" in s
    assert "offset by North (−50)" in s
    # honesty notes: windows named, quarantine/quality stated
    assert any("Comparison windows" in n for n in b["notes"])
    assert "Executive brief — Exec view" in b["text"]


async def test_brief_without_date_column_is_honest(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="static",
                          content="region,amount\nSouth,10\nNorth,20\n")
    d = await _dash_with_kpi(client, tok, ds)
    b = (await client.get(f"/api/v1/dashboards/{d['id']}/brief",
                          headers=auth(tok))).json()
    assert "no date column" in b["headlines"][0]["sentence"]
    assert b["headlines"][0]["current"] == 30


async def test_ask_explains_measures_and_columns(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="sales", content=_pop_csv())
    r = await client.post(f"/api/v1/datasets/{ds['id']}/measures",
                          headers=auth(tok),
                          json={"name": "revenue", "formula": "sum(amount)",
                                "certified": True})
    assert r.status_code == 201
    r = await client.post(f"/api/v1/datasets/{ds['id']}/ask", headers=auth(tok),
                          json={"question": "explain revenue"})
    exp = r.json()["explanation"]
    assert "adds up the 'amount' column" in exp["text"]
    assert "certified measure 'revenue'" in exp["text"]
    assert exp["certified_measure"] == "revenue"

    r = await client.post(f"/api/v1/datasets/{ds['id']}/ask", headers=auth(tok),
                          json={"question": "what does region mean"})
    assert "text column" in r.json()["explanation"]["text"]


async def test_report_email_leads_with_brief(client):
    from test_distribution import _rewind

    from insightforge_api.scheduler import run_due_reports_once

    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="sales", content=_pop_csv())
    d = await _dash_with_kpi(client, tok, ds)
    await client.post(f"/api/v1/dashboards/{d['id']}/publish", headers=auth(tok))
    r = await client.post(f"/api/v1/dashboards/{d['id']}/report-schedules",
                          headers=auth(tok),
                          json={"recipients": ["boss@acme.dev"],
                                "interval_minutes": 1440})
    assert r.status_code == 201, r.text
    await _rewind("report_schedules", "next_run_at")
    assert await run_due_reports_once() == 1
    mail = [b for b in outbox_bodies() if "Scheduled report" in b][-1]
    assert "Executive brief — Exec view" in mail
    assert "up 53%" in mail and "driven by South" in mail
    assert "attached" in mail  # PDF still rides along


async def test_drivers_never_use_date_columns_and_stale_data_is_named(client):
    """Reproduces the field bug: a date-grouped line widget must not make
    order_date the driver dimension, and an empty current window says why."""
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    old = (date.today() - timedelta(days=45)).isoformat()  # prior window only
    csv = ("order_date,region,amount\n"
           f"{old},South,900\n{old},North,300\n")
    ds = await upload_csv(client, tok, ws, name="stale", content=csv)
    r = await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "Stale view", "widgets": [
            {"type": "kpi", "title": "Revenue", "dataset_id": ds["id"],
             "formula": "sum(amount)"},
            {"type": "line", "title": "Over time", "dataset_id": ds["id"],
             "formula": "sum(amount)", "group_by": "order_date"}]})
    d = r.json()
    b = (await client.get(f"/api/v1/dashboards/{d['id']}/brief",
                          headers=auth(tok))).json()
    sent = b["headlines"][0]["sentence"]
    assert "order_date" not in sent            # dates are not drivers
    assert "Across region" in sent             # the text column is
    assert "South" in sent and "−900" in sent
    assert "may be stale" in sent              # empty window explained
