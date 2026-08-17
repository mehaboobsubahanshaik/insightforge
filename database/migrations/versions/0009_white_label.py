"""MVP4 E3: white-label theme + custom domain per tenant."""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS "
               "theme jsonb NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS "
               "custom_domain varchar(255)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_tenants_custom_domain "
               "ON tenants (custom_domain) WHERE custom_domain IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_tenants_custom_domain")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS custom_domain")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS theme")
