"""MVP5 G5: ML model registry (forecast/scenario/external)."""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS ml_models (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        name varchar(120) NOT NULL,
        kind varchar(16) NOT NULL,
        dataset_id uuid,
        config jsonb NOT NULL DEFAULT '{}',
        metrics jsonb NOT NULL DEFAULT '{}',
        status varchar(12) NOT NULL DEFAULT 'active',
        created_at timestamptz NOT NULL DEFAULT now(),
        evaluated_at timestamptz
    )""")
    op.execute("ALTER TABLE ml_models ENABLE ROW LEVEL SECURITY")
    for p, c in (("tenant_isolation", "USING (tenant_id::text = "
                  "current_setting('app.tenant_id', true))"),
                 ("tenant_insert", "FOR INSERT WITH CHECK "
                  "(tenant_id::text = "
                  "current_setting('app.tenant_id', true))")):
        op.execute(f"DROP POLICY IF EXISTS {p} ON ml_models")
        op.execute(f"CREATE POLICY {p} ON ml_models {c}")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ml_models TO app_user")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_models")
