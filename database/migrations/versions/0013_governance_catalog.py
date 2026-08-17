"""MVP5 G3: business glossary + approval workflows."""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

TBLS = {
    "glossary_terms": """
    CREATE TABLE IF NOT EXISTS glossary_terms (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        term varchar(120) NOT NULL,
        definition text NOT NULL,
        steward varchar(320) NOT NULL DEFAULT '',
        links jsonb NOT NULL DEFAULT '[]',
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (tenant_id, term)
    )""",
    "approvals": """
    CREATE TABLE IF NOT EXISTS approvals (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        kind varchar(32) NOT NULL,
        subject_id varchar(64) NOT NULL,
        note text NOT NULL DEFAULT '',
        status varchar(12) NOT NULL DEFAULT 'pending',
        requested_by uuid NOT NULL,
        decided_by uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        decided_at timestamptz
    )""",
}


def upgrade() -> None:
    for name, ddl in TBLS.items():
        op.execute(ddl)
        op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
        for p, c in (("tenant_isolation", "USING (tenant_id::text = "
                      "current_setting('app.tenant_id', true))"),
                     ("tenant_insert", "FOR INSERT WITH CHECK "
                      "(tenant_id::text = "
                      "current_setting('app.tenant_id', true))")):
            op.execute(f"DROP POLICY IF EXISTS {p} ON {name}")
            op.execute(f"CREATE POLICY {p} ON {name} {c}")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} "
                   "TO app_user")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS approvals")
    op.execute("DROP TABLE IF EXISTS glossary_terms")
