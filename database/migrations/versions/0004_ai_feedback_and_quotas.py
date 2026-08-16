"""MVP3 chapter 3: ai_feedback table (thumbs on AI answers/briefs, RLS'd)
and per-plan daily AI-question quotas appended to plan limits.
Append-only per ADR 0004; idempotent guards for early dev databases.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS ai_feedback (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        user_id uuid NOT NULL,
        kind varchar(20) NOT NULL,
        subject text NOT NULL,
        helpful boolean NOT NULL,
        comment text,
        created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_feedback_tenant "
               "ON ai_feedback (tenant_id, created_at)")
    op.execute("ALTER TABLE ai_feedback ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_feedback")
    op.execute("CREATE POLICY tenant_isolation ON ai_feedback USING "
               "(tenant_id::text = current_setting('app.tenant_id', true))")
    op.execute("DROP POLICY IF EXISTS tenant_insert ON ai_feedback")
    op.execute("CREATE POLICY tenant_insert ON ai_feedback FOR INSERT "
               "WITH CHECK (tenant_id::text = "
               "current_setting('app.tenant_id', true))")
    op.execute("GRANT SELECT, INSERT ON ai_feedback TO app_user")
    # cost control: per-plan daily AI question allowance
    op.execute("UPDATE plans SET limits = limits || "
               "'{\"ai_questions_per_day\": 50}' WHERE code = 'free'")
    op.execute("UPDATE plans SET limits = limits || "
               "'{\"ai_questions_per_day\": 500}' WHERE code = 'starter'")
    op.execute("UPDATE plans SET limits = limits || "
               "'{\"ai_questions_per_day\": 5000}' WHERE code = 'growth'")


def downgrade() -> None:
    op.execute("UPDATE plans SET limits = limits - 'ai_questions_per_day'")
    op.execute("DROP TABLE IF EXISTS ai_feedback")
