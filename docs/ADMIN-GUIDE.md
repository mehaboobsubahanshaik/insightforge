# Administrator Guide

**Roles**: owner (billing, plan, offboarding, everything), admin (members, settings, data), analyst (create/edit data + dashboards), viewer (read).

**Members**: Members page — invite by email (link lands in outbox/SMTP), change roles, remove. MFA: each user enrolls in Settings; recovery codes shown once.

**Plans & billing**: Billing page — usage bars vs limits, plan switch (instant), 14-day Growth trial (once), invoices (generate monthly), offboarding (30-day grace, purge after).

**Data**: Sources (connectors + sync schedules; 3 failures → owner email + webhook), Datasets (upload/clean/suggest-fixes/measures/alerts incl. anomaly kind), Dashboards (draft→publish, views, brief, report schedules).

**Notifications**: Settings → Manage webhooks (generic HMAC / Slack / Teams; test button), Manage alerts, Manage reports.

**AI governance**: quotas per plan (429 past daily limit), every question/brief audited, feedback listable at GET /api/v1/ai/feedback, evals in docs/AI-EVALS.md.

**Ops**: status at GET /api/v1/platform/status; support via in-app request; runbooks in docs/RUNBOOKS.md.
