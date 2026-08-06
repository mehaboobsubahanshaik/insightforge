"""End-to-end live smoke: exercises the real API the way the UI does.

Run with the API up:
    cd backend && python -m uvicorn --app-dir src insightforge_api.main:app --port 8000 &
    python scripts/live_smoke.py

Covers: register -> workspace -> CSV upload+pipeline -> recipe clean ->
template dashboard -> hydration -> drill filters -> publish -> public share ->
ML insights -> alert -> report schedule -> billing. Prints
"ALL SMOKE CHECKS PASSED" only if every step succeeds.
"""

import asyncio
import time

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
PW = "correct-horse-battery"

CSV = (
    "order_date,customer,region,product,quantity,unit_price,total\n"
    "2026-06-01,Acme,South,Widget A,2,49.90,99.80\n"
    "2026-06-02,Bolt,North,Widget B,1,120.00,120.00\n"
    "2026-06-03,Cass,East,Widget A,3,49.90,149.70\n"
    "2026-06-04,Dune,West,Widget C,1,210.00,210.00\n"
    "2026-06-05,Acme,South,Widget B,2,120.00,240.00\n"
    "2026-06-06,Bolt,North,Widget A,4,49.90,199.60\n"
    "2026-06-07,Cass,East,Widget C,2,210.00,420.00\n"
    "2026-06-08,Dune,West,Widget B,999999,120.00,not-a-number\n"
    "2026-06-09,Acme,South,Widget A,1,49.90,49.90\n"
    "2026-06-10,Bolt,North,Widget C,1,210.00,210.00\n"
)

CHECKS: list[str] = []


def ok(label: str) -> None:
    CHECKS.append(label)
    print(f"  ✔ {label}")


