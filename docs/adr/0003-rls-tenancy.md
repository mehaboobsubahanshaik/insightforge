# ADR 0003 - Row-Level Security as the tenancy boundary

**Status**: accepted

Application WHERE-clauses fail open on the one forgotten query. RLS fails closed: session GUC app.tenant_id + policies on every tenant table; the API connects as non-superuser app_user in production. Cost: care with connection pooling (GUC set per checkout) - accepted and tested from the attacker's seat.
