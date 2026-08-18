"""MVP5 G6 capstone: the enterprise journey end-to-end — provision via
SCIM, govern the data, certify through approval, and prove the governed
answer respects every layer at once."""

from conftest import auth, get_workspace, register_and_login, upload_csv


async def test_enterprise_journey(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="hr",
                          content="order_date,region,amount,salary\n"
                                  "2026-08-01,South,100,900\n"
                                  "2026-08-02,North,50,800\n")
    # SCIM provisions a member; ABAC attribute set
    scim = (await client.post("/api/v1/enterprise/scim/token",
                              headers=auth(tok))).json()["scim_token"]
    uid = (await client.post("/api/v1/enterprise/scim/v2/Users",
                             headers={"Authorization": f"Bearer {scim}"},
                             json={"userName": "ana@acme.dev"})).json()["id"]
    await client.put("/api/v1/enterprise/members/attributes",
                     headers=auth(tok),
                     json={"user_id": uid,
                           "attributes": {"department": "sales"}})
    # governance: classify + restrict + row policy
    await client.put(f"/api/v1/datasets/{ds['id']}/governance",
                     headers=auth(tok), json={
        "classification": {"salary": "confidential"},
        "column_policy": {"salary": ["admin"]},
        "row_policies": [{"match": {"role": "tenant_owner"},
                          "filters": [{"column": "region", "op": "eq",
                                       "value": "South"}]}]})
    # certification only via approval
    a = (await client.post("/api/v1/catalog/approvals", headers=auth(tok),
                           json={"kind": "certify_dataset",
                                 "subject_id": ds["id"]})).json()
    await client.post(f"/api/v1/catalog/approvals/{a['id']}/decide",
                      headers=auth(tok), json={"decision": "approve"})
    cat = (await client.get("/api/v1/catalog", headers=auth(tok))).json()
    row = cat["datasets"][0]
    assert row["certified"] and row["classification"]["salary"] == "confidential"
    # the governed answer: row policy applied, certified, audited
    ans = (await client.post(f"/api/v1/datasets/{ds['id']}/ask",
                             headers=auth(tok),
                             json={"question": "total amount"})).json()
    assert ans["answer"]["value"] == 100  # South only — policy held
    # export the evidence trail an auditor would ask for
    exp = (await client.get("/api/v1/enterprise/audit/export",
                            headers=auth(tok))).text
    for needle in ("scim.provision", "abac.attributes", "governance.set",
                   "approval.approved", "ai.question"):
        assert needle in exp
