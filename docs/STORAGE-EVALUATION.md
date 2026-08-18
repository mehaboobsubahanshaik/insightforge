# Analytical Storage Evaluation (per master-prompt §6.6)

Current: Postgres serves ALL layers (metadata + rows-as-JSONB + query).
Honest ceiling: ~5–10M rows/tenant with sub-second aggregates; beyond that
a columnar engine is warranted.

| Option | Strength | Cost/Complexity | Verdict |
|---|---|---|---|
| Postgres (today) | one engine, RLS isolation proven, cheapest | JSONB scan cost at scale | KEEP for SMB tier |
| DuckDB per-tenant | embedded columnar, zero infra | file lifecycle mgmt, no RLS story | Best first upgrade for analytics reads |
| ClickHouse | massive aggregates | cluster ops, weaker per-row isolation | Dedicated/enterprise tier |
| Iceberg/Delta + object storage | cheap history, engine-agnostic | needs a query engine on top | Adopt with lake ambitions |
| Snowflake/BigQuery/Databricks | managed scale | per-query cost vs SMB economics | White-glove enterprise only |
| TimescaleDB | time-series compression | only helps timestamped metrics | Adopt for audit/metrics tables first |

Migration path: (1) mirror dataset_rows to per-tenant DuckDB files for
reads, (2) route querysvc reads by size threshold, (3) Timescale for
audit/billing_events, (4) revisit ClickHouse at first >50M-row tenant.
