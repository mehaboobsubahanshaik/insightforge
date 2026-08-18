"""R1: security headers + PII detection suggestions."""

from conftest import auth, get_workspace, register_and_login, upload_csv


async def test_security_headers_on_api(client):
    r = await client.get("/api/v1/platform/status")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


async def test_pii_scan_suggests_never_applies(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    csv = ("name,email,notes\n"
           "A,a@x.io,hello\nB,b@y.dev,world\nC,c@z.com,ok\n")
    ds = await upload_csv(client, tok, ws, name="people", content=csv)
    r = (await client.post(f"/api/v1/datasets/{ds['id']}/pii-scan",
                           headers=auth(tok))).json()
    assert r["detected"] == {"email": "email"}
    assert r["suggested_governance"]["classification"] == {"email": "pii"}
    gov = (await client.get(f"/api/v1/datasets/{ds['id']}/governance",
                            headers=auth(tok))).json()["governance"]
    assert "classification" not in gov  # nothing auto-applied
