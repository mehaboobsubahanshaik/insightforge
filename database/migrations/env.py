import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

DSN = os.environ.get("DATABASE_URL") or os.environ.get(
    "ALEMBIC_DSN", "postgresql+asyncpg://postgres:devpassword@127.0.0.1:5432/insightforge"
)


def run_migrations_online() -> None:
    engine = create_async_engine(DSN)

    def do_migrations(conn):
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()

    async def run():
        async with engine.connect() as conn:
            await conn.run_sync(do_migrations)
            await conn.commit()
        await engine.dispose()

    asyncio.run(run())


run_migrations_online()
