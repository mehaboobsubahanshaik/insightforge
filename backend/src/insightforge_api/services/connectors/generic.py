"""Generic connectors (R2): any JSON REST API + Google Sheets published CSV.
Same SDK contract as every certified connector — fetch rows, let the shared
trust pipeline (typing, quality, quarantine, lineage) do the rest."""

import csv
import io

import httpx

from .base import ExtractResult


def _dig(obj, path: str):
    for key in [p for p in (path or "").split(".") if p]:
        obj = obj.get(key) if isinstance(obj, dict) else None
    return obj


def records_to_result(records: list, cursor_field: str | None,
                      cursor: str | None) -> ExtractResult:
    records = [r for r in records if isinstance(r, dict)]
    if cursor_field and cursor:
        records = [r for r in records
                   if str(r.get(cursor_field, "")) > str(cursor)]
    headers: list[str] = []
    for r in records:
        for k in r:
            if k not in headers:
                headers.append(k)
    rows = [["" if r.get(h) is None else str(r.get(h)) for h in headers]
            for r in records]
    new_cursor = (str(records[-1].get(cursor_field, cursor))
                  if cursor_field and records else cursor)
    return ExtractResult(headers, rows, new_cursor)


class RestApiConnector:
    """Point at any JSON endpoint: config = url, records_path (dot path to
    the list, empty if the response IS the list), cursor_field, header_name;
    credentials = header_value (e.g. 'Bearer xyz'). Read-only by design."""

    type_name = "rest-api"

    def _headers(self, config, credentials):
        h = {"Accept": "application/json"}
        if config.get("header_name") and credentials.get("header_value"):
            h[config["header_name"]] = credentials["header_value"]
        return h

    async def _fetch(self, config, credentials):
        async with httpx.AsyncClient(timeout=30,
                                     follow_redirects=True) as c:
            r = await c.get(config["url"],
                            headers=self._headers(config, credentials))
            r.raise_for_status()
            return r.json()

    async def test_connection(self, config, credentials):
        if not str(config.get("url", "")).startswith("https://"):
            raise ValueError("url must be https://")
        payload = await self._fetch(config, credentials)
        records = _dig(payload, config.get("records_path", "")) \
            if config.get("records_path") else payload
        if not isinstance(records, list):
            raise ValueError(
                f"records_path '{config.get('records_path', '')}' did not "
                "resolve to a list — set it to the JSON key holding the rows")

    async def extract(self, config, credentials, cursor):
        payload = await self._fetch(config, credentials)
        records = _dig(payload, config.get("records_path", "")) \
            if config.get("records_path") else payload
        if not isinstance(records, list):
            raise ValueError("records_path did not resolve to a list")
        return records_to_result(records, config.get("cursor_field"), cursor)


class GoogleSheetCsvConnector:
    """Google Sheets via File > Share > Publish to web > CSV. No OAuth —
    the published URL is the credential surface (revoke by unpublishing)."""

    type_name = "google-sheets-csv"

    async def _fetch_text(self, config):
        async with httpx.AsyncClient(timeout=30,
                                     follow_redirects=True) as c:
            r = await c.get(config["csv_url"])
            r.raise_for_status()
            return r.text

    async def test_connection(self, config, credentials):
        url = str(config.get("csv_url", ""))
        if not (url.startswith("https://docs.google.com/")
                and "output=csv" in url):
            raise ValueError("csv_url must be a docs.google.com "
                             "'Publish to web' CSV link (output=csv)")
        text = await self._fetch_text(config)
        if not text.strip():
            raise ValueError("Published sheet is empty")

    async def extract(self, config, credentials, cursor):
        text = await self._fetch_text(config)
        reader = csv.reader(io.StringIO(text))
        rows = [r for r in reader if any(c.strip() for c in r)]
        if not rows:
            return ExtractResult([], [], cursor)
        headers, data = rows[0], rows[1:]
        if config.get("cursor_field") in headers and cursor:
            idx = headers.index(config["cursor_field"])
            data = [r for r in data if str(r[idx]) > str(cursor)]
        new_cursor = (str(data[-1][headers.index(config["cursor_field"])])
                      if config.get("cursor_field") in headers and data
                      else cursor)
        return ExtractResult(headers, data, new_cursor)
