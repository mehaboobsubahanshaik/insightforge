"""MVP3 chapter 4 (P2 notifications): tenant webhooks with HMAC-signed
delivery (generic / Slack / Teams formats), and anomaly-kind alert rules.
Append-only additive changes; idempotent guards.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS webhooks (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        name varchar(120) NOT NULL,
        url text NOT NULL,
        secret varchar(64) NOT NULL,
        format varchar(10) NOT NULL DEFAULT 'generic',
        events jsonb NOT NULL DEFAULT '[]',
        active boolean NOT NULL DEFAULT true,
        last_status varchar(255) NOT NULL DEFAULT '',
        last_delivery_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_webhooks_tenant "
               "ON webhooks (tenant_id)")
    op.execute("ALTER TABLE webhooks ENABLE ROW LEVEL SECURITY")
    for policy, clause in (
        ("tenant_isolation", "USING (tenant_id::text = "
         "current_setting('app.tenant_id', true))"),
        ("tenant_insert", "FOR INSERT WITH CHECK (tenant_id::text = "
         "current_setting('app.tenant_id', true))"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON webhooks")
        op.execute(f"CREATE POLICY {policy} ON webhooks {clause}")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON webhooks TO app_user")
    # anomaly alerts: additive columns on alert_rules
    op.execute("ALTER TABLE alert_rules ADD COLUMN IF NOT EXISTS "
               "kind varchar(12) NOT NULL DEFAULT 'threshold'")
    op.execute("ALTER TABLE alert_rules ADD COLUMN IF NOT EXISTS "
               "date_column varchar(63)")


def downgrade() -> None:
    op.execute("ALTER TABLE alert_rules DROP COLUMN IF EXISTS date_column")
    op.execute("ALTER TABLE alert_rules DROP COLUMN IF EXISTS kind")
    op.execute("DROP TABLE IF EXISTS webhooks")
