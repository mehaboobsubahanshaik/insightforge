"""MVP5 G2: classification, column/row policies, retention, CMK config."""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS "
               "governance jsonb NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS "
               "cmk jsonb NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS cmk")
    op.execute("ALTER TABLE datasets DROP COLUMN IF EXISTS governance")
