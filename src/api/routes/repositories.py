from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.repository import RepositoryCreate, RepositoryDetail, RepositoryList
from src.db import get_db
from src.services.repository_service import RepositoryService

router = APIRouter()


@router.post(
    "",
    response_model=RepositoryDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Add a repository to track",
)
async def create_repository(
    data: RepositoryCreate,
    db: AsyncSession = Depends(get_db),
) -> RepositoryDetail:
    """Add a GitHub repository to the tracking system."""
    service = RepositoryService(db)
    repository = await service.add_repository(data.owner, data.name)
    return RepositoryDetail.model_validate(repository)


@router.get(
    "",
    response_model=RepositoryList,
    summary="List all tracked repositories",
)
async def list_repositories(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> RepositoryList:
    """Get a paginated list of all tracked repositories."""
    service = RepositoryService(db)
    repositories, total = await service.list_repositories(page, page_size)
    return RepositoryList(
        repositories=[RepositoryDetail.model_validate(r) for r in repositories],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{owner}/{name}",
    response_model=RepositoryDetail,
    summary="Get repository details",
)
async def get_repository(
    owner: str,
    name: str,
    db: AsyncSession = Depends(get_db),
) -> RepositoryDetail:
    """Get details of a specific tracked repository."""
    service = RepositoryService(db)
    repository = await service.get_repository(owner, name)
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {owner}/{name} not found",
        )
    return RepositoryDetail.model_validate(repository)


@router.delete(
    "/{owner}/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove repository from tracking",
)
async def delete_repository(
    owner: str,
    name: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a repository from the tracking system."""
    service = RepositoryService(db)
    deleted = await service.delete_repository(owner, name)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {owner}/{name} not found",
        )


@router.post(
    "/{owner}/{name}/refresh",
    response_model=dict,
    summary="Trigger manual data refresh",
)
async def refresh_repository(
    owner: str,
    name: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger a manual refresh of repository data."""
    service = RepositoryService(db)
    job = await service.trigger_refresh(owner, name)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {owner}/{name} not found",
        )
    return {"message": "Refresh job queued", "job_id": job.id}


@router.post(
    "/{owner}/{name}/scrape",
    response_model=dict,
    summary="Trigger full BigQuery scrape",
)
async def scrape_repository(
    owner: str,
    name: str,
    force: bool = Query(False, description="Force re-scrape even if already completed"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger a full BigQuery scrape for repository data (requires Celery worker)."""
    from sqlalchemy import select

    from src.db.models.job import JobStatus, ScrapeJob
    from src.db.models.repository import RepositoryStatus
    from src.workers.tasks.scrape_tasks import trigger_repository_scrape

    service = RepositoryService(db)
    repository = await service.get_repository(owner, name)
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {owner}/{name} not found",
        )

    # Check if already scraping or has pending job
    pending_job = await db.execute(
        select(ScrapeJob).where(
            ScrapeJob.repository_id == repository.id,
            ScrapeJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        )
    )
    if pending_job.scalar_one_or_none():
        return {
            "message": "Scrape already in progress or queued",
            "repository": f"{owner}/{name}",
            "status": "already_queued",
        }

    # Check if already completed and not forcing
    if repository.status == RepositoryStatus.COMPLETED and not force:
        return {
            "message": "Repository already scraped. Use force=true to re-scrape.",
            "repository": f"{owner}/{name}",
            "status": "already_completed",
            "last_scraped": repository.last_scraped_at.isoformat()
            if repository.last_scraped_at
            else None,
        }

    # Trigger async scrape via Celery
    result = trigger_repository_scrape.delay(owner, name)

    return {
        "message": "Scrape job queued",
        "task_id": result.id,
        "repository": f"{owner}/{name}",
    }
