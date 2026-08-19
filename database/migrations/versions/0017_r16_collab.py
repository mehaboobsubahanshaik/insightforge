"""R16: widget-anchored annotations on comments."""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE comments ADD COLUMN IF NOT EXISTS "
               "widget_anchor integer")


def downgrade() -> None:
    op.execute("ALTER TABLE comments DROP COLUMN IF EXISTS widget_anchor")
