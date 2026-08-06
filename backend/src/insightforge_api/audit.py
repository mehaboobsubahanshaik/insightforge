"""Immutable audit trail (INSERT-only; app_user has no DELETE anywhere)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditEvent


async def record(
    session: AsyncSession, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None,
    action: str, resource_type: str, resource_id: str = "", detail: dict | None = None,
    correlation_id: str = "",
) -> None:
    session.add(AuditEvent(
        tenant_id=tenant_id, actor_user_id=actor_user_id, action=action,
        resource_type=resource_type, resource_id=resource_id, detail=detail or {},
        correlation_id=correlation_id,
    ))
