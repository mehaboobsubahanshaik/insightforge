"""SaaS connectors: QuickBooks, HubSpot, Salesforce, Shopify, Stripe, GA4.

Each ships two modes:
- sandbox_demo: bundled realistic fixtures, fully tested end-to-end through
  the trust pipeline (typing, quality, idempotent incremental sync).
- live: implemented to the vendor's documented API contract (httpx, bearer /
  basic auth from the vault). NOT verified against live vendor servers from
  this build environment — enabling live mode is a design-partner task that
  needs real credentials per vendor.
"""

import datetime as dt
import re

import httpx

from .base import ExtractResult, demo_extract


class QuickBooksConnector:
    type_name = "quickbooks"
    HEADERS = ["invoice_id", "txn_date", "customer", "amount", "balance", "status"]
    DEMO = [
        (2001, "2026-01-05", "Sharma Textiles", 18500.00, 0, "Paid"),
        (2002, "2026-01-19", "Patel Hardware", 7250.50, 7250.50, "Open"),
        (2003, "2026-02-02", "Deccan Foods", 12900.00, 0, "Paid"),
        (2004, "2026-02-16", "Krishna Motors", 22100.00, 5000.00, "Partial"),
        (2005, "2026-03-01", "Lotus Pharma", 31600.00, 0, "Paid"),
        (2006, "2026-03-15", "New Era Traders", 4300.00, 4300.00, "Overdue"),
        (2007, "2026-03-29", "Sharma Textiles", 15750.00, 0, "Paid"),
        (2008, "2026-04-12", "Patel Hardware", 9800.00, 0, "Paid"),
        (2009, "2026-04-26", "Deccan Foods", 18200.00, 18200.00, "Open"),
        (2010, "2026-05-10", "Krishna Motors", 27400.00, 0, "Paid"),
        (2011, "2026-05-24", "Lotus Pharma", 8900.00, 0, "Paid"),
        (2012, "2026-06-07", "New Era Traders", 5600.00, 5600.00, "Open"),
        (2013, "2026-06-21", "Sharma Textiles", 21300.00, 0, "Paid"),
        (2014, "2026-07-01", "Patel Hardware", 11450.00, 11450.00, "Open"),
        (2015, "2026-07-10", "Deccan Foods", 16800.00, 0, "Paid"),
    ]

    async def test_connection(self, config, credentials):
        if config.get("sandbox_demo"):
            return
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"https://sandbox-quickbooks.api.intuit.com/v3/company/"
                f"{config['realm_id']}/companyinfo/{config['realm_id']}",
                headers={"Authorization": f"Bearer {credentials['access_token']}",
                         "Accept": "application/json"})
            r.raise_for_status()

    async def extract(self, config, credentials, cursor):
        if config.get("sandbox_demo"):
            return demo_extract(self.HEADERS, self.DEMO, 1, cursor)
        # QuickBooks Query Language (not our DB); cursor must be a plain ISO date
        if cursor and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(cursor)):
            cursor = None
        where = f" WHERE TxnDate > '{cursor}'" if cursor else ""
        query = f"SELECT * FROM Invoice{where} ORDERBY TxnDate"  # noqa: S608
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"https://sandbox-quickbooks.api.intuit.com/v3/company/"
                f"{config['realm_id']}/query",
                params={"query": query},
                headers={"Authorization": f"Bearer {credentials['access_token']}",
                         "Accept": "application/json"})
            r.raise_for_status()
            invoices = r.json().get("QueryResponse", {}).get("Invoice", [])
        rows = [[i.get("Id", ""), i.get("TxnDate", ""),
                 i.get("CustomerRef", {}).get("name", ""), i.get("TotalAmt", ""),
                 i.get("Balance", ""),
                 "Paid" if not i.get("Balance") else "Open"] for i in invoices]
        new_cursor = rows[-1][1] if rows else cursor
        return ExtractResult(self.HEADERS, [[str(c) for c in r] for r in rows], new_cursor)


