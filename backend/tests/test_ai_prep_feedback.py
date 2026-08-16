"""MVP3 chapter 3: prep suggestions from real evidence, feedback capture
with tenant isolation, and the AI cost-control quota."""

import asyncpg
import pytest
from conftest import ADMIN_DSN, auth, get_workspace, register_and_login, upload_csv

pytestmark = pytest.mark.ai_eval

MESSY = (
    "order_date,region,amount\n"
    "2026-06-01,  South ,Rs.100\n"
    "2026-06-02,south,Rs.200\n"
    "2026-06-03,North,Rs.50\n"
    "2026-06-04,,Rs.75\n"
    "2026-06-05, North,Rs.125\n"
)


async def test_prep_suggestions_from_evidence_and_apply_improves(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="messy", content=MESSY)
    r = await client.get(f"/api/v1/datasets/{ds['id']}/prep-suggestions",
                         headers=auth(tok))
    assert r.status_code == 200, r.text
    sugs = r.json()["suggestions"]
    by_key = {(s["op"], s["column"]): s for s in sugs}
    # (whitespace is already normalized at ingest, so no trim suggestion —
    #  the suggester only reports problems that actually exist in the data)
    assert ("uppercase", "region") in by_key       # 'South' vs 'south'
    assert ("fill_missing", "region") in by_key    # one blank region
    assert ("strip_non_numeric", "amount") in by_key  # Rs.-prefixed numbers
    # evidence is named, not asserted
    assert "casing" in by_key[("uppercase", "region")]["reason"]
    assert "'Rs.100'" in by_key[("strip_non_numeric", "amount")]["reason"]

    # one-click apply: run the suggested steps through the recipe engine
    steps = [{"op": s["op"], "column": s["column"],
              **({"value": s["value"]} if "value" in s else {})}
             for s in sugs]
    r = await client.post(f"/api/v1/datasets/{ds['id']}/recipe/apply",
                          headers=auth(tok), json={"steps": steps})
    assert r.status_code == 200, r.text
    cleaned = r.json()
    types = {c["name"]: c["inferred_type"] for c in cleaned["schema"]}
    assert types["amount"] in ("number", "integer")  # aggregatable now
    # a clean dataset yields (near) nothing to suggest
    r = await client.get(f"/api/v1/datasets/{ds['id']}/prep-suggestions",
                         headers=auth(tok))
    assert all(s["op"] != "strip_non_numeric"
               for s in r.json()["suggestions"])


async def test_feedback_capture_and_tenant_isolation(client):
    tok = await register_and_login(client)
    r = await client.post("/api/v1/ai/feedback", headers=auth(tok),
                          json={"kind": "question", "subject": "total by region",
                                "helpful": False, "comment": "picked wrong column"})
    assert r.status_code == 201, r.text
    r = await client.post("/api/v1/ai/feedback", headers=auth(tok),
                          json={"kind": "brief", "subject": "Exec view",
                                "helpful": True})
    assert r.status_code == 201
    listing = (await client.get("/api/v1/ai/feedback", headers=auth(tok))).json()
    assert listing["total"] == 2 and listing["helpful"] == 1
    assert listing["items"][0]["kind"] in ("brief", "question")

    # another tenant sees nothing
    tok2 = await register_and_login(client, slug="rival", email="o@rival.dev")
    listing2 = (await client.get("/api/v1/ai/feedback", headers=auth(tok2))).json()
    assert listing2["total"] == 0

    # bad kind rejected
    r = await client.post("/api/v1/ai/feedback", headers=auth(tok),
                          json={"kind": "vibes", "subject": "x", "helpful": True})
    assert r.status_code == 422


async def test_ai_question_quota_enforced(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws)
    # shrink the free plan's allowance so the test doesn't loop 50 asks
    conn = await asyncpg.connect(ADMIN_DSN)
    await conn.execute("UPDATE plans SET limits = limits || "
                       "'{\"ai_questions_per_day\": 3}' WHERE code = 'free'")
    await conn.close()
    try:
        for _ in range(3):
            r = await client.post(f"/api/v1/datasets/{ds['id']}/ask",
                                  headers=auth(tok),
                                  json={"question": "total total"})
            assert r.status_code == 200
            assert r.json()["elapsed_ms"] < 5000  # latency is measured
        r = await client.post(f"/api/v1/datasets/{ds['id']}/ask",
                              headers=auth(tok),
                              json={"question": "total total"})
        assert r.status_code == 429
        assert "Daily AI question limit" in r.json()["detail"]
    finally:
        conn = await asyncpg.connect(ADMIN_DSN)
        await conn.execute("UPDATE plans SET limits = limits || "
                           "'{\"ai_questions_per_day\": 50}' WHERE code = 'free'")
        await conn.close()
