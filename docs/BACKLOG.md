# Backlog (post-MVP2, ordered)

1. **Snowflake/BigQuery/ClickHouse tiles** — catalog rows + engine adapters.
2. Workspace archive + retention policies (extends the workspace model).
3. Report themes + logo upload for PDF branding.
4. Seasonal forecasting (Holt-Winters triple smoothing) behind the same
   `forecast_series()` contract (ADR 0011 upgrade path).
5. Alert channels: Slack webhook + generic webhook alongside email.
6. Dataset joins in the semantic layer (measure across datasets).
7. SSO (Google Workspace first — SMB reality), then SAML.
8. Row-level permissions within a tenant (viewer sees region X only).
9. Usage-based billing hooks from meter_readings → Stripe.
10. Import diffing UI ("what changed between generations 4 and 5?").