class HubSpotConnector:
    type_name = "hubspot"
    HEADERS = ["deal_id", "deal_name", "stage", "amount", "close_date", "owner"]
    DEMO = [
        (501, "Sharma renewal", "closedwon", 12000, "2026-01-10", "priya"),
        (502, "Patel expansion", "negotiation", 8500, "2026-01-22", "arjun"),
        (503, "Deccan pilot", "closedwon", 4300, "2026-02-05", "priya"),
        (504, "Krishna upsell", "qualified", 15200, "2026-02-18", "meera"),
        (505, "Lotus new logo", "closedwon", 22000, "2026-03-02", "arjun"),
        (506, "NewEra pilot", "closedlost", 6000, "2026-03-15", "meera"),
        (507, "Sharma phase 2", "negotiation", 18000, "2026-03-28", "priya"),
        (508, "Patel add-on", "closedwon", 3900, "2026-04-11", "arjun"),
        (509, "Deccan expansion", "qualified", 9800, "2026-04-24", "meera"),
        (510, "Krishna renewal", "closedwon", 14100, "2026-05-08", "priya"),
        (511, "Lotus add-on", "negotiation", 5600, "2026-05-21", "arjun"),
        (512, "NewEra new logo", "closedwon", 11700, "2026-06-04", "meera"),
    ]

    async def test_connection(self, config, credentials):
        if config.get("sandbox_demo"):
            return
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://api.hubapi.com/crm/v3/objects/deals?limit=1",
                            headers={"Authorization": f"Bearer {credentials['access_token']}"})
            r.raise_for_status()

    async def extract(self, config, credentials, cursor):
        if config.get("sandbox_demo"):
            return demo_extract(self.HEADERS, self.DEMO, 4, cursor)
        props = "dealname,dealstage,amount,closedate,hubspot_owner_id"
        params = {"limit": 100, "properties": props}
        if cursor:
            params["after"] = cursor
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://api.hubapi.com/crm/v3/objects/deals", params=params,
                            headers={"Authorization": f"Bearer {credentials['access_token']}"})
            r.raise_for_status()
            data = r.json()
        rows = [[d["id"], d["properties"].get("dealname", ""),
                 d["properties"].get("dealstage", ""), d["properties"].get("amount", ""),
                 d["properties"].get("closedate", ""),
                 d["properties"].get("hubspot_owner_id", "")]
                for d in data.get("results", [])]
        new_cursor = data.get("paging", {}).get("next", {}).get("after", cursor)
        return ExtractResult(self.HEADERS, [[str(c) for c in r] for r in rows], new_cursor)


class SalesforceConnector:
    type_name = "salesforce"
    HEADERS = ["opportunity_id", "name", "stage", "amount", "close_date", "account"]
    DEMO = [
        (9001, "Enterprise rollout", "Closed Won", 45000, "2026-01-14", "Sharma Textiles"),
        (9002, "Regional pilot", "Proposal", 12000, "2026-02-01", "Patel Hardware"),
        (9003, "Annual contract", "Closed Won", 28000, "2026-02-19", "Deccan Foods"),
        (9004, "Fleet analytics", "Negotiation", 33500, "2026-03-07", "Krishna Motors"),
        (9005, "Compliance suite", "Closed Won", 51000, "2026-03-25", "Lotus Pharma"),
        (9006, "Starter pack", "Closed Lost", 8000, "2026-04-12", "New Era Traders"),
        (9007, "Expansion seats", "Closed Won", 19500, "2026-04-30", "Sharma Textiles"),
        (9008, "API add-on", "Proposal", 7400, "2026-05-18", "Patel Hardware"),
        (9009, "Multi-site deal", "Closed Won", 62000, "2026-06-05", "Deccan Foods"),
        (9010, "Renewal", "Negotiation", 27500, "2026-06-23", "Krishna Motors"),
    ]

    async def test_connection(self, config, credentials):
        if config.get("sandbox_demo"):
            return
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{config['instance_url']}/services/data/v59.0/limits",
                            headers={"Authorization": f"Bearer {credentials['access_token']}"})
            r.raise_for_status()

    async def extract(self, config, credentials, cursor):
        if config.get("sandbox_demo"):
            return demo_extract(self.HEADERS, self.DEMO, 4, cursor)
        if cursor and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(cursor)):
            cursor = None
        base = "SELECT Id, Name, StageName, Amount, CloseDate, Account.Name FROM Opportunity"
        where = f" WHERE CloseDate > {cursor}" if cursor else ""  # noqa: S608 - date-literal validated above
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{config['instance_url']}/services/data/v59.0/query",
                            params={"q": base + where + " ORDER BY CloseDate LIMIT 1000"},
                            headers={"Authorization": f"Bearer {credentials['access_token']}"})
            r.raise_for_status()
            recs = r.json().get("records", [])
        rows = [[x.get("Id", ""), x.get("Name", ""), x.get("StageName", ""),
                 x.get("Amount", ""), x.get("CloseDate", ""),
                 (x.get("Account") or {}).get("Name", "")] for x in recs]
        new_cursor = rows[-1][4] if rows else cursor
        return ExtractResult(self.HEADERS, [[str(c) for c in r] for r in rows], new_cursor)


