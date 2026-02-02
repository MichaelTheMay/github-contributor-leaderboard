import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.db.database import async_session_maker
from src.db.models.contribution import ContributionEvent, EventType
from src.db.models.job import JobStatus, JobType, ScrapeJob
from src.db.models.leaderboard import GlobalLeaderboard, RepositoryLeaderboard
from src.db.models.repository import Repository, RepositoryStatus
from src.db.models.scoring import ScoringWeight
from src.db.models.user import GitHubUser
from src.services.bigquery_service import BigQueryService
from src.workers.celery_app import celery_app

logger = structlog.get_logger()


def run_async(coro):
    """Run async code in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=3)
def scrape_repository(self, repository_id: int, job_id: int) -> dict:
    """
    Scrape all contribution events for a repository from BigQuery.
    """
    return run_async(_scrape_repository_async(self, repository_id, job_id))


async def _scrape_repository_async(task, repository_id: int, job_id: int) -> dict:
    """Async implementation of repository scraping."""
    logger.info("Starting repository scrape", repository_id=repository_id, job_id=job_id)

    async with async_session_maker() as db:
        # Get repository and job
        repo_result = await db.execute(
            select(Repository).where(Repository.id == repository_id)
        )
        repository = repo_result.scalar_one_or_none()

        job_result = await db.execute(
            select(ScrapeJob).where(ScrapeJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()

        if not repository or not job:
            logger.error("Repository or job not found", repository_id=repository_id, job_id=job_id)
            return {"status": "failed", "error": "Repository or job not found"}

        try:
            # Update job status
            job.status = JobStatus.RUNNING
            job.started_at = datetime.utcnow()
            repository.status = RepositoryStatus.SCRAPING
            await db.commit()

            # Fetch data from BigQuery
            bigquery = BigQueryService()
            repo_full_name = f"{repository.owner}/{repository.name}"

            logger.info("Fetching data from BigQuery", repository=repo_full_name)

            # Get aggregated stats (more efficient than individual events)
            stats = await bigquery.fetch_aggregated_stats(
                repositories=[repo_full_name],
                start_date=datetime.utcnow() - timedelta(days=365 * 2),  # 2 years
            )

            events_processed = 0
            users_created = 0

            # Get scoring weights
            weights = await _get_scoring_weights(db)

            for stat in stats:
                # Ensure user exists
                user = await _get_or_create_user(db, stat["user_id"], stat["username"])
                if user.id is None:
                    await db.flush()
                users_created += 1

                # Calculate score for this user in this repo
                score = _calculate_user_score(stat, weights)

                # Create or update leaderboard entry
                await _upsert_leaderboard_entry(
                    db, repository.id, user.id, stat, score
                )

                events_processed += (
                    stat["commit_events"] +
                    stat["prs_opened"] +
                    stat["prs_merged"] +
                    stat["prs_reviewed"] +
                    stat["issues_opened"] +
                    stat["issues_closed"] +
                    stat["comments"] +
                    stat["releases"]
                )

            # Update rankings
            await _update_repository_rankings(db, repository.id)

            # Update job and repository status
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.events_processed = events_processed
            repository.status = RepositoryStatus.COMPLETED
            repository.last_scraped_at = datetime.utcnow()
            await db.commit()

            logger.info(
                "Repository scrape completed",
                repository=repo_full_name,
                events_processed=events_processed,
                users=users_created,
            )

            # Trigger global leaderboard recalculation
            recalculate_global_leaderboard.delay()

            return {
                "status": "completed",
                "repository_id": repository_id,
                "events_processed": events_processed,
                "users_processed": users_created,
            }

        except Exception as exc:
            logger.error(
                "Repository scrape failed",
                repository_id=repository_id,
                error=str(exc),
            )

            job.status = JobStatus.FAILED
            job.completed_at = datetime.utcnow()
            job.error_message = str(exc)
            repository.status = RepositoryStatus.FAILED
            await db.commit()

            raise task.retry(exc=exc, countdown=60 * (task.request.retries + 1))


async def _get_scoring_weights(db: AsyncSession) -> dict[str, Decimal]:
    """Get scoring weights from database."""
    result = await db.execute(select(ScoringWeight))
    weights = result.scalars().all()
    return {w.event_type: w.base_points for w in weights}


async def _get_or_create_user(
    db: AsyncSession,
    github_id: int,
    username: str,
) -> GitHubUser:
    """Get or create a GitHub user."""
    result = await db.execute(
        select(GitHubUser).where(GitHubUser.github_id == github_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        user = GitHubUser(
            github_id=github_id,
            username=username,
            profile_url=f"https://github.com/{username}",
        )
        db.add(user)

    return user


def _calculate_user_score(stat: dict, weights: dict[str, Decimal]) -> Decimal:
    """Calculate total score for a user's contributions."""
    score = Decimal("0")

    score += Decimal(str(stat["commit_events"])) * weights.get("commit", Decimal("10"))
    score += Decimal(str(stat["prs_opened"])) * weights.get("pr_opened", Decimal("15"))
    score += Decimal(str(stat["prs_merged"])) * weights.get("pr_merged", Decimal("25"))
    score += Decimal(str(stat["prs_reviewed"])) * weights.get("pr_reviewed", Decimal("20"))
    score += Decimal(str(stat["issues_opened"])) * weights.get("issue_opened", Decimal("8"))
    score += Decimal(str(stat["issues_closed"])) * weights.get("issue_closed", Decimal("5"))
    score += Decimal(str(stat["comments"])) * weights.get("comment", Decimal("3"))
    score += Decimal(str(stat["releases"])) * weights.get("release", Decimal("30"))

    # Line bonus
    score += Decimal(str(stat["total_lines_added"] or 0)) * Decimal("0.1")
    score += Decimal(str(stat["total_lines_deleted"] or 0)) * Decimal("0.05")

    return score


