"""Self-service BI: widget validation, hydration, publish/version/revert,
templates, saved views, threaded comments, secure sharing, PDF."""

from conftest import auth, get_workspace, register_and_login, token_from_outbox, upload_csv


async def make_dash(client, tok, ds, widgets=None):
    r = await client.post("/api/v1/dashboards", headers=auth(tok), json={
        "workspace_id": ds["workspace_id"], "name": "Sales",
        "widgets": widgets if widgets is not None else [
            {"type": "kpi", "title": "Revenue", "dataset_id": ds["id"],
             "formula": "sum(total)"},
            {"type": "bar", "title": "By region", "dataset_id": ds["id"],
             "formula": "sum(total)", "group_by": "region"}]})
    assert r.status_code == 201, r.text
    return r.json()


async def test_widget_validation_422s(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    cases = [
        [{"type": "gauge", "title": "x", "dataset_id": ds["id"], "formula": "count()"}],
        [{"type": "kpi", "title": "x", "dataset_id": ds["id"], "formula": "sum(nope)"}],
        [{"type": "bar", "title": "x", "dataset_id": ds["id"], "formula": "count()",
          "group_by": "nope"}],
        [{"type": "pivot", "title": "x", "dataset_id": ds["id"], "formula": "count()",
          "group_by": "region", "group_by2": "region"}],
        [{"type": "kpi", "title": "x", "dataset_id": "not-a-uuid", "formula": "count()"}],
    ]
    for widgets in cases:
        r = await client.post("/api/v1/dashboards", headers=auth(tok), json={
            "workspace_id": ws, "name": "bad", "widgets": widgets})
        assert r.status_code == 422, widgets


async def test_hydration_kpi_groups_filters(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    d = await make_dash(client, tok, ds)
    r = await client.get(f"/api/v1/dashboards/{d['id']}/data", headers=auth(tok))
    body = r.json()
    kpi, bar = body["widgets"]
    assert abs(kpi["value"] - 2642.32) < 0.01
    groups = {g["group"]: g["value"] for g in bar["groups"]}
    assert abs(groups["South"] - 1794.90) < 0.01
    assert body["quality_score"] == ds["quality_score"] and body["freshness"]
    # global filter narrows both widgets
    import json

    filters = json.dumps([{"column": "region", "op": "eq", "value": "South"}])
    r = await client.get(f"/api/v1/dashboards/{d['id']}/data?filters={filters}",
                         headers=auth(tok))
    kpi2 = r.json()["widgets"][0]
    assert abs(kpi2["value"] - 1794.90) < 0.01


async def test_pivot_area_table_widgets(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    d = await make_dash(client, tok, ds, widgets=[
        {"type": "pivot", "title": "P", "dataset_id": ds["id"], "formula": "sum(total)",
         "group_by": "region", "group_by2": "product"},
        {"type": "area", "title": "A", "dataset_id": ds["id"], "formula": "sum(total)",
         "group_by": "order_date"},
        {"type": "table", "title": "T", "dataset_id": ds["id"], "limit": 3}])
    body = (await client.get(f"/api/v1/dashboards/{d['id']}/data",
                             headers=auth(tok))).json()
    pv, area, table = body["widgets"]
    assert set(pv["pivot"]["rows"]) == {"South", "North", "East"}
    total = sum(v for row in pv["pivot"]["cells"] for v in row if v is not None)
    assert abs(total - 2642.32) < 0.01
    assert len(area["groups"]) == 5
    assert len(table["rows"]) == 3


async def test_publish_version_snapshot_and_revert(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    d = await make_dash(client, tok, ds)
    r = await client.post(f"/api/v1/dashboards/{d['id']}/publish", headers=auth(tok))
    assert r.json()["published_version"] == 1
    # edit the draft: published must keep serving v1
    r = await client.patch(f"/api/v1/dashboards/{d['id']}", headers=auth(tok), json={
        "widgets": [{"type": "kpi", "title": "Only orders", "dataset_id": ds["id"],
                     "formula": "count()"}]})
    assert r.json()["status"] == "draft"
    pub = (await client.get(f"/api/v1/dashboards/{d['id']}/data?view=published",
                            headers=auth(tok))).json()
    assert len(pub["widgets"]) == 2 and abs(pub["widgets"][0]["value"] - 2642.32) < 0.01
    draft = (await client.get(f"/api/v1/dashboards/{d['id']}/data?view=draft",
                              headers=auth(tok))).json()
    assert len(draft["widgets"]) == 1 and draft["widgets"][0]["value"] == 5
    # publish v2, verify version list, revert to v1
    await client.post(f"/api/v1/dashboards/{d['id']}/publish", headers=auth(tok))
    versions = (await client.get(f"/api/v1/dashboards/{d['id']}/versions",
                                 headers=auth(tok))).json()
    assert [v["version"] for v in versions] == [2, 1]
    r = await client.post(f"/api/v1/dashboards/{d['id']}/revert?version=1",
                          headers=auth(tok))
    assert r.json()["status"] == "draft" and len(r.json()["widgets"]) == 2


async def test_templates_generate_working_dashboards(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    keys = {t["key"] for t in (await client.get("/api/v1/dashboard-templates",
                                                headers=auth(tok))).json()}
    assert keys == {"sales_overview", "finance_cashflow"}
    r = await client.post("/api/v1/dashboard-templates/sales_overview/apply",
                          headers=auth(tok), json={
                              "workspace_id": ws, "dataset_id": ds["id"],
                              "value_column": "total", "category_column": "region",
                              "date_column": "order_date"})
    assert r.status_code == 201
    d = r.json()
    assert len(d["widgets"]) == 5
    body = (await client.get(f"/api/v1/dashboards/{d['id']}/data",
                             headers=auth(tok))).json()
    assert all("error" not in w for w in body["widgets"])


async def test_personal_vs_shared_views(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    d = await make_dash(client, tok, ds)
    base = f"/api/v1/dashboards/{d['id']}/views"
    await client.post(base, headers=auth(tok), json={
        "name": "My south", "filters": [{"column": "region", "op": "eq",
                                         "value": "South"}], "shared": False})
    await client.post(base, headers=auth(tok), json={
        "name": "Team view", "filters": [], "shared": True})
    # second member sees only the shared view
    await client.post("/api/v1/members/invitations", headers=auth(tok),
                      json={"email": "peer@acme.dev", "role": "analyst"})
    raw = token_from_outbox(r"token:\n(\S+)")
    peer = (await client.post("/api/v1/auth/invitations/accept", json={
        "token": raw, "password": "peer-password-12"})).json()
    mine = (await client.get(base, headers=auth(tok))).json()
    theirs = (await client.get(base, headers=auth(peer))).json()
    assert {v["name"] for v in mine} == {"My south", "Team view"}
    assert {v["name"] for v in theirs} == {"Team view"}


async def test_threaded_comments_and_mention_validation(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    d = await make_dash(client, tok, ds)
    base = f"/api/v1/dashboards/{d['id']}/comments"
    r = await client.post(base, headers=auth(tok), json={"body": "Why the June dip?"})
    root = r.json()["id"]
    r = await client.post(base, headers=auth(tok), json={
        "body": "Seasonal — see the filter", "parent_id": root})
    assert r.status_code == 201 and r.json()["parent_id"] == root
    # mentioning a non-member is rejected
    r = await client.post(base, headers=auth(tok), json={
        "body": "cc @stranger@other.dev", "mentions": ["stranger@other.dev"]})
    assert r.status_code == 422
    # mentioning a member emails them
    r = await client.post(base, headers=auth(tok), json={
        "body": "ping @owner@acme.dev", "mentions": ["owner@acme.dev"]})
    assert r.status_code == 201
    comments = (await client.get(base, headers=auth(tok))).json()
    assert len(comments) == 3
    assert any(c["parent_id"] == root for c in comments)


async def test_share_link_lifecycle_and_draft_never_leaks(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    d = await make_dash(client, tok, ds)
    # sharing an unpublished dashboard is refused
    r = await client.post(f"/api/v1/dashboards/{d['id']}/share", headers=auth(tok),
                          json={"expires_in_hours": 24})
    assert r.status_code == 422
    await client.post(f"/api/v1/dashboards/{d['id']}/publish", headers=auth(tok))
    r = await client.post(f"/api/v1/dashboards/{d['id']}/share", headers=auth(tok),
                          json={"expires_in_hours": 24})
    share = r.json()
    # public endpoint needs no auth and serves the published snapshot
    r = await client.get(f"/api/v1/public/dashboards/{share['token']}")
    assert r.status_code == 200
    pub = r.json()
    assert pub["read_only"] is True and len(pub["widgets"]) == 2
    # edit the draft with a secret title: the public link must NOT show it
    await client.patch(f"/api/v1/dashboards/{d['id']}", headers=auth(tok), json={
        "widgets": [{"type": "kpi", "title": "SECRET DRAFT", "dataset_id": ds["id"],
                     "formula": "count()"}]})
    pub = (await client.get(f"/api/v1/public/dashboards/{share['token']}")).json()
    assert all(w["title"] != "SECRET DRAFT" for w in pub["widgets"])
    # revoke kills the link; garbage tokens are 404 too
    await client.post(f"/api/v1/shares/{share['share_id']}/revoke", headers=auth(tok))
    assert (await client.get(f"/api/v1/public/dashboards/{share['token']}")).status_code == 404
    assert (await client.get("/api/v1/public/dashboards/garbage")).status_code == 404


async def test_pdf_export(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    d = await make_dash(client, tok, ds)
    # unicode punctuation must not 500 the latin-1 core-font renderer
    r = await client.patch(f"/api/v1/dashboards/{d['id']}", headers=auth(tok),
                           json={"name": "Q3 — revenue × region"})
    assert r.status_code == 200
    r = await client.get(f"/api/v1/dashboards/{d['id']}/export.pdf", headers=auth(tok))
    assert r.status_code == 404  # not yet published
    r = await client.get(f"/api/v1/dashboards/{d['id']}/export.pdf?view=draft",
                         headers=auth(tok))
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
