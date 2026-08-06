"""Additive migration: datasets.recipe column + identity-table RLS.

Written IDEMPOTENTLY on purpose: some development databases were created
from revision 0001 *before* these changes were folded into it (the squash
was amended pre-release — see ADR 0004). Whatever state a 0001 database is
in, this migration converges it; on databases created from the final 0001
it is a no-op. From this revision onward the schema history is append-only.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

U = "nullif(current_setting('app.user_id', true), '')::uuid"
T = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def _create_policy_if_missing(table: str, name: str, ddl: str) -> None:
    op.execute(f"""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid
            WHERE c.relname = '{table}' AND p.polname = '{name}'
        ) THEN
            {ddl};
        END IF;
    END $$;
    """)


def upgrade() -> None:
    op.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS recipe jsonb "
               "NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY")
    _create_policy_if_missing("users", "identity_access", f"""
        CREATE POLICY identity_access ON users USING (
            id = {U}
            OR email = current_setting('app.login_email', true)
            OR reset_hash = current_setting('app.reset_hash', true)
            OR EXISTS (SELECT 1 FROM memberships m
                       WHERE m.user_id = users.id AND m.tenant_id = {T}))""")
    _create_policy_if_missing("users", "identity_insert",
                              "CREATE POLICY identity_insert ON users "
                              "FOR INSERT WITH CHECK (true)")
    _create_policy_if_missing("refresh_tokens", "identity_access", f"""
        CREATE POLICY identity_access ON refresh_tokens USING (
            user_id = {U}
            OR token_hash = current_setting('app.refresh_token_hash', true))""")
    _create_policy_if_missing("refresh_tokens", "identity_insert",
                              "CREATE POLICY identity_insert ON refresh_tokens "
                              "FOR INSERT WITH CHECK (true)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS identity_access ON refresh_tokens")
    op.execute("DROP POLICY IF EXISTS identity_insert ON refresh_tokens")
    op.execute("DROP POLICY IF EXISTS identity_access ON users")
    op.execute("DROP POLICY IF EXISTS identity_insert ON users")
    op.execute("ALTER TABLE refresh_tokens DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE datasets DROP COLUMN IF EXISTS recipe")
