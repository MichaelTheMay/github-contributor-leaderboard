from functools import lru_cache
from typing import Any

from pydantic import PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "GitHub Contributor Leaderboard"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "development"

    # Database
    database_url: PostgresDsn
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # Redis
    redis_url: RedisDsn

    # GitHub API
    github_token: str
    github_api_base_url: str = "https://api.github.com"
    github_rate_limit_buffer: int = 100  # Keep this many requests in reserve

    # BigQuery
    bigquery_project: str
    google_application_credentials: str | None = None

    # Enrichment APIs (optional)
    clearbit_api_key: str | None = None
    hunter_api_key: str | None = None
    apollo_api_key: str | None = None
    proxycurl_api_key: str | None = None

    # Scoring defaults
    default_commit_points: float = 10.0
    default_pr_opened_points: float = 15.0
    default_pr_merged_points: float = 25.0
    default_pr_reviewed_points: float = 20.0
    default_issue_opened_points: float = 8.0
    default_issue_closed_points: float = 5.0
    default_comment_points: float = 3.0
    default_release_points: float = 30.0
    default_lines_added_multiplier: float = 0.1
    default_lines_deleted_multiplier: float = 0.05

    # Job processing
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    job_default_timeout: int = 3600  # 1 hour
    job_max_retries: int = 3

    # API settings
    api_rate_limit_per_minute: int = 60
    api_pagination_default_limit: int = 50
    api_pagination_max_limit: int = 100

    @field_validator("celery_broker_url", "celery_result_backend", mode="before")
    @classmethod
    def set_celery_urls(cls, v: str | None, info: Any) -> str | None:
        if v is None and "redis_url" in info.data:
            return str(info.data["redis_url"])
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
