# ADR 0002 - FastAPI + async SQLAlchemy + PostgreSQL

**Status**: accepted

Async end-to-end fits an IO-bound BI workload (connector pulls, dashboard fan-out hydration). PostgreSQL chosen for RLS (tenancy), JSONB (schemas/widgets/profiles), and operational ubiquity among SMB hosts.
