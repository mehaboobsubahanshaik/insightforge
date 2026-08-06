# ADR 0008 - Platform tiles share wire-protocol engines

**Status**: accepted

Supabase/Neon/RDS/CloudSQL/Azure/Timescale/Cockroach ARE PostgreSQL wire; MariaDB/RDS-MySQL/CloudSQL/Azure ARE MySQL wire. One hardened engine per protocol, many honest tiles (catalog.py). Adding a platform = one catalog row.
