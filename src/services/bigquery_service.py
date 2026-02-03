from datetime import datetime, timedelta

import structlog
from google.cloud import bigquery

from src.core.config import settings

logger = structlog.get_logger()


BIGQUERY_EVENTS_QUERY = """
WITH repo_events AS (
    SELECT
        repo.name as repo_name,
        actor.id as user_id,
        actor.login as username,
        type as event_type,
        JSON_EXTRACT_SCALAR(payload, '$.action') as action,
        JSON_EXTRACT_SCALAR(payload, '$.pull_request.merged') as pr_merged,
        JSON_EXTRACT_SCALAR(payload, '$.review.state') as review_state,
        CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64) as commit_count,
        CAST(JSON_EXTRACT_SCALAR(payload, '$.pull_request.additions') AS INT64) as lines_added,
        CAST(JSON_EXTRACT_SCALAR(payload, '$.pull_request.deletions') AS INT64) as lines_deleted,
        id as event_id,
        created_at as event_timestamp
    FROM `githubarchive.day.{date_table}`
    WHERE repo.name IN ({repo_list})
)
SELECT
    repo_name,
    user_id,
    username,
    CASE
        WHEN event_type = 'PushEvent' THEN 'commit'
        WHEN event_type = 'PullRequestEvent' AND action = 'opened' THEN 'pr_opened'
        WHEN event_type = 'PullRequestEvent' AND action = 'closed' AND pr_merged = 'true' THEN 'pr_merged'
        WHEN event_type = 'PullRequestReviewEvent' THEN 'pr_reviewed'
        WHEN event_type = 'PullRequestReviewCommentEvent' THEN 'pr_review_comment'
        WHEN event_type = 'IssuesEvent' AND action = 'opened' THEN 'issue_opened'
        WHEN event_type = 'IssuesEvent' AND action = 'closed' THEN 'issue_closed'
        WHEN event_type = 'IssueCommentEvent' THEN 'comment'
        WHEN event_type = 'ReleaseEvent' THEN 'release'
        ELSE NULL
    END as mapped_event_type,
    event_id,
    COALESCE(commit_count, 1) as event_count,
    COALESCE(lines_added, 0) as lines_added,
    COALESCE(lines_deleted, 0) as lines_deleted,
    event_timestamp
FROM repo_events
WHERE event_type IN (
    'PushEvent', 'PullRequestEvent', 'PullRequestReviewEvent',
    'PullRequestReviewCommentEvent', 'IssuesEvent', 'IssueCommentEvent', 'ReleaseEvent'
)
ORDER BY event_timestamp DESC
"""


class BigQueryJobStats:
    """Statistics from a BigQuery job execution."""

    def __init__(
        self,
        bytes_processed: int = 0,
        bytes_billed: int = 0,
        slot_millis: int = 0,
        cache_hit: bool = False,
    ):
        self.bytes_processed = bytes_processed
        self.bytes_billed = bytes_billed
        self.slot_millis = slot_millis
        self.cache_hit = cache_hit

    def to_dict(self) -> dict:
        return {
            "bytes_processed": self.bytes_processed,
            "bytes_billed": self.bytes_billed,
            "slot_millis": self.slot_millis,
            "cache_hit": self.cache_hit,
        }


