import asyncio
import json
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.db.models.contribution import ContributionEvent
from src.db.models.job import JobStatus, JobType, ScrapeJob
from src.db.models.leaderboard import GlobalLeaderboard, RepositoryLeaderboard
from src.db.models.repository import Repository, RepositoryStatus
from src.db.models.user import GitHubUser

router = APIRouter()

# Pipeline automation settings (in-memory, could be persisted to DB)
pipeline_settings = {
    "auto_refresh_stale_repos": True,
    "auto_recalc_global_after_scrape": True,
    "auto_recalc_global_interval": True,
    "stale_threshold_hours": 24,
    "scrape_lookback_days": 730,  # 2 years
}

# In-memory log buffer and connected clients
log_buffer: deque[dict[str, Any]] = deque(maxlen=1000)
connected_clients: set[WebSocket] = set()


class LogBroadcaster:
    """Broadcasts logs to all connected WebSocket clients."""

    @staticmethod
    async def broadcast(message: dict[str, Any]) -> None:
        """Send message to all connected clients."""
        log_buffer.append(message)
        disconnected = set()

        for client in connected_clients:
            try:
                await client.send_json(message)
            except Exception:
                disconnected.add(client)

        # Clean up disconnected clients
        for client in disconnected:
            connected_clients.discard(client)

    @staticmethod
    async def log(level: str, message: str) -> None:
        """Log a message and broadcast to clients."""
        log_entry = {
            "type": "log",
            "level": level,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await LogBroadcaster.broadcast(log_entry)


# Global broadcaster instance
broadcaster = LogBroadcaster()


def get_template_path() -> Path:
    """Get the path to the templates directory."""
    return Path(__file__).parent.parent / "templates"


@router.get("/", response_class=HTMLResponse)
async def dashboard_page() -> HTMLResponse:
    """Serve the monitoring dashboard."""
    template_path = get_template_path() / "dashboard.html"
    return HTMLResponse(content=template_path.read_text(encoding="utf-8"))


@router.get("/pipeline", response_class=HTMLResponse)
async def pipeline_page() -> HTMLResponse:
    """Serve the pipeline control dashboard."""
    template_path = get_template_path() / "pipeline.html"
    return HTMLResponse(content=template_path.read_text(encoding="utf-8"))


@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket) -> None:
    """WebSocket endpoint for live log streaming."""
    await websocket.accept()
    connected_clients.add(websocket)

    try:
        # Send recent logs from buffer
        for log_entry in list(log_buffer)[-50:]:
            await websocket.send_json(log_entry)

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for any message (ping/pong or commands)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # Send periodic stats update
                pass

    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(websocket)


