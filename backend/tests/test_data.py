"""Ingestion trust pipeline, quality engine, semantic measures, RBAC."""

from conftest import auth, get_workspace, register_and_login, upload_csv

DIRTY_CSV = (
    "order_date,region,product,quantity,total\n"
    "2026-06-01,South,Widget A,10,499.00\n"
    "2026-06-02,,Widget B,5,600.00\n"
    "2026-06-02,,Widget B,5,600.00\n"          # exact duplicate -> R002
    "2026-06-03,East,Widget C,six,300.00\n"    # 'six' breaks integer type -> R003
)


async def test_dirty_upload_pipeline(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="dirty", content=DIRTY_CSV)
    types = {c["name"]: c["inferred_type"] for c in ds["schema"]}
    assert types == {"order_date": "date", "region": "text", "product": "text",
                     "quantity": "integer", "total": "number"}
    assert ds["row_count"] == 2 and ds["quarantined_count"] == 2
    assert 0 < ds["quality_score"] < 100
    detail = (await client.get(f"/api/v1/datasets/{ds['id']}", headers=auth(tok))).json()
    rules = {d["rule"]: d for d in detail["dq_results"]}
    assert rules["R001"]["affected"] >= 2   # missing regions
    assert rules["R002"]["affected"] == 1   # one duplicate
    assert rules["R003"]["affected"] == 1   # one type nonconformance
    assert detail["lineage"]["source"] == "upload"
    assert detail["lineage"]["import_id"] == ds["current_import_id"]


async def test_preview_quarantine_toggle(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="dirty", content=DIRTY_CSV)
    clean = (await client.get(f"/api/v1/datasets/{ds['id']}/preview",
                              headers=auth(tok))).json()
    assert len(clean["rows"]) == 2 and clean["quarantine"] == []
    both = (await client.get(
        f"/api/v1/datasets/{ds['id']}/preview?include_quarantined=true",
        headers=auth(tok))).json()
    assert len(both["rows"]) == 4
    reasons = {q["reason"][:4] for q in both["quarantine"]}
    assert reasons == {"R002", "R003"}


async def test_xlsx_upload(client):
    import io

    import openpyxl

    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    wb = openpyxl.Workbook()
    s = wb.active
    s.append(["month", "revenue"])
    for row in (["2026-01", 1000], ["2026-02", 1400], ["2026-03", 900]):
        s.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    r = await client.post(f"/api/v1/datasets/upload?workspace_id={ws}&name=xl",
                          headers=auth(tok),
                          files={"file": ("book.xlsx", buf.getvalue(), "application/xlsx")})
    assert r.status_code == 201 and r.json()["row_count"] == 3


