# ADR 0004 - Squashed 0001, append-only after

**Status**: accepted

Pre-release we amended the 0001 squash for velocity; 0002 is idempotent to converge any early database, and from 0002 onward history is append-only. The trade-off is documented in 0002's docstring so future readers understand why it guards with IF NOT EXISTS.
