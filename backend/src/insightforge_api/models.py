"""Single source of truth for the schema. Mirrors migration 0001 exactly.

Multi-tenant invariants:
- Every tenant-owned row carries tenant_id; RLS enforces it in PostgreSQL.
- The app connects as `app_user` (NOBYPASSRLS, no DELETE anywhere).
- users / refresh_tokens / plans are platform-scoped (no tenant_id).
"""

import os
import time
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uuid7() -> uuid.UUID:
    """Time-ordered UUIDv7 (RFC 9562) — sortable primary keys, index-friendly."""
    ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms << 80) | (0x7 << 76) | ((rand >> 62) & 0x0FFF) << 64 | (0b10 << 62) | (
        rand & 0x3FFFFFFFFFFFFFFF
    )
    return uuid.UUID(int=value)


class Base(DeclarativeBase):
    pass


def _pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)


def _tid():
    return mapped_column(UUID(as_uuid=True), index=True)


def _now():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_recovery_codes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verify_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reset_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reset_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _now()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = _pk()
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active")
    plan_code: Mapped[str] = mapped_column(String(32), default="free")
    features: Mapped[dict] = mapped_column(JSONB, default=dict)
    theme: Mapped[dict] = mapped_column(JSONB, default=dict)
    sso: Mapped[dict] = mapped_column(JSONB, default=dict)
    cmk: Mapped[dict] = mapped_column(JSONB, default=dict)
    scim_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True)
    parent_tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True)
    custom_domain: Mapped[str | None] = mapped_column(
        String(255), nullable=True)
    embed_secret: Mapped[str | None] = mapped_column(
        String(64), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    deletion_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _now()


class AccessReview(Base):
    __tablename__ = "access_reviews"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    status: Mapped[str] = mapped_column(String(12), default="open")
    items: Mapped[list] = mapped_column(JSONB, default=list)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _now()
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _now()


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    name: Mapped[str] = mapped_column(String(255))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(32))  # upload|connector
    connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    schema_def: Mapped[list] = mapped_column(JSONB, default=list)
    row_count: Mapped[int] = mapped_column(default=0)
    quarantined_count: Mapped[int] = mapped_column(default=0)
    quality_score: Mapped[int | None] = mapped_column(nullable=True)
    access_policy: Mapped[dict] = mapped_column(JSONB, default=dict)
    governance: Mapped[dict] = mapped_column(JSONB, default=dict)
    profile: Mapped[dict] = mapped_column(JSONB, default=dict)
    recipe: Mapped[list] = mapped_column(JSONB, default=list)
    current_import_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()


class DatasetRow(Base):
    """Append-only import generations: rows carry import_id; the dataset's
    current_import_id pointer flips atomically on successful (re)load."""

    __tablename__ = "dataset_rows"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"), index=True)
    import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    row_index: Mapped[int] = mapped_column()
    data: Mapped[dict] = mapped_column(JSONB)
    is_quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    quarantine_reason: Mapped[str] = mapped_column(String(255), default="")


class DQResult(Base):
    __tablename__ = "dq_results"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"), index=True)
    import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    rule: Mapped[str] = mapped_column(String(16))  # R001 missing | R002 duplicate | R003 type
    severity: Mapped[str] = mapped_column(String(16))
    affected: Mapped[int] = mapped_column(default=0)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _now()


class DQHistory(Base):
    __tablename__ = "dq_history"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"), index=True)
    score: Mapped[int] = mapped_column()
    row_count: Mapped[int] = mapped_column()
    quarantined_count: Mapped[int] = mapped_column()
    recorded_at: Mapped[datetime] = _now()


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String(255))
    connector_type: Mapped[str] = mapped_column(String(32))
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    credentials_enc: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active")
    sync_cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()


