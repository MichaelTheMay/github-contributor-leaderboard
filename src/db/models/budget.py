"""Budget tracking and audit log models."""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.base import Base, TimestampMixin


class CostCategory(str, Enum):
    """Categories for cost tracking."""

    BIGQUERY_SCAN = "bigquery_scan"
    BIGQUERY_STORAGE = "bigquery_storage"
    GITHUB_API = "github_api"
    ENRICHMENT_API = "enrichment_api"
    INFRASTRUCTURE = "infrastructure"


class AuditAction(str, Enum):
    """Types of auditable actions."""

    JOB_STARTED = "job_started"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    REPOSITORY_ADDED = "repository_added"
    REPOSITORY_REMOVED = "repository_removed"
    LEADERBOARD_RECALCULATED = "leaderboard_recalculated"
    SETTINGS_CHANGED = "settings_changed"
    COST_RECORDED = "cost_recorded"
    BUDGET_ALERT = "budget_alert"


class BudgetConfig(Base, TimestampMixin):
    """Budget configuration and limits."""

    __tablename__ = "budget_config"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Monthly budget limits (in USD)
    monthly_budget_limit: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("50.00"))
    daily_budget_limit: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("10.00"))
    per_job_limit: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("5.00"))

    # Alert thresholds (percentage of budget)
    alert_threshold_warning: Mapped[int] = mapped_column(default=70)  # 70%
    alert_threshold_critical: Mapped[int] = mapped_column(default=90)  # 90%

    # Auto-pause when budget exceeded
    auto_pause_on_budget_exceeded: Mapped[bool] = mapped_column(default=True)

    # BigQuery pricing (per TB scanned, in USD)
    bigquery_price_per_tb: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("5.00"))

    # Is this the active config
    is_active: Mapped[bool] = mapped_column(default=True)


class CostRecord(Base, TimestampMixin):
    """Individual cost records for tracking expenses."""

    __tablename__ = "cost_records"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Link to job (optional - some costs may not be job-related)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Link to repository (optional)
    repository_id: Mapped[int | None] = mapped_column(
        ForeignKey("repositories.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Cost details
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=True)

    # Amounts
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    actual_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))

    # BigQuery specific metrics
    bytes_processed: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_billed: Mapped[int] = mapped_column(BigInteger, default=0)

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int] = mapped_column(default=0)

    # Additional data (renamed from 'metadata' which is reserved in SQLAlchemy)
    extra_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    job = relationship("ScrapeJob", back_populates="cost_records")
    repository = relationship("Repository", back_populates="cost_records")

    __table_args__ = (
        Index("idx_cost_records_category", "category"),
        Index("idx_cost_records_created", "created_at"),
        Index("idx_cost_records_job", "job_id"),
    )


class DailyCostSummary(Base, TimestampMixin):
    """Daily aggregated cost summary for quick lookups."""

    __tablename__ = "daily_cost_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Date for this summary
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=True)

    # Aggregated costs by category
    bigquery_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    github_api_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    enrichment_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    infrastructure_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))

    # Metrics
    total_bytes_processed: Mapped[int] = mapped_column(BigInteger, default=0)
    jobs_completed: Mapped[int] = mapped_column(default=0)
    jobs_failed: Mapped[int] = mapped_column(default=0)
    repositories_scraped: Mapped[int] = mapped_column(default=0)

    __table_args__ = (Index("idx_daily_cost_date", "date"),)


class AuditLog(Base):
    """Comprehensive audit log for all system actions."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    # Action details
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    # Related entities
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    repository_id: Mapped[int | None] = mapped_column(
        ForeignKey("repositories.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("github_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Cost tracking
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    bytes_processed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Outcome
    success: Mapped[bool] = mapped_column(default=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Additional context (renamed from 'metadata' which is reserved in SQLAlchemy)
    extra_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Source of action
    source: Mapped[str] = mapped_column(String(50), default="system")  # system, api, scheduler
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    __table_args__ = (
        Index("idx_audit_timestamp", "timestamp"),
        Index("idx_audit_action", "action"),
        Index("idx_audit_category", "category"),
        Index("idx_audit_job", "job_id"),
        Index("idx_audit_repository", "repository_id"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} at {self.timestamp}>"
