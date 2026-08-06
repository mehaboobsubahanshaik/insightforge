# ADR 0007 - Per-tenant envelope encryption for connector credentials

**Status**: accepted

Master key (env) wraps per-tenant data keys (Fernet); credentials decrypt only inside sync execution and are never serialized outward. Rotation = rewrap data keys.
