# ADR 0005 - Immutable import generations

**Status**: accepted

Every ingest/recipe application writes a new import_id row-set and repoints current_import_id. Queries are snapshot-consistent, cleaning is non-destructive (quarantined rows are rescuable), lineage is an append-only story. Cost: storage - acceptable at SMB scale; compaction is in the backlog.
