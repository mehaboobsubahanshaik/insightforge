"""MVP3 P3 commercial: trial fields, offboarding fields, invoices table."""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS "
               "trial_ends_at timestamptz")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS "
               "deletion_due_at timestamptz")
    op.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        period_start date NOT NULL,
        period_end date NOT NULL,
        plan_code varchar(32) NOT NULL,
        amount_usd numeric(10,2) NOT NULL,
        line_items jsonb NOT NULL DEFAULT '[]',
        status varchar(12) NOT NULL DEFAULT 'issued',
        issued_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoices_tenant "
               "ON invoices (tenant_id, period_start)")
    op.execute("ALTER TABLE invoices ENABLE ROW LEVEL SECURITY")
    for policy, clause in (
        ("tenant_isolation", "USING (tenant_id::text = "
         "current_setting('app.tenant_id', true))"),
        ("tenant_insert", "FOR INSERT WITH CHECK (tenant_id::text = "
         "current_setting('app.tenant_id', true))"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON invoices")
        op.execute(f"CREATE POLICY {policy} ON invoices {clause}")
    op.execute("GRANT SELECT, INSERT ON invoices TO app_user")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS invoices")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS deletion_due_at")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS trial_ends_at")
