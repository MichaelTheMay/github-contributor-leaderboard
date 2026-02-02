from celery import Celery

from src.core.config import settings

celery_app = Celery(
    "github_leaderboard",
    broker=settings.celery_broker_url or str(settings.redis_url),
    backend=settings.celery_result_backend or str(settings.redis_url),
    include=[
        "src.workers.tasks.scrape_tasks",
        "src.workers.tasks.leaderboard_tasks",
        "src.workers.tasks.enrichment_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.job_default_timeout,
    task_soft_time_limit=settings.job_default_timeout - 60,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# Periodic tasks
celery_app.conf.beat_schedule = {
    "refresh-stale-repositories": {
        "task": "src.workers.tasks.scrape_tasks.refresh_stale_repositories",
        "schedule": 3600.0,  # Every hour
    },
    "recalculate-global-leaderboard": {
        "task": "src.workers.tasks.leaderboard_tasks.recalculate_global_leaderboard",
        "schedule": 1800.0,  # Every 30 minutes
    },
}
