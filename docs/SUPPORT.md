# Support Workflow

**Channels**: in-app `POST /api/v1/support` (routed to SUPPORT_EMAIL inbox, audited as `support.request`) or direct email.

**SLA**: acknowledge < 1 business day; triage to severity (see INCIDENT-PROCESS.md table); resolution target Sev-2 < 3 days, Sev-3 best effort. Bug reports reproduce → regression test → fix (the project's standing rule: field bugs become tests).

**Escalation**: anything smelling of security or cross-tenant data goes straight to incident Sev-1 regardless of reporter's framing.
