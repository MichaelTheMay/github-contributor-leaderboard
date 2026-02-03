"""Test configuration and fixtures.

This file contains fixtures used across all tests.
Integration test fixtures (db_session, client) are only loaded when needed.
"""

import asyncio
import os
from collections.abc import AsyncGenerator, Generator

import pytest


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Only import database-related modules when integration tests are run
# This allows unit tests to run without database configuration
def pytest_configure(config):
    """Register integration test marker."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring database"
    )


@pytest.fixture(scope="function")
def mock_settings(monkeypatch):
    """Mock settings for unit tests that don't need real configuration."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("BIGQUERY_PROJECT", "test-project")


# Integration test fixtures - only used by tests in tests/integration/
@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator:
    """Create a fresh database session for each integration test."""
    import pytest_asyncio
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from src.db.models import Base

    # Use environment variable if set, otherwise use local default
    TEST_DATABASE_URL = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/leaderboard_test",
    )

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    test_session_maker = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_maker() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await test_engine.dispose()


@pytest.fixture(scope="function")
async def client(db_session) -> AsyncGenerator:
    """Create a test client with overridden database dependency."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.api.app import create_app
    from src.db import get_db

    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