async def _upsert_leaderboard_entry(
    db: AsyncSession,
    repository_id: int,
    user_id: int,
    stat: dict,
    score: Decimal,
) -> None:
    """Create or update a repository leaderboard entry."""
    result = await db.execute(
        select(RepositoryLeaderboard).where(
            RepositoryLeaderboard.repository_id == repository_id,
            RepositoryLeaderboard.user_id == user_id,
        )
    )
    entry = result.scalar_one_or_none()

    if entry:
        entry.total_score = score
        entry.commit_count = stat["commit_events"]
        entry.pr_opened_count = stat["prs_opened"]
        entry.pr_merged_count = stat["prs_merged"]
        entry.pr_reviewed_count = stat["prs_reviewed"]
        entry.issues_opened_count = stat["issues_opened"]
        entry.issues_closed_count = stat["issues_closed"]
        entry.comments_count = stat["comments"]
        entry.lines_added = stat["total_lines_added"] or 0
        entry.lines_deleted = stat["total_lines_deleted"] or 0
        entry.first_contribution_at = stat["first_contribution"]
        entry.last_contribution_at = stat["last_contribution"]
    else:
        entry = RepositoryLeaderboard(
            repository_id=repository_id,
            user_id=user_id,
            rank=0,  # Will be updated later
            total_score=score,
            commit_count=stat["commit_events"],
            pr_opened_count=stat["prs_opened"],
            pr_merged_count=stat["prs_merged"],
            pr_reviewed_count=stat["prs_reviewed"],
            issues_opened_count=stat["issues_opened"],
            issues_closed_count=stat["issues_closed"],
            comments_count=stat["comments"],
            lines_added=stat["total_lines_added"] or 0,
            lines_deleted=stat["total_lines_deleted"] or 0,
            first_contribution_at=stat["first_contribution"],
            last_contribution_at=stat["last_contribution"],
        )
        db.add(entry)


async def _update_repository_rankings(db: AsyncSession, repository_id: int) -> None:
    """Update rank values for all entries in a repository leaderboard."""
    result = await db.execute(
        select(RepositoryLeaderboard)
        .where(RepositoryLeaderboard.repository_id == repository_id)
        .order_by(RepositoryLeaderboard.total_score.desc())
    )
    entries = result.scalars().all()

    for rank, entry in enumerate(entries, start=1):
        entry.rank = rank


@celery_app.task
def refresh_stale_repositories() -> dict:
    """Periodic task to refresh repositories not updated in 24 hours."""
    return run_async(_refresh_stale_repositories_async())


