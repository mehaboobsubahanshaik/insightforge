# Event Catalog
## Webhook events (HMAC-signed, notify.EVENTS)
alert.triggered · anomaly.detected · sync.failed · report.sent ·
siem.audit (batched security actions) · forecast.breach
## Billing meter kinds
embed.view · ai.question · ai.tokens (+ plan events)
## Audit action families (export via /enterprise/audit/export)
auth/sso/scim.* · tenant.* · dataset.*/governance.*/pii.scan ·
dashboard.*(+snapshot) · embed.token/view/query/edit · ai.*(question/agent/
orchestrate/llm/injection_blocked) · plan.*/approval.* · ml.* ·
security.break_glass/impersonation · legal_hold.set · connection.rotate ·
access_review.* · semantic.model/measure.update
Consumers: SIEM stream (cursor'd), audit exports, Activity page.
