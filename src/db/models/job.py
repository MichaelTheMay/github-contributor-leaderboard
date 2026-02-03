from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.base import Base, TimestampMixin


class JobType(str, Enum):
    FULL_SCRAPE = "full_scrape"
    INCREMENTAL = "incremental"
    SPECIFIC_TYPE = "specific_type"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ScrapeJob(Base, TimestampMixin):
    __tablename__ = "scrape_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_type: Mapped[JobType] = mapped_column(String(50), nullable=False)
    status: Mapped[JobStatus] = mapped_column(String(50), default=JobStatus.QUEUED)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    events_processed: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text)

    # Cost tracking fields
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    actual_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    bytes_processed: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_billed: Mapped[int] = mapped_column(BigInteger, default=0)

    # Relationships
    repository = relationship("Repository", back_populates="scrape_jobs")
    cost_records = relationship("CostRecord", back_populates="job", cascade="all, delete-orphan")
    scrape_window = relationship("ScrapeWindow", back_populates="job", uselist=False)

    __table_args__ = (
        Index("idx_scrape_jobs_repo_status", "repository_id", "status"),
        Index("idx_scrape_jobs_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<ScrapeJob {self.job_type} for repo_id={self.repository_id} status={self.status}>"