async def _refresh_stale_repositories_async() -> dict:
    """Async implementation of stale repository refresh."""
    logger.info("Checking for stale repositories")

    async with async_session_maker() as db:
        cutoff = datetime.utcnow() - timedelta(hours=24)

        result = await db.execute(
            select(Repository).where(
                (Repository.last_scraped_at < cutoff) |
                (Repository.last_scraped_at.is_(None)),
                Repository.status != RepositoryStatus.SCRAPING,
            )
        )
        stale_repos = result.scalars().all()

        queued = 0
        for repo in stale_repos:
            job = ScrapeJob(
                repository_id=repo.id,
                job_type=JobType.INCREMENTAL,
            )
            db.add(job)
            await db.flush()

            # Queue the scrape task
            scrape_repository.delay(repo.id, job.id)
            queued += 1

        await db.commit()

        logger.info("Queued stale repository refreshes", count=queued)
        return {"status": "completed", "repositories_queued": queued}


@celery_app.task
def recalculate_global_leaderboard() -> dict:
    """Recalculate the global leaderboard from all repository leaderboards."""
    return run_async(_recalculate_global_leaderboard_async())


async def _recalculate_global_leaderboard_async() -> dict:
    """Async implementation of global leaderboard recalculation."""
    logger.info("Recalculating global leaderboard")

    async with async_session_maker() as db:
        # Aggregate scores per user across all repositories
        result = await db.execute(
            select(
                RepositoryLeaderboard.user_id,
                func.sum(RepositoryLeaderboard.total_score).label("total_score"),
                func.count(RepositoryLeaderboard.repository_id).label("repos"),
                func.sum(RepositoryLeaderboard.commit_count).label("commits"),
                func.sum(RepositoryLeaderboard.pr_merged_count).label("prs_merged"),
                func.sum(RepositoryLeaderboard.pr_reviewed_count).label("prs_reviewed"),
                func.sum(RepositoryLeaderboard.issues_opened_count).label("issues"),
                func.sum(RepositoryLeaderboard.comments_count).label("comments"),
                func.sum(RepositoryLeaderboard.lines_added).label("lines_added"),
                func.min(RepositoryLeaderboard.first_contribution_at).label("first"),
                func.max(RepositoryLeaderboard.last_contribution_at).label("last"),
            )
            .group_by(RepositoryLeaderboard.user_id)
            .order_by(func.sum(RepositoryLeaderboard.total_score).desc())
        )
        aggregates = result.all()

        # Clear existing global leaderboard
        await db.execute(
            GlobalLeaderboard.__table__.delete()
        )

        # Insert new rankings
        for rank, agg in enumerate(aggregates, start=1):
            entry = GlobalLeaderboard(
                user_id=agg.user_id,
                global_rank=rank,
                total_score=agg.total_score or Decimal("0"),
                repositories_contributed=agg.repos or 0,
                total_commits=agg.commits or 0,
                total_prs_merged=agg.prs_merged or 0,
                total_prs_reviewed=agg.prs_reviewed or 0,
                total_issues_opened=agg.issues or 0,
                total_comments=agg.comments or 0,
                total_lines_added=agg.lines_added or 0,
                first_contribution_at=agg.first,
                last_contribution_at=agg.last,
            )
            db.add(entry)

        await db.commit()

        logger.info("Global leaderboard recalculated", total_contributors=len(aggregates))
        return {"status": "completed", "total_contributors": len(aggregates)}


@celery_app.task(bind=True, max_retries=3)
def trigger_repository_scrape(self, owner: str, name: str) -> dict:
    """Trigger a scrape for a repository by name."""
    return run_async(_trigger_repository_scrape_async(self, owner, name))


async def _trigger_repository_scrape_async(task, owner: str, name: str) -> dict:
    """Async implementation of triggering a repository scrape."""
    async with async_session_maker() as db:
        result = await db.execute(
            select(Repository).where(
                Repository.owner == owner,
                Repository.name == name,
            )
        )
        repository = result.scalar_one_or_none()

        if not repository:
            return {"status": "failed", "error": "Repository not found"}

        job = ScrapeJob(
            repository_id=repository.id,
            job_type=JobType.FULL_SCRAPE,
        )
        db.add(job)
        await db.flush()

        # Queue the actual scrape
        scrape_repository.delay(repository.id, job.id)

        await db.commit()

        return {
            "status": "queued",
            "repository": f"{owner}/{name}",
            "job_id": job.id,
        }
