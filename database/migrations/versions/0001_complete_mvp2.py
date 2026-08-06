"""InsightForge complete MVP 2 schema, RLS policies, app role, plan seeds.

Security model:
- app_user: NOBYPASSRLS, SELECT/INSERT/UPDATE only (no DELETE anywhere;
  destructive flows use archived/revoked flags -> auditable, reversible).
- RLS on every tenant-owned table keyed on transaction-local GUC app.tenant_id.
- Special arms (each a lesson baked in from the previous build):
  * tenants: visible via membership of app.user_id (login slug resolution)
  * memberships: user arm (pre-tenant login context)
  * invitations: token-hash arm (unauthenticated acceptance)
  * share_links: token-hash arm (public dashboard viewing)
  * sync_schedules/report_schedules/alert_rules: job_runner READ arm
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

T = "nullif(current_setting('app.tenant_id', true), '')::uuid"
U = "nullif(current_setting('app.user_id', true), '')::uuid"
JOB = "current_setting('app.job_runner', true) = 'true'"


def upgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user LOGIN PASSWORD 'app_dev_password' NOBYPASSRLS;
      END IF;
    END $$""")

    op.execute("""
    CREATE TABLE users (
      id uuid PRIMARY KEY, email varchar(320) NOT NULL UNIQUE,
      display_name varchar(255) NOT NULL, password_hash varchar(255) NOT NULL,
      mfa_secret varchar(64), mfa_enabled boolean NOT NULL DEFAULT false,
      email_verified boolean NOT NULL DEFAULT false, email_verify_hash varchar(64),
      reset_hash varchar(64), reset_expires timestamptz,
      created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE TABLE refresh_tokens (
      id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id),
      token_hash varchar(64) NOT NULL UNIQUE, expires_at timestamptz NOT NULL,
      revoked boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE INDEX ix_refresh_user ON refresh_tokens(user_id)""")
    op.execute("""
    CREATE TABLE tenants (
      id uuid PRIMARY KEY, slug varchar(63) NOT NULL UNIQUE, name varchar(255) NOT NULL,
      status varchar(32) NOT NULL DEFAULT 'active',
      plan_code varchar(32) NOT NULL DEFAULT 'free',
      features jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE TABLE memberships (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      user_id uuid NOT NULL REFERENCES users(id), role varchar(32) NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (tenant_id, user_id))""")
    op.execute("""
    CREATE INDEX ix_memberships_tenant ON memberships(tenant_id)""")
    op.execute("""
    CREATE INDEX ix_memberships_user ON memberships(user_id)""")
    op.execute("""
    CREATE TABLE invitations (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL, email varchar(320) NOT NULL,
      role varchar(32) NOT NULL, token_hash varchar(64) NOT NULL UNIQUE,
      expires_at timestamptz NOT NULL, accepted boolean NOT NULL DEFAULT false,
      created_by uuid NOT NULL REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE TABLE workspaces (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL, name varchar(255) NOT NULL,
      archived boolean NOT NULL DEFAULT false,
      created_by uuid NOT NULL REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (tenant_id, name))""")
    op.execute("""
    CREATE TABLE datasets (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      workspace_id uuid NOT NULL REFERENCES workspaces(id), name varchar(255) NOT NULL,
      source_type varchar(32) NOT NULL, connection_id uuid,
      schema_def jsonb NOT NULL DEFAULT '[]'::jsonb,
      row_count integer NOT NULL DEFAULT 0, quarantined_count integer NOT NULL DEFAULT 0,
      quality_score integer, profile jsonb NOT NULL DEFAULT '{}'::jsonb,
      recipe jsonb NOT NULL DEFAULT '[]'::jsonb,
      current_import_id uuid, ingested_at timestamptz,
      archived boolean NOT NULL DEFAULT false,
      created_by uuid NOT NULL REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE INDEX ix_datasets_tenant ON datasets(tenant_id)""")
    op.execute("""
    CREATE TABLE dataset_rows (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      dataset_id uuid NOT NULL REFERENCES datasets(id), import_id uuid NOT NULL,
      row_index integer NOT NULL, data jsonb NOT NULL,
      is_quarantined boolean NOT NULL DEFAULT false,
      quarantine_reason varchar(255) NOT NULL DEFAULT '')""")
    op.execute("""
    CREATE INDEX ix_rows_dataset_import ON dataset_rows(dataset_id, import_id)""")
    op.execute("""
    CREATE INDEX ix_rows_tenant ON dataset_rows(tenant_id)""")
    op.execute("""
    CREATE TABLE dq_results (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      dataset_id uuid NOT NULL REFERENCES datasets(id), import_id uuid NOT NULL,
      rule varchar(16) NOT NULL, severity varchar(16) NOT NULL,
      affected integer NOT NULL DEFAULT 0, detail jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE TABLE dq_history (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      dataset_id uuid NOT NULL REFERENCES datasets(id), score integer NOT NULL,
      row_count integer NOT NULL, quarantined_count integer NOT NULL,
      recorded_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE TABLE connections (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      workspace_id uuid NOT NULL REFERENCES workspaces(id), name varchar(255) NOT NULL,
      connector_type varchar(32) NOT NULL, config jsonb NOT NULL DEFAULT '{}'::jsonb,
      credentials_enc text NOT NULL DEFAULT '', status varchar(16) NOT NULL DEFAULT 'active',
      sync_cursor varchar(255), last_sync_at timestamptz,
      consecutive_failures integer NOT NULL DEFAULT 0, last_error text NOT NULL DEFAULT '',
      created_by uuid NOT NULL REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (tenant_id, name))""")
    op.execute("""
    CREATE TABLE sync_schedules (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      connection_id uuid NOT NULL UNIQUE REFERENCES connections(id),
      interval_minutes integer NOT NULL DEFAULT 1440, enabled boolean NOT NULL DEFAULT true,
      next_run_at timestamptz NOT NULL DEFAULT now(), last_run_at timestamptz)""")
    op.execute("""
    CREATE TABLE sync_runs (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      connection_id uuid NOT NULL REFERENCES connections(id), dataset_id uuid,
      mode varchar(16) NOT NULL, trigger varchar(16) NOT NULL, status varchar(16) NOT NULL,
      rows_extracted integer NOT NULL DEFAULT 0, rows_loaded integer NOT NULL DEFAULT 0,
      error text NOT NULL DEFAULT '', started_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz)""")
    op.execute("""
    CREATE INDEX ix_runs_connection ON sync_runs(connection_id)""")
    op.execute("""
    CREATE TABLE measures (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      dataset_id uuid NOT NULL REFERENCES datasets(id), name varchar(255) NOT NULL,
      formula varchar(500) NOT NULL, description varchar(500) NOT NULL DEFAULT '',
      certified boolean NOT NULL DEFAULT false,
      created_by uuid NOT NULL REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, dataset_id, name))""")
    op.execute("""
    CREATE TABLE dashboards (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      workspace_id uuid NOT NULL REFERENCES workspaces(id), name varchar(255) NOT NULL,
      widgets jsonb NOT NULL DEFAULT '[]'::jsonb, status varchar(16) NOT NULL DEFAULT 'draft',
      published_version integer, archived boolean NOT NULL DEFAULT false,
      created_by uuid NOT NULL REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE TABLE dashboard_versions (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      dashboard_id uuid NOT NULL REFERENCES dashboards(id), version integer NOT NULL,
      widgets jsonb NOT NULL DEFAULT '[]'::jsonb,
      published_by uuid NOT NULL REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, dashboard_id, version))""")
    op.execute("""
    CREATE TABLE dashboard_views (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      dashboard_id uuid NOT NULL REFERENCES dashboards(id), name varchar(255) NOT NULL,
      filters jsonb NOT NULL DEFAULT '[]'::jsonb, shared boolean NOT NULL DEFAULT false,
      archived boolean NOT NULL DEFAULT false,
      created_by uuid NOT NULL REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE TABLE comments (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      dashboard_id uuid NOT NULL REFERENCES dashboards(id),
      author_id uuid NOT NULL REFERENCES users(id), parent_id uuid, body text NOT NULL,
      mentions jsonb NOT NULL DEFAULT '[]'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE TABLE share_links (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      dashboard_id uuid NOT NULL REFERENCES dashboards(id),
      token_hash varchar(64) NOT NULL UNIQUE, expires_at timestamptz NOT NULL,
      revoked boolean NOT NULL DEFAULT false,
      created_by uuid NOT NULL REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE TABLE report_schedules (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      dashboard_id uuid NOT NULL REFERENCES dashboards(id),
      recipients jsonb NOT NULL DEFAULT '[]'::jsonb,
      interval_minutes integer NOT NULL DEFAULT 1440, enabled boolean NOT NULL DEFAULT true,
      next_run_at timestamptz NOT NULL DEFAULT now(), last_run_at timestamptz,
      last_status varchar(16) NOT NULL DEFAULT '',
      created_by uuid NOT NULL REFERENCES users(id))""")
    op.execute("""
    CREATE TABLE alert_rules (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      dataset_id uuid NOT NULL REFERENCES datasets(id), name varchar(255) NOT NULL,
      formula varchar(500) NOT NULL, operator varchar(8) NOT NULL,
      threshold double precision NOT NULL, interval_minutes integer NOT NULL DEFAULT 60,
      enabled boolean NOT NULL DEFAULT true, recipients jsonb NOT NULL DEFAULT '[]'::jsonb,
      next_check_at timestamptz NOT NULL DEFAULT now(),
      last_state varchar(8) NOT NULL DEFAULT 'ok',
      created_by uuid NOT NULL REFERENCES users(id))""")
    op.execute("""
    CREATE TABLE alert_events (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
      rule_id uuid NOT NULL REFERENCES alert_rules(id), value double precision,
      message text NOT NULL DEFAULT '', fired_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE TABLE email_outbox (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL, to_email varchar(320) NOT NULL,
      subject varchar(500) NOT NULL, body text NOT NULL,
      kind varchar(32) NOT NULL DEFAULT 'generic', attachment_name varchar(255),
      status varchar(16) NOT NULL DEFAULT 'queued',
      created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE TABLE plans (
      code varchar(32) PRIMARY KEY, name varchar(64) NOT NULL,
      limits jsonb NOT NULL DEFAULT '{}'::jsonb,
      monthly_price_usd double precision NOT NULL DEFAULT 0)""")
    op.execute("""
    CREATE TABLE billing_events (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL, kind varchar(32) NOT NULL,
      quantity double precision NOT NULL DEFAULT 1,
      meta jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE TABLE meter_readings (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL, meter varchar(64) NOT NULL,
      value double precision NOT NULL, recorded_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE TABLE audit_events (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL, actor_user_id uuid,
      action varchar(64) NOT NULL, resource_type varchar(32) NOT NULL,
      resource_id varchar(64) NOT NULL DEFAULT '',
      detail jsonb NOT NULL DEFAULT '{}'::jsonb,
      correlation_id varchar(64) NOT NULL DEFAULT '',
      created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""
    CREATE INDEX ix_audit_tenant_time ON audit_events(tenant_id, created_at)""")

    # ---------------- RLS ----------------
    plain = ["workspaces", "datasets", "dataset_rows", "dq_results", "dq_history",
             "connections", "sync_runs", "measures", "dashboards", "dashboard_versions",
             "dashboard_views", "comments", "alert_events", "email_outbox",
             "billing_events", "meter_readings", "audit_events"]
    for t in plain:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} "
                   f"USING (tenant_id = {T}) WITH CHECK (tenant_id = {T})")
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute(f"""CREATE POLICY tenant_isolation ON tenants USING (
        id = {T} OR id IN (SELECT tenant_id FROM memberships WHERE user_id = {U})
      ) WITH CHECK (id = {T})""")
    op.execute("ALTER TABLE memberships ENABLE ROW LEVEL SECURITY")
    op.execute(f"""CREATE POLICY tenant_isolation ON memberships USING (
        tenant_id = {T} OR user_id = {U}) WITH CHECK (tenant_id = {T})""")
    op.execute("ALTER TABLE invitations ENABLE ROW LEVEL SECURITY")
    op.execute(f"""CREATE POLICY tenant_isolation ON invitations USING (
        tenant_id = {T} OR token_hash = current_setting('app.invite_token_hash', true)
      ) WITH CHECK (tenant_id = {T})""")
    op.execute("ALTER TABLE share_links ENABLE ROW LEVEL SECURITY")
    op.execute(f"""CREATE POLICY tenant_isolation ON share_links USING (
        tenant_id = {T} OR token_hash = current_setting('app.share_token_hash', true)
      ) WITH CHECK (tenant_id = {T})""")
    for t in ("sync_schedules", "report_schedules", "alert_rules"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} "
                   f"USING (tenant_id = {T} OR {JOB}) WITH CHECK (tenant_id = {T})")

    # Identity tables: GUC-armed RLS so even the restricted role sees only
    # what the current request legitimately needs (self, pre-auth lookup by
    # email/token, or members of the armed tenant).
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute(f"""CREATE POLICY identity_access ON users USING (
        id = {U}
        OR email = current_setting('app.login_email', true)
        OR reset_hash = current_setting('app.reset_hash', true)
        OR EXISTS (SELECT 1 FROM memberships m
                   WHERE m.user_id = users.id AND m.tenant_id = {T})
      )""")
    op.execute("CREATE POLICY identity_insert ON users FOR INSERT WITH CHECK (true)")
    op.execute("ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY")
    op.execute(f"""CREATE POLICY identity_access ON refresh_tokens USING (
        user_id = {U}
        OR token_hash = current_setting('app.refresh_token_hash', true)
      )""")
    op.execute(
        "CREATE POLICY identity_insert ON refresh_tokens FOR INSERT WITH CHECK (true)")

    op.execute("GRANT USAGE ON SCHEMA public TO app_user")
    op.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO app_user")
    op.execute("REVOKE INSERT, UPDATE ON plans FROM app_user")  # catalog is read-only

    op.execute("""
    INSERT INTO plans (code, name, limits, monthly_price_usd) VALUES
    ('free',   'Free',    '{"datasets": 3,  "members": 3,  "connections": 1,
                            "dashboards": 3,  "min_sync_interval": 1440,
                            "reports": 1,  "alerts": 2}', 0),
    ('starter','Starter', '{"datasets": 20, "members": 10, "connections": 5,
                            "dashboards": 20, "min_sync_interval": 60,
                            "reports": 10, "alerts": 20}', 49),
    ('growth', 'Growth',  '{"datasets": 100,"members": 50, "connections": 20,
                            "dashboards": 100,"min_sync_interval": 15,
                            "reports": 50, "alerts": 100}', 199)""")


def downgrade() -> None:
    for t in ("audit_events", "meter_readings", "billing_events", "plans", "email_outbox",
              "alert_events", "alert_rules", "report_schedules", "share_links", "comments",
              "dashboard_views", "dashboard_versions", "dashboards", "measures", "sync_runs",
              "sync_schedules", "connections", "dq_history", "dq_results", "dataset_rows",
              "datasets", "workspaces", "invitations", "memberships", "tenants",
              "refresh_tokens", "users"):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
