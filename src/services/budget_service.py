"""Budget tracking, cost estimation, and audit logging service."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.budget import (
    AuditAction,
    AuditLog,
    BudgetConfig,
    CostCategory,
    CostRecord,
)
from src.db.models.job import ScrapeJob
from src.db.models.repository import Repository

logger = structlog.get_logger()

# BigQuery cost estimation constants
BYTES_PER_TB = 1024 * 1024 * 1024 * 1024  # 1 TB in bytes
DEFAULT_PRICE_PER_TB = Decimal("5.00")  # $5 per TB scanned

# Repository size estimation (rough bytes per year of activity)
REPO_SIZE_ESTIMATES = {
    "small": 50 * 1024 * 1024,  # 50 MB - small repos
    "medium": 200 * 1024 * 1024,  # 200 MB - medium repos
    "large": 500 * 1024 * 1024,  # 500 MB - large repos
    "huge": 2 * 1024 * 1024 * 1024,  # 2 GB - very active repos
}


class BudgetService:
    """Service for budget tracking, cost estimation, and audit logging."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # =========================================================================
    # Budget Configuration
    # =========================================================================

    async def get_active_config(self) -> BudgetConfig:
        """Get or create the active budget configuration."""
        result = await self.db.execute(select(BudgetConfig).where(BudgetConfig.is_active.is_(True)))
        config = result.scalar_one_or_none()

        if not config:
            config = BudgetConfig(is_active=True)
            self.db.add(config)
            await self.db.commit()
            await self.db.refresh(config)

        return config

    async def update_config(self, updates: dict[str, Any]) -> BudgetConfig:
        """Update budget configuration."""
        config = await self.get_active_config()

        for key, value in updates.items():
            if hasattr(config, key):
                setattr(config, key, value)

        await self.db.commit()
        await self.db.refresh(config)

        await self.log_audit(
            action=AuditAction.SETTINGS_CHANGED,
            category="budget",
            description=f"Budget config updated: {updates}",
            extra_data=updates,
        )

        return config

    # =========================================================================
    # Cost Estimation
    # =========================================================================

    async def estimate_scrape_cost(
        self,
        repository_id: int,
        lookback_days: int = 730,
    ) -> dict[str, Any]:
        """Estimate the cost of scraping a repository."""
        config = await self.get_active_config()

        # Get repository info
        result = await self.db.execute(select(Repository).where(Repository.id == repository_id))
        repository = result.scalar_one_or_none()

        if not repository:
            return {"error": "Repository not found"}

        # Estimate bytes based on repository size (stars as proxy)
        stars = repository.stars or 0
        if stars > 50000:
            size_category = "huge"
        elif stars > 10000:
            size_category = "large"
        elif stars > 1000:
            size_category = "medium"
        else:
            size_category = "small"

        # Base bytes estimate adjusted for lookback period
        years = lookback_days / 365
        estimated_bytes = int(REPO_SIZE_ESTIMATES[size_category] * years)

        # Calculate cost
        estimated_cost = self._calculate_cost(estimated_bytes, config.bigquery_price_per_tb)

        # Check against budget
        budget_status = await self._check_budget_status(estimated_cost, config)

        return {
            "repository": f"{repository.owner}/{repository.name}",
            "stars": stars,
            "size_category": size_category,
            "lookback_days": lookback_days,
            "estimated_bytes": estimated_bytes,
            "estimated_bytes_human": self._format_bytes(estimated_bytes),
            "estimated_cost_usd": float(estimated_cost),
            "price_per_tb_usd": float(config.bigquery_price_per_tb),
            "budget_status": budget_status,
            "can_proceed": budget_status["can_proceed"],
        }

    async def estimate_batch_cost(
        self,
        repository_ids: list[int],
        lookback_days: int = 730,
    ) -> dict[str, Any]:
        """Estimate cost for scraping multiple repositories."""
        estimates = []
        total_cost = Decimal("0")
        total_bytes = 0

        for repo_id in repository_ids:
            estimate = await self.estimate_scrape_cost(repo_id, lookback_days)
            if "error" not in estimate:
                estimates.append(estimate)
                total_cost += Decimal(str(estimate["estimated_cost_usd"]))
                total_bytes += estimate["estimated_bytes"]

        config = await self.get_active_config()
        budget_status = await self._check_budget_status(total_cost, config)

        return {
            "repository_count": len(estimates),
            "estimates": estimates,
            "total_estimated_bytes": total_bytes,
            "total_estimated_bytes_human": self._format_bytes(total_bytes),
            "total_estimated_cost_usd": float(total_cost),
            "budget_status": budget_status,
            "can_proceed": budget_status["can_proceed"],
        }

    async def _check_budget_status(
        self,
        estimated_cost: Decimal,
        config: BudgetConfig,
    ) -> dict[str, Any]:
        """Check if the estimated cost fits within budget."""
        # Get current spending
        today = datetime.utcnow().date()
        month_start = today.replace(day=1)

        # Daily spend
        daily_result = await self.db.execute(
            select(func.sum(CostRecord.actual_cost)).where(
                func.date(CostRecord.created_at) == today
            )
        )
        daily_spent = daily_result.scalar() or Decimal("0")

        # Monthly spend
        monthly_result = await self.db.execute(
            select(func.sum(CostRecord.actual_cost)).where(
                CostRecord.created_at >= datetime.combine(month_start, datetime.min.time())
            )
        )
        monthly_spent = monthly_result.scalar() or Decimal("0")

        # Calculate projections
        daily_projected = daily_spent + estimated_cost
        monthly_projected = monthly_spent + estimated_cost

        # Check limits
        exceeds_daily = daily_projected > config.daily_budget_limit
        exceeds_monthly = monthly_projected > config.monthly_budget_limit
        exceeds_per_job = estimated_cost > config.per_job_limit

        # Calculate percentages
        daily_pct = (
            (float(daily_projected) / float(config.daily_budget_limit)) * 100
            if config.daily_budget_limit
            else 0
        )
        monthly_pct = (
            (float(monthly_projected) / float(config.monthly_budget_limit)) * 100
            if config.monthly_budget_limit
            else 0
        )

        # Determine warning level
        warning_level = "normal"
        if (
            daily_pct >= config.alert_threshold_critical
            or monthly_pct >= config.alert_threshold_critical
        ):
            warning_level = "critical"
        elif (
            daily_pct >= config.alert_threshold_warning
            or monthly_pct >= config.alert_threshold_warning
        ):
            warning_level = "warning"

        can_proceed = not (exceeds_daily or exceeds_monthly or exceeds_per_job)
        if config.auto_pause_on_budget_exceeded and not can_proceed:
            can_proceed = False

        return {
            "daily_spent_usd": float(daily_spent),
            "daily_limit_usd": float(config.daily_budget_limit),
            "daily_projected_usd": float(daily_projected),
            "daily_percentage": round(daily_pct, 1),
            "monthly_spent_usd": float(monthly_spent),
            "monthly_limit_usd": float(config.monthly_budget_limit),
            "monthly_projected_usd": float(monthly_projected),
            "monthly_percentage": round(monthly_pct, 1),
            "per_job_limit_usd": float(config.per_job_limit),
            "exceeds_daily": exceeds_daily,
            "exceeds_monthly": exceeds_monthly,
            "exceeds_per_job": exceeds_per_job,
            "warning_level": warning_level,
            "can_proceed": can_proceed,
            "auto_pause_enabled": config.auto_pause_on_budget_exceeded,
        }

    # =========================================================================
    # Cost Recording
    # =========================================================================

    async def record_job_cost(
        self,
        job_id: int,
        bytes_processed: int,
        bytes_billed: int,
        duration_seconds: int,
        metadata: dict[str, Any] | None = None,
    ) -> CostRecord:
        """Record actual cost after a job completes."""
        config = await self.get_active_config()

        # Calculate actual cost
        actual_cost = self._calculate_cost(bytes_billed, config.bigquery_price_per_tb)

        # Get job and repository info
        job_result = await self.db.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
        job = job_result.scalar_one_or_none()

        # Create cost record
        record = CostRecord(
            job_id=job_id,
            repository_id=job.repository_id if job else None,
            category=CostCategory.BIGQUERY_SCAN.value,
            description=f"BigQuery scan for job {job_id}",
            estimated_cost=job.estimated_cost if job else Decimal("0"),
            actual_cost=actual_cost,
            bytes_processed=bytes_processed,
            bytes_billed=bytes_billed,
            started_at=job.started_at if job else None,
            completed_at=datetime.utcnow(),
            duration_seconds=duration_seconds,
            extra_data=metadata,
        )
        self.db.add(record)

        # Update job with actual cost
        if job:
            job.actual_cost = actual_cost
            job.bytes_processed = bytes_processed
            job.bytes_billed = bytes_billed

        await self.db.commit()
        await self.db.refresh(record)

        # Log audit
        await self.log_audit(
            action=AuditAction.COST_RECORDED,
            category="cost",
            description=f"Cost recorded: ${actual_cost:.6f} for job {job_id}",
            job_id=job_id,
            actual_cost=actual_cost,
            bytes_processed=bytes_processed,
            extra_data=metadata,
        )

        # Check if budget alert needed
        await self._check_and_alert_budget(actual_cost, config)

        return record

    async def record_estimated_cost(
        self,
        job_id: int,
        estimated_cost: Decimal,
    ) -> None:
        """Record estimated cost when job is created."""
        job_result = await self.db.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
        job = job_result.scalar_one_or_none()
        if job:
            job.estimated_cost = estimated_cost
            await self.db.commit()

    async def _check_and_alert_budget(
        self,
        cost: Decimal,
        config: BudgetConfig,
    ) -> None:
        """Check budget thresholds and log alerts if needed."""
        status = await self._check_budget_status(Decimal("0"), config)

        if status["warning_level"] == "critical":
            await self.log_audit(
                action=AuditAction.BUDGET_ALERT,
                category="budget",
                description=f"CRITICAL: Budget threshold exceeded - Daily: {status['daily_percentage']}%, Monthly: {status['monthly_percentage']}%",
                extra_data=status,
            )
        elif status["warning_level"] == "warning":
            await self.log_audit(
                action=AuditAction.BUDGET_ALERT,
                category="budget",
                description=f"WARNING: Approaching budget limit - Daily: {status['daily_percentage']}%, Monthly: {status['monthly_percentage']}%",
                extra_data=status,
            )

    # =========================================================================
    # Analytics
    # =========================================================================

    async def get_budget_analytics(self, days: int = 30) -> dict[str, Any]:
        """Get comprehensive budget analytics."""
        config = await self.get_active_config()
        today = datetime.utcnow().date()
        start_date = today - timedelta(days=days)

        # Daily costs for the period
        daily_result = await self.db.execute(
            select(
                func.date(CostRecord.created_at).label("date"),
                func.sum(CostRecord.actual_cost).label("cost"),
                func.sum(CostRecord.bytes_billed).label("bytes"),
                func.count(CostRecord.id).label("jobs"),
            )
            .where(CostRecord.created_at >= datetime.combine(start_date, datetime.min.time()))
            .group_by(func.date(CostRecord.created_at))
            .order_by(func.date(CostRecord.created_at))
        )
        daily_data = [
            {
                "date": str(row.date),
                "cost_usd": float(row.cost or 0),
                "bytes_billed": row.bytes or 0,
                "jobs": row.jobs or 0,
            }
            for row in daily_result.all()
        ]

        # Total for period
        total_result = await self.db.execute(
            select(
                func.sum(CostRecord.actual_cost).label("total_cost"),
                func.sum(CostRecord.bytes_billed).label("total_bytes"),
                func.count(CostRecord.id).label("total_jobs"),
            ).where(CostRecord.created_at >= datetime.combine(start_date, datetime.min.time()))
        )
        totals = total_result.one()

        # Cost by repository
        repo_result = await self.db.execute(
            select(
                Repository.owner,
                Repository.name,
                func.sum(CostRecord.actual_cost).label("cost"),
                func.sum(CostRecord.bytes_billed).label("bytes"),
                func.count(CostRecord.id).label("jobs"),
            )
            .join(Repository, CostRecord.repository_id == Repository.id)
            .where(CostRecord.created_at >= datetime.combine(start_date, datetime.min.time()))
            .group_by(Repository.owner, Repository.name)
            .order_by(func.sum(CostRecord.actual_cost).desc())
        )
        by_repository = [
            {
                "repository": f"{row.owner}/{row.name}",
                "cost_usd": float(row.cost or 0),
                "bytes_billed": row.bytes or 0,
                "jobs": row.jobs or 0,
            }
            for row in repo_result.all()
        ]

        # Current budget status
        budget_status = await self._check_budget_status(Decimal("0"), config)

        # Recent jobs with costs
        recent_result = await self.db.execute(
            select(ScrapeJob)
            .where(ScrapeJob.actual_cost > 0)
            .order_by(ScrapeJob.completed_at.desc())
            .limit(10)
        )
        recent_jobs = []
        for job in recent_result.scalars().all():
            recent_jobs.append(
                {
                    "job_id": job.id,
                    "repository_id": job.repository_id,
                    "estimated_cost_usd": float(job.estimated_cost),
                    "actual_cost_usd": float(job.actual_cost),
                    "bytes_processed": job.bytes_processed,
                    "accuracy_pct": round(
                        (float(job.actual_cost) / float(job.estimated_cost) * 100), 1
                    )
                    if job.estimated_cost
                    else 0,
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                }
            )

        return {
            "period_days": days,
            "config": {
                "daily_limit_usd": float(config.daily_budget_limit),
                "monthly_limit_usd": float(config.monthly_budget_limit),
                "per_job_limit_usd": float(config.per_job_limit),
                "price_per_tb_usd": float(config.bigquery_price_per_tb),
                "warning_threshold_pct": config.alert_threshold_warning,
                "critical_threshold_pct": config.alert_threshold_critical,
            },
            "totals": {
                "cost_usd": float(totals.total_cost or 0),
                "bytes_billed": totals.total_bytes or 0,
                "bytes_billed_human": self._format_bytes(totals.total_bytes or 0),
                "jobs": totals.total_jobs or 0,
            },
            "daily_data": daily_data,
            "by_repository": by_repository,
            "recent_jobs": recent_jobs,
            "current_status": budget_status,
        }

    # =========================================================================
    # Audit Logging
    # =========================================================================

    async def log_audit(
        self,
        action: AuditAction,
        category: str,
        description: str | None = None,
        job_id: int | None = None,
        repository_id: int | None = None,
        user_id: int | None = None,
        estimated_cost: Decimal | None = None,
        actual_cost: Decimal | None = None,
        bytes_processed: int | None = None,
        success: bool = True,
        error_message: str | None = None,
        extra_data: dict[str, Any] | None = None,
        source: str = "system",
    ) -> AuditLog:
        """Create an audit log entry."""
        entry = AuditLog(
            action=action.value if isinstance(action, AuditAction) else action,
            category=category,
            description=description,
            job_id=job_id,
            repository_id=repository_id,
            user_id=user_id,
            estimated_cost=estimated_cost,
            actual_cost=actual_cost,
            bytes_processed=bytes_processed,
            success=success,
            error_message=error_message,
            extra_data=extra_data,
            source=source,
        )
        self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(entry)

        logger.info(
            "Audit log created",
            action=action,
            category=category,
            description=description,
        )

        return entry

    async def get_audit_logs(
        self,
        page: int = 1,
        page_size: int = 50,
        category: str | None = None,
        action: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get paginated audit logs with filters."""
        query = select(AuditLog)

        if category:
            query = query.where(AuditLog.category == category)
        if action:
            query = query.where(AuditLog.action == action)
        if start_date:
            query = query.where(AuditLog.timestamp >= start_date)
        if end_date:
            query = query.where(AuditLog.timestamp <= end_date)

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Get paginated results
        query = query.order_by(AuditLog.timestamp.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)

        logs = []
        for entry in result.scalars().all():
            logs.append(
                {
                    "id": entry.id,
                    "timestamp": entry.timestamp.isoformat(),
                    "action": entry.action,
                    "category": entry.category,
                    "description": entry.description,
                    "job_id": entry.job_id,
                    "repository_id": entry.repository_id,
                    "estimated_cost_usd": float(entry.estimated_cost)
                    if entry.estimated_cost
                    else None,
                    "actual_cost_usd": float(entry.actual_cost) if entry.actual_cost else None,
                    "bytes_processed": entry.bytes_processed,
                    "success": entry.success,
                    "error_message": entry.error_message,
                    "source": entry.source,
                    "extra_data": entry.extra_data,
                }
            )

        return logs, total

    # =========================================================================
    # Helpers
    # =========================================================================

    def _calculate_cost(self, bytes_billed: int, price_per_tb: Decimal) -> Decimal:
        """Calculate cost from bytes billed."""
        if bytes_billed <= 0:
            return Decimal("0")
        tb_scanned = Decimal(str(bytes_billed)) / Decimal(str(BYTES_PER_TB))
        return tb_scanned * price_per_tb

    def _format_bytes(self, bytes_val: int) -> str:
        """Format bytes as human-readable string."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(bytes_val) < 1024:
                return f"{bytes_val:.2f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.2f} PB"
