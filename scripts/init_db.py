#!/usr/bin/env python
"""Initialize database with default data."""

import asyncio
from decimal import Decimal

from sqlalchemy import select

from src.core.config import settings
from src.db.database import async_session_maker, init_db
from src.db.models.contribution import EventType
from src.db.models.scoring import ScoringWeight


DEFAULT_WEIGHTS = [
    (EventType.RELEASE.value, Decimal("30.0"), "Points for publishing a release"),
    (EventType.PR_MERGED.value, Decimal("25.0"), "Points for merged pull request"),
    (EventType.PR_REVIEWED.value, Decimal("20.0"), "Points for reviewing a pull request"),
    (EventType.PR_OPENED.value, Decimal("15.0"), "Points for opening a pull request"),
    (EventType.COMMIT.value, Decimal("10.0"), "Base points per commit"),
    (EventType.ISSUE_OPENED.value, Decimal("8.0"), "Points for opening an issue"),
    (EventType.ISSUE_CLOSED.value, Decimal("5.0"), "Points for closing an issue"),
    (EventType.PR_REVIEW_COMMENT.value, Decimal("5.0"), "Points for PR review comment"),
    (EventType.COMMENT.value, Decimal("3.0"), "Points per comment"),
]


async def init_scoring_weights() -> None:
    """Initialize default scoring weights."""
    async with async_session_maker() as session:
        # Check if weights already exist
        result = await session.execute(select(ScoringWeight))
        existing = result.scalars().first()

        if existing:
            print("Scoring weights already initialized")
            return

        for event_type, points, description in DEFAULT_WEIGHTS:
            weight = ScoringWeight(
                event_type=event_type,
                base_points=points,
                description=description,
            )
            session.add(weight)

        await session.commit()
        print(f"Initialized {len(DEFAULT_WEIGHTS)} scoring weights")


async def main() -> None:
    """Main initialization function."""
    print(f"Initializing database: {settings.database_url}")

    # Create tables
    await init_db()
    print("Database tables created")

    # Initialize default data
    await init_scoring_weights()

    print("Database initialization complete!")


if __name__ == "__main__":
    asyncio.run(main())
