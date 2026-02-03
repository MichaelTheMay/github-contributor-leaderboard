from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Computed, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.base import Base, TimestampMixin


class RepositoryStatus(str, Enum):
    PENDING = "pending"
    SCRAPING = "scraping"
    COMPLETED = "completed"
    FAILED = "failed"


class Repository(Base, TimestampMixin):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(
        String(512),
        Computed("owner || '/' || name"),
        nullable=False,
    )
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    stars: Mapped[int] = mapped_column(default=0)
    forks: Mapped[int] = mapped_column(default=0)
    status: Mapped[RepositoryStatus] = mapped_column(
        String(50),
        default=RepositoryStatus.PENDING,
    )
    last_scraped_at: Mapped[datetime | None] = mapped_column()

    # Scrape tracking fields for incremental scraping
    first_scraped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    earliest_data_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    latest_data_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    never_rescrape_before: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    # Relationships
    contribution_events = relationship(
        "ContributionEvent",
        back_populates="repository",
        cascade="all, delete-orphan",
    )
    leaderboard_entries = relationship(
        "RepositoryLeaderboard",
        back_populates="repository",
        cascade="all, delete-orphan",
    )
    scrape_jobs = relationship(
        "ScrapeJob",
        back_populates="repository",
        cascade="all, delete-orphan",
    )
    scrape_windows = relationship(
        "ScrapeWindow",
        back_populates="repository",
        cascade="all, delete-orphan",
    )
    cost_records = relationship(
        "CostRecord",
        back_populates="repository",
    )

    __table_args__ = (
        Index("idx_repositories_owner_name", "owner", "name", unique=True),
        Index("idx_repositories_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Repository {self.full_name}>"
