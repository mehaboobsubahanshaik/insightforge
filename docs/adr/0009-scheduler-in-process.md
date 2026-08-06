# ADR 0009 - In-process scheduler for MVP

**Status**: accepted

A single asyncio scheduler loop (syncs, reports, alerts) instead of Celery. SMB scale fits comfortably; the loop is disabled under tests and later splits horizontally by moving the same jobs onto Redis (already in the stack).