@router.get("/stats")
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Get current dashboard statistics."""
    # Count active jobs
    active_jobs_result = await db.execute(
        select(func.count(ScrapeJob.id)).where(
            ScrapeJob.status == JobStatus.RUNNING
        )
    )
    active_jobs = active_jobs_result.scalar() or 0

    # Count repositories
    repo_count_result = await db.execute(select(func.count(Repository.id)))
    repo_count = repo_count_result.scalar() or 0

    # Count events
    event_count_result = await db.execute(select(func.count(ContributionEvent.id)))
    event_count = event_count_result.scalar() or 0

    # Count errors in last 24 hours
    yesterday = datetime.utcnow() - timedelta(hours=24)
    error_count_result = await db.execute(
        select(func.count(ScrapeJob.id)).where(
            ScrapeJob.status == JobStatus.FAILED,
            ScrapeJob.completed_at >= yesterday,
        )
    )
    error_count = error_count_result.scalar() or 0

    return {
        "active_jobs": active_jobs,
        "repositories": repo_count,
        "events": event_count,
        "errors_24h": error_count,
    }


@router.get("/errors")
async def get_recent_errors(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get recent job errors."""
    result = await db.execute(
        select(ScrapeJob)
        .where(ScrapeJob.status == JobStatus.FAILED)
        .order_by(ScrapeJob.completed_at.desc())
        .limit(limit)
    )
    jobs = result.scalars().all()

    return [
        {
            "id": job.id,
            "repository_id": job.repository_id,
            "job_type": job.job_type.value,
            "error_message": job.error_message,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
        for job in jobs
    ]


# Helper function to log from anywhere in the application
async def log_info(message: str) -> None:
    await broadcaster.log("info", message)


async def log_error(message: str) -> None:
    await broadcaster.log("error", message)


async def log_warning(message: str) -> None:
    await broadcaster.log("warning", message)


async def log_debug(message: str) -> None:
    await broadcaster.log("debug", message)


# ============================================================================
# PIPELINE CONTROL ENDPOINTS
# ============================================================================

class PipelineSettings(BaseModel):
    """Settings for pipeline automation."""
    auto_refresh_stale_repos: bool = True
    auto_recalc_global_after_scrape: bool = True
    auto_recalc_global_interval: bool = True
    stale_threshold_hours: int = 24
    scrape_lookback_days: int = 730


class ScrapeConfig(BaseModel):
    """Configuration for a scrape operation."""
    lookback_days: int = 730
    force: bool = False


@router.get("/pipeline/status")
async def get_pipeline_status(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Get comprehensive pipeline status with prerequisite checks."""

    # Count repositories by status
    repo_stats = {}
    for status in RepositoryStatus:
        result = await db.execute(
            select(func.count(Repository.id)).where(Repository.status == status)
        )
        repo_stats[status.value] = result.scalar() or 0

    total_repos = sum(repo_stats.values())
    completed_repos = repo_stats.get("completed", 0)

    # Count jobs by status
    job_stats = {}
    for status in JobStatus:
        result = await db.execute(
            select(func.count(ScrapeJob.id)).where(ScrapeJob.status == status)
        )
        job_stats[status.value] = result.scalar() or 0

    # Count leaderboard entries
    repo_lb_result = await db.execute(select(func.count(RepositoryLeaderboard.id)))
    repo_lb_count = repo_lb_result.scalar() or 0

    global_lb_result = await db.execute(select(func.count(GlobalLeaderboard.id)))
    global_lb_count = global_lb_result.scalar() or 0

    # Count contributors
    user_result = await db.execute(select(func.count(GitHubUser.id)))
    user_count = user_result.scalar() or 0

    # Find stale repositories (not scraped in threshold hours)
    threshold = datetime.utcnow() - timedelta(hours=pipeline_settings["stale_threshold_hours"])
    stale_result = await db.execute(
        select(func.count(Repository.id)).where(
            (Repository.last_scraped_at < threshold) | (Repository.last_scraped_at.is_(None)),
            Repository.status != RepositoryStatus.SCRAPING,
        )
    )
    stale_count = stale_result.scalar() or 0

    # Get list of pending/failed repos that can be scraped
    scrapable_result = await db.execute(
        select(Repository).where(
            Repository.status.in_([RepositoryStatus.PENDING, RepositoryStatus.FAILED, RepositoryStatus.COMPLETED])
        ).order_by(Repository.last_scraped_at.asc().nullsfirst())
    )
    scrapable_repos = [
        {
            "id": r.id,
            "full_name": f"{r.owner}/{r.name}",
            "status": r.status.value if hasattr(r.status, 'value') else r.status,
            "last_scraped": r.last_scraped_at.isoformat() if r.last_scraped_at else None,
            "stars": r.stars,
        }
        for r in scrapable_result.scalars().all()
    ]

    # Determine which pipeline actions are available
    can_scrape = total_repos > 0 and job_stats.get("running", 0) == 0
    can_recalc_repo = completed_repos > 0
    can_recalc_global = repo_lb_count > 0
    can_enrich = user_count > 0
    has_new_data = completed_repos > 0  # Simplified check

    return {
        "settings": pipeline_settings,
        "repositories": {
            "total": total_repos,
            "by_status": repo_stats,
            "stale_count": stale_count,
            "scrapable": scrapable_repos,
        },
        "jobs": {
            "by_status": job_stats,
            "active": job_stats.get("running", 0) + job_stats.get("queued", 0),
        },
        "leaderboards": {
            "repository_entries": repo_lb_count,
            "global_entries": global_lb_count,
        },
        "contributors": {
            "total": user_count,
        },
        "prerequisites": {
            "can_add_repository": True,  # Always can add
            "can_scrape_repository": can_scrape,
            "can_recalculate_repo_leaderboard": can_recalc_repo,
            "can_recalculate_global_leaderboard": can_recalc_global,
            "can_enrich_contributors": can_enrich,
            "can_refresh_stale": stale_count > 0,
            "has_new_data_to_aggregate": has_new_data,
        },
        "messages": _generate_status_messages(
            total_repos, completed_repos, repo_lb_count, global_lb_count,
            stale_count, job_stats.get("running", 0)
        ),
    }


def _generate_status_messages(
    total_repos: int,
    completed_repos: int,
    repo_lb_count: int,
    global_lb_count: int,
    stale_count: int,
    running_jobs: int,
) -> list[dict[str, str]]:
    """Generate helpful status messages based on current state."""
    messages = []

    if total_repos == 0:
        messages.append({
            "type": "info",
            "text": "No repositories tracked yet. Add a repository to get started.",
        })
    elif completed_repos == 0:
        messages.append({
            "type": "warning",
            "text": "No repositories have been scraped yet. Trigger a scrape to populate leaderboards.",
        })

    if running_jobs > 0:
        messages.append({
            "type": "info",
            "text": f"{running_jobs} job(s) currently running. Wait for completion before starting new scrapes.",
        })

    if stale_count > 0:
        messages.append({
            "type": "warning",
            "text": f"{stale_count} repository(ies) have stale data and should be refreshed.",
        })

    if repo_lb_count > 0 and global_lb_count == 0:
        messages.append({
            "type": "warning",
            "text": "Repository leaderboards exist but global leaderboard is empty. Trigger global recalculation.",
        })

    return messages


@router.get("/pipeline/settings")
async def get_pipeline_settings() -> dict[str, Any]:
    """Get current pipeline automation settings."""
    return pipeline_settings


@router.put("/pipeline/settings")
async def update_pipeline_settings(settings: PipelineSettings) -> dict[str, Any]:
    """Update pipeline automation settings."""
    global pipeline_settings
    pipeline_settings.update(settings.model_dump())
    await broadcaster.log("info", f"Pipeline settings updated: {settings.model_dump()}")
    return pipeline_settings


@router.post("/pipeline/scrape/{owner}/{name}")
async def trigger_scrape(
    owner: str,
    name: str,
    config: ScrapeConfig = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Manually trigger a repository scrape with configuration."""
    from src.workers.tasks.scrape_tasks import scrape_repository

    if config is None:
        config = ScrapeConfig()

    # Find repository
    result = await db.execute(
        select(Repository).where(
            Repository.owner == owner,
            Repository.name == name,
        )
    )
    repository = result.scalar_one_or_none()

    if not repository:
        raise HTTPException(status_code=404, detail=f"Repository {owner}/{name} not found")

    # Check for existing pending/running jobs
    pending_result = await db.execute(
        select(ScrapeJob).where(
            ScrapeJob.repository_id == repository.id,
            ScrapeJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        )
    )
    if pending_result.scalar_one_or_none() and not config.force:
        raise HTTPException(
            status_code=409,
            detail="A job is already queued or running for this repository. Use force=true to override."
        )

    # Create job
    job = ScrapeJob(
        repository_id=repository.id,
        job_type=JobType.FULL_SCRAPE,
    )
    db.add(job)
    await db.flush()

    # Queue task
    task = scrape_repository.delay(repository.id, job.id)
    await db.commit()

    await broadcaster.log("info", f"Scrape triggered for {owner}/{name} (job {job.id}, lookback {config.lookback_days} days)")

    return {
        "status": "queued",
        "job_id": job.id,
        "task_id": task.id,
        "repository": f"{owner}/{name}",
        "config": config.model_dump(),
    }


@router.post("/pipeline/scrape-all-pending")
async def trigger_scrape_all_pending(
    config: ScrapeConfig = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Trigger scrapes for all pending/failed repositories."""
    from src.workers.tasks.scrape_tasks import scrape_repository

    if config is None:
        config = ScrapeConfig()

    # Find all pending/failed repos without active jobs
    result = await db.execute(
        select(Repository).where(
            Repository.status.in_([RepositoryStatus.PENDING, RepositoryStatus.FAILED])
        )
    )
    repos = result.scalars().all()

    queued = []
    skipped = []

    for repo in repos:
        # Check for existing job
        job_result = await db.execute(
            select(ScrapeJob).where(
                ScrapeJob.repository_id == repo.id,
                ScrapeJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
        )
        if job_result.scalar_one_or_none():
            skipped.append(f"{repo.owner}/{repo.name}")
            continue

        # Create job
        job = ScrapeJob(
            repository_id=repo.id,
            job_type=JobType.FULL_SCRAPE,
        )
        db.add(job)
        await db.flush()

        scrape_repository.delay(repo.id, job.id)
        queued.append({"repo": f"{repo.owner}/{repo.name}", "job_id": job.id})

    await db.commit()

    await broadcaster.log("info", f"Batch scrape triggered: {len(queued)} queued, {len(skipped)} skipped")

    return {
        "status": "queued",
        "queued": queued,
        "skipped": skipped,
    }


@router.post("/pipeline/recalculate-repo/{owner}/{name}")
async def trigger_recalculate_repo_leaderboard(
    owner: str,
    name: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Manually recalculate a repository's leaderboard rankings."""
    # Find repository
    result = await db.execute(
        select(Repository).where(
            Repository.owner == owner,
            Repository.name == name,
        )
    )
    repository = result.scalar_one_or_none()

    if not repository:
        raise HTTPException(status_code=404, detail=f"Repository {owner}/{name} not found")

    # Check if there's any leaderboard data
    lb_result = await db.execute(
        select(func.count(RepositoryLeaderboard.id)).where(
            RepositoryLeaderboard.repository_id == repository.id
        )
    )
    lb_count = lb_result.scalar() or 0

    if lb_count == 0:
        raise HTTPException(
            status_code=400,
            detail=f"No leaderboard data for {owner}/{name}. Scrape the repository first."
        )

    # Recalculate rankings in place
    entries_result = await db.execute(
        select(RepositoryLeaderboard)
        .where(RepositoryLeaderboard.repository_id == repository.id)
        .order_by(RepositoryLeaderboard.total_score.desc())
    )
    entries = entries_result.scalars().all()

    for rank, entry in enumerate(entries, start=1):
        entry.rank = rank

    await db.commit()

    await broadcaster.log("info", f"Repository leaderboard recalculated for {owner}/{name} ({lb_count} entries)")

    return {
        "status": "completed",
        "repository": f"{owner}/{name}",
        "entries_ranked": lb_count,
    }


@router.post("/pipeline/recalculate-global")
async def trigger_recalculate_global_leaderboard(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Manually trigger global leaderboard recalculation."""
    from src.workers.tasks.scrape_tasks import recalculate_global_leaderboard

    # Check prerequisite
    lb_result = await db.execute(select(func.count(RepositoryLeaderboard.id)))
    lb_count = lb_result.scalar() or 0

    if lb_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No repository leaderboard data exists. Scrape repositories first."
        )

    # Trigger async task
    task = recalculate_global_leaderboard.delay()

    await broadcaster.log("info", f"Global leaderboard recalculation triggered (task {task.id})")

    return {
        "status": "queued",
        "task_id": task.id,
        "source_entries": lb_count,
    }


@router.post("/pipeline/recalculate-scores")
async def trigger_recalculate_all_scores(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Recalculate all scores using current scoring formula (synchronous)."""
    from decimal import Decimal

    # Get all repository leaderboard entries
    result = await db.execute(select(RepositoryLeaderboard))
    entries = result.scalars().all()

    if not entries:
        raise HTTPException(
            status_code=400,
            detail="No leaderboard entries to recalculate."
        )

    await broadcaster.log("info", f"Starting score recalculation for {len(entries)} entries...")

    # Recalculate each entry
    for entry in entries:
        score = Decimal("0")
        score += Decimal(str(entry.commit_count)) * Decimal("10")
        score += Decimal(str(entry.pr_opened_count)) * Decimal("15")
        score += Decimal(str(entry.pr_merged_count)) * Decimal("25")
        score += Decimal(str(entry.pr_reviewed_count)) * Decimal("20")
        score += Decimal(str(entry.issues_opened_count)) * Decimal("8")
        score += Decimal(str(entry.issues_closed_count)) * Decimal("5")
        score += Decimal(str(entry.comments_count)) * Decimal("3")

        # Line bonus (capped at 500)
        line_bonus = (Decimal(str(entry.lines_added)) * Decimal("0.01")) + \
                     (Decimal(str(entry.lines_deleted)) * Decimal("0.005"))
        line_bonus = min(line_bonus, Decimal("500"))
        score += line_bonus

        entry.total_score = score

    await db.commit()

    # Now recalculate rankings per repository
    repo_ids_result = await db.execute(
        select(RepositoryLeaderboard.repository_id).distinct()
    )
    repo_ids = [r[0] for r in repo_ids_result.all()]

    for repo_id in repo_ids:
        entries_result = await db.execute(
            select(RepositoryLeaderboard)
            .where(RepositoryLeaderboard.repository_id == repo_id)
            .order_by(RepositoryLeaderboard.total_score.desc())
        )
        repo_entries = entries_result.scalars().all()
        for rank, e in enumerate(repo_entries, start=1):
            e.rank = rank

    await db.commit()

    await broadcaster.log("info", f"Score recalculation complete: {len(entries)} entries updated")

    # Trigger global leaderboard recalc
    from src.workers.tasks.scrape_tasks import recalculate_global_leaderboard
    task = recalculate_global_leaderboard.delay()

    return {
        "status": "completed",
        "entries_recalculated": len(entries),
        "repositories_ranked": len(repo_ids),
        "global_recalc_task_id": task.id,
    }


@router.post("/pipeline/refresh-stale")
async def trigger_refresh_stale(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Manually trigger refresh of stale repositories."""
    from src.workers.tasks.scrape_tasks import scrape_repository

    threshold = datetime.utcnow() - timedelta(hours=pipeline_settings["stale_threshold_hours"])

    result = await db.execute(
        select(Repository).where(
            (Repository.last_scraped_at < threshold) | (Repository.last_scraped_at.is_(None)),
            Repository.status != RepositoryStatus.SCRAPING,
        )
    )
    stale_repos = result.scalars().all()

    if not stale_repos:
        return {
            "status": "no_action",
            "message": "No stale repositories found.",
            "threshold_hours": pipeline_settings["stale_threshold_hours"],
        }

    queued = []
    for repo in stale_repos:
        # Check for existing job
        job_result = await db.execute(
            select(ScrapeJob).where(
                ScrapeJob.repository_id == repo.id,
                ScrapeJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
        )
        if job_result.scalar_one_or_none():
            continue

        job = ScrapeJob(
            repository_id=repo.id,
            job_type=JobType.INCREMENTAL,
        )
        db.add(job)
        await db.flush()

        scrape_repository.delay(repo.id, job.id)
        queued.append(f"{repo.owner}/{repo.name}")

    await db.commit()

    await broadcaster.log("info", f"Stale refresh triggered: {len(queued)} repositories queued")

    return {
        "status": "queued",
        "repositories_queued": queued,
        "threshold_hours": pipeline_settings["stale_threshold_hours"],
    }


@router.post("/pipeline/cleanup-jobs")
async def cleanup_stale_jobs(
    max_age_hours: int = Query(default=2, ge=1, le=24),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Clean up stale queued/running jobs that are stuck."""
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)

    result = await db.execute(
        select(ScrapeJob).where(
            ScrapeJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            ScrapeJob.created_at < cutoff,
        )
    )
    stale_jobs = result.scalars().all()

    cleaned = []
    for job in stale_jobs:
        job.status = JobStatus.FAILED
        job.error_message = f"Marked as failed - stale job (older than {max_age_hours} hours)"
        job.completed_at = datetime.utcnow()
        cleaned.append(job.id)

    # Also reset stuck SCRAPING repositories
    stuck_result = await db.execute(
        select(Repository).where(Repository.status == RepositoryStatus.SCRAPING)
    )
    stuck_repos = stuck_result.scalars().all()
    reset_repos = []
    for repo in stuck_repos:
        repo.status = RepositoryStatus.PENDING
        reset_repos.append(f"{repo.owner}/{repo.name}")

    await db.commit()

    await broadcaster.log("warning", f"Cleanup: {len(cleaned)} jobs failed, {len(reset_repos)} repos reset")

    return {
        "status": "completed",
        "jobs_cleaned": cleaned,
        "repositories_reset": reset_repos,
        "max_age_hours": max_age_hours,
    }


# ============================================================================
# BUDGET & COST TRACKING ENDPOINTS
# ============================================================================

class BudgetConfigUpdate(BaseModel):
    """Budget configuration update model."""
    monthly_budget_limit: float | None = None
    daily_budget_limit: float | None = None
    per_job_limit: float | None = None
    alert_threshold_warning: int | None = None
    alert_threshold_critical: int | None = None
    auto_pause_on_budget_exceeded: bool | None = None
    bigquery_price_per_tb: float | None = None


@router.get("/budget/config")
async def get_budget_config(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Get current budget configuration."""
    from src.services.budget_service import BudgetService
    service = BudgetService(db)
    config = await service.get_active_config()

    return {
        "monthly_budget_limit_usd": float(config.monthly_budget_limit),
        "daily_budget_limit_usd": float(config.daily_budget_limit),
        "per_job_limit_usd": float(config.per_job_limit),
        "alert_threshold_warning_pct": config.alert_threshold_warning,
        "alert_threshold_critical_pct": config.alert_threshold_critical,
        "auto_pause_on_budget_exceeded": config.auto_pause_on_budget_exceeded,
        "bigquery_price_per_tb_usd": float(config.bigquery_price_per_tb),
    }


@router.put("/budget/config")
async def update_budget_config(
    config: BudgetConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update budget configuration."""
    from decimal import Decimal
    from src.services.budget_service import BudgetService

    service = BudgetService(db)
    updates = {}

    if config.monthly_budget_limit is not None:
        updates["monthly_budget_limit"] = Decimal(str(config.monthly_budget_limit))
    if config.daily_budget_limit is not None:
        updates["daily_budget_limit"] = Decimal(str(config.daily_budget_limit))
    if config.per_job_limit is not None:
        updates["per_job_limit"] = Decimal(str(config.per_job_limit))
    if config.alert_threshold_warning is not None:
        updates["alert_threshold_warning"] = config.alert_threshold_warning
    if config.alert_threshold_critical is not None:
        updates["alert_threshold_critical"] = config.alert_threshold_critical
    if config.auto_pause_on_budget_exceeded is not None:
        updates["auto_pause_on_budget_exceeded"] = config.auto_pause_on_budget_exceeded
    if config.bigquery_price_per_tb is not None:
        updates["bigquery_price_per_tb"] = Decimal(str(config.bigquery_price_per_tb))

    if updates:
        await service.update_config(updates)

    await broadcaster.log("info", f"Budget config updated: {updates}")
    return await get_budget_config(db)


@router.get("/budget/status")
async def get_budget_status(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Get current budget status and spending."""
    from decimal import Decimal
    from src.services.budget_service import BudgetService

    service = BudgetService(db)
    config = await service.get_active_config()
    status = await service._check_budget_status(Decimal("0"), config)

    return status


@router.get("/budget/analytics")
async def get_budget_analytics(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get comprehensive budget analytics."""
    from src.services.budget_service import BudgetService

    service = BudgetService(db)
    return await service.get_budget_analytics(days)


@router.get("/budget/estimate/{owner}/{name}")
async def estimate_scrape_cost(
    owner: str,
    name: str,
    lookback_days: int = Query(default=730, ge=1, le=3650),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Estimate cost for scraping a repository."""
    from src.services.budget_service import BudgetService

    # Find repository
    result = await db.execute(
        select(Repository).where(
            Repository.owner == owner,
            Repository.name == name,
        )
    )
    repository = result.scalar_one_or_none()

    if not repository:
        raise HTTPException(status_code=404, detail=f"Repository {owner}/{name} not found")

    service = BudgetService(db)
    return await service.estimate_scrape_cost(repository.id, lookback_days)


@router.get("/budget/estimate-batch")
async def estimate_batch_cost(
    lookback_days: int = Query(default=730, ge=1, le=3650),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Estimate cost for scraping all pending repositories."""
    from src.services.budget_service import BudgetService

    # Get all pending/failed repos
    result = await db.execute(
        select(Repository).where(
            Repository.status.in_([RepositoryStatus.PENDING, RepositoryStatus.FAILED])
        )
    )
    repos = result.scalars().all()
    repo_ids = [r.id for r in repos]

    if not repo_ids:
        return {
            "repository_count": 0,
            "estimates": [],
            "total_estimated_cost_usd": 0,
            "message": "No pending repositories to estimate",
        }

    service = BudgetService(db)
    return await service.estimate_batch_cost(repo_ids, lookback_days)


@router.get("/audit/logs")
async def get_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    category: str | None = None,
    action: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get paginated audit logs."""
    from src.services.budget_service import BudgetService

    service = BudgetService(db)
    logs, total = await service.get_audit_logs(
        page=page,
        page_size=page_size,
        category=category,
        action=action,
    )

    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
