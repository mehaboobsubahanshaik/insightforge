# Data Security (MVP5 G2)

**Classification**: label columns (pii/confidential/internal/public) via
`PUT /datasets/{id}/governance {"classification": {...}}` — labels surface in
restriction errors and the catalog.

**Column-level security**: `"column_policy": {"salary": ["admin"]}` — any
ask/query referencing a restricted column is 403'd for other roles, with the
classification named. Owners are never column-blocked.

**Advanced row policies**: `"row_policies": [{"match": {"role": ...} |
{"attribute": {...}}, "filters": [...]}]` — mandatory server-side filters by
role or ABAC attribute (G1); callers cannot see or remove them.

**Advanced retention**: `"retention": {"column": "order_date", "days": 365}`
— the scheduler purges rows past the window (date-column validated).

**Customer-managed keys**: `PUT /enterprise/cmk` stores the tenant's
aws-kms/azure-keyvault/gcp-kms key reference (audited). Production rollout =
envelope encryption of data-at-rest under that key at the storage layer;
until then the config records intent + enables key-rotation workflows.
