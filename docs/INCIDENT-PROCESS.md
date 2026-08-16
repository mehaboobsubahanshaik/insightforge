# Incident Process

**Declare** when: status endpoint degraded >15 min, data integrity suspected, security event, or cross-tenant defect (always Sev-1).

| Sev | Meaning | Response |
|---|---|---|
| 1 | Data breach / cross-tenant leak / total outage | Immediately, all hands |
| 2 | Feature down for many tenants | < 1 h |
| 3 | Degraded, workaround exists | Next business day |

**Roles**: Incident lead (decisions, comms), operator (hands on keyboard). One person may hold both at current team size.

**Loop**: assess (status endpoint, logs, audit trail) → mitigate (RUNBOOKS.md; rollback early rather than debug live) → communicate (status note to affected tenants at declare + resolve) → record.

**Postmortem** (blameless, within 3 days): timeline, root cause, what limited/worsened impact, action items with owners. Store in `docs/postmortems/`. Security incidents additionally follow PRIVACY.md breach-notification duties.

**Drill log**: 2026-08-16 tabletop — scheduler-stall scenario walked via RB-1; gaps found: none blocking; heartbeat added to status endpoint as a result.
