"""R2: generic REST connector, Google-Sheets CSV connector, JSON upload —
all flowing through the shared trust pipeline."""

import json

from conftest import auth, get_workspace, register_and_login

from insightforge_api.services.connectors.base import ExtractResult
from insightforge_api.services.connectors.generic import (
    GoogleSheetCsvConnector,
    RestApiConnector,
    records_to_result,
)


def test_records_to_result_shapes_and_cursor():
    recs = [{"id": 1, "region": "South", "amount": 10},
            {"id": 2, "amount": 20, "extra": "x"}]
    r = records_to_result(recs, "id", None)
    assert r.headers == ["id", "region", "amount", "extra"]
    assert r.rows[1] == ["2", "", "20", "x"]
    assert r.cursor == "2"
    r2 = records_to_result(recs, "id", "1")
    assert len(r2.rows) == 1 and r2.rows[0][0] == "2"


async def test_rest_connector_extracts_via_mock(monkeypatch):
    conn = RestApiConnector()

    async def fake_fetch(self, config, credentials):
        assert credentials["header_value"] == "Bearer k"
        return {"data": {"items": [{"day": "2026-08-01", "sales": 5},
                                   {"day": "2026-08-02", "sales": 7}]}}
    monkeypatch.setattr(RestApiConnector, "_fetch", fake_fetch)
    await conn.test_connection(
        {"url": "https://api.example.com/v1/sales",
         "records_path": "data.items"}, {"header_value": "Bearer k"})
    res = await conn.extract(
        {"url": "https://api.example.com/v1/sales",
         "records_path": "data.items", "cursor_field": "day",
         "header_name": "Authorization"},
        {"header_value": "Bearer k"}, "2026-08-01")
    assert isinstance(res, ExtractResult)
    assert res.rows == [["2026-08-02", "7"]] and res.cursor == "2026-08-02"
    # plain http refused
    try:
        await conn.test_connection({"url": "http://x"}, {})
        raise AssertionError("should refuse http")
    except ValueError:
        pass


async def test_gsheet_csv_connector(monkeypatch):
    conn = GoogleSheetCsvConnector()

    async def fake_text(self, config):
        return "order_date,amount\n2026-08-01,10\n2026-08-02,20\n"
    monkeypatch.setattr(GoogleSheetCsvConnector, "_fetch_text", fake_text)
    await conn.test_connection(
        {"csv_url": "https://docs.google.com/spreadsheets/d/e/X/pub"
                    "?output=csv"}, {})
    res = await conn.extract({"csv_url": "https://docs.google.com/x?output=csv",
                              "cursor_field": "order_date"}, {}, "2026-08-01")
    assert res.rows == [["2026-08-02", "20"]]
    try:
        await conn.test_connection({"csv_url": "https://evil.com/a.csv"}, {})
        raise AssertionError("should refuse non-google URL")
    except ValueError:
        pass


async def test_json_upload_through_trust_pipeline(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    payload = [{"region": "South", "amount": 100},
               {"region": "West", "amount": 40},
               {"region": "East", "amount": 60},
               {"region": "North", "amount": "not-a-number"}]
    r = await client.post(
        f"/api/v1/datasets/upload-json?workspace_id={ws}&name=api-data",
        headers=auth(tok),
        files={"file": ("d.json", json.dumps(payload), "application/json")})
    assert r.status_code == 201, r.text
    ds = r.json()
    assert ds["row_count"] >= 1
    # the trust pipeline judged the bad row exactly like a CSV upload
    a = (await client.post(f"/api/v1/datasets/{ds['id']}/ask",
                           headers=auth(tok),
                           json={"question": "total amount"})).json()
    assert a["answer"]["value"] == 200  # bad row quarantined
    r = await client.post(
        f"/api/v1/datasets/upload-json?workspace_id={ws}&name=bad",
        headers=auth(tok), files={"file": ("b.json", "{not json",
                                           "application/json")})
    assert r.status_code == 422
