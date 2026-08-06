"""Session management with tenant context. Every request-scoped session sets
the transaction-local GUC `app.tenant_id` that RLS policies key on — tenant
identity always derives from the authenticated token, never from client input."""

import uuid
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .config import database_url


@lru_cache(maxsize=1)
def engine():
    return create_async_engine(database_url(), pool_pre_ping=True)


@lru_cache(maxsize=1)
def session_factory():
    return async_sessionmaker(engine(), expire_on_commit=False)


@asynccontextmanager
async def tenant_scoped_session(tenant_id: uuid.UUID):
    async with session_factory()() as s:
        async with s.begin():
            await s.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
            )
            yield s


@asynccontextmanager
async def user_scoped_session(user_id: uuid.UUID):
    """Pre-tenant context (login, invitation acceptance): only membership/
    tenant rows belonging to this user are visible."""
    async with session_factory()() as s:
        async with s.begin():
            await s.execute(
                text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)}
            )
            yield s


@asynccontextmanager
async def bootstrap_session(tenant_id: uuid.UUID):
    async with tenant_scoped_session(tenant_id) as s:
        yield s
