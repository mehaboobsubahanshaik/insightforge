# Connector SDK (R2)

A connector is ~40 lines implementing two methods; the platform's shared
trust pipeline (type inference, quality rules, quarantine, scoring, lineage,
incremental cursors, health monitoring) does everything else.

## Contract (services/connectors/base.py)
```python
class MyConnector:
    type_name = "my-service"
    async def test_connection(self, config, credentials) -> None: ...
    async def extract(self, config, credentials,
                      cursor) -> ExtractResult: ...
# ExtractResult(headers: list[str], rows: list[list[str]], cursor: str|None)
```
Rules: read-only APIs only; raise on failure (the platform records health +
retries); return NEW cursor for incremental sync; never log credentials
(vault stores them encrypted); strings in, typing is the platform's job.

## Register
1. Class in services/connectors/<name>.py
2. Entry in catalog.py CATALOG (type/label/engine/category/docs)
3. Engine in __init__._ENGINES + config keys in _keys_for
4. Tests: test_connection failure modes + extract with/without cursor

## Zero-code integration paths already built in
- **rest-api**: any https JSON endpoint (config: url, records_path,
  cursor_field, header_name; credential: header_value)
- **google-sheets-csv**: a sheet's Publish-to-web CSV link
- **JSON upload**: POST /datasets/upload-json (array of objects)

Vendor OAuth connectors (QuickBooks/HubSpot/Salesforce/Shopify/Stripe/GA4)
ship with real API clients + sandbox_demo mode; live use needs the
customer's OAuth credentials (Bucket B in docs/GAP-REGISTER.md).
