# ADR-002: Shared schema + Postgres RLS tenancy
Status: accepted (MVP1). Every tenant row carries tenant_id; RLS policies +
per-request scoped sessions enforce isolation below the app. Rationale:
cheapest per-tenant cost, provable via tests. Tradeoff: noisy-neighbor risk.
Path: dedicated deployment posture (MVP5 G4) -> per-tenant DB for regulated.