async def main() -> None:
    async with httpx.AsyncClient(timeout=120) as c:
        slug = f"smoke{int(time.time()) % 100000}"

        # -- auth + tenant ------------------------------------------------
        r = await c.post(f"{BASE}/auth/register", json={
            "tenant_name": "Smoke Co", "tenant_slug": slug,
            "display_name": "Smokey", "email": f"owner@{slug}.dev",
            "password": PW})
        assert r.status_code == 201, r.text
        tok = r.json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        me = (await c.get(f"{BASE}/auth/me", headers=h)).json()
        assert me["display_name"] == "Smokey" and me["role"] == "tenant_owner"
        ok("register + /auth/me profile")

        r = await c.post(f"{BASE}/billing/plan", headers=h,
                         json={"plan_code": "growth"})
        assert r.status_code == 200, r.text
        ok("plan upgrade -> growth")

        ws = (await c.get(f"{BASE}/workspaces", headers=h)).json()[0]["id"]

        # -- ingest + quality --------------------------------------------
        r = await c.post(f"{BASE}/datasets/upload", headers=h,
                         files={"file": ("orders.csv", CSV.encode(), "text/csv")},
                         params={"name": "orders", "workspace_id": ws})
        assert r.status_code == 201, r.text
        ds = r.json()
        assert ds["row_count"] == 9 and ds["quarantined_count"] == 1
        assert 0 < ds["quality_score"] < 100
        ok(f"CSV pipeline: 9 clean + 1 quarantined, quality {ds['quality_score']}")

        r = await c.get(f"{BASE}/datasets/{ds['id']}", headers=h)
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["dq_results"] and detail["lineage"]["source"] == "upload"
        ok("dataset detail embeds dq_results + lineage")

        pv = (await c.get(
            f"{BASE}/datasets/{ds['id']}/preview?limit=50",
            headers=h)).json()
        assert len(pv["rows"]) == 9 and not pv["quarantine"]
        pvq = (await c.get(
            f"{BASE}/datasets/{ds['id']}/preview"
            "?limit=50&include_quarantined=true", headers=h)).json()
        assert len(pvq["quarantine"]) == 1 and pvq["quarantine"][0]["reason"]
        ok("preview separates clean rows from quarantine (with reasons)")

        # -- cleaning recipe ---------------------------------------------
        r = await c.post(f"{BASE}/datasets/{ds['id']}/recipe/apply",
                         headers=h, json={
                             "steps": [{"op": "uppercase",
                                        "column": "region"}]})
        assert r.status_code == 200, r.text
        assert r.json()["quality_score"] is not None
        ok("recipe applied + dataset re-scored")

        # -- drill filters ------------------------------------------------
        pv = (await c.get(
            f"{BASE}/datasets/{ds['id']}/preview",
            params={"filters": '[{"column":"region","value":"SOUTH"}]'},
            headers=h)).json()
        assert pv["rows"] and {r_["region"] for r_ in pv["rows"]} == {"SOUTH"}
        ok("drill-through preview filters rows (post-recipe values)")

        # -- template dashboard + hydration ------------------------------
        tpls = (await c.get(f"{BASE}/dashboard-templates", headers=h)).json()
        assert any(t["key"] == "sales_overview" for t in tpls)
        r = await c.post(f"{BASE}/dashboard-templates/sales_overview/apply",
                         headers=h, json={
                             "workspace_id": ws, "dataset_id": ds["id"],
                             "value_column": "total",
                             "category_column": "region",
                             "date_column": "order_date"})
        assert r.status_code == 201, r.text
        db = r.json()
        data = (await c.get(f"{BASE}/dashboards/{db['id']}/data",
                            headers=h)).json()
        kpis = [w for w in data["widgets"] if w["type"] == "kpi"]
        charts = [w for w in data["widgets"] if w.get("groups")]
        assert kpis and kpis[0]["value"] is not None and charts
        assert data["quality_score"] is not None
        ok(f"template dashboard hydrates ({len(data['widgets'])} widgets)")

        fdata = (await c.get(
            f"{BASE}/dashboards/{db['id']}/data",
            params={"filters": '[{"column":"region","value":"SOUTH"}]'},
            headers=h)).json()
        fk = next(w for w in fdata["widgets"] if w["type"] == "kpi")
        assert fk["value"] < kpis[0]["value"]
        ok("cross-filtered hydration narrows KPIs")

        # -- publish + public share --------------------------------------
        r = await c.post(f"{BASE}/dashboards/{db['id']}/publish", headers=h)
        assert r.status_code == 200 and r.json()["published_version"] == 1
        r = await c.post(f"{BASE}/dashboards/{db['id']}/share", headers=h,
                         json={"expires_in_hours": 24})
        assert r.status_code == 201, r.text
        share = r.json()
        pub = await c.get(f"{BASE}/public/dashboards/{share['token']}")
        assert pub.status_code == 200
        pd = pub.json()
        assert pd["read_only"] and pd["published_version"] == 1 and pd["widgets"]
        anon = await c.get(f"{BASE}/dashboards/{db['id']}/data")
        assert anon.status_code == 401
        ok("publish -> tokenised public share (auth still enforced elsewhere)")

        # -- ML insights --------------------------------------------------
        r = await c.get(
            f"{BASE}/datasets/{ds['id']}/insights",
            params={"value_column": "total", "date_column": "order_date",
                    "horizon": 5}, headers=h)
        assert r.status_code == 200, r.text
        ins = r.json()
        assert len(ins["forecast"]["points"]) == 5
        assert "anomalies" in ins
        ok("ML insights: 5-step forecast + anomaly scan")

        # -- alert + report schedule -------------------------------------
        r = await c.post(f"{BASE}/datasets/{ds['id']}/alerts", headers=h, json={
            "name": "Revenue floor", "formula": "sum(total)",
            "operator": "lt", "threshold": 10.0,
            "interval_minutes": 60, "recipients": [f"ops@{slug}.dev"]})
        assert r.status_code == 201, r.text
        alerts = (await c.get(f"{BASE}/datasets/{ds['id']}/alerts",
                              headers=h)).json()
        assert alerts and alerts[0]["enabled"]
        ok("threshold alert armed")

        r = await c.post(f"{BASE}/dashboards/{db['id']}/report-schedules",
                         headers=h, json={"recipients": [f"ceo@{slug}.dev"],
                                          "interval_minutes": 1440})
        assert r.status_code == 201, r.text
        ok("daily report schedule created")

        # -- billing reflects usage --------------------------------------
        b = (await c.get(f"{BASE}/billing/summary", headers=h)).json()
        assert b["plan_code"] == "growth"
        assert b["usage"]["datasets"] == 1 and b["usage"]["dashboards"] == 1
        ok("billing summary meters live usage")

    print(f"\nALL SMOKE CHECKS PASSED ({len(CHECKS)} checks)")


if __name__ == "__main__":
    asyncio.run(main())
