"""MVP4 E4: OEM tenant hierarchy, tenant templates, embed view quotas."""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS "
               "parent_tenant_id uuid REFERENCES tenants(id)")
    op.execute("""
    CREATE TABLE IF NOT EXISTS tenant_templates (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        name varchar(120) NOT NULL,
        config jsonb NOT NULL DEFAULT '{}',
        created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("ALTER TABLE tenant_templates ENABLE ROW LEVEL SECURITY")
    for policy, clause in (
        ("tenant_isolation", "USING (tenant_id::text = "
         "current_setting('app.tenant_id', true))"),
        ("tenant_insert", "FOR INSERT WITH CHECK (tenant_id::text = "
         "current_setting('app.tenant_id', true))"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON tenant_templates")
        op.execute(f"CREATE POLICY {policy} ON tenant_templates {clause}")
    op.execute("GRANT SELECT, INSERT, DELETE ON tenant_templates TO app_user")
    op.execute("UPDATE plans SET limits = limits || "
               "'{\"embed_views_per_day\": 500}' WHERE code = 'free'")
    op.execute("UPDATE plans SET limits = limits || "
               "'{\"embed_views_per_day\": 10000}' WHERE code = 'starter'")
    op.execute("UPDATE plans SET limits = limits || "
               "'{\"embed_views_per_day\": 100000}' WHERE code = 'growth'")


def downgrade() -> None:
    op.execute("UPDATE plans SET limits = limits - 'embed_views_per_day'")
    op.execute("DROP TABLE IF EXISTS tenant_templates")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS parent_tenant_id")
