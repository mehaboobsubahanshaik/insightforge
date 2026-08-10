"""MFA recovery codes: users.mfa_recovery_codes stores SHA-256 hashes of
one-time recovery codes (JSONB list). Plaintext codes are shown to the user
exactly once at generation and are never stored. Append-only per ADR 0004.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS "
               "mfa_recovery_codes JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS mfa_recovery_codes")