class SyncSchedule(Base):
    __tablename__ = "sync_schedules"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connections.id"), unique=True)
    interval_minutes: Mapped[int] = mapped_column(default=1440)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime] = _now()
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connections.id"), index=True)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    mode: Mapped[str] = mapped_column(String(16))  # incremental|full_refresh
    trigger: Mapped[str] = mapped_column(String(16))  # manual|scheduled
    status: Mapped[str] = mapped_column(String(16))  # succeeded|no_change|failed
    rows_extracted: Mapped[int] = mapped_column(default=0)
    rows_loaded: Mapped[int] = mapped_column(default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIFeedback(Base):
    """Thumbs up/down on AI outputs (questions, briefs, prep suggestions) —
    the raw material for evaluating and improving the AI layer."""

    __tablename__ = "ai_feedback"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(Text)
    helpful: Mapped[bool] = mapped_column(Boolean)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _now()


class Measure(Base):
    """Governed, reusable calculated measure — the semantic layer unit.
    Formulas are validated by services/formulas.py at write time."""

    __tablename__ = "measures"
    __table_args__ = (UniqueConstraint("tenant_id", "dataset_id", "name"),)
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    formula: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(String(500), default="")
    certified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()


class Dashboard(Base):
    __tablename__ = "dashboards"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String(255))
    widgets: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|published
    published_version: Mapped[int | None] = mapped_column(nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()


class DashboardVersion(Base):
    __tablename__ = "dashboard_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "dashboard_id", "version"),)
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    dashboard_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dashboards.id"), index=True)
    version: Mapped[int] = mapped_column()
    widgets: Mapped[list] = mapped_column(JSONB, default=list)
    published_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()


class DashboardView(Base):
    """Saved filter sets: personal by default, shareable with the team."""

    __tablename__ = "dashboard_views"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    dashboard_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dashboards.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    filters: Mapped[list] = mapped_column(JSONB, default=list)
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    dashboard_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dashboards.id"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = _now()


class ShareLink(Base):
    __tablename__ = "share_links"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    dashboard_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dashboards.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()


class ReportSchedule(Base):
    __tablename__ = "report_schedules"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    dashboard_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dashboards.id"), index=True)
    recipients: Mapped[list] = mapped_column(JSONB, default=list)
    interval_minutes: Mapped[int] = mapped_column(default=1440)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime] = _now()
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), default="")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class Webhook(Base):
    """Tenant notification endpoint: HMAC-signed event delivery (MVP3 P2)."""

    __tablename__ = "webhooks"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(Text)
    secret: Mapped[str] = mapped_column(String(64))
    format: Mapped[str] = mapped_column(String(10), default="generic")
    events: Mapped[list] = mapped_column(JSONB, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_status: Mapped[str] = mapped_column(String(255), default="")
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _now()


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    formula: Mapped[str] = mapped_column(String(500))
    operator: Mapped[str] = mapped_column(String(8))  # gt|gte|lt|lte
    threshold: Mapped[float] = mapped_column()
    lifecycle: Mapped[dict] = mapped_column(JSONB, default=dict)
    interval_minutes: Mapped[int] = mapped_column(default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    recipients: Mapped[list] = mapped_column(JSONB, default=list)
    next_check_at: Mapped[datetime] = _now()
    last_state: Mapped[str] = mapped_column(String(8), default="ok")  # ok|fired
    kind: Mapped[str] = mapped_column(String(12), default="threshold")  # threshold|anomaly
    date_column: Mapped[str | None] = mapped_column(String(63), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_rules.id"), index=True)
    value: Mapped[float | None] = mapped_column(nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    fired_at: Mapped[datetime] = _now()
    acked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    acked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True)


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    to_email: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32), default="generic")
    attachment_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    created_at: Mapped[datetime] = _now()


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    plan_code: Mapped[str] = mapped_column(String(32))
    amount_usd: Mapped[float] = mapped_column()
    line_items: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(12), default="issued")
    issued_at: Mapped[datetime] = _now()


class APIKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(12), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list] = mapped_column(JSONB, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _now()
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class TenantTemplate(Base):
    __tablename__ = "tenant_templates"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    name: Mapped[str] = mapped_column(String(120))
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _now()


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"
    __table_args__ = (UniqueConstraint("tenant_id", "term"),)
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    term: Mapped[str] = mapped_column(String(120))
    definition: Mapped[str] = mapped_column(Text)
    steward: Mapped[str] = mapped_column(String(320), default="")
    links: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = _now()


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    kind: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="pending")
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = _now()
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class MLModel(Base):
    __tablename__ = "ml_models"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="active")
    created_at: Mapped[datetime] = _now()
    evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class Plan(Base):
    __tablename__ = "plans"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    limits: Mapped[dict] = mapped_column(JSONB, default=dict)
    monthly_price_usd: Mapped[float] = mapped_column(default=0)


class BillingEvent(Base):
    __tablename__ = "billing_events"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    kind: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[float] = mapped_column(default=1)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _now()


class MeterReading(Base):
    __tablename__ = "meter_readings"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    meter: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column()
    recorded_at: Mapped[datetime] = _now()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tid()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(32))
    resource_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = _now()
