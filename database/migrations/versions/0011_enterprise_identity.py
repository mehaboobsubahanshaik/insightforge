"""MVP5 G1: SSO/SCIM config, member attributes (ABAC), access reviews."""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS sso jsonb "
               "NOT NULL DEFAULT '{}'")  # {entity_id, sso_url, cert_digest}
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS "
               "scim_token_hash varchar(64)")
    op.execute("ALTER TABLE memberships ADD COLUMN IF NOT EXISTS "
               "attributes jsonb NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS "
               "access_policy jsonb NOT NULL DEFAULT '{}'")
    op.execute("""
    CREATE TABLE IF NOT EXISTS access_reviews (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        status varchar(12) NOT NULL DEFAULT 'open',
        items jsonb NOT NULL DEFAULT '[]',
        created_by uuid NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        closed_at timestamptz
    )""")
    op.execute("ALTER TABLE access_reviews ENABLE ROW LEVEL SECURITY")
    for p, c in (("tenant_isolation", "USING (tenant_id::text = "
                  "current_setting('app.tenant_id', true))"),
                 ("tenant_insert", "FOR INSERT WITH CHECK (tenant_id::text = "
                  "current_setting('app.tenant_id', true))")):
        op.execute(f"DROP POLICY IF EXISTS {p} ON access_reviews")
        op.execute(f"CREATE POLICY {p} ON access_reviews {c}")
    op.execute("GRANT SELECT, INSERT, UPDATE ON access_reviews TO app_user")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS access_reviews")
    op.execute("ALTER TABLE datasets DROP COLUMN IF EXISTS access_policy")
    op.execute("ALTER TABLE memberships DROP COLUMN IF EXISTS attributes")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS scim_token_hash")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS sso")
