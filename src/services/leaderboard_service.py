from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.db.models.leaderboard import GlobalLeaderboard, RepositoryLeaderboard
from src.db.models.repository import Repository
from src.db.models.user import GitHubUser

logger = structlog.get_logger()


class LeaderboardService:
    """Service for managing and querying leaderboards."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_global_leaderboard(
        self,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict], int]:
        """Get the global leaderboard with pagination."""
        offset = (page - 1) * page_size

        # Get total count
        count_result = await self.db.execute(select(func.count(GlobalLeaderboard.id)))
        total = count_result.scalar() or 0

        # Get paginated results with user info
        result = await self.db.execute(
            select(GlobalLeaderboard)
            .options(joinedload(GlobalLeaderboard.user))
            .order_by(GlobalLeaderboard.global_rank)
            .offset(offset)
            .limit(page_size)
        )
        entries = result.scalars().all()

        formatted = []
        for entry in entries:
            formatted.append(
                {
                    "global_rank": entry.global_rank,
                    "user": {
                        "username": entry.user.username,
                        "display_name": entry.user.display_name,
                        "avatar_url": entry.user.avatar_url,
                        "profile_url": entry.user.profile_url,
                    },
                    "total_score": entry.total_score,
                    "repositories_contributed": entry.repositories_contributed,
                    "total_commits": entry.total_commits,
                    "total_prs_merged": entry.total_prs_merged,
                    "total_prs_reviewed": entry.total_prs_reviewed,
                    "total_issues_opened": entry.total_issues_opened,
                    "total_comments": entry.total_comments,
                    "total_lines_added": entry.total_lines_added,
                    "first_contribution_at": entry.first_contribution_at,
                    "last_contribution_at": entry.last_contribution_at,
                }
            )

        return formatted, total

    async def get_repository_leaderboard(
        self,
        owner: str,
        name: str,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict], int] | None:
        """Get leaderboard for a specific repository."""
        # Find repository
        repo_result = await self.db.execute(
            select(Repository).where(
                Repository.owner == owner,
                Repository.name == name,
            )
        )
        repository = repo_result.scalar_one_or_none()
        if not repository:
            return None

        offset = (page - 1) * page_size

        # Get total count
        count_result = await self.db.execute(
            select(func.count(RepositoryLeaderboard.id)).where(
                RepositoryLeaderboard.repository_id == repository.id
            )
        )
        total = count_result.scalar() or 0

        # Get paginated results
        result = await self.db.execute(
            select(RepositoryLeaderboard)
            .options(joinedload(RepositoryLeaderboard.user))
            .where(RepositoryLeaderboard.repository_id == repository.id)
            .order_by(RepositoryLeaderboard.rank)
            .offset(offset)
            .limit(page_size)
        )
        entries = result.scalars().all()

        formatted = []
        for entry in entries:
            formatted.append(
                {
                    "rank": entry.rank,
                    "user": {
                        "username": entry.user.username,
                        "display_name": entry.user.display_name,
                        "avatar_url": entry.user.avatar_url,
                        "profile_url": entry.user.profile_url,
                    },
                    "total_score": entry.total_score,
                    "commit_count": entry.commit_count,
                    "pr_opened_count": entry.pr_opened_count,
                    "pr_merged_count": entry.pr_merged_count,
                    "pr_reviewed_count": entry.pr_reviewed_count,
                    "issues_opened_count": entry.issues_opened_count,
                    "issues_closed_count": entry.issues_closed_count,
                    "comments_count": entry.comments_count,
                    "lines_added": entry.lines_added,
                    "lines_deleted": entry.lines_deleted,
                    "first_contribution_at": entry.first_contribution_at,
                    "last_contribution_at": entry.last_contribution_at,
                }
            )

        return formatted, total

    async def compare_repositories(
        self,
        repos: list[str],
        limit: int = 10,
    ) -> dict:
        """Compare contributor rankings across multiple repositories."""
        comparison: dict = {"repositories": [], "common_contributors": []}

        repo_data = []
        for repo_str in repos:
            parts = repo_str.split("/")
            if len(parts) != 2:
                continue
            owner, name = parts

            result = await self.get_repository_leaderboard(owner, name, 1, limit)
            if result:
                entries, total = result
                repo_data.append(
                    {
                        "repository": repo_str,
                        "total_contributors": total,
                        "top_contributors": entries,
                    }
                )

        comparison["repositories"] = repo_data

        # Find common contributors across repositories
        if len(repo_data) >= 2:
            contributor_sets = []
            for rd in repo_data:
                usernames = {e["user"]["username"] for e in rd["top_contributors"]}
                contributor_sets.append(usernames)

            common = contributor_sets[0]
            for s in contributor_sets[1:]:
                common = common.intersection(s)

            comparison["common_contributors"] = list(common)

        return comparison

    async def recalculate_repository_leaderboard(self, repository_id: int) -> None:
        """Recalculate leaderboard for a single repository."""
        # This would be implemented with the actual scoring logic
        logger.info("Recalculating repository leaderboard", repository_id=repository_id)

    async def recalculate_global_leaderboard(self) -> None:
        """Recalculate the global leaderboard from all repository leaderboards."""
        logger.info("Recalculating global leaderboard")
