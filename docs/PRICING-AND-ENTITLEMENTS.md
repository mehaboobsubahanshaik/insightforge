# Pricing & Entitlements

| | Free | Starter $49/mo | Growth $199/mo | Enterprise (contact us) |
|---|---|---|---|---|
| Datasets | 3 | 20 | 100 | custom |
| Members | 3 | 10 | 50 | custom |
| Connections | 1 | 5 | 20 | custom |
| Dashboards | 3 | 20 | 100 | custom |
| Min sync interval | daily (1440m) | hourly (60m) | 15m | 5m + priority workers |
| Scheduled reports | 1 | 10 | 50 | custom |
| Alert rules | 2 | 10 | 50 | custom |

**Enterprise** is a sales-assisted tier, not a self-serve plan row in the
database yet: SSO/SAML, custom limits, an uptime SLA, IP allowlists and audit
export land with the backlog items that implement them. Structurally it is
just another row in `plans` with bespoke `limits` JSON — no schema change —
which is why it stays out of the seeded plans until the first contract.

Enforcement is server-side in `services/entitlements.py`, checked at create
time and at schedule time (sync intervals clamp to the plan floor). Every
plan change emits a `billing.plan_changed` billing event + audit event —
invoicing providers (Stripe Billing) attach to that stream without schema
change. Meters are recorded per day in `meter_readings` for usage-based
add-ons later. Limits deliberately generous at Growth: the expansion lever is
sync frequency + seats, the two things growing SMBs actually hit.