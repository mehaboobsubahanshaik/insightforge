"""Data security enforcement (MVP5 G2): column-level security + advanced
row-level policies, evaluated per-request from dataset governance config.

governance = {
  "classification": {"amount": "confidential", "email": "pii"},
  "column_policy":  {"amount": ["tenant_owner", "admin"]},   # allowed roles
  "row_policies":   [{"match": {"role": "analyst"},
                      "filters": [{"column": "region", "op": "eq",
                                   "value": "South"}]},
                     {"match": {"attribute": {"department": "finance"}},
                      "filters": [...]}],
  "retention": {"column": "order_date", "days": 365}
}
Enforced on ask/preview/query surfaces; owners are never column-blocked.
"""

from fastapi import HTTPException


def check_columns(governance: dict, role: str, columns: list[str]) -> None:
    """Column-level security: 403 if any referenced column is restricted
    to roles that don't include the caller's."""
    policy = (governance or {}).get("column_policy") or {}
    for col in columns:
        allowed = policy.get(col)
        if allowed and role not in allowed and role != "tenant_owner":
            raise HTTPException(
                403, f"Column '{col}' is restricted "
                     f"(classification: "
                     f"{(governance.get('classification') or {}).get(col, 'restricted')}). "
                     f"Allowed roles: {allowed}.")


def row_filters(governance: dict, role: str, attributes: dict) -> list[dict]:
    """Advanced row-level policies: mandatory filters for matching
    role/attribute rules — appended server-side, invisible to remove."""
    out: list[dict] = []
    for rule in (governance or {}).get("row_policies") or []:
        match = rule.get("match") or {}
        if "role" in match and match["role"] != role:
            continue
        if "attribute" in match:
            need = match["attribute"]
            if not all((attributes or {}).get(k) == v for k, v in need.items()):
                continue
        out.extend(rule.get("filters") or [])
    return out
