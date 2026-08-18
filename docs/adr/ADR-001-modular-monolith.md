# ADR-001: Modular monolith + single scheduler worker
Status: accepted (MVP1). FastAPI app with routers/services as bounded
contexts; one asyncio scheduler for jobs. Rationale: SMB economics, one
deployable, testability. Tradeoff: no independent scaling. Migration path:
extract workers (ingestion, notify) first when volume justifies.
