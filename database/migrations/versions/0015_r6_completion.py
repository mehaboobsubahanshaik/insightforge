"""R6: alert lifecycle (ack/quiet-hours) + acknowledgment columns."""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE alert_rules ADD COLUMN IF NOT EXISTS "
               "lifecycle jsonb NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS "
               "acked_at timestamptz")
    op.execute("ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS "
               "acked_by uuid")


def downgrade() -> None:
    op.execute("ALTER TABLE alert_events DROP COLUMN IF EXISTS acked_by")
    op.execute("ALTER TABLE alert_events DROP COLUMN IF EXISTS acked_at")
    op.execute("ALTER TABLE alert_rules DROP COLUMN IF EXISTS lifecycle")
