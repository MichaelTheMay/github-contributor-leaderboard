from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.scoring import ScoringWeightCreate
from src.core.config import settings
from src.db.models.contribution import EventType
from src.db.models.scoring import ScoringWeight

logger = structlog.get_logger()


DEFAULT_WEIGHTS = {
    EventType.COMMIT.value: (settings.default_commit_points, "Points per commit"),
    EventType.PR_OPENED.value: (settings.default_pr_opened_points, "Points for opening a PR"),
    EventType.PR_MERGED.value: (settings.default_pr_merged_points, "Points for merged PR"),
    EventType.PR_REVIEWED.value: (settings.default_pr_reviewed_points, "Points for PR review"),
    EventType.PR_REVIEW_COMMENT.value: (5.0, "Points for PR review comment"),
    EventType.ISSUE_OPENED.value: (
        settings.default_issue_opened_points,
        "Points for opening issue",
    ),
    EventType.ISSUE_CLOSED.value: (
        settings.default_issue_closed_points,
        "Points for closing issue",
    ),
    EventType.COMMENT.value: (settings.default_comment_points, "Points per comment"),
    EventType.RELEASE.value: (settings.default_release_points, "Points for publishing release"),
}


class ScoringService:
    """Service for managing scoring weights and calculations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all_weights(self) -> list[ScoringWeight]:
        """Get all scoring weights, initializing defaults if needed."""
        result = await self.db.execute(select(ScoringWeight))
        weights = list(result.scalars().all())

        # Initialize defaults if empty
        if not weights:
            weights = await self._initialize_defaults()

        return weights

    async def _initialize_defaults(self) -> list[ScoringWeight]:
        """Initialize default scoring weights."""
        weights = []
        for event_type, (points, description) in DEFAULT_WEIGHTS.items():
            weight = ScoringWeight(
                event_type=event_type,
                base_points=Decimal(str(points)),
                description=description,
            )
            self.db.add(weight)
            weights.append(weight)

        await self.db.flush()
        logger.info("Initialized default scoring weights")
        return weights

    async def get_weight(self, event_type: str) -> ScoringWeight | None:
        """Get scoring weight for a specific event type."""
        result = await self.db.execute(
            select(ScoringWeight).where(ScoringWeight.event_type == event_type)
        )
        return result.scalar_one_or_none()

    async def update_weights(
        self,
        weights: list[ScoringWeightCreate],
    ) -> list[ScoringWeight]:
        """Update scoring weights and trigger leaderboard recalculation."""
        updated = []

        for weight_data in weights:
            existing = await self.get_weight(weight_data.event_type)
            if existing:
                existing.base_points = weight_data.base_points
                if weight_data.description:
                    existing.description = weight_data.description
                updated.append(existing)
            else:
                new_weight = ScoringWeight(
                    event_type=weight_data.event_type,
                    base_points=weight_data.base_points,
                    description=weight_data.description,
                )
                self.db.add(new_weight)
                updated.append(new_weight)

        await self.db.flush()
        logger.info("Scoring weights updated", count=len(updated))

        # Trigger leaderboard recalculation (would be async task in production)
        # await self._trigger_recalculation()

        return updated

    def calculate_score(
        self,
        event_type: str,
        weight: Decimal,
        lines_added: int = 0,
        lines_deleted: int = 0,
    ) -> Decimal:
        """Calculate score for a single event."""
        base_score = weight

        # Add line-based bonus for commits
        if event_type == EventType.COMMIT.value:
            line_bonus = Decimal(str(lines_added)) * Decimal(
                str(settings.default_lines_added_multiplier)
            ) + Decimal(str(lines_deleted)) * Decimal(
                str(settings.default_lines_deleted_multiplier)
            )
            base_score += line_bonus

        return base_score