class BigQueryService:
    """Service for fetching GitHub events from BigQuery."""

    def __init__(self) -> None:
        self.client = bigquery.Client(project=settings.bigquery_project)
        self._last_job_stats: BigQueryJobStats | None = None

    @property
    def last_job_stats(self) -> BigQueryJobStats | None:
        """Get statistics from the last executed query."""
        return self._last_job_stats

    def _capture_job_stats(self, query_job: bigquery.QueryJob) -> BigQueryJobStats:
        """Capture statistics from a completed query job."""
        stats = BigQueryJobStats(
            bytes_processed=query_job.total_bytes_processed or 0,
            bytes_billed=query_job.total_bytes_billed or 0,
            slot_millis=query_job.slot_millis or 0,
            cache_hit=query_job.cache_hit or False,
        )
        self._last_job_stats = stats
        return stats

    async def fetch_events_for_repositories(
        self,
        repositories: list[str],
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        """
        Fetch contribution events from BigQuery for specified repositories.

        Args:
            repositories: List of repository names in 'owner/name' format
            start_date: Start of date range (defaults to 1 year ago)
            end_date: End of date range (defaults to today)

        Returns:
            List of event dictionaries
        """
        if not repositories:
            return []

        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=365)
        if not end_date:
            end_date = datetime.utcnow()

        # Format repository list for SQL
        repo_list = ", ".join(f"'{repo}'" for repo in repositories)

        all_events = []

        # Query each day's table
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime("%Y%m%d")

            try:
                query = BIGQUERY_EVENTS_QUERY.format(
                    date_table=date_str,
                    repo_list=repo_list,
                )

                query_job = self.client.query(query)
                results = query_job.result()

                for row in results:
                    if row.mapped_event_type:
                        all_events.append(
                            {
                                "repo_name": row.repo_name,
                                "user_id": row.user_id,
                                "username": row.username,
                                "event_type": row.mapped_event_type,
                                "event_id": str(row.event_id),
                                "event_count": row.event_count,
                                "lines_added": row.lines_added or 0,
                                "lines_deleted": row.lines_deleted or 0,
                                "event_timestamp": row.event_timestamp,
                            }
                        )

                logger.info(
                    "BigQuery day fetched",
                    date=date_str,
                    events_count=len(all_events),
                )

            except Exception as e:
                logger.warning(
                    "BigQuery fetch failed for date",
                    date=date_str,
                    error=str(e),
                )

            current_date += timedelta(days=1)

        return all_events

    async def fetch_aggregated_stats(
        self,
        repositories: list[str],
        start_date: datetime | None = None,
    ) -> list[dict]:
        """
        Fetch aggregated contribution statistics from BigQuery.

        More efficient for initial leaderboard population.
        """
        if not repositories:
            return []

        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=365 * 2)

        repo_list = ", ".join(f"'{repo}'" for repo in repositories)
        date_str = start_date.strftime("%Y-%m-%d")

        aggregation_query = f"""
        SELECT
            repo.name as repo_name,
            actor.id as user_id,
            actor.login as username,
            -- Count actual commits from PushEvents (payload.size = number of commits in push)
            SUM(CASE
                WHEN type = 'PushEvent' THEN COALESCE(CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64), 1)
                ELSE 0
            END) as commit_events,
            COUNT(CASE WHEN type = 'PullRequestEvent' AND JSON_EXTRACT_SCALAR(payload, '$.action') = 'opened' THEN 1 END) as prs_opened,
            COUNT(CASE WHEN type = 'PullRequestEvent' AND JSON_EXTRACT_SCALAR(payload, '$.action') = 'closed' AND JSON_EXTRACT_SCALAR(payload, '$.pull_request.merged') = 'true' THEN 1 END) as prs_merged,
            COUNT(CASE WHEN type = 'PullRequestReviewEvent' THEN 1 END) as prs_reviewed,
            COUNT(CASE WHEN type = 'IssuesEvent' AND JSON_EXTRACT_SCALAR(payload, '$.action') = 'opened' THEN 1 END) as issues_opened,
            COUNT(CASE WHEN type = 'IssuesEvent' AND JSON_EXTRACT_SCALAR(payload, '$.action') = 'closed' THEN 1 END) as issues_closed,
            COUNT(CASE WHEN type = 'IssueCommentEvent' THEN 1 END) as comments,
            COUNT(CASE WHEN type = 'ReleaseEvent' THEN 1 END) as releases,
            -- Count total events for display (different from commit count)
            COUNT(*) as total_events,
            SUM(CAST(COALESCE(JSON_EXTRACT_SCALAR(payload, '$.pull_request.additions'), '0') AS INT64)) as total_lines_added,
            SUM(CAST(COALESCE(JSON_EXTRACT_SCALAR(payload, '$.pull_request.deletions'), '0') AS INT64)) as total_lines_deleted,
            MIN(created_at) as first_contribution,
            MAX(created_at) as last_contribution
        FROM `githubarchive.month.*`
        WHERE repo.name IN ({repo_list})
            AND _TABLE_SUFFIX >= '{date_str[:7].replace("-", "")}'
        GROUP BY repo_name, user_id, username
        ORDER BY prs_merged + commit_events DESC
        """

        try:
            query_job = self.client.query(aggregation_query)
            results = query_job.result()

            # Capture job statistics for cost tracking
            job_stats = self._capture_job_stats(query_job)

            stats = []
            for row in results:
                stats.append(
                    {
                        "repo_name": row.repo_name,
                        "user_id": row.user_id,
                        "username": row.username,
                        "commit_events": row.commit_events or 0,
                        "prs_opened": row.prs_opened,
                        "prs_merged": row.prs_merged,
                        "prs_reviewed": row.prs_reviewed,
                        "issues_opened": row.issues_opened,
                        "issues_closed": row.issues_closed,
                        "comments": row.comments,
                        "releases": row.releases,
                        "total_events": row.total_events,
                        "total_lines_added": row.total_lines_added,
                        "total_lines_deleted": row.total_lines_deleted,
                        "first_contribution": row.first_contribution,
                        "last_contribution": row.last_contribution,
                    }
                )

            logger.info(
                "BigQuery aggregation complete",
                stats_count=len(stats),
                bytes_processed=job_stats.bytes_processed,
                bytes_billed=job_stats.bytes_billed,
                cache_hit=job_stats.cache_hit,
            )
            return stats

        except Exception as e:
            logger.error("BigQuery aggregation failed", error=str(e))
            raise

    def get_last_query_cost_estimate(self, price_per_tb_usd: float = 5.0) -> dict:
        """Get cost estimate from the last executed query."""
        if not self._last_job_stats:
            return {"error": "No query executed yet"}

        bytes_per_tb = 1024 * 1024 * 1024 * 1024
        tb_billed = self._last_job_stats.bytes_billed / bytes_per_tb
        estimated_cost = tb_billed * price_per_tb_usd

        return {
            "bytes_processed": self._last_job_stats.bytes_processed,
            "bytes_billed": self._last_job_stats.bytes_billed,
            "tb_billed": round(tb_billed, 6),
            "estimated_cost_usd": round(estimated_cost, 6),
            "cache_hit": self._last_job_stats.cache_hit,
            "price_per_tb_usd": price_per_tb_usd,
        }
