from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings

engine = create_async_engine(
    str(settings.database_url),
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    echo=settings.debug,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def create_worker_session_maker():
    """Create a fresh engine and session maker for worker tasks.

    This is needed because Celery workers run in a different event loop
    than where the global engine was created.
    """
    worker_engine = create_async_engine(
        str(settings.database_url),
        pool_size=5,
        max_overflow=10,
        echo=settings.debug,
    )
    return async_sessionmaker(
        worker_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize database tables."""
    from src.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
