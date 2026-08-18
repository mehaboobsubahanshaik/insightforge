"""R7: union, favorites, embedded builder, relative-change +
freshness/DQ alerts, seasonality, rate limit + idempotency."""

from datetime import date, timedelta

from conftest import auth, get_workspace, register_and_login, upload_csv
from insightforge_ml.forecast import holt_winters_additive


def test_holt_winters_seasonality():
    season = [10, 20, 30, 40]
    values = season * 4  # 4 perfect seasons of length 4
    f = holt_winters_additive(values, 4, horizon=4)
    got = [p["forecast"] for p in f["points"]]
    for g, want in zip(got, season):
        assert abs(g - want) < 3  # pattern learned
    assert f["method"] == "holt-winters-additive"
    try:
        holt_winters_additive([1, 2, 3], 4)
        raise AssertionError("should refuse thin data")
    except ValueError as e:
        assert "2 full seasons" in str(e)


async def test_union_and_favorites(client):
    tok = await register_and_login(client)
    await client.post("/api/v1/billing/plan", headers=auth(tok),
                      json={"plan_code": "growth"})
    ws = await get_workspace(client, tok)
    a = await upload_csv(client, tok, ws, name="q1",
                         content="region,amount\nSouth,10\n")
    b = await upload_csv(client, tok, ws, name="q2",
                         content="region,amount,channel\nNorth,20,web\n")
    u = (await client.post("/api/v1/datasets/union", headers=auth(tok),
                           json={"left_id": a["id"], "right_id": b["id"],
                                 "name": "h1"})).json()
    assert u["row_count"] == 2
    ans = (await client.post(f"/api/v1/datasets/{u['id']}/ask",
                             headers=auth(tok),
                             json={"question": "total amount"})).json()
    assert ans["answer"]["value"] == 30
    d = (await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "Fav", "widgets": []})).json()
    r = (await client.post(f"/api/v1/me/favorites/{d['id']}",
                           headers=auth(tok))).json()
    assert r["favorite"] is True
    favs = (await client.get("/api/v1/me/favorites",
                             headers=auth(tok))).json()["favorites"]
    assert d["id"] in favs
    r = (await client.post(f"/api/v1/me/favorites/{d['id']}",
                           headers=auth(tok))).json()
    assert r["favorite"] is False  # toggle off


async def test_embedded_builder_edit_scope(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="fin",
                          content="customer,amount\nc1,100\n")
    d = (await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "Build me", "widgets": [
            {"type": "kpi", "title": "Seed", "dataset_id": ds["id"],
             "formula": "sum(amount)"}]})).json()
    await client.post(f"/api/v1/dashboards/{d['id']}/publish",
                      headers=auth(tok))

    async def mint(scope):
        r = await client.post("/api/v1/embed/tokens", headers=auth(tok),
                              json={"dashboard_id": d["id"],
                                    "customer_label": "C", "scope": scope,
                                    "filters": [{"column": "customer",
                                                 "op": "eq", "value": "c1"}]})
        return r.json()["token"]

    view_t, edit_t = await mint("view"), await mint("edit")
    widgets = [{"type": "kpi", "title": "Spend", "dataset_id": ds["id"],
                "formula": "sum(amount)"}]
    r = await client.put(f"/api/v1/embed/{view_t}/widgets",
                         json={"widgets": widgets})
    assert r.status_code == 403  # view tokens cannot build
    r = await client.put(f"/api/v1/embed/{edit_t}/widgets",
                         json={"widgets": widgets})
    assert r.status_code == 200 and r.json()["draft_widgets"] == 1
    # foreign dataset refused
    r = await client.put(f"/api/v1/embed/{edit_t}/widgets", json={
        "widgets": [{"type": "kpi",
                     "dataset_id": "00000000-0000-0000-0000-000000000000"}]})
    assert r.status_code == 422


async def test_relative_change_and_health_alerts(client):
    import asyncpg
    from conftest import ADMIN_DSN

    from insightforge_api.scheduler import (
        run_dataset_health_once,
        run_due_alerts_once,
    )

    tok = await register_and_login(client)
    await client.post("/api/v1/billing/plan", headers=auth(tok),
                      json={"plan_code": "growth"})
    ws = await get_workspace(client, tok)
    t = date.today()
    csv = ("order_date,amount\n"
           f"{(t - timedelta(days=35)).isoformat()},100\n"
           f"{(t - timedelta(days=5)).isoformat()},200\n")  # +100% PoP
    ds = await upload_csv(client, tok, ws, name="rev", content=csv)
    r = await client.post(f"/api/v1/datasets/{ds['id']}/alerts",
                          headers=auth(tok), json={
        "name": "Rev swing", "formula": "sum(amount)", "operator": "gt",
        "threshold": 10**12, "interval_minutes": 60,
        "recipients": ["ops@acme.dev"]})
    rid = r.json()["id"]
    await client.put(f"/api/v1/datasets/{ds['id']}/alerts/{rid}/lifecycle",
                     headers=auth(tok),
                     json={})  # keep lifecycle endpoint happy baseline
    conn = await asyncpg.connect(ADMIN_DSN)
    await conn.execute(
        "UPDATE alert_rules SET lifecycle = lifecycle || "
        "'{\"relative_pct\": 50, \"date_column\": \"order_date\"}', "
        "next_check_at = now() - interval '1 hour' WHERE id = $1", rid)
    await conn.close()
    assert await run_due_alerts_once() == 1  # 100% change >= 50% -> fires
    # freshness + quality health alerts
    await client.put(f"/api/v1/datasets/{ds['id']}/governance",
                     headers=auth(tok),
                     json={"classification": {}})
    conn = await asyncpg.connect(ADMIN_DSN)
    await conn.execute(
        "UPDATE datasets SET governance = governance || "
        "'{\"alerts\": {\"freshness_hours\": 1, \"min_quality\": 101}}', "
        "ingested_at = now() - interval '48 hours' WHERE id = $1", ds["id"])
    await conn.close()
    assert await run_dataset_health_once() == 1
    assert await run_dataset_health_once() == 0  # once per day


async def test_rate_limit_and_idempotency(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1000000")
    tok = await register_and_login(client)
    ws_payload = {"name": "Once"}
    h = {**auth(tok), "Idempotency-Key": "abc-123"}
    r1 = await client.post("/api/v1/workspaces", headers=h, json=ws_payload)
    r2 = await client.post("/api/v1/workspaces", headers=h, json=ws_payload)
    assert r1.status_code == 201
    assert r2.headers.get("idempotency-replayed") == "true"
    assert r1.json()["id"] == r2.json()["id"]  # same resource, not a dup
    listing = (await client.get("/api/v1/workspaces",
                                headers=auth(tok))).json()
    assert sum(1 for w in listing if w["name"] == "Once") == 1
    # rate limiter: tiny window -> 429
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "3")
    codes = []
    for _ in range(5):
        codes.append((await client.get("/api/v1/workspaces",
                                       headers=auth(tok))).status_code)
    assert 429 in codes
