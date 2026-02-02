import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.job import JobType, ScrapeJob
from src.db.models.repository import Repository, RepositoryStatus
from src.services.github_service import GitHubService

logger = structlog.get_logger()


class RepositoryService:
    """Service for managing tracked repositories."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.github = GitHubService()

    async def add_repository(self, owner: str, name: str) -> Repository:
        """Add a new repository to track."""
        # Check if already exists
        existing = await self.get_repository(owner, name)
        if existing:
            logger.info("Repository already tracked", owner=owner, name=name)
            return existing

        # Validate repository exists on GitHub
        github_repo = await self.github.get_repository(owner, name)
        if not github_repo:
            raise ValueError(f"Repository {owner}/{name} not found on GitHub")

        # Create repository record
        repository = Repository(
            owner=owner,
            name=name,
            github_id=github_repo["id"],
            description=github_repo.get("description"),
            stars=github_repo.get("stargazers_count", 0),
            forks=github_repo.get("forks_count", 0),
            status=RepositoryStatus.PENDING,
        )
        self.db.add(repository)
        await self.db.flush()

        # Create initial scrape job
        job = ScrapeJob(
            repository_id=repository.id,
            job_type=JobType.FULL_SCRAPE,
        )
        self.db.add(job)

        logger.info("Repository added", owner=owner, name=name, repo_id=repository.id)
        return repository

    async def get_repository(self, owner: str, name: str) -> Repository | None:
        """Get a repository by owner and name."""
        result = await self.db.execute(
            select(Repository).where(
                Repository.owner == owner,
                Repository.name == name,
            )
        )
        return result.scalar_one_or_none()

    async def list_repositories(
        self,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Repository], int]:
        """List all tracked repositories with pagination."""
        offset = (page - 1) * page_size

        # Get total count
        count_result = await self.db.execute(select(func.count(Repository.id)))
        total = count_result.scalar() or 0

        # Get paginated results
        result = await self.db.execute(
            select(Repository)
            .order_by(Repository.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        repositories = list(result.scalars().all())

        return repositories, total

    async def delete_repository(self, owner: str, name: str) -> bool:
        """Delete a repository from tracking."""
        repository = await self.get_repository(owner, name)
        if not repository:
            return False

        await self.db.delete(repository)
        logger.info("Repository deleted", owner=owner, name=name)
        return True

    async def trigger_refresh(self, owner: str, name: str) -> ScrapeJob | None:
        """Trigger a manual refresh for a repository."""
        repository = await self.get_repository(owner, name)
        if not repository:
            return None

        job = ScrapeJob(
            repository_id=repository.id,
            job_type=JobType.INCREMENTAL,
        )
        self.db.add(job)
        await self.db.flush()

        logger.info("Refresh triggered", owner=owner, name=name, job_id=job.id)
        return job

    async def update_status(
        self,
        repository_id: int,
        status: RepositoryStatus,
    ) -> None:
        """Update repository status."""
        result = await self.db.execute(
            select(Repository).where(Repository.id == repository_id)
        )
        repository = result.scalar_one_or_none()
        if repository:
            repository.status = status
