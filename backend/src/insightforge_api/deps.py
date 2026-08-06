"""Request dependencies: bearer auth -> TenantContext -> RLS-armed session."""

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text

from .db import session_factory
from .roles import role_allows
from .security import decode_access_token


@dataclass
class TenantContext:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    correlation_id: str


def get_context(request: Request) -> TenantContext:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    claims = decode_access_token(auth[7:])
    if claims is None:
        raise HTTPException(401, "Session expired — log in again")
    return TenantContext(
        user_id=uuid.UUID(claims["sub"]), tenant_id=uuid.UUID(claims["tid"]),
        role=claims["role"], correlation_id=getattr(request.state, "correlation_id", ""),
    )


def require(permission: str):
    def checker(ctx: TenantContext = Depends(get_context)) -> TenantContext:
        if not role_allows(ctx.role, permission):
            raise HTTPException(403, f"Your role ({ctx.role}) cannot perform this action")
        return ctx

    return checker


async def get_session(ctx: TenantContext = Depends(get_context)):
    """Tenant-scoped DB session. RLS GUCs are transaction-local; handlers that
    mutate call `await session.commit()` themselves right before returning so a
    scripted client's next request is guaranteed to see the write (dependency
    teardown runs only after the response is sent). The teardown commit below
    is a safety net for read paths and is a no-op after an explicit commit."""
    async with session_factory()() as s:
        await s.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(ctx.tenant_id)},
        )
        await s.execute(
            text("SELECT set_config('app.user_id', :uid, true)"),
            {"uid": str(ctx.user_id)},
        )
        try:
            yield s
            if s.in_transaction():
                await s.commit()
        except BaseException:
            if s.in_transaction():
                await s.rollback()
            raise
