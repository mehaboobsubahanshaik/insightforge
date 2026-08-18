"""Connector registry. Every platform tile in the catalog resolves to a real
engine here — PostgreSQL-wire platforms share the PostgreSQL driver and
MySQL-wire platforms share the MySQL driver (the wire protocol IS the
integration); the six SaaS connectors are individual implementations."""

from .catalog import BY_TYPE, CATALOG
from .generic import GoogleSheetCsvConnector, RestApiConnector
from .mysql import MySQLConnector
from .postgres import PostgresConnector
from .saas import (
    GA4Connector,
    HubSpotConnector,
    QuickBooksConnector,
    SalesforceConnector,
    ShopifyConnector,
    StripeConnector,
)

_PG = PostgresConnector()
_MY = MySQLConnector()
_ENGINES = {
    "postgresql": _PG,
    "mysql": _MY,
    "quickbooks": QuickBooksConnector(),
    "hubspot": HubSpotConnector(),
    "salesforce": SalesforceConnector(),
    "shopify": ShopifyConnector(),
    "stripe": StripeConnector(),
    "ga4": GA4Connector(),
    "rest-api": RestApiConnector(),
    "google-sheets-csv": GoogleSheetCsvConnector(),
}

REGISTRY = {c["type"]: _ENGINES[c["engine"]] for c in CATALOG}

_PG_KEYS = {"host", "port", "database", "table", "cursor_column", "sslmode"}
_MY_KEYS = {"host", "port", "database", "table", "cursor_column", "ssl"}
_SAAS_KEYS = {
    "quickbooks": {"realm_id", "sandbox_demo"},
    "hubspot": {"sandbox_demo"},
    "salesforce": {"instance_url", "sandbox_demo"},
    "shopify": {"shop_domain", "sandbox_demo"},
    "stripe": {"sandbox_demo"},
    "ga4": {"property_id", "sandbox_demo"},
}


def _keys_for(entry) -> set:
    if entry["engine"] == "postgresql":
        return set(_PG_KEYS)
    if entry["engine"] == "mysql":
        return set(_MY_KEYS)
    if entry["engine"] == "rest-api":
        return {"url", "records_path", "cursor_field", "header_name"}
    if entry["engine"] == "google-sheets-csv":
        return {"csv_url", "cursor_field"}
    return set(_SAAS_KEYS[entry["engine"]])


ALLOWED_CONFIG_KEYS = {c["type"]: _keys_for(c) for c in CATALOG}

__all__ = ["REGISTRY", "ALLOWED_CONFIG_KEYS", "CATALOG", "BY_TYPE",
           "PostgresConnector", "MySQLConnector"]
