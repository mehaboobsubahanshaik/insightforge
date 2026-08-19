"""R17: passwordless magic-link, per-key API usage, Parquet ingestion."""

import io
import re

from conftest import auth, get_workspace, outbox_bodies, register_and_login, upload_csv


async def test_magic_link_single_use(client):
    await register_and_login(client)
    r = await client.post("/api/v1/auth/magic-link", json={
        "email": "owner@acme.dev", "tenant_slug": "acme"})
    assert r.status_code == 200, r.text
    # no enumeration: unknown email gets the same 200
    r2 = await client.post("/api/v1/auth/magic-link", json={
        "email": "ghost@nowhere.dev", "tenant_slug": "acme"})
    assert r2.status_code == 200 and r2.json() == r.json()
    link_mail = next(b for b in outbox_bodies() if "magic-token=" in b)
    token = re.search(r"magic-token=(\S+)", link_mail).group(1)
    login = await client.post("/api/v1/auth/magic-login", json={
        "token": token, "tenant_slug": "acme"})
    assert login.status_code == 200
    bundle = login.json()
    ws = await client.get("/api/v1/workspaces",
                          headers=auth(bundle))
    assert ws.status_code == 200
    # single use: second redemption dies
    again = await client.post("/api/v1/auth/magic-login", json={
        "token": token, "tenant_slug": "acme"})
    assert again.status_code == 401


async def test_per_key_usage_and_parquet(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="fin",
                          content="region,amount\nSouth,100\n")
    key = (await client.post("/api/v1/api-keys", headers=auth(tok), json={
        "name": "partner-key", "scopes": ["data:read"]})).json()
    kh = {"X-API-Key": key["api_key"]}
    r = await client.post(f"/api/v1/public/datasets/{ds['id']}/query",
                          headers=kh, json={"formula": "sum(amount)"})
    assert r.status_code == 200
    usage = (await client.get("/api/v1/api-keys/usage",
                              headers=auth(tok))).json()["month_to_date"]
    assert usage.get("partner-key") == 1
    # Parquet through the trust pipeline
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({"region": ["South", "North"], "amount": [10, 20]})
    buf = io.BytesIO()
    pq.write_table(table, buf)
    r = await client.post(
        f"/api/v1/datasets/upload-parquet?workspace_id={ws}&name=pq",
        headers=auth(tok),
        files={"file": ("d.parquet", buf.getvalue(),
                        "application/octet-stream")})
    assert r.status_code == 201, r.text
    a = (await client.post(f"/api/v1/datasets/{r.json()['id']}/ask",
                           headers=auth(tok),
                           json={"question": "total amount"})).json()
    assert a["answer"]["value"] == 30
    bad = await client.post(
        f"/api/v1/datasets/upload-parquet?workspace_id={ws}&name=bad",
        headers=auth(tok), files={"file": ("x.parquet", b"nope", "a/b")})
    assert bad.status_code == 422
