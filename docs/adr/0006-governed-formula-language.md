# ADR 0006 - Small governed formula language

**Status**: accepted

A deliberately tiny expression grammar (aggregations over columns + arithmetic) instead of SQL passthrough. Parsed and validated server-side against the dataset schema; errors are friendly. Keeps self-service inside governance.
