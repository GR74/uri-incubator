from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from uri_backend.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    if settings.database_url is None:
        raise RuntimeError("URI_DATABASE_URL is required for PostgreSQL access.")
    if not settings.database_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("URI_DATABASE_URL must use postgresql+psycopg://.")
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
