"""MVP5 G3: catalog, glossary, lineage, impact, approval-driven
certification."""

from conftest import auth, get_workspace, register_and_login, upload_csv


async def test_catalog_glossary_lineage_impact_approvals(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    d = (await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ws, "name": "Rev", "widgets": [
            {"type": "kpi", "dataset_id": ds["id"],
             "formula": "sum(total)"}]})).json()
    await client.post(f"/api/v1/dashboards/{d['id']}/publish", headers=auth(tok))
    # glossary term linked to a column
    r = await client.post("/api/v1/catalog/glossary", headers=auth(tok), json={
        "term": "Revenue", "definition": "Sum of order totals, net of tax.",
        "steward": "owner@acme.dev",
        "links": [{"dataset_id": ds["id"], "column": "total"}]})
    assert r.status_code == 201
    # duplicate term -> conflict
    r = await client.post("/api/v1/catalog/glossary", headers=auth(tok), json={
        "term": "Revenue", "definition": "dup"})
    assert r.status_code == 409
    terms = (await client.get("/api/v1/catalog/glossary",
                              headers=auth(tok))).json()["terms"]
    assert terms[0]["links"][0]["column"] == "total"
    # catalog aggregates
    cat = (await client.get("/api/v1/catalog", headers=auth(tok))).json()
    row = cat["datasets"][0]
    assert row["glossary_covered"] and row["used_by_dashboards"] == 1
    assert row["certified"] is False
    # full lineage
    lin = (await client.get(f"/api/v1/catalog/lineage/{ds['id']}",
                            headers=auth(tok))).json()
    assert lin["upstream"]["source"] in ("upload", "csv")
    assert lin["downstream"]["dashboards"][0]["name"] == "Rev"
    # impact: published dashboard -> high severity
    imp = (await client.get(f"/api/v1/catalog/impact/{ds['id']}",
                            headers=auth(tok))).json()
    assert imp["severity"] == "high" and "1 dashboard(s)" in imp["summary"]
    # approval workflow certifies the dataset
    a = (await client.post("/api/v1/catalog/approvals", headers=auth(tok),
                           json={"kind": "certify_dataset",
                                 "subject_id": ds["id"],
                                 "note": "Q3 sign-off"})).json()
    r = await client.post(f"/api/v1/catalog/approvals/{a['id']}/decide",
                          headers=auth(tok), json={"decision": "approve"})
    assert r.json()["status"] == "approved"
    cat = (await client.get("/api/v1/catalog", headers=auth(tok))).json()
    assert cat["datasets"][0]["certified"] is True
    # rejected approvals change nothing; double-decide 404s
    r = await client.post(f"/api/v1/catalog/approvals/{a['id']}/decide",
                          headers=auth(tok), json={"decision": "reject"})
    assert r.status_code == 404