async def test_bad_upload_rejected(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    r = await client.post(f"/api/v1/datasets/upload?workspace_id={ws}&name=bad",
                          headers=auth(tok),
                          files={"file": ("bad.csv", b"only_header\n", "text/csv")})
    assert r.status_code == 422


async def test_dq_history_accumulates(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    hist = (await client.get(f"/api/v1/datasets/{ds['id']}/dq-history",
                             headers=auth(tok))).json()
    assert len(hist) == 1 and hist[0]["score"] == ds["quality_score"]


async def test_measures_validation_execution_and_injection(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    base = f"/api/v1/datasets/{ds['id']}/measures"
    r = await client.post(base, headers=auth(tok), json={
        "name": "AOV", "formula": "sum(total) / count()", "certified": True})
    assert r.status_code == 201
    mid = r.json()["id"]
    # unknown column
    r = await client.post(base, headers=auth(tok),
                          json={"name": "bad", "formula": "sum(profit)"})
    assert r.status_code == 422 and "profit" in r.json()["detail"]
    # injection attempts die in the tokenizer / parser
    for evil in ("sum(total); DROP TABLE users", "sum(total') --", "pg_sleep(10)"):
        r = await client.post(base, headers=auth(tok), json={"name": "evil", "formula": evil})
        assert r.status_code == 422, evil
    r = await client.get(f"{base}/{mid}/result", headers=auth(tok))
    assert abs(r.json()["value"] - 2642.32 / 5) < 0.01
    r = await client.get(f"{base}/{mid}/result?group_by=region", headers=auth(tok))
    groups = {g["group"]: g["value"] for g in r.json()["groups"]}
    assert abs(groups["South"] - 1794.90 / 3) < 0.01


async def test_csv_export_neutralizes_formulas(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    evil = ("name,amount\n=cmd|calc,10\n+SUM(A1),20\nnormal,30\n")
    ds = await upload_csv(client, tok, ws, name="evil", content=evil)
    r = await client.get(f"/api/v1/datasets/{ds['id']}/export.csv", headers=auth(tok))
    text = r.text
    assert "'=cmd|calc" in text and "'+SUM(A1)" in text


async def test_cross_tenant_isolation_404(client):
    tok_a = await register_and_login(client, slug="alpha", email="a@alpha.dev")
    ws_a = await get_workspace(client, tok_a)
    ds = await upload_csv(client, tok_a, ws_a)
    tok_b = await register_and_login(client, slug="beta", email="b@beta.dev")
    r = await client.get(f"/api/v1/datasets/{ds['id']}", headers=auth(tok_b))
    assert r.status_code == 404
    r = await client.get(f"/api/v1/datasets/{ds['id']}/preview", headers=auth(tok_b))
    assert r.status_code == 404
    assert (await client.get("/api/v1/datasets", headers=auth(tok_b))).json() == []


async def test_viewer_rbac_forbidden(client):
    from conftest import token_from_outbox

    tok = await register_and_login(client)
    await client.post("/api/v1/members/invitations", headers=auth(tok),
                      json={"email": "view@acme.dev", "role": "viewer"})
    raw = token_from_outbox(r"token:\n(\S+)")
    viewer = (await client.post("/api/v1/auth/invitations/accept", json={
        "token": raw, "password": "viewer-password-1"})).json()
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    # viewer can read
    r = await client.get("/api/v1/datasets", headers=auth(viewer))
    assert r.status_code == 200 and len(r.json()) == 1
    # but cannot create/manage
    r = await client.post(f"/api/v1/datasets/upload?workspace_id={ws}&name=x",
                          headers=auth(viewer),
                          files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
    assert r.status_code == 403
    r = await client.post(f"/api/v1/datasets/{ds['id']}/measures", headers=auth(viewer),
                          json={"name": "m", "formula": "count()"})
    assert r.status_code == 403
    r = await client.post("/api/v1/members/invitations", headers=auth(viewer),
                          json={"email": "z@acme.dev", "role": "viewer"})
    assert r.status_code == 403
    r = await client.post("/api/v1/workspaces", headers=auth(viewer), json={"name": "W2"})
    assert r.status_code == 403


async def test_last_owner_cannot_be_demoted(client):
    tok = await register_and_login(client)
    members = (await client.get("/api/v1/members", headers=auth(tok))).json()
    r = await client.patch(f"/api/v1/members/{members[0]['membership_id']}",
                           headers=auth(tok), json={"role": "analyst"})
    assert r.status_code == 409


async def test_workspace_lifecycle_and_activity(client):
    tok = await register_and_login(client)
    r = await client.post("/api/v1/workspaces", headers=auth(tok), json={"name": "Finance"})
    assert r.status_code == 201
    wid = r.json()["id"]
    r = await client.patch(f"/api/v1/workspaces/{wid}", headers=auth(tok),
                           json={"archived": True})
    assert r.json()["archived"] is True
    names = [w["name"] for w in
             (await client.get("/api/v1/workspaces", headers=auth(tok))).json()]
    assert "Finance" not in names
    feed = (await client.get("/api/v1/activity", headers=auth(tok))).json()
    actions = {e["action"] for e in feed}
    assert {"tenant.registered", "workspace.created"} <= actions


async def test_notifications_show_my_mail(client):
    tok = await register_and_login(client)
    notes = (await client.get("/api/v1/notifications", headers=auth(tok))).json()
    assert any(n["kind"] == "verify_email" for n in notes)
