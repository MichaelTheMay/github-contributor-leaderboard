"""Celery tasks for contributor enrichment.

These tasks run in Celery workers and use synchronous database access.
"""

from datetime import datetime, timedelta, timezone

import structlog

from src.workers.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(bind=True, max_retries=3, rate_limit="10/m")
def enrich_contributor(self, user_id: int) -> dict:
    """
    Enrich a single contributor's profile with external data.

    This task:
    1. Creates sync DB session (Celery is sync)
    2. Loads user from DB
    3. Calls GitHubEnricherSync
    4. Updates enrichment record
    5. Returns enrichment result

    Args:
        user_id: The database ID of the GitHubUser to enrich

    Returns:
        dict with status, user_id, username, and sources_found
    """
    logger.info("Enriching contributor", user_id=user_id, task_id=self.request.id)

    try:
        # Import here to avoid circular imports and lazy-load sync session
        from src.db.database import get_sync_db
        from src.db.models.user import GitHubUser
        from src.enrichment.github_enricher_sync import GitHubEnricherSync

        with get_sync_db() as db:
            # Load user from database
            user = db.query(GitHubUser).filter(GitHubUser.id == user_id).first()
            if not user:
                logger.warning("User not found for enrichment", user_id=user_id)
                return {
                    "status": "error",
                    "error": "User not found",
                    "user_id": user_id,
                }

            # Perform enrichment
            enricher = GitHubEnricherSync(db)
            enrichment = enricher.enrich_user(user)

            # Commit changes
            db.commit()

            # Build result
            sources = enrichment.enrichment_sources or {}
            sources_found = sources.get("sources", [])

            logger.info(
                "Contributor enrichment completed",
                user_id=user_id,
                username=user.username,
                sources=sources_found,
                status=enrichment.enrichment_status.value,
            )

            return {
                "status": "completed",
                "user_id": user_id,
                "username": user.username,
                "enrichment_status": enrichment.enrichment_status.value,
                "sources_found": sources_found,
                "fields_found": enrichment.count_sources_found(),
            }

    except Exception as exc:
        logger.error(
            "Contributor enrichment failed",
            user_id=user_id,
            error=str(exc),
            retries=self.request.retries,
        )
        # Exponential backoff: 2min, 4min, 8min
        raise self.retry(exc=exc, countdown=120 * (2**self.request.retries))


