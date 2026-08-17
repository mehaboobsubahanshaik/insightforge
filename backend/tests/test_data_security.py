"""MVP5 G2: column-level security, row policies, classification,
retention, CMK config."""

from datetime import date, timedelta

from conftest import auth, get_workspace, register_and_login, upload_csv

CSV = ("order_date,region,amount,salary\n"
       "2026-08-01,South,100,900\n2026-08-02,North,50,800\n")



async def test_column_and_row_policies_enforced(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="hr", content=CSV)
    r = await client.put(f"/api/v1/datasets/{ds['id']}/governance",
                         headers=auth(tok), json={
        "classification": {"salary": "confidential"},
        "column_policy": {"salary": ["admin"]},
        "row_policies": [{"match": {"role": "tenant_owner"},
                          "filters": [{"column": "region", "op": "eq",
                                       "value": "South"}]}]})
    assert r.status_code == 200
    got = (await client.get(f"/api/v1/datasets/{ds['id']}/governance",
                            headers=auth(tok))).json()["governance"]
    assert got["classification"]["salary"] == "confidential"
    # column policy: owner bypasses (owners are never column-blocked)
    a = (await client.post(f"/api/v1/datasets/{ds['id']}/ask",
                           headers=auth(tok),
                           json={"question": "total salary"})).json()
    assert a["answered"]
    # row policy matched the owner's role: only South rows counted
    a = (await client.post(f"/api/v1/datasets/{ds['id']}/ask",
                           headers=auth(tok),
                           json={"question": "total amount"})).json()
    assert a["answer"]["value"] == 100  # North's 50 filtered out
    # bad governance keys rejected
    r = await client.put(f"/api/v1/datasets/{ds['id']}/governance",
                         headers=auth(tok), json={"nonsense": 1})
    assert r.status_code == 422


async def test_retention_and_cmk(client):
    from insightforge_api.scheduler import run_lifecycle_once

    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    old = (date.today() - timedelta(days=400)).isoformat()
    new = (date.today() - timedelta(days=5)).isoformat()
    csv = f"order_date,region,amount\n{old},South,999\n{new},South,100\n"
    ds = await upload_csv(client, tok, ws, name="aging", content=csv)
    r = await client.put(f"/api/v1/datasets/{ds['id']}/governance",
                         headers=auth(tok),
                         json={"retention": {"column": "order_date",
                                             "days": 365}})
    assert r.status_code == 200
    assert await run_lifecycle_once() >= 1  # purge ran
    a = (await client.post(f"/api/v1/datasets/{ds['id']}/ask",
                           headers=auth(tok),
                           json={"question": "total amount"})).json()
    assert a["answer"]["value"] == 100  # 400-day-old row purged
    # retention validation: non-date column refused
    r = await client.put(f"/api/v1/datasets/{ds['id']}/governance",
                         headers=auth(tok),
                         json={"retention": {"column": "region", "days": 30}})
    assert r.status_code == 422
    # CMK config
    r = await client.put("/api/v1/enterprise/cmk", headers=auth(tok), json={
        "provider": "aws-kms",
        "key_id": "arn:aws:kms:eu-west-1:123:key/abc"})
    assert r.json()["cmk"]["status"] == "configured"
    r = await client.put("/api/v1/enterprise/cmk", headers=auth(tok),
                         json={"provider": "my-usb-stick", "key_id": "x"})
    assert r.status_code == 422
