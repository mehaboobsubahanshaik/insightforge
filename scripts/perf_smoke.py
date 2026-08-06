"""Performance smoke: proves headline latencies on a developer laptop.

Run with the API up (single-process dev mode is fine):
    cd backend && python -m uvicorn --app-dir src insightforge_api.main:app --port 8000 &
    python scripts/perf_smoke.py
Measures: 50k-row CSV upload+pipeline, dashboard hydration p50 over 20 calls,
10 concurrent hydrations, preview latency.
"""

import asyncio
import io
import random
import statistics
import time

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
PW = "correct-horse-battery"


def big_csv(rows: int = 50_000) -> bytes:
    buf = io.StringIO()
    buf.write("order_date,customer,region,product,quantity,unit_price,total\n")
    regions = ["South", "North", "East", "West"]
    for i in range(rows):
        day = 1 + (i % 28)
        qty = 1 + (i % 9)
        price = random.choice([49.90, 120.00, 210.00])
        buf.write(f"2026-06-{day:02d},Cust {i % 500},{regions[i % 4]},"
                  f"Widget {chr(65 + i % 3)},{qty},{price},{qty * price:.2f}\n")
    return buf.getvalue().encode()


async def main():
    async with httpx.AsyncClient(timeout=180) as c:
        slug = f"perf{int(time.time()) % 100000}"
        r = await c.post(f"{BASE}/auth/register", json={
            "tenant_name": "Perf Co", "tenant_slug": slug, "display_name": "Perf",
            "email": f"perf@{slug}.dev", "password": PW})
        r.raise_for_status()
        tok = r.json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        ws = (await c.get(f"{BASE}/workspaces", headers=h)).json()[0]["id"]
        await c.post(f"{BASE}/billing/plan", headers=h, json={"plan_code": "growth"})

        t0 = time.perf_counter()
        r = await c.post(f"{BASE}/datasets/upload", headers=h,
                         files={"file": ("big.csv", big_csv(), "text/csv")},
                         params={"name": "big", "workspace_id": ws})
        r.raise_for_status()
        ds = r.json()
        t_upload = time.perf_counter() - t0
        print(f"50k-row upload + full pipeline: {t_upload:.2f}s "
              f"(quality {ds['quality_score']}, {ds['row_count']} rows)")

        r = await c.post(f"{BASE}/dashboard-templates/sales_overview/apply",
                         headers=h, json={
                             "workspace_id": ws, "dataset_id": ds["id"],
                             "value_column": "total", "category_column": "region",
                             "date_column": "order_date"})
        r.raise_for_status()
        db = r.json()

        times = []
        for _ in range(20):
            t0 = time.perf_counter()
            r = await c.get(f"{BASE}/dashboards/{db['id']}/data", headers=h)
            r.raise_for_status()
            times.append((time.perf_counter() - t0) * 1000)
        print(f"dashboard hydration p50 over 20 calls: "
              f"{statistics.median(times):.0f}ms (p95 {sorted(times)[18]:.0f}ms)")

        t0 = time.perf_counter()
        rs = await asyncio.gather(*[
            c.get(f"{BASE}/dashboards/{db['id']}/data", headers=h)
            for _ in range(10)])
        assert all(r.status_code == 200 for r in rs)
        print(f"10 concurrent hydrations: {time.perf_counter() - t0:.2f}s total")

        t0 = time.perf_counter()
        r = await c.get(f"{BASE}/datasets/{ds['id']}/preview?limit=50", headers=h)
        r.raise_for_status()
        print(f"preview 50 rows: {(time.perf_counter() - t0) * 1000:.0f}ms")


if __name__ == "__main__":
    asyncio.run(main())
