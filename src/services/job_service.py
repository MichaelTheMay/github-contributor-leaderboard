import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.db.models.job import JobStatus, ScrapeJob

logger = structlog.get_logger()


class JobService:
    """Service for managing scrape jobs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_jobs(
        self,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict], int]:
        """List scrape jobs with optional status filter."""
        offset = (page - 1) * page_size

        # Build query
        query = select(ScrapeJob).options(joinedload(ScrapeJob.repository))

        if status:
            try:
                status_enum = JobStatus(status)
                query = query.where(ScrapeJob.status == status_enum)
            except ValueError:
                pass

        # Get total count
        count_query = select(func.count(ScrapeJob.id))
        if status:
            try:
                status_enum = JobStatus(status)
                count_query = count_query.where(ScrapeJob.status == status_enum)
            except ValueError:
                pass

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # Get paginated results
        result = await self.db.execute(
            query.order_by(ScrapeJob.created_at.desc()).offset(offset).limit(page_size)
        )
        jobs = result.scalars().all()

        formatted = []
        for job in jobs:
            formatted.append(
                {
                    "id": job.id,
                    "repository": (
                        job.repository.full_name if job.repository else "Unknown"
                    ),
                    "job_type": job.job_type.value,
                    "status": job.status.value,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "completed_at": (
                        job.completed_at.isoformat() if job.completed_at else None
                    ),
                    "events_processed": job.events_processed,
                    "error_message": job.error_message,
                    "created_at": job.created_at.isoformat(),
                }
            )

        return formatted, total

    async def get_job(self, job_id: int) -> ScrapeJob | None:
        """Get a specific job by ID."""
        result = await self.db.execute(
            select(ScrapeJob)
            .options(joinedload(ScrapeJob.repository))
            .where(ScrapeJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def update_job_status(
        self,
        job_id: int,
        status: JobStatus,
        events_processed: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update job status and metadata."""
        job = await self.get_job(job_id)
        if job:
            job.status = status
            if events_processed is not None:
                job.events_processed = events_processed
            if error_message:
                job.error_message = error_message

            logger.info(
                "Job status updated",
                job_id=job_id,
                status=status.value,
            )