class ShopifyConnector:
    type_name = "shopify"
    HEADERS = ["order_id", "created_at", "customer", "total_price", "financial_status", "items"]
    DEMO = [
        (7001, "2026-01-06", "Asha R", 2350.00, "paid", 3),
        (7002, "2026-01-13", "Vikram S", 1180.50, "paid", 1),
        (7003, "2026-01-27", "Neha P", 4620.00, "paid", 5),
        (7004, "2026-02-08", "Rahul K", 899.00, "refunded", 1),
        (7005, "2026-02-21", "Divya M", 3410.75, "paid", 4),
        (7006, "2026-03-05", "Asha R", 1975.00, "paid", 2),
        (7007, "2026-03-19", "Sanjay T", 5240.00, "paid", 6),
        (7008, "2026-04-02", "Neha P", 760.25, "pending", 1),
        (7009, "2026-04-16", "Vikram S", 2890.00, "paid", 3),
        (7010, "2026-05-01", "Divya M", 4115.50, "paid", 4),
        (7011, "2026-05-15", "Rahul K", 1530.00, "paid", 2),
        (7012, "2026-06-01", "Sanjay T", 3675.00, "paid", 3),
    ]

    async def test_connection(self, config, credentials):
        if config.get("sandbox_demo"):
            return
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"https://{config['shop_domain']}/admin/api/2024-01/shop.json",
                            headers={"X-Shopify-Access-Token": credentials["access_token"]})
            r.raise_for_status()

    async def extract(self, config, credentials, cursor):
        if config.get("sandbox_demo"):
            return demo_extract(self.HEADERS, self.DEMO, 1, cursor)
        params = {"limit": 250, "status": "any"}
        if cursor:
            params["created_at_min"] = cursor
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"https://{config['shop_domain']}/admin/api/2024-01/orders.json",
                            params=params,
                            headers={"X-Shopify-Access-Token": credentials["access_token"]})
            r.raise_for_status()
            orders = r.json().get("orders", [])
        rows = [[o.get("id", ""), o.get("created_at", "")[:10],
                 ((o.get("customer") or {}).get("first_name", "") + " "
                  + (o.get("customer") or {}).get("last_name", "")).strip(),
                 o.get("total_price", ""), o.get("financial_status", ""),
                 len(o.get("line_items", []))] for o in orders]
        new_cursor = rows[-1][1] if rows else cursor
        return ExtractResult(self.HEADERS, [[str(c) for c in r] for r in rows], new_cursor)


