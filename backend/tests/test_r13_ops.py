"""R13: legal hold, feature flags, cost report, credential rotation,
drift report, outlier advisory, alert ownership."""

from datetime import date, timedelta

from conftest import auth, get_workspace, register_and_login, upload_csv


async def test_legal_hold_blocks_retention(client):
    from insightforge_api.scheduler import run_lifecycle_once

    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    old = (date.today() - timedelta(days=400)).isoformat()
    ds = await upload_csv(client, tok, ws, name="aging",
                          content=f"order_date,amount\n{old},999\n")
    await client.put(f"/api/v1/datasets/{ds['id']}/governance",
                     headers=auth(tok),
                     json={"retention": {"column": "order_date",
                                         "days": 365}})
    r = await client.put("/api/v1/enterprise/legal-hold", headers=auth(tok),
                         json={"enabled": True,
                               "reason": "Litigation matter 2026-114 "
                                         "document preservation"})
    assert r.status_code == 200
    assert (await client.put("/api/v1/enterprise/legal-hold",
                             headers=auth(tok),
                             json={"enabled": True,
                                   "reason": "x"})).status_code == 422
    await run_lifecycle_once()
    a = (await client.post(f"/api/v1/datasets/{ds['id']}/ask",
                           headers=auth(tok),
                           json={"question": "total amount"})).json()
    assert a["answer"]["value"] == 999  # hold beat retention
    # release hold -> purge proceeds
    await client.put("/api/v1/enterprise/legal-hold", headers=auth(tok),
                     json={"enabled": False, "reason": "matter closed"})
    await run_lifecycle_once()
    a = (await client.post(f"/api/v1/datasets/{ds['id']}/ask",
                           headers=auth(tok),
                           json={"question": "total amount"})).json()
    assert not a["answered"] or (a["answer"]["value"] or 0) == 0


async def test_flags_cost_drift_outliers_owner(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    # flags
    f = (await client.get("/api/v1/enterprise/flags",
                          headers=auth(tok))).json()["flags"]
    assert f["ai_summaries"] is True
    r = (await client.put("/api/v1/enterprise/flags", headers=auth(tok),
                          json={"flag": "voice_ask",
                                "enabled": False})).json()
    assert r["flags"]["voice_ask"] is False
    assert (await client.put("/api/v1/enterprise/flags", headers=auth(tok),
                             json={"flag": "time_travel",
                                   "enabled": True})).status_code == 422
    # cost report picks up metered AI usage
    ds = await upload_csv(client, tok, ws, name="fin",
                          content="order_date,amount\n2026-08-01,100\n")
    await client.post("/api/v1/ai/summarize", headers=auth(tok),
                      json={"dataset_id": ds["id"]})
    cost = (await client.get("/api/v1/enterprise/cost-report",
                             headers=auth(tok))).json()["month_to_date"]
    assert cost.get("ai.tokens", 0) >= 1
    # drift report: governance references a ghost column
    await client.put(f"/api/v1/datasets/{ds['id']}/governance",
                     headers=auth(tok),
                     json={"column_policy": {"ghost_col": ["admin"]}})
    drift = (await client.get(f"/api/v1/datasets/{ds['id']}/drift-report",
                              headers=auth(tok))).json()
    assert drift["drifted"] is True
    assert any(f["kind"] == "governance.column_policy"
               for f in drift["findings"])
    # outlier advisory in suggestions
    vals = "\n".join(["region,amount"]
                     + [f"S,{100 + i}" for i in range(20)] + ["S,99999"])
    ods = await upload_csv(client, tok, ws, name="spiky", content=vals + "\n")
    sugg = (await client.get(f"/api/v1/datasets/{ods['id']}/prep-suggestions",
                             headers=auth(tok))).json()
    hits = [s for s in sugg["suggestions"]
            if s["op"] == "review_outliers"]
    assert hits and hits[0]["advisory"] is True
    assert "never auto-removed" in hits[0]["effect"]
    # alert ownership stored on lifecycle
    r = await client.post(f"/api/v1/datasets/{ds['id']}/alerts",
                          headers=auth(tok), json={
        "name": "A", "formula": "sum(amount)", "operator": "gt",
        "threshold": 1, "interval_minutes": 1440,
        "recipients": ["ops@acme.dev"]})
    rid = r.json()["id"]
    r = (await client.put(
        f"/api/v1/datasets/{ds['id']}/alerts/{rid}/lifecycle",
        headers=auth(tok),
        json={"owner_email": "daniel@acme.dev"})).json()
    assert r["lifecycle"]["owner_email"] == "daniel@acme.dev"
