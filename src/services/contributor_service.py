import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.api.schemas.contributor import (
    ContributorActivity,
    ContributorDetail,
    ContributorEnrichmentInfo,
    ContributorRepository,
)
from src.db.models.contribution import ContributionEvent
from src.db.models.leaderboard import RepositoryLeaderboard
from src.db.models.repository import Repository
from src.db.models.user import GitHubUser

logger = structlog.get_logger()


class ContributorService:
    """Service for managing contributor profiles and data."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_contributor(self, username: str) -> ContributorDetail | None:
        """Get full contributor profile with enrichment and rankings."""
        result = await self.db.execute(
            select(GitHubUser)
            .options(
                joinedload(GitHubUser.enrichment),
                joinedload(GitHubUser.global_leaderboard_entry),
            )
            .where(GitHubUser.username == username)
        )
        user = result.unique().scalar_one_or_none()
        if not user:
            return None

        global_entry = user.global_leaderboard_entry
        enrichment = user.enrichment

        return ContributorDetail(
            id=user.id,
            github_id=user.github_id,
            username=user.username,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            profile_url=user.profile_url,
            email=user.email,
            company=user.company,
            location=user.location,
            bio=user.bio,
            followers=user.followers,
            public_repos=user.public_repos,
            global_rank=global_entry.global_rank if global_entry else None,
            total_score=global_entry.total_score if global_entry else None,
            repositories_contributed=(
                global_entry.repositories_contributed if global_entry else None
            ),
            enrichment=(
                ContributorEnrichmentInfo.model_validate(enrichment) if enrichment else None
            ),
            created_at=user.created_at,
        )

    async def get_activity(
        self,
        username: str,
        page: int = 1,
        page_size: int = 50,
    ) -> list[ContributorActivity] | None:
        """Get contribution activity timeline for a user."""
        # Get user
        user_result = await self.db.execute(
            select(GitHubUser).where(GitHubUser.username == username)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return None

        offset = (page - 1) * page_size

        result = await self.db.execute(
            select(ContributionEvent, Repository.full_name)
            .join(Repository)
            .where(ContributionEvent.user_id == user.id)
            .order_by(ContributionEvent.event_timestamp.desc())
            .offset(offset)
            .limit(page_size)
        )

        activities = []
        for event, repo_name in result.all():
            activities.append(
                ContributorActivity(
                    event_type=event.event_type.value,
                    event_timestamp=event.event_timestamp,
                    repository_name=repo_name,
                    lines_added=event.lines_added,
                    lines_deleted=event.lines_deleted,
                )
            )

        return activities

    async def get_repositories(
        self,
        username: str,
    ) -> list[ContributorRepository] | None:
        """Get per-repository breakdown for a user."""
        # Get user
        user_result = await self.db.execute(
            select(GitHubUser).where(GitHubUser.username == username)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return None

        result = await self.db.execute(
            select(RepositoryLeaderboard, Repository.full_name)
            .join(Repository)
            .where(RepositoryLeaderboard.user_id == user.id)
            .order_by(RepositoryLeaderboard.total_score.desc())
        )

        repos = []
        for entry, repo_name in result.all():
            repos.append(
                ContributorRepository(
                    repository_id=entry.repository_id,
                    repository_name=repo_name,
                    rank=entry.rank,
                    total_score=entry.total_score,
                    commit_count=entry.commit_count,
                    pr_merged_count=entry.pr_merged_count,
                    pr_reviewed_count=entry.pr_reviewed_count,
                    first_contribution_at=entry.first_contribution_at,
                    last_contribution_at=entry.last_contribution_at,
                )
            )

        return repos

    async def trigger_enrichment(self, username: str) -> bool:
        """Trigger enrichment pipeline for a contributor."""
        user_result = await self.db.execute(
            select(GitHubUser).where(GitHubUser.username == username)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return False

        # In a real implementation, this would queue a Celery task
        logger.info("Enrichment triggered", username=username, user_id=user.id)
        return True
