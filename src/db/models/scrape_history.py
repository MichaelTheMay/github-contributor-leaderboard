from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.base import Base, TimestampMixin


class ScrapeWindow(Base, TimestampMixin):
    """Track each BigQuery scrape operation per repository.

    This enables incremental scraping by tracking what time periods have been
    scraped, avoiding expensive full re-scrapes and enabling deduplication.
    """

    __tablename__ = "scrape_windows"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Time window that was scraped from BigQuery
    data_start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    data_end_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Metrics from this scrape
    events_fetched: Mapped[int] = mapped_column(default=0)
    contributors_found: Mapped[int] = mapped_column(default=0)
    bytes_processed: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_billed: Mapped[int] = mapped_column(BigInteger, default=0)

    # Relationships
    repository = relationship("Repository", back_populates="scrape_windows")
    job = relationship("ScrapeJob", back_populates="scrape_window")

    __table_args__ = (
        Index("idx_scrape_windows_repo_dates", "repository_id", "data_end_date"),
        UniqueConstraint(
            "repository_id",
            "data_start_date",
            "data_end_date",
            name="uq_scrape_windows_repo_date_range",
        ),
    )

    def __repr__(self) -> str:
        return f"<ScrapeWindow repo_id={self.repository_id} {self.data_start_date} to {self.data_end_date}>"
