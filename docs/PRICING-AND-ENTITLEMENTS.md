# Pricing & Entitlements

| | Free | Starter $49/mo | Growth $199/mo |
|---|---|---|---|
| Datasets | 3 | 20 | 100 |
| Members | 3 | 10 | 50 |
| Connections | 1 | 5 | 20 |
| Dashboards | 3 | 20 | 100 |
| Min sync interval | daily (1440m) | hourly (60m) | 15m |
| Scheduled reports | 1 | 10 | 50 |
| Alert rules | 2 | 10 | 50 |

Enforcement is server-side in `services/entitlements.py`, checked at create
time and at schedule time (sync intervals clamp to the plan floor). Every
plan change emits a `billing.plan_changed` billing event + audit event —
invoicing providers (Stripe Billing) attach to that stream without schema
change. Meters are recorded per day in `meter_readings` for usage-based
add-ons later. Limits deliberately generous at Growth: the expansion lever is
sync frequency + seats, the two things growing SMBs actually hit.
