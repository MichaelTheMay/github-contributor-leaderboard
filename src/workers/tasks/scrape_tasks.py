import asyncio
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.db.database import create_worker_session_maker
from src.db.models.contribution import ContributionEvent, EventType
from src.db.models.job import JobStatus, JobType, ScrapeJob
from src.db.models.leaderboard import GlobalLeaderboard, RepositoryLeaderboard
from src.db.models.repository import Repository, RepositoryStatus
from src.db.models.scoring import ScoringWeight
from src.db.models.scrape_history import ScrapeWindow
from src.db.models.user import GitHubUser
from src.services.bigquery_service import BigQueryService
from src.workers.celery_app import celery_app

logger = structlog.get_logger()

# Windows requires ProactorEventLoop for asyncpg
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def run_async(coro):
    """Run async code in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        # Properly cleanup pending tasks
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        loop.close()


async def _determine_scrape_window(
    db: AsyncSession,
    repository: Repository,
    job_type: JobType,
) -> tuple[datetime, datetime]:
    """Determine what date range to scrape (avoiding duplicates).

    For incremental scrapes, starts from last scraped date minus 1 day overlap.
    For full scrapes, goes back 2 years.
    """
    # For full scrapes, always go back 2 years
    if job_type == JobType.FULL_SCRAPE:
        start_date = datetime.utcnow() - timedelta(days=730)
        end_date = datetime.utcnow()
        return start_date, end_date

    # Check existing scrape windows for incremental
    result = await db.execute(
        select(ScrapeWindow)
        .where(ScrapeWindow.repository_id == repository.id)
        .order_by(ScrapeWindow.data_end_date.desc())
        .limit(1)
    )
    last_window = result.scalar_one_or_none()

    if last_window:
        # Incremental: start from last scraped date (minus 1 day overlap for safety)
        start_date = last_window.data_end_date - timedelta(days=1)
    elif repository.latest_data_date:
        # No scrape window but have data - start from there
        start_date = repository.latest_data_date - timedelta(days=1)
    else:
        # First scrape: go back 2 years
        start_date = datetime.utcnow() - timedelta(days=730)

    # Don't go earlier than never_rescrape_before if set
    if repository.never_rescrape_before and start_date < repository.never_rescrape_before:
        start_date = repository.never_rescrape_before

    end_date = datetime.utcnow()

    return start_date, end_date


def _map_bigquery_event_type(event_type: str) -> EventType | None:
    """Map BigQuery event type string to EventType enum."""
    mapping = {
        "commit": EventType.COMMIT,
        "pr_opened": EventType.PR_OPENED,
        "pr_merged": EventType.PR_MERGED,
        "pr_reviewed": EventType.PR_REVIEWED,
        "pr_review_comment": EventType.PR_REVIEW_COMMENT,
        "issue_opened": EventType.ISSUE_OPENED,
        "issue_closed": EventType.ISSUE_CLOSED,
        "comment": EventType.COMMENT,
        "release": EventType.RELEASE,
    }
    return mapping.get(event_type)


async def _store_raw_events(
    db: AsyncSession,
    repository_id: int,
    events: list[dict],
) -> tuple[int, int, set[int]]:
    """Store raw events with deduplication.

    Returns:
        Tuple of (events_stored, events_skipped, unique_user_ids)
    """
    events_stored = 0
    events_skipped = 0
    unique_user_ids: set[int] = set()

    for event in events:
        # Check if event already exists (deduplication)
        result = await db.execute(
            select(ContributionEvent.id).where(
                ContributionEvent.event_id == event["event_id"]
            )
        )
        if result.scalar_one_or_none():
            events_skipped += 1
            continue

        # Get or create user
        user = await _get_or_create_user(
            db, event["user_id"], event["username"]
        )
        if user.id is None:
            await db.flush()

        unique_user_ids.add(user.id)

        # Map event type
        event_type = _map_bigquery_event_type(event["event_type"])
        if not event_type:
            events_skipped += 1
            continue

        # Create ContributionEvent
        contribution_event = ContributionEvent(
            repository_id=repository_id,
            user_id=user.id,
            event_type=event_type,
            event_id=event["event_id"],
            event_timestamp=event["event_timestamp"],
            lines_added=event.get("lines_added", 0),
            lines_deleted=event.get("lines_deleted", 0),
            event_data=event,  # Store full payload in JSONB
        )
        db.add(contribution_event)
        events_stored += 1

    return events_stored, events_skipped, unique_user_ids


@celery_app.task(bind=True, max_retries=3)
def scrape_repository(self, repository_id: int, job_id: int) -> dict:
    """
    Scrape all contribution events for a repository from BigQuery.
    """
    return run_async(_scrape_repository_async(self, repository_id, job_id))


async def _scrape_repository_async(task, repository_id: int, job_id: int) -> dict:
    """Async implementation of repository scraping with incremental support."""
    logger.info("Starting repository scrape", repository_id=repository_id, job_id=job_id)

    async with create_worker_session_maker()() as db:
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

        # Import budget service for cost tracking
        from src.services.budget_service import BudgetService, AuditAction
        budget_service = BudgetService(db)

        # Log job start
        await budget_service.log_audit(
            action=AuditAction.JOB_STARTED,
            category="scrape",
            description=f"Started scraping {repository.owner}/{repository.name}",
            job_id=job_id,
            repository_id=repository_id,
        )

        start_time = datetime.utcnow()

        try:
            # Update job status
            job.status = JobStatus.RUNNING
            job.started_at = start_time
            repository.status = RepositoryStatus.SCRAPING
            await db.commit()

            # Determine scrape window (incremental vs full)
            scrape_start, scrape_end = await _determine_scrape_window(
                db, repository, job.job_type
            )

            logger.info(
                "Determined scrape window",
                repository=f"{repository.owner}/{repository.name}",
                start_date=scrape_start.isoformat(),
                end_date=scrape_end.isoformat(),
                job_type=job.job_type.value,
            )

            # Fetch data from BigQuery
            bigquery = BigQueryService()
            repo_full_name = f"{repository.owner}/{repository.name}"

            logger.info("Fetching data from BigQuery", repository=repo_full_name)

            # Get aggregated stats using incremental date range
            stats = await bigquery.fetch_aggregated_stats(
                repositories=[repo_full_name],
                start_date=scrape_start,
            )

            # Capture BigQuery job statistics for cost tracking
            bq_stats = bigquery.last_job_stats
            bytes_processed = bq_stats.bytes_processed if bq_stats else 0
            bytes_billed = bq_stats.bytes_billed if bq_stats else 0

            events_processed = 0
            users_created = 0

            # Get scoring weights
            weights = await _get_scoring_weights(db)

            batch_size = 100
            for i, stat in enumerate(stats):
                try:
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

                    # Commit in batches to avoid large transactions
                    if (i + 1) % batch_size == 0:
                        await db.commit()
                        logger.info("Batch committed", processed=i + 1, total=len(stats))

                except Exception as e:
                    logger.warning(
                        "Error processing user, skipping",
                        username=stat.get("username"),
                        error=str(e),
                    )
                    await db.rollback()
                    continue

            # Update rankings
            await _update_repository_rankings(db, repository.id)

            # Calculate duration
            end_time = datetime.utcnow()
            duration_seconds = int((end_time - start_time).total_seconds())

            # Create ScrapeWindow record for tracking
            scrape_window = ScrapeWindow(
                repository_id=repository.id,
                job_id=job.id,
                data_start_date=scrape_start,
                data_end_date=scrape_end,
                events_fetched=events_processed,
                contributors_found=users_created,
                bytes_processed=bytes_processed,
                bytes_billed=bytes_billed,
            )
            db.add(scrape_window)

            # Update job and repository status
            job.status = JobStatus.COMPLETED
            job.completed_at = end_time
            job.events_processed = events_processed
            job.bytes_processed = bytes_processed
            job.bytes_billed = bytes_billed
            repository.status = RepositoryStatus.COMPLETED
            repository.last_scraped_at = end_time

            # Update repository scrape tracking fields
            if not repository.first_scraped_at:
                repository.first_scraped_at = end_time
            if not repository.earliest_data_date or scrape_start < repository.earliest_data_date:
                repository.earliest_data_date = scrape_start
            if not repository.latest_data_date or scrape_end > repository.latest_data_date:
                repository.latest_data_date = scrape_end

            await db.commit()

            # Record actual cost
            cost_record = await budget_service.record_job_cost(
                job_id=job_id,
                bytes_processed=bytes_processed,
                bytes_billed=bytes_billed,
                duration_seconds=duration_seconds,
                metadata={
                    "repository": repo_full_name,
                    "users_processed": users_created,
                    "events_processed": events_processed,
                    "cache_hit": bq_stats.cache_hit if bq_stats else False,
                },
            )

            # Log job completion
            await budget_service.log_audit(
                action=AuditAction.JOB_COMPLETED,
                category="scrape",
                description=f"Completed scraping {repo_full_name}: {users_created} users, {events_processed} events",
                job_id=job_id,
                repository_id=repository_id,
                actual_cost=cost_record.actual_cost,
                bytes_processed=bytes_processed,
                extra_data={
                    "duration_seconds": duration_seconds,
                    "users_processed": users_created,
                    "events_processed": events_processed,
                },
            )

            logger.info(
                "Repository scrape completed",
                repository=repo_full_name,
                events_processed=events_processed,
                users=users_created,
                bytes_billed=bytes_billed,
                actual_cost=float(cost_record.actual_cost),
                scrape_window=f"{scrape_start.date()} to {scrape_end.date()}",
            )

            # Trigger global leaderboard recalculation
            recalculate_global_leaderboard.delay()

            return {
                "status": "completed",
                "repository_id": repository_id,
                "events_processed": events_processed,
                "users_processed": users_created,
                "bytes_processed": bytes_processed,
                "bytes_billed": bytes_billed,
                "actual_cost_usd": float(cost_record.actual_cost),
                "duration_seconds": duration_seconds,
                "scrape_window": {
                    "start": scrape_start.isoformat(),
                    "end": scrape_end.isoformat(),
                },
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

            # Log job failure
            await budget_service.log_audit(
                action=AuditAction.JOB_FAILED,
                category="scrape",
                description=f"Failed scraping repository {repository_id}: {str(exc)}",
                job_id=job_id,
                repository_id=repository_id,
                success=False,
                error_message=str(exc),
            )

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
    from sqlalchemy import or_

    # Check by github_id OR username (both are unique)
    result = await db.execute(
        select(GitHubUser).where(
            or_(
                GitHubUser.github_id == github_id,
                GitHubUser.username == username,
            )
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        user = GitHubUser(
            github_id=github_id,
            username=username,
            profile_url=f"https://github.com/{username}",
        )
        db.add(user)
    elif user.github_id != github_id:
        # Username exists but with different github_id - update it
        user.github_id = github_id
    elif user.username != username:
        # github_id exists but username changed - update it
        user.username = username
        user.profile_url = f"https://github.com/{username}"

    return user


def _calculate_user_score(stat: dict, weights: dict[str, Decimal]) -> Decimal:
    """Calculate total score for a user's contributions.

    Scoring prioritizes meaningful contributions:
    - PRs merged/reviewed are weighted highest (actual code integration)
    - Commits and PRs opened are moderate
    - Issues and comments are lower but still valuable
    - Line changes have minimal impact (capped) to prevent gaming
    """
    score = Decimal("0")

    # Core contribution scoring
    score += Decimal(str(stat["commit_events"])) * weights.get("commit", Decimal("10"))
    score += Decimal(str(stat["prs_opened"])) * weights.get("pr_opened", Decimal("15"))
    score += Decimal(str(stat["prs_merged"])) * weights.get("pr_merged", Decimal("25"))
    score += Decimal(str(stat["prs_reviewed"])) * weights.get("pr_reviewed", Decimal("20"))
    score += Decimal(str(stat["issues_opened"])) * weights.get("issue_opened", Decimal("8"))
    score += Decimal(str(stat["issues_closed"])) * weights.get("issue_closed", Decimal("5"))
    score += Decimal(str(stat["comments"])) * weights.get("comment", Decimal("3"))
    score += Decimal(str(stat["releases"])) * weights.get("release", Decimal("30"))

    # Line bonus - heavily reduced and capped to prevent gaming
    # Max 500 points from lines (was previously uncapped and could be 30,000+)
    lines_added = Decimal(str(stat["total_lines_added"] or 0))
    lines_deleted = Decimal(str(stat["total_lines_deleted"] or 0))
    line_bonus = (lines_added * Decimal("0.01")) + (lines_deleted * Decimal("0.005"))
    line_bonus = min(line_bonus, Decimal("500"))  # Cap at 500 points
    score += line_bonus

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

    async with create_worker_session_maker()() as db:
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

    async with create_worker_session_maker()() as db:
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
    async with create_worker_session_maker()() as db:
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


@celery_app.task
def recalculate_leaderboard_from_events(repository_id: int) -> dict:
    """Recalculate repository leaderboard by aggregating ContributionEvent records.

    This is useful for rebuilding leaderboard data from raw events when needed,
    ensuring counts are accurate and match stored events.
    """
    return run_async(_recalculate_leaderboard_from_events_async(repository_id))


async def _recalculate_leaderboard_from_events_async(repository_id: int) -> dict:
    """Async implementation of leaderboard recalculation from events."""
    logger.info("Recalculating leaderboard from events", repository_id=repository_id)

    async with create_worker_session_maker()() as db:
        # Get repository
        repo_result = await db.execute(
            select(Repository).where(Repository.id == repository_id)
        )
        repository = repo_result.scalar_one_or_none()

        if not repository:
            return {"status": "failed", "error": "Repository not found"}

        # Aggregate events by user
        result = await db.execute(
            select(
                ContributionEvent.user_id,
                func.count(ContributionEvent.id).filter(
                    ContributionEvent.event_type == EventType.COMMIT
                ).label("commits"),
                func.count(ContributionEvent.id).filter(
                    ContributionEvent.event_type == EventType.PR_OPENED
                ).label("prs_opened"),
                func.count(ContributionEvent.id).filter(
                    ContributionEvent.event_type == EventType.PR_MERGED
                ).label("prs_merged"),
                func.count(ContributionEvent.id).filter(
                    ContributionEvent.event_type == EventType.PR_REVIEWED
                ).label("prs_reviewed"),
                func.count(ContributionEvent.id).filter(
                    ContributionEvent.event_type == EventType.ISSUE_OPENED
                ).label("issues_opened"),
                func.count(ContributionEvent.id).filter(
                    ContributionEvent.event_type == EventType.ISSUE_CLOSED
                ).label("issues_closed"),
                func.count(ContributionEvent.id).filter(
                    ContributionEvent.event_type == EventType.COMMENT
                ).label("comments"),
                func.sum(ContributionEvent.lines_added).label("lines_added"),
                func.sum(ContributionEvent.lines_deleted).label("lines_deleted"),
                func.min(ContributionEvent.event_timestamp).label("first_contribution"),
                func.max(ContributionEvent.event_timestamp).label("last_contribution"),
            )
            .where(ContributionEvent.repository_id == repository_id)
            .group_by(ContributionEvent.user_id)
        )
        aggregates = result.all()

        if not aggregates:
            logger.info("No events found for repository", repository_id=repository_id)
            return {"status": "completed", "message": "No events found", "users_updated": 0}

        # Get scoring weights
        weights = await _get_scoring_weights(db)

        users_updated = 0
        for agg in aggregates:
            # Build stat dict for score calculation
            stat = {
                "commit_events": agg.commits or 0,
                "prs_opened": agg.prs_opened or 0,
                "prs_merged": agg.prs_merged or 0,
                "prs_reviewed": agg.prs_reviewed or 0,
                "issues_opened": agg.issues_opened or 0,
                "issues_closed": agg.issues_closed or 0,
                "comments": agg.comments or 0,
                "releases": 0,  # Not tracked in current event types
                "total_lines_added": agg.lines_added or 0,
                "total_lines_deleted": agg.lines_deleted or 0,
                "first_contribution": agg.first_contribution,
                "last_contribution": agg.last_contribution,
            }

            score = _calculate_user_score(stat, weights)

            # Update or create leaderboard entry
            await _upsert_leaderboard_entry(
                db, repository_id, agg.user_id, stat, score
            )
            users_updated += 1

        # Update rankings
        await _update_repository_rankings(db, repository_id)
        await db.commit()

        logger.info(
            "Leaderboard recalculated from events",
            repository_id=repository_id,
            users_updated=users_updated,
        )

        return {
            "status": "completed",
            "repository_id": repository_id,
            "users_updated": users_updated,
        }