@celery_app.task(bind=True, max_retries=2)
def batch_enrich_top_contributors(
    self,
    limit: int = 10,
    min_score: float | None = None,
    force_refresh: bool = False,
) -> dict:
    """
    Enrich top contributors who haven't been enriched recently.

    This task:
    1. Queries top N contributors by score without recent enrichment
    2. Filters those not enriched in last 7 days (unless force_refresh)
    3. Queues individual enrichment tasks (staggered)

    Args:
        limit: Maximum number of contributors to enrich (1-100)
        min_score: Optional minimum score threshold
        force_refresh: If True, re-enrich even recently enriched users

    Returns:
        dict with status, contributors_queued, and skipped counts
    """
    logger.info(
        "Starting batch enrichment",
        limit=limit,
        min_score=min_score,
        force_refresh=force_refresh,
    )

    try:
        from sqlalchemy import or_

        from src.db.database import get_sync_db
        from src.db.models.enrichment import ContributorEnrichment, EnrichmentStatus
        from src.db.models.leaderboard import GlobalLeaderboard
        from src.db.models.user import GitHubUser

        with get_sync_db() as db:
            # Get cutoff for "recently enriched" (7 days)
            enrichment_cutoff = datetime.now(timezone.utc) - timedelta(days=7)

            # Build query for top contributors needing enrichment
            query = (
                db.query(GitHubUser)
                .outerjoin(GlobalLeaderboard, GlobalLeaderboard.user_id == GitHubUser.id)
                .outerjoin(ContributorEnrichment, ContributorEnrichment.user_id == GitHubUser.id)
            )

            # Filter by minimum score if specified
            if min_score is not None:
                query = query.filter(GlobalLeaderboard.total_score >= min_score)

            # Filter to users needing enrichment (unless force_refresh)
            if not force_refresh:
                query = query.filter(
                    or_(
                        ContributorEnrichment.id.is_(None),  # No enrichment record
                        ContributorEnrichment.last_enriched_at.is_(None),  # Never enriched
                        ContributorEnrichment.last_enriched_at < enrichment_cutoff,  # Stale
                        ContributorEnrichment.enrichment_status == EnrichmentStatus.FAILED,
                    )
                )

            # Order by score (descending) and limit
            query = query.order_by(GlobalLeaderboard.total_score.desc().nullslast())
            query = query.limit(limit)

            users = query.all()

            queued = []
            skipped = []

            # Queue individual enrichment tasks with staggered timing
            for i, user in enumerate(users):
                try:
                    # Stagger tasks: 0s, 6s, 12s, 18s, etc. (10/min rate limit)
                    countdown = i * 6

                    task = enrich_contributor.apply_async(
                        args=[user.id],
                        countdown=countdown,
                    )

                    queued.append({
                        "user_id": user.id,
                        "username": user.username,
                        "task_id": task.id,
                        "countdown": countdown,
                    })

                    logger.debug(
                        "Queued enrichment task",
                        user_id=user.id,
                        username=user.username,
                        task_id=task.id,
                        countdown=countdown,
                    )

                except Exception as e:
                    logger.warning(
                        "Failed to queue enrichment task",
                        user_id=user.id,
                        username=user.username,
                        error=str(e),
                    )
                    skipped.append({
                        "user_id": user.id,
                        "username": user.username,
                        "error": str(e),
                    })

            logger.info(
                "Batch enrichment tasks queued",
                queued_count=len(queued),
                skipped_count=len(skipped),
            )

            return {
                "status": "queued",
                "contributors_queued": len(queued),
                "contributors_skipped": len(skipped),
                "queued": queued,
                "skipped": skipped,
            }

    except Exception as exc:
        logger.error(
            "Batch enrichment failed",
            error=str(exc),
            retries=self.request.retries,
        )
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(rate_limit="5/m")
def fetch_twitter_profile(username: str, twitter_handle: str) -> dict:
    """
    Fetch Twitter/X profile data for a contributor.

    Note: This requires Twitter API access and is rate limited.
    """
    logger.info("Fetching Twitter profile", username=username, twitter=twitter_handle)

    # Implementation would call Twitter API
    # Rate limited to respect API quotas
    # For now, return placeholder

    return {
        "status": "not_implemented",
        "twitter_handle": twitter_handle,
        "message": "Twitter API integration not configured",
    }


@celery_app.task(rate_limit="2/m")
def fetch_linkedin_profile(username: str, linkedin_url: str) -> dict:
    """
    Fetch LinkedIn profile data via Proxycurl or similar service.

    Note: This requires Proxycurl API key and is heavily rate limited due to cost.
    """
    logger.info("Fetching LinkedIn profile", username=username, linkedin_url=linkedin_url)

    # Implementation would call Proxycurl API
    # Heavily rate limited due to cost/restrictions
    # For now, return placeholder

    return {
        "status": "not_implemented",
        "linkedin_url": linkedin_url,
        "message": "LinkedIn enrichment not configured",
    }


@celery_app.task
def enrich_contributor_by_username(username: str) -> dict:
    """
    Enrich a contributor by their GitHub username.

    This is a convenience wrapper that looks up the user ID first.

    Args:
        username: GitHub username to enrich

    Returns:
        dict with status and enrichment result
    """
    logger.info("Enriching contributor by username", username=username)

    try:
        from src.db.database import get_sync_db
        from src.db.models.user import GitHubUser

        with get_sync_db() as db:
            user = db.query(GitHubUser).filter(GitHubUser.username == username).first()
            if not user:
                return {
                    "status": "error",
                    "error": f"User {username} not found",
                    "username": username,
                }

            # Queue the enrichment task
            task = enrich_contributor.delay(user.id)

            return {
                "status": "queued",
                "username": username,
                "user_id": user.id,
                "task_id": task.id,
            }

    except Exception as e:
        logger.error("Failed to queue enrichment by username", username=username, error=str(e))
        return {
            "status": "error",
            "error": str(e),
            "username": username,
        }
