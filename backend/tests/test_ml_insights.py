"""API-level tests for /datasets/{id}/insights (the ml/ package wired in)."""

from conftest import auth, get_workspace, register_and_login, upload_csv

TREND_CSV = "day,revenue\n" + "\n".join(
    f"2026-06-{d:02d},{1000 + 50 * d}" for d in range(1, 15))

SPIKE_CSV = "day,revenue\n" + "\n".join(
    f"2026-06-{d:02d},{9000 if d == 8 else 1000}" for d in range(1, 15))


async def test_insights_forecast_continues_trend(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="trend", content=TREND_CSV)
    r = await client.get(
        f"/api/v1/datasets/{ds['id']}/insights"
        f"?value_column=revenue&date_column=day&horizon=3", headers=auth(tok))
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["series"]) == 14 and d["series"][0]["value"] == 1050
    f = d["forecast"]
    assert f["method"] == "holt-linear"
    # series ends at 1700 rising 50/day -> next ≈ 1750
    assert abs(f["points"][0]["forecast"] - 1750) < 25
    assert f["points"][0]["lo"] <= f["points"][0]["forecast"] <= f["points"][0]["hi"]
    assert d["anomalies"]["anomalies"] == []
    assert d["quality_score"] is not None and d["freshness"]


async def test_insights_flags_spike_day(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="spike", content=SPIKE_CSV)
    r = await client.get(
        f"/api/v1/datasets/{ds['id']}/insights"
        f"?value_column=revenue&date_column=day", headers=auth(tok))
    d = r.json()
    hits = d["anomalies"]["anomalies"]
    assert len(hits) == 1
    assert hits[0]["label"] == "2026-06-08" and hits[0]["direction"] == "spike"


async def test_insights_validates_columns(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="v", content=TREND_CSV)
    r = await client.get(
        f"/api/v1/datasets/{ds['id']}/insights"
        f"?value_column=day&date_column=day", headers=auth(tok))
    assert r.status_code == 422
    r = await client.get(
        f"/api/v1/datasets/{ds['id']}/insights"
        f"?value_column=revenue&date_column=nope", headers=auth(tok))
    assert r.status_code == 422


async def test_insights_tenant_isolated(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="mine", content=TREND_CSV)
    tok2 = await register_and_login(client, slug="rival", email="rival@rival.dev")
    r = await client.get(
        f"/api/v1/datasets/{ds['id']}/insights"
        f"?value_column=revenue&date_column=day", headers=auth(tok2))
    assert r.status_code == 404
