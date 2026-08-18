"""R11: measure units + version history."""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE measures ADD COLUMN IF NOT EXISTS "
               "unit varchar(24)")
    op.execute("ALTER TABLE measures ADD COLUMN IF NOT EXISTS "
               "versions jsonb NOT NULL DEFAULT '[]'")


def downgrade() -> None:
    op.execute("ALTER TABLE measures DROP COLUMN IF EXISTS versions")
    op.execute("ALTER TABLE measures DROP COLUMN IF EXISTS unit")
