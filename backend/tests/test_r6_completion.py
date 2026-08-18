"""R6: role catalog, alert ack/quiet-hours/escalation, data-issue
reporting."""

from datetime import datetime, timedelta, timezone

import asyncpg
from conftest import ADMIN_DSN, auth, get_workspace, outbox_bodies, register_and_login, upload_csv

from insightforge_api.roles import ROLES, role_allows
from insightforge_api.scheduler import _in_quiet_hours, run_escalations_once


def test_role_catalog_scopes():
    assert len(ROLES) == 9
    assert role_allows("security_auditor", "audit:read")
    assert not role_allows("security_auditor", "dataset:create")
    assert role_allows("billing_admin", "usage:read")
    assert not role_allows("billing_admin", "dataset:read")
    assert role_allows("executive_viewer", "dashboard:read")
    assert not role_allows("executive_viewer", "dashboard:create")
    assert role_allows("data_admin", "connection:manage")
    assert not role_allows("bi_developer", "connection:manage")


def test_quiet_hours_window_math():
    lc = {"quiet_start": "22:00", "quiet_end": "06:00"}
    assert _in_quiet_hours(lc, "23:30") and _in_quiet_hours(lc, "05:59")
    assert not _in_quiet_hours(lc, "12:00")
    assert not _in_quiet_hours({}, "23:30")


async def test_ack_escalation_and_issue_reporting(client):
    tok = await register_and_login(client)
    await client.post("/api/v1/billing/plan", headers=auth(tok),
                      json={"plan_code": "growth"})
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    r = await client.post(f"/api/v1/datasets/{ds['id']}/alerts",
                          headers=auth(tok), json={
        "name": "Rev high", "formula": "sum(total)", "operator": "gt",
        "threshold": 1, "interval_minutes": 60,
        "recipients": ["ops@acme.dev"]})
    rule_id = r.json()["id"]
    r = await client.put(
        f"/api/v1/datasets/{ds['id']}/alerts/{rule_id}/lifecycle",
        headers=auth(tok), json={"escalate_after_minutes": 30,
                                 "escalate_to": "boss@acme.dev"})
    assert r.json()["lifecycle"]["escalate_to"] == "boss@acme.dev"
    # plant an old unacked firing -> escalation email fires exactly once
    conn = await asyncpg.connect(ADMIN_DSN)
    old = datetime.now(timezone.utc) - timedelta(minutes=90)
    await conn.execute(
        "INSERT INTO alert_events (id, tenant_id, rule_id, value, message, "
        "fired_at) SELECT gen_random_uuid(), tenant_id, id, 99, 'fired', $1 "
        "FROM alert_rules WHERE id = $2", old, rule_id)
    await conn.close()
    assert await run_escalations_once() == 1
    assert any("ESCALATION" in b and "not been acknowledged" in b
               for b in outbox_bodies())
    assert await run_escalations_once() == 0  # once only
    # ack stops future escalation and is audited
    r = await client.post(f"/api/v1/datasets/{ds['id']}/alerts/{rule_id}/ack",
                          headers=auth(tok))
    assert "acked_at" in r.json()
    # data-issue reporting -> approvals queue
    r = await client.post(f"/api/v1/datasets/{ds['id']}/issues",
                          headers=auth(tok),
                          json={"description": "March totals look double-"
                                               "counted vs bank statement"})
    assert r.status_code == 201
    aps = (await client.get("/api/v1/catalog/approvals",
                            headers=auth(tok))).json()["approvals"]
    issue = next(a for a in aps if a["kind"] == "data_issue")
    assert "double-counted" in issue["note"]
