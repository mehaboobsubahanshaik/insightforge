"""MVP3 P5: scoped API keys + governed public query endpoints."""

from conftest import auth, get_workspace, register_and_login, upload_csv


async def test_api_key_lifecycle_and_governed_query(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    r = await client.post("/api/v1/api-keys", headers=auth(tok),
                          json={"name": "CI reader"})
    assert r.status_code == 201, r.text
    key = r.json()["api_key"]
    assert key.startswith("ifk_") and "only once" in r.json()["note"]
    listing = (await client.get("/api/v1/api-keys", headers=auth(tok))).json()
    assert "api_key" not in str(listing)  # secret never shown again

    h = {"X-API-Key": key}
    dsl = (await client.get("/api/v1/public/datasets", headers=h)).json()
    assert dsl["datasets"][0]["name"] == "orders"
    r = await client.post(f"/api/v1/public/datasets/{ds['id']}/query",
                          headers=h, json={"formula": "sum(total)",
                                           "group_by": "region"})
    assert r.status_code == 200
    groups = {g["group"]: g["value"] for g in r.json()["groups"]}
    assert round(groups["South"], 2) == 1794.9
    # SQL cannot ride a formula
    r = await client.post(f"/api/v1/public/datasets/{ds['id']}/query",
                          headers=h, json={"formula": "sum(total); DROP TABLE x"})
    assert r.status_code == 422

    # bad key, revoked key, tenant isolation
    assert (await client.get("/api/v1/public/datasets",
                             headers={"X-API-Key": "ifk_bad_key"})).status_code == 401
    kid = listing["keys"][0]["id"]
    await client.delete(f"/api/v1/api-keys/{kid}", headers=auth(tok))
    assert (await client.get("/api/v1/public/datasets",
                             headers=h)).status_code == 401
    tok2 = await register_and_login(client, slug="rival", email="o@rival.dev")
    k2 = (await client.post("/api/v1/api-keys", headers=auth(tok2),
                            json={"name": "spy"})).json()["api_key"]
    r = await client.post(f"/api/v1/public/datasets/{ds['id']}/query",
                          headers={"X-API-Key": k2},
                          json={"formula": "sum(total)"})
    assert r.status_code == 404  # other tenant's dataset invisible
