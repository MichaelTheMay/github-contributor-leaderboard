from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from src.db.models.enrichment import EnrichmentStatus


class ContributorEnrichmentInfo(BaseModel):
    twitter_username: str | None
    twitter_url: str | None
    twitter_followers: int | None
    linkedin_url: str | None
    linkedin_title: str | None
    linkedin_company: str | None
    personal_website: str | None
    personal_email: str | None
    work_email: str | None
    discord_username: str | None
    mastodon_handle: str | None
    youtube_channel: str | None
    dev_to_username: str | None
    medium_username: str | None
    substack_url: str | None
    enrichment_status: EnrichmentStatus
    last_enriched_at: datetime | None

    model_config = {"from_attributes": True}


class ContributorDetail(BaseModel):
    id: int
    github_id: int
    username: str
    display_name: str | None
    avatar_url: str | None
    profile_url: str | None
    email: str | None
    company: str | None
    location: str | None
    bio: str | None
    followers: int
    public_repos: int
    global_rank: int | None
    total_score: Decimal | None
    repositories_contributed: int | None
    enrichment: ContributorEnrichmentInfo | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContributorActivity(BaseModel):
    event_type: str
    event_timestamp: datetime
    repository_name: str
    lines_added: int
    lines_deleted: int

    model_config = {"from_attributes": True}


class ContributorRepository(BaseModel):
    repository_id: int
    repository_name: str
    rank: int
    total_score: Decimal
    commit_count: int
    pr_merged_count: int
    pr_reviewed_count: int
    first_contribution_at: datetime | None
    last_contribution_at: datetime | None

    model_config = {"from_attributes": True}
