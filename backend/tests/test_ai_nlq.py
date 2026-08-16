"""MVP3 governed NLQ: grounding, permissions, dates, measures, injection."""

import pytest
from conftest import auth, get_workspace, register_and_login, upload_csv

pytestmark = pytest.mark.ai_eval

NLQ_CSV = (
    "order_date,region,product,quantity,total\n"
    "2026-06-01,South,Widget A,10,499.00\n"
    "2026-06-02,North,Widget B,5,600.00\n"
    "2026-06-03,South,Widget A,8,399.20\n"
    "2026-07-04,South,Widget C,3,896.70\n"
    "2026-07-05,East,Widget B,2,247.42\n"
)



async def _ds(client, tok):
    ws = await get_workspace(client, tok)
    return await upload_csv(client, tok, ws, name="orders", content=NLQ_CSV)


async def ask(client, tok, ds, q):
    r = await client.post(f"/api/v1/datasets/{ds['id']}/ask",
                          headers=auth(tok), json={"question": q})
    assert r.status_code == 200, r.text
    return r.json()


async def test_simple_aggregate_and_groupby(client):
    tok = await register_and_login(client)
    ds = await _ds(client, tok)
    a = await ask(client, tok, ds, "What is the total total?")
    assert a["answered"] and a["grounded"]
    assert abs(a["answer"]["value"] - 2642.32) < 0.01
    assert a["confidence"] == "high" and a["quality_score"] is not None

    a = await ask(client, tok, ds, "total by region")
    groups = {g["group"]: g["value"] for g in a["answer"]["groups"]}
    assert abs(groups["South"] - 1794.90) < 0.01
    assert a["suggested_widget"]["type"] == "bar"
    assert a["suggested_widget"]["group_by"] == "region"

    a = await ask(client, tok, ds, "how many orders are there")
    assert a["answer"]["value"] == 5


async def test_date_grammar_and_value_grounding(client):
    tok = await register_and_login(client)
    ds = await _ds(client, tok)
    a = await ask(client, tok, ds, "total total in June 2026")
    assert abs(a["answer"]["value"] - 1498.20) < 0.01
    assert "June 2026" in a["description"]

    # bare "in South" resolves against the data, case-insensitively
    a = await ask(client, tok, ds, "average quantity in south")
    assert abs(a["answer"]["value"] - 7.0) < 0.01
    assert "region is South" in a["description"]
    assert a["confidence"] == "high"

    a = await ask(client, tok, ds, "top 2 products by total")
    assert len(a["answer"]["groups"]) == 2


async def test_certified_measure_outranks_columns(client):
    tok = await register_and_login(client)
    ds = await _ds(client, tok)
    r = await client.post(f"/api/v1/datasets/{ds['id']}/measures",
                          headers=auth(tok),
                          json={"name": "revenue", "formula": "sum(total)",
                                "certified": True})
    assert r.status_code == 201, r.text
    a = await ask(client, tok, ds, "revenue by region")
    assert a["used"]["measure"] == "revenue"
    groups = {g["group"]: g["value"] for g in a["answer"]["groups"]}
    assert abs(groups["North"] - 600.00) < 0.01


async def test_honest_refusal_and_injection_is_inert(client):
    tok = await register_and_login(client)
    ds = await _ds(client, tok)
    a = await ask(client, tok, ds, "what is the meaning of life")
    assert a["answered"] is False and a["grounded"]
    assert "total" in a["answerable"]["numeric_columns"]
    assert a["answerable"]["examples"]

    # hostile input is just an unanswerable string — and the tables survive
    a = await ask(client, tok, ds,
                  "total total'; DROP TABLE dataset_rows; --")
    assert a["grounded"]
    b = await ask(client, tok, ds, "how many orders")
    assert b["answer"]["value"] == 5  # data intact

    # permission-awareness: another tenant cannot ask about this dataset
    tok2 = await register_and_login(client, slug="rival",
                                    email="owner@rival.dev")
    r = await client.post(f"/api/v1/datasets/{ds['id']}/ask",
                          headers=auth(tok2), json={"question": "total total"})
    assert r.status_code == 404


async def test_single_numeric_column_defaults(client):
    tok = await register_and_login(client, slug="onenum",
                                   email="owner@onenum.dev")
    ws = await get_workspace(client, tok)
    csv = ("order_id,region,amount\n"
           "ORD-1,South,100\nORD-2,North,50\nORD-3,South,25\n")
    ds = await upload_csv(client, tok, ws, name="sales", content=csv)
    a = await ask(client, tok, ds, "total by region")  # column not named
    assert a["answered"], a
    groups = {g["group"]: g["value"] for g in a["answer"]["groups"]}
    assert groups == {"South": 125.0, "North": 50.0}
    assert a["used"]["column"] == "amount"
    # and refusal examples never suggest grouping by an id column
    bad = await ask(client, tok, ds, "what is happiness")
    assert all("order_id" not in e for e in bad["answerable"]["examples"])
