"""MVP3 P5: scoped API keys for the public API."""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS api_keys (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        name varchar(120) NOT NULL,
        prefix varchar(12) NOT NULL UNIQUE,
        key_hash varchar(64) NOT NULL,
        scopes jsonb NOT NULL DEFAULT '["data:read"]',
        active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(),
        last_used_at timestamptz
    )""")
    op.execute("ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY")
    for policy, clause in (
        ("tenant_isolation", "USING (tenant_id::text = "
         "current_setting('app.tenant_id', true))"),
        ("tenant_insert", "FOR INSERT WITH CHECK (tenant_id::text = "
         "current_setting('app.tenant_id', true))"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON api_keys")
        op.execute(f"CREATE POLICY {policy} ON api_keys {clause}")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON api_keys TO app_user")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS api_keys")
