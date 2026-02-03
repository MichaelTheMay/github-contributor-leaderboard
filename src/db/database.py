from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import settings

# =============================================================================
# Async Engine & Session (for FastAPI)
# =============================================================================
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
    """Create a fresh async engine and session maker for worker tasks.

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


# =============================================================================
# Sync Engine & Session (for Celery workers)
# =============================================================================
_sync_engine = None
_sync_session_maker = None


def _get_sync_database_url() -> str:
    """Convert async database URL to sync (replace asyncpg with psycopg2-binary)."""
    url = str(settings.database_url)
    # postgresql+asyncpg:// -> postgresql+psycopg2://
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg2")
    # postgresql:// -> postgresql+psycopg2://
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://")
    return url


def get_sync_engine():
    """Get or create the sync database engine (lazy initialization).

    This is lazily initialized to avoid import errors when psycopg2 is not installed.
    """
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            _get_sync_database_url(),
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=settings.debug,
        )
    return _sync_engine


def get_sync_session_maker():
    """Get or create the sync session maker (lazy initialization)."""
    global _sync_session_maker
    if _sync_session_maker is None:
        _sync_session_maker = sessionmaker(
            bind=get_sync_engine(),
            expire_on_commit=False,
        )
    return _sync_session_maker


@contextmanager
def get_sync_db() -> Generator[Session, None, None]:
    """Context manager for synchronous database sessions.

    Usage in Celery tasks:
        with get_sync_db() as db:
            user = db.query(GitHubUser).filter(...).first()
            db.commit()

    Note: Requires psycopg2 or psycopg2-binary to be installed.
    Install with: pip install psycopg2-binary
    """
    session_maker = get_sync_session_maker()
    session = session_maker()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
