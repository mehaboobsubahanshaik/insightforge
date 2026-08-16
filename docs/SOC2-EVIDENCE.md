# SOC 2 Evidence Foundation (readiness map, not an audit)

| Control area | Implementation | Evidence |
|---|---|---|
| Logical access | RBAC + MFA + recovery codes | auth code, test_mfa*, audit trail |
| Tenant segregation | Postgres RLS everywhere | migrations 0001–0006, cross-tenant 404 tests |
| Change management | PR flow, CI (tests+lint+pip-audit+migration cycle+ai_eval) | .github/workflows/ci.yml, git history |
| Availability | status endpoint, scheduler heartbeat, backoff/retry | routers/platform.py, RUNBOOKS.md |
| Incident response | documented process + drill log | INCIDENT-PROCESS.md |
| Backup/DR | tested restore procedure | BACKUP-RESTORE.md, DR-VALIDATION.md |
| Data disposal | offboarding purge (tested), privacy requests | test_commercial.py, PRIVACY.md |
| Monitoring/audit | append-only audit events, billing meters | audit.py, Activity UI |
| Vendor mgmt | subprocessor list | PRIVACY.md |
| Risk register | known open items tracked | SECURITY-HARDENING.md |

Gap to a real SOC 2: continuous evidence collection, HR/vendor controls, external auditor. This map is the "foundation" the checklist asks for.
