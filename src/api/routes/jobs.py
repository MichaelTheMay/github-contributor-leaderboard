from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.services.job_service import JobService

router = APIRouter()


@router.get(
    "",
    summary="List recent jobs",
)
async def list_jobs(
    status: str | None = Query(None, description="Filter by job status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a list of recent scrape jobs."""
    service = JobService(db)
    jobs, total = await service.list_jobs(status, page, page_size)
    return {
        "jobs": jobs,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