class StripeConnector:
    type_name = "stripe"
    HEADERS = ["charge_id", "created_date", "customer_email", "amount", "currency", "status"]
    DEMO = [
        ("ch_1001", "2026-01-04", "asha@example.com", 4900, "usd", "succeeded"),
        ("ch_1002", "2026-01-18", "vikram@example.com", 19900, "usd", "succeeded"),
        ("ch_1003", "2026-02-02", "neha@example.com", 4900, "usd", "succeeded"),
        ("ch_1004", "2026-02-16", "rahul@example.com", 4900, "usd", "failed"),
        ("ch_1005", "2026-03-03", "divya@example.com", 19900, "usd", "succeeded"),
        ("ch_1006", "2026-03-17", "sanjay@example.com", 4900, "usd", "succeeded"),
        ("ch_1007", "2026-04-01", "asha@example.com", 4900, "usd", "refunded"),
        ("ch_1008", "2026-04-15", "vikram@example.com", 19900, "usd", "succeeded"),
        ("ch_1009", "2026-05-02", "neha@example.com", 4900, "usd", "succeeded"),
        ("ch_1010", "2026-05-16", "divya@example.com", 19900, "usd", "succeeded"),
        ("ch_1011", "2026-06-01", "rahul@example.com", 4900, "usd", "succeeded"),
    ]

    async def test_connection(self, config, credentials):
        if config.get("sandbox_demo"):
            return
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://api.stripe.com/v1/charges?limit=1",
                            auth=(credentials["secret_key"], ""))
            r.raise_for_status()

    async def extract(self, config, credentials, cursor):
        if config.get("sandbox_demo"):
            return demo_extract(self.HEADERS, self.DEMO, 1, cursor)
        params = {"limit": 100}
        if cursor:
            params["starting_after"] = cursor
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://api.stripe.com/v1/charges", params=params,
                            auth=(credentials["secret_key"], ""))
            r.raise_for_status()
            charges = r.json().get("data", [])
        rows = [[ch["id"],
                 dt.datetime.fromtimestamp(ch["created"], tz=dt.timezone.utc).date().isoformat(),
                 ch.get("billing_details", {}).get("email", ""), ch.get("amount", ""),
                 ch.get("currency", ""), ch.get("status", "")] for ch in charges]
        new_cursor = charges[-1]["id"] if charges else cursor
        return ExtractResult(self.HEADERS, [[str(c) for c in r] for r in rows], new_cursor)


class GA4Connector:
    type_name = "ga4"
    HEADERS = ["date", "channel", "sessions", "users", "conversions"]
    DEMO = [
        ("2026-01-31", "organic", 4210, 3300, 88),
        ("2026-01-31", "paid", 1850, 1600, 121),
        ("2026-02-28", "organic", 4890, 3750, 95),
        ("2026-02-28", "paid", 2100, 1820, 140),
        ("2026-02-28", "referral", 640, 590, 22),
        ("2026-03-31", "organic", 5320, 4100, 103),
        ("2026-03-31", "paid", 2380, 2010, 158),
        ("2026-03-31", "referral", 710, 655, 25),
        ("2026-04-30", "organic", 5760, 4420, 112),
        ("2026-04-30", "paid", 2550, 2190, 171),
        ("2026-05-31", "organic", 6100, 4700, 118),
        ("2026-05-31", "paid", 2790, 2400, 186),
        ("2026-06-30", "organic", 6480, 4980, 127),
        ("2026-06-30", "paid", 3010, 2580, 199),
    ]

    async def test_connection(self, config, credentials):
        if config.get("sandbox_demo"):
            return
        raise RuntimeError("GA4 live mode requires Google OAuth service-account setup "
                           "(design-partner task); use sandbox_demo for evaluation")

    async def extract(self, config, credentials, cursor):
        if config.get("sandbox_demo"):
            return demo_extract(self.HEADERS, self.DEMO, 0, cursor)
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"https://analyticsdata.googleapis.com/v1beta/properties/"
                f"{config['property_id']}:runReport",
                headers={"Authorization": f"Bearer {credentials['access_token']}"},
                json={"dateRanges": [{"startDate": cursor or "90daysAgo", "endDate": "today"}],
                      "dimensions": [{"name": "date"},
                                     {"name": "sessionDefaultChannelGroup"}],
                      "metrics": [{"name": "sessions"}, {"name": "totalUsers"},
                                  {"name": "conversions"}]})
            r.raise_for_status()
            data = r.json()
        rows = [[*(d["value"] for d in row["dimensionValues"]),
                 *(m["value"] for m in row["metricValues"])]
                for row in data.get("rows", [])]
        new_cursor = rows[-1][0] if rows else cursor
        return ExtractResult(self.HEADERS, [[str(c) for c in r] for r in rows], new_cursor)
