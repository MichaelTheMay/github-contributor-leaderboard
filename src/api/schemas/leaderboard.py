from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class LeaderboardUserInfo(BaseModel):
    username: str
    display_name: str | None
    avatar_url: str | None
    profile_url: str | None

    model_config = {"from_attributes": True}


class RepositoryLeaderboardEntry(BaseModel):
    rank: int
    user: LeaderboardUserInfo
    total_score: Decimal
    commit_count: int
    pr_opened_count: int
    pr_merged_count: int
    pr_reviewed_count: int
    issues_opened_count: int
    issues_closed_count: int
    comments_count: int
    lines_added: int
    lines_deleted: int
    first_contribution_at: datetime | None
    last_contribution_at: datetime | None

    model_config = {"from_attributes": True}


class GlobalLeaderboardEntry(BaseModel):
    global_rank: int
    user: LeaderboardUserInfo
    total_score: Decimal
    repositories_contributed: int
    total_commits: int
    total_prs_merged: int
    total_prs_reviewed: int
    total_issues_opened: int
    total_comments: int
    total_lines_added: int
    first_contribution_at: datetime | None
    last_contribution_at: datetime | None

    model_config = {"from_attributes": True}


class LeaderboardResponse(BaseModel):
    entries: list[RepositoryLeaderboardEntry] | list[GlobalLeaderboardEntry]
    total: int
    page: int
    page_size: int
