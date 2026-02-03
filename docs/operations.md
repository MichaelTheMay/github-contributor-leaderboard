# Operations & Deployment Guide

## Overview

This document covers hosting the GitHub Contributor Leaderboard on a scheduler with optimal error checking, comprehensive logging, and production best practices.

---

## Table of Contents

1. [Database Optimizations](#database-optimizations)
2. [Scheduler Configuration](#scheduler-configuration)
3. [Logging Strategy](#logging-strategy)
4. [Error Handling](#error-handling)
5. [Production Deployment](#production-deployment)
6. [Monitoring & Alerts](#monitoring--alerts)

---

## Database Optimizations

### Current Schema Analysis

#### Identified Issues & Recommendations

1. **Missing Indexes for Common Queries**
   ```sql
   -- Add index for leaderboard queries by score
   CREATE INDEX CONCURRENTLY idx_repo_lb_repo_score
   ON repository_leaderboards(repository_id, total_score DESC);

   -- Add index for contribution events time-range queries
   CREATE INDEX CONCURRENTLY idx_contribution_events_repo_timestamp
   ON contribution_events(repository_id, event_timestamp DESC);

   -- Add index for scrape windows date lookups
   CREATE INDEX CONCURRENTLY idx_scrape_windows_latest
   ON scrape_windows(repository_id, data_end_date DESC);
   ```

2. **Table Partitioning for Large Tables**
   ```sql
   -- Partition contribution_events by year for better query performance
   -- (requires PostgreSQL 11+)
   CREATE TABLE contribution_events_partitioned (
       LIKE contribution_events INCLUDING ALL
   ) PARTITION BY RANGE (event_timestamp);

   CREATE TABLE contribution_events_2024
       PARTITION OF contribution_events_partitioned
       FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');

   CREATE TABLE contribution_events_2025
       PARTITION OF contribution_events_partitioned
       FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
   ```

3. **Connection Pooling**
   - Current: `database_pool_size: 5, max_overflow: 10`
   - Recommendation: Use PgBouncer for production
   ```yaml
   # docker-compose.production.yml
   pgbouncer:
     image: edoburu/pgbouncer
     environment:
       DATABASE_URL: postgres://user:pass@postgres:5432/db
       POOL_MODE: transaction
       MAX_CLIENT_CONN: 100
       DEFAULT_POOL_SIZE: 20
   ```

4. **Vacuum and Analyze Schedule**
   ```sql
   -- Run weekly maintenance
   VACUUM ANALYZE contribution_events;
   VACUUM ANALYZE repository_leaderboards;
   VACUUM ANALYZE scrape_windows;
   VACUUM ANALYZE cost_records;
   ```

5. **Data Retention Policy**
   ```python
   # Add to scheduled tasks
   async def cleanup_old_data():
       """Delete audit logs older than 90 days, cost records older than 365 days."""
       cutoff_audit = datetime.utcnow() - timedelta(days=90)
       cutoff_costs = datetime.utcnow() - timedelta(days=365)

       await db.execute(
           delete(AuditLog).where(AuditLog.timestamp < cutoff_audit)
       )
       await db.execute(
           delete(CostRecord).where(CostRecord.created_at < cutoff_costs)
       )
   ```

---

## Scheduler Configuration

### Option 1: GitHub Actions (Recommended for Small/Medium Scale)

Already configured in `.github/workflows/scheduled-pipeline.yml`:
- Runs daily at 2 AM UTC
- Budget-aware execution
- Automatic issue creation on failures

**Pros:**
- No infrastructure to manage
- Built-in secrets management
- Integrated with repository

**Cons:**
- 6-hour max runtime
- Limited concurrency

### Option 2: Celery Beat (Recommended for Production)

```python
# src/workers/celery_config.py
from celery.schedules import crontab

CELERYBEAT_SCHEDULE = {
    # Refresh stale repositories every 6 hours
    'refresh-stale-repos': {
        'task': 'src.workers.tasks.scrape_tasks.refresh_stale_repositories',
        'schedule': crontab(minute=0, hour='*/6'),
        'options': {'queue': 'scraping'}
    },

    # Recalculate global leaderboard every 4 hours
    'recalculate-global-leaderboard': {
        'task': 'src.workers.tasks.scrape_tasks.recalculate_global_leaderboard',
        'schedule': crontab(minute=30, hour='*/4'),
        'options': {'queue': 'calculations'}
    },

    # Daily budget report at midnight
    'daily-budget-report': {
        'task': 'src.workers.tasks.budget_tasks.generate_daily_report',
        'schedule': crontab(minute=0, hour=0),
        'options': {'queue': 'reports'}
    },

    # Weekly full recalculation on Sunday at 3 AM
    'weekly-full-recalc': {
        'task': 'src.workers.tasks.scrape_tasks.full_recalculation',
        'schedule': crontab(minute=0, hour=3, day_of_week='sunday'),
        'options': {'queue': 'calculations'}
    },

    # Cleanup old data monthly
    'monthly-cleanup': {
        'task': 'src.workers.tasks.maintenance.cleanup_old_data',
        'schedule': crontab(minute=0, hour=4, day_of_month=1),
        'options': {'queue': 'maintenance'}
    },
}

CELERY_QUEUES = {
    'default': {'routing_key': 'default'},
    'scraping': {'routing_key': 'scraping'},
    'calculations': {'routing_key': 'calculations'},
    'reports': {'routing_key': 'reports'},
    'maintenance': {'routing_key': 'maintenance'},
}
```

**Docker Compose for Celery:**
```yaml
# docker-compose.production.yml
services:
  celery-worker-scraping:
    build: .
    command: celery -A src.workers.celery_app worker -Q scraping -c 2 --loglevel=INFO
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    depends_on:
      - redis
      - postgres
    deploy:
      resources:
        limits:
          memory: 2G

  celery-worker-calculations:
    build: .
    command: celery -A src.workers.celery_app worker -Q calculations,reports -c 4 --loglevel=INFO
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    depends_on:
      - redis
      - postgres

  celery-beat:
    build: .
    command: celery -A src.workers.celery_app beat --loglevel=INFO
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    depends_on:
      - redis
      - postgres
```

### Option 3: Kubernetes CronJobs

```yaml
# k8s/cronjobs.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: refresh-stale-repos
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      activeDeadlineSeconds: 7200  # 2 hour timeout
      template:
        spec:
          restartPolicy: OnFailure
          containers:
          - name: pipeline
            image: your-registry/github-leaderboard:latest
            command: ["python", "-m", "scripts.run_pipeline", "--action", "refresh-stale"]
            envFrom:
            - secretRef:
                name: leaderboard-secrets
            resources:
              requests:
                memory: "512Mi"
                cpu: "500m"
              limits:
                memory: "2Gi"
                cpu: "2000m"
```

---

## Logging Strategy

### Structured Logging Configuration

```python
# src/core/logging_config.py
import structlog
import logging
import sys
from datetime import datetime

def configure_logging(environment: str = "production"):
    """Configure comprehensive structured logging."""

    # Shared processors for all loggers
    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="ISO"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if environment == "production":
        # JSON output for production (easy to parse by log aggregators)
        processors = shared_processors + [
            structlog.processors.JSONRenderer()
        ]
    else:
        # Pretty console output for development
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True)
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

# Usage in code:
logger = structlog.get_logger()

# Log with context
logger.info("scrape_started",
    repository="owner/repo",
    job_id=123,
    scrape_window_start="2024-01-01",
    scrape_window_end="2024-06-01",
)

logger.error("scrape_failed",
    repository="owner/repo",
    job_id=123,
    error_type="BigQueryTimeout",
    error_message="Query exceeded 5 minute timeout",
    bytes_processed=1_500_000_000,
)
```

### Log Levels Guide

| Level | Use Case | Example |
|-------|----------|---------|
| DEBUG | Detailed debugging info | Query parameters, intermediate calculations |
| INFO | Normal operations | Job started, scrape completed, leaderboard updated |
| WARNING | Recoverable issues | Rate limit approaching, slow query, retry |
| ERROR | Operation failures | Scrape failed, API error, constraint violation |
| CRITICAL | System-wide issues | Database connection lost, out of memory |

### Key Events to Log

```python
# Pipeline lifecycle events
"pipeline_started"      # When scheduled pipeline begins
"pipeline_completed"    # When pipeline finishes successfully
"pipeline_failed"       # When pipeline fails

# Scraping events
"scrape_job_created"    # New scrape job queued
"scrape_started"        # BigQuery query begins
"scrape_progress"       # Batch processed (every 100 records)
"scrape_completed"      # Scrape finished successfully
"scrape_failed"         # Scrape failed with error
"scrape_retrying"       # Retry attempt

# Leaderboard events
"leaderboard_recalc_started"
"leaderboard_recalc_completed"
"leaderboard_entry_updated"

# Budget events
"budget_check"          # Budget status checked
"budget_warning"        # Approaching limit
"budget_exceeded"       # Limit exceeded
"cost_recorded"         # Actual cost logged

# Error events
"database_error"
"bigquery_error"
"rate_limit_hit"
"validation_error"
```

### Log Aggregation Setup

**For Production with ELK Stack:**
```yaml
# docker-compose.logging.yml
services:
  filebeat:
    image: elastic/filebeat:8.11.0
    volumes:
      - ./logs:/var/log/app:ro
      - ./filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
    depends_on:
      - elasticsearch
      - logstash

  logstash:
    image: logstash:8.11.0
    volumes:
      - ./logstash.conf:/usr/share/logstash/pipeline/logstash.conf:ro
    ports:
      - "5044:5044"

  elasticsearch:
    image: elasticsearch:8.11.0
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
    ports:
      - "9200:9200"

  kibana:
    image: kibana:8.11.0
    ports:
      - "5601:5601"
    depends_on:
      - elasticsearch
```

---

## Error Handling

### Comprehensive Error Handling Strategy

```python
# src/core/errors.py
from enum import Enum
from typing import Any
import structlog

logger = structlog.get_logger()

class ErrorSeverity(Enum):
    LOW = "low"           # Retry and continue
    MEDIUM = "medium"     # Skip item and continue
    HIGH = "high"         # Stop current job
    CRITICAL = "critical" # Stop all processing

class PipelineError(Exception):
    """Base exception for pipeline errors."""

    def __init__(
        self,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        context: dict[str, Any] | None = None,
        recoverable: bool = True,
    ):
        super().__init__(message)
        self.severity = severity
        self.context = context or {}
        self.recoverable = recoverable

    def log(self):
        """Log the error with full context."""
        logger.error(
            "pipeline_error",
            error_type=self.__class__.__name__,
            message=str(self),
            severity=self.severity.value,
            recoverable=self.recoverable,
            **self.context
        )

class BigQueryError(PipelineError):
    """BigQuery-specific errors."""
    pass

class RateLimitError(PipelineError):
    """API rate limit exceeded."""
    def __init__(self, retry_after: int = 60, **kwargs):
        super().__init__(**kwargs)
        self.retry_after = retry_after

class BudgetExceededError(PipelineError):
    """Budget limit exceeded."""
    def __init__(self, **kwargs):
        super().__init__(recoverable=False, severity=ErrorSeverity.HIGH, **kwargs)

class DatabaseError(PipelineError):
    """Database operation errors."""
    pass

# Error handling decorator
def handle_errors(max_retries: int = 3, backoff_base: int = 60):
    """Decorator for comprehensive error handling."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            last_error = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)

                except RateLimitError as e:
                    e.log()
                    if attempt < max_retries:
                        wait_time = e.retry_after
                        logger.info("rate_limit_waiting", wait_seconds=wait_time)
                        await asyncio.sleep(wait_time)
                    else:
                        raise

                except BudgetExceededError as e:
                    e.log()
                    raise  # Don't retry budget errors

                except BigQueryError as e:
                    e.log()
                    if e.recoverable and attempt < max_retries:
                        wait_time = backoff_base * (2 ** attempt)
                        logger.info("bigquery_retry", attempt=attempt + 1, wait_seconds=wait_time)
                        await asyncio.sleep(wait_time)
                    else:
                        raise

                except DatabaseError as e:
                    e.log()
                    if attempt < max_retries:
                        await asyncio.sleep(5)  # Quick retry for DB
                    else:
                        raise

                except Exception as e:
                    logger.error("unexpected_error",
                        error_type=type(e).__name__,
                        error=str(e),
                        attempt=attempt + 1
                    )
                    last_error = e
                    if attempt < max_retries:
                        await asyncio.sleep(backoff_base * (2 ** attempt))
                    else:
                        raise

            raise last_error
        return wrapper
    return decorator
```

### Error Recovery Patterns

```python
# Pattern 1: Dead Letter Queue for failed jobs
async def handle_failed_job(job_id: int, error: Exception):
    """Move failed job to dead letter queue for manual review."""
    await db.execute(
        insert(FailedJobQueue).values(
            job_id=job_id,
            error_type=type(error).__name__,
            error_message=str(error),
            failed_at=datetime.utcnow(),
            retry_count=0,
        )
    )
    logger.warning("job_moved_to_dlq", job_id=job_id, error=str(error))

# Pattern 2: Circuit Breaker for external services
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 300):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open

    async def call(self, func, *args, **kwargs):
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
            else:
                raise CircuitBreakerOpenError("Circuit breaker is open")

        try:
            result = await func(*args, **kwargs)
            if self.state == "half-open":
                self.state = "closed"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.warning("circuit_breaker_opened",
                    failure_count=self.failure_count)
            raise

# Usage
bigquery_circuit = CircuitBreaker(failure_threshold=3, recovery_timeout=600)
result = await bigquery_circuit.call(bigquery.fetch_aggregated_stats, ...)
```

---

## Production Deployment

### Recommended Architecture

```
                                    ┌─────────────────┐
                                    │   CloudFlare    │
                                    │      CDN        │
                                    └────────┬────────┘
                                             │
                                    ┌────────▼────────┐
                                    │  Load Balancer  │
                                    │   (nginx/ALB)   │
                                    └────────┬────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    │                        │                        │
           ┌────────▼────────┐     ┌────────▼────────┐     ┌────────▼────────┐
           │    API Server   │     │    API Server   │     │    API Server   │
           │   (uvicorn)     │     │   (uvicorn)     │     │   (uvicorn)     │
           └────────┬────────┘     └────────┬────────┘     └────────┬────────┘
                    │                        │                        │
                    └────────────────────────┼────────────────────────┘
                                             │
              ┌──────────────────────────────┼──────────────────────────────┐
              │                              │                              │
    ┌─────────▼─────────┐         ┌─────────▼─────────┐         ┌─────────▼─────────┐
    │    PostgreSQL     │         │      Redis        │         │   Celery Workers  │
    │    (Primary)      │         │    (Cluster)      │         │   (Autoscaling)   │
    └─────────┬─────────┘         └───────────────────┘         └───────────────────┘
              │
    ┌─────────▼─────────┐
    │    PostgreSQL     │
    │    (Replica)      │
    └───────────────────┘
```

### Environment Variables

```bash
# .env.production
# Database
DATABASE_URL=postgresql+asyncpg://user:password@pgbouncer:6432/leaderboard
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=40

# Redis
REDIS_URL=redis://redis-cluster:6379/0

# BigQuery
BIGQUERY_PROJECT=your-gcp-project
GOOGLE_APPLICATION_CREDENTIALS=/secrets/bigquery-sa.json

# Celery
CELERY_BROKER_URL=redis://redis-cluster:6379/1
CELERY_RESULT_BACKEND=redis://redis-cluster:6379/2

# Security
SECRET_KEY=your-secure-secret-key
ALLOWED_HOSTS=api.yourdomain.com

# Monitoring
SENTRY_DSN=https://xxx@sentry.io/xxx
PROMETHEUS_ENABLED=true

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

### Health Checks

```python
# src/api/routes/health.py
from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta

router = APIRouter()

@router.get("/health")
async def health_check():
    """Basic health check."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@router.get("/health/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness check - verifies all dependencies."""
    checks = {}

    # Database check
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"unhealthy: {e}"

    # Redis check
    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "healthy"
    except Exception as e:
        checks["redis"] = f"unhealthy: {e}"

    # Celery check
    try:
        from src.workers.celery_app import celery_app
        inspect = celery_app.control.inspect()
        if inspect.active():
            checks["celery"] = "healthy"
        else:
            checks["celery"] = "no workers"
    except Exception as e:
        checks["celery"] = f"unhealthy: {e}"

    all_healthy = all(v == "healthy" for v in checks.values())

    if not all_healthy:
        raise HTTPException(status_code=503, detail=checks)

    return {"status": "ready", "checks": checks}

@router.get("/health/live")
async def liveness_check():
    """Liveness check - just verifies the process is running."""
    return {"status": "alive"}
```

---

## Monitoring & Alerts

### Prometheus Metrics

```python
# src/core/metrics.py
from prometheus_client import Counter, Histogram, Gauge

# Scraping metrics
SCRAPE_JOBS_TOTAL = Counter(
    'scrape_jobs_total',
    'Total scrape jobs',
    ['status', 'repository']
)

SCRAPE_DURATION_SECONDS = Histogram(
    'scrape_duration_seconds',
    'Time spent on scraping',
    ['repository'],
    buckets=[10, 30, 60, 120, 300, 600, 1200, 3600]
)

SCRAPE_EVENTS_PROCESSED = Counter(
    'scrape_events_processed_total',
    'Total events processed',
    ['repository', 'event_type']
)

# Budget metrics
BIGQUERY_COST_DOLLARS = Counter(
    'bigquery_cost_dollars_total',
    'Total BigQuery cost in dollars'
)

BUDGET_UTILIZATION_PERCENT = Gauge(
    'budget_utilization_percent',
    'Current budget utilization',
    ['period']  # 'daily' or 'monthly'
)

# API metrics
API_REQUESTS_TOTAL = Counter(
    'api_requests_total',
    'Total API requests',
    ['method', 'endpoint', 'status']
)

API_REQUEST_DURATION_SECONDS = Histogram(
    'api_request_duration_seconds',
    'API request duration',
    ['method', 'endpoint'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0]
)

# Database metrics
DB_POOL_SIZE = Gauge('db_pool_size', 'Database connection pool size')
DB_POOL_CHECKED_OUT = Gauge('db_pool_checked_out', 'Active database connections')
```

### Alert Rules (Prometheus/Alertmanager)

```yaml
# alerting_rules.yml
groups:
  - name: leaderboard_alerts
    rules:
      - alert: ScrapeJobFailed
        expr: increase(scrape_jobs_total{status="failed"}[1h]) > 3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Multiple scrape jobs failed"
          description: "{{ $value }} scrape jobs failed in the last hour"

      - alert: BudgetWarning
        expr: budget_utilization_percent{period="daily"} > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Daily budget utilization above 80%"
          description: "Current utilization: {{ $value }}%"

      - alert: BudgetCritical
        expr: budget_utilization_percent{period="daily"} > 95
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Daily budget nearly exhausted"
          description: "Current utilization: {{ $value }}%"

      - alert: APIHighLatency
        expr: histogram_quantile(0.95, rate(api_request_duration_seconds_bucket[5m])) > 2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "API 95th percentile latency above 2s"

      - alert: CeleryWorkersDown
        expr: absent(celery_workers_active) or celery_workers_active == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "No Celery workers active"

      - alert: DatabaseConnectionPoolExhausted
        expr: db_pool_checked_out / db_pool_size > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Database connection pool nearly exhausted"
```

### Grafana Dashboard

Key panels to include:
1. **Pipeline Overview**: Jobs running, completed, failed
2. **Cost Tracking**: Daily/monthly spend, forecast
3. **Leaderboard Stats**: Total contributors, repos, events
4. **API Performance**: Request rate, latency percentiles
5. **Error Rates**: By type, by service
6. **Resource Usage**: CPU, memory, connections

---

## Summary

### Quick Start Checklist

1. [ ] Set up PostgreSQL with proper indexes
2. [ ] Configure Redis cluster for Celery
3. [ ] Set up BigQuery service account
4. [ ] Configure environment variables
5. [ ] Deploy Celery workers with beat scheduler
6. [ ] Set up log aggregation (ELK/CloudWatch)
7. [ ] Configure Prometheus + Alertmanager
8. [ ] Create Grafana dashboards
9. [ ] Set up GitHub Actions secrets
10. [ ] Enable branch protection

### Maintenance Schedule

| Task | Frequency | Method |
|------|-----------|--------|
| Refresh stale repos | Every 6 hours | Celery Beat |
| Recalculate global leaderboard | Every 4 hours | Celery Beat |
| Database VACUUM ANALYZE | Weekly | Cron job |
| Log rotation | Daily | Logrotate |
| Backup database | Daily | pg_dump |
| Clean old audit logs | Monthly | Celery Beat |
| Review failed jobs | Daily | Manual/Alert |
