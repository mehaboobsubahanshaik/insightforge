"""Scheduler outcomes: report delivery, alert fire/recover, failure backoff."""

import uuid

import asyncpg
from conftest import ADMIN_DSN, auth, get_workspace, outbox_bodies, register_and_login, upload_csv
from test_connectors import make_pg_connection


async def _rewind(table: str, column: str):
    conn = await asyncpg.connect(ADMIN_DSN)
    await conn.execute(f"UPDATE {table} SET {column} = now() - interval '1 minute'")
    await conn.close()


async def test_scheduled_report_sends_pdf_and_bills(client):
    from insightforge_api.scheduler import run_due_reports_once

    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    r = await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "Weekly", "widgets": [
            {"type": "kpi", "title": "Rev", "dataset_id": ds["id"],
             "formula": "sum(total)"}]})
    d = r.json()
    # requires publish first
    r = await client.post(f"/api/v1/dashboards/{d['id']}/report-schedules",
                          headers=auth(tok),
                          json={"recipients": ["boss@acme.dev"]})
    assert r.status_code == 422
    await client.post(f"/api/v1/dashboards/{d['id']}/publish", headers=auth(tok))
    r = await client.post(f"/api/v1/dashboards/{d['id']}/report-schedules",
                          headers=auth(tok),
                          json={"recipients": ["boss@acme.dev"],
                                "interval_minutes": 1440})
    assert r.status_code == 201
    await _rewind("report_schedules", "next_run_at")
    assert await run_due_reports_once() == 1
    assert await run_due_reports_once() == 0  # not due again
    mails = [b for b in outbox_bodies() if "Scheduled report" in b]
    assert mails and "attachment:" in mails[-1] and ".pdf" in mails[-1]
    summary = (await client.get("/api/v1/billing/summary", headers=auth(tok))).json()
    assert any(e["kind"] == "report.sent" for e in summary["billing_events"])
    sched = (await client.get(f"/api/v1/dashboards/{d['id']}/report-schedules",
                              headers=auth(tok))).json()[0]
    assert sched["last_status"] == "sent"


async def test_report_quota_on_free_plan(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    for i in range(2):
        r = await client.post("/api/v1/dashboards", headers=auth(tok), json={
            "workspace_id": ws, "name": f"D{i}", "widgets": [
                {"type": "kpi", "title": "n", "dataset_id": ds["id"],
                 "formula": "count()"}]})
        did = r.json()["id"]
        await client.post(f"/api/v1/dashboards/{did}/publish", headers=auth(tok))
        r = await client.post(f"/api/v1/dashboards/{did}/report-schedules",
                              headers=auth(tok),
                              json={"recipients": ["a@b.dev"]})
        if i == 0:
            assert r.status_code == 201
        else:
            assert r.status_code == 403  # free plan: 1 report schedule


async def test_alert_fire_once_recover_refire(client):
    from insightforge_api.scheduler import run_due_alerts_once

    tok = await register_and_login(client)
    await client.post("/api/v1/billing/plan", headers=auth(tok),
                      json={"plan_code": "growth"})  # 60-min cadence needs growth
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    r = await client.post(f"/api/v1/datasets/{ds['id']}/alerts", headers=auth(tok), json={
        "name": "Revenue high", "formula": "sum(total)", "operator": "gt",
        "threshold": 1000, "interval_minutes": 60,
        "recipients": ["ops@acme.dev"]})
    assert r.status_code == 201, r.text
    await _rewind("alert_rules", "next_check_at")
    assert await run_due_alerts_once() == 1  # 2642.32 > 1000 -> fires
    await _rewind("alert_rules", "next_check_at")
    assert await run_due_alerts_once() == 0  # still breached -> no spam
    # raise the threshold above the value: state recovers silently
    conn = await asyncpg.connect(ADMIN_DSN)
    await conn.execute("UPDATE alert_rules SET threshold = 99999")
    await conn.close()
    await _rewind("alert_rules", "next_check_at")
    assert await run_due_alerts_once() == 0
    # lower it again -> re-fires exactly once
    conn = await asyncpg.connect(ADMIN_DSN)
    await conn.execute("UPDATE alert_rules SET threshold = 1000")
    await conn.close()
    await _rewind("alert_rules", "next_check_at")
    assert await run_due_alerts_once() == 1
    alerts = [b for b in outbox_bodies() if "InsightForge alert" in b]
    assert len(alerts) == 2
    listed = (await client.get(f"/api/v1/datasets/{ds['id']}/alerts",
                               headers=auth(tok))).json()
    assert listed[0]["last_state"] == "fired"


async def test_scheduled_sync_failure_backoff_and_heal(client):
    from insightforge_api.scheduler import run_due_schedules_once

    tok = await register_and_login(client)
    conn_info = await make_pg_connection(client, tok)
    await client.post(f"/api/v1/connections/{conn_info['id']}/sync", headers=auth(tok),
                      json={"mode": "incremental"})
    await client.put(f"/api/v1/connections/{conn_info['id']}/schedule", headers=auth(tok),
                     json={"interval_minutes": 1440})
    # sabotage: point the connection at a database that does not exist
    admin = await asyncpg.connect(ADMIN_DSN)
    await admin.execute(
        "UPDATE connections SET config = jsonb_set(config, '{database}', "
        "'\"no_such_db\"') WHERE id = $1", uuid.UUID(conn_info["id"]))
    await admin.close()
    await _rewind("sync_schedules", "next_run_at")
    assert await run_due_schedules_once() == 1
    conns = (await client.get("/api/v1/connections", headers=auth(tok))).json()
    assert conns[0]["consecutive_failures"] == 1 and conns[0]["health"] == "degraded"
    runs = (await client.get(f"/api/v1/connections/{conn_info['id']}/runs",
                             headers=auth(tok))).json()
    assert runs[0]["status"] == "failed" and runs[0]["trigger"] == "scheduled"
    # heal the config: next scheduled run succeeds and resets failures
    admin = await asyncpg.connect(ADMIN_DSN)
    await admin.execute(
        "UPDATE connections SET config = jsonb_set(config, '{database}', "
        "'\"demo_shop\"') WHERE id = $1", uuid.UUID(conn_info["id"]))
    await admin.close()
    await _rewind("sync_schedules", "next_run_at")
    assert await run_due_schedules_once() == 1
    conns = (await client.get("/api/v1/connections", headers=auth(tok))).json()
    assert conns[0]["consecutive_failures"] == 0 and conns[0]["health"] == "healthy"
