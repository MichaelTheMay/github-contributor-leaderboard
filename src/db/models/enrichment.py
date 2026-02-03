from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.base import Base, TimestampMixin


class EnrichmentStatus(str, Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    COMPLETE = "complete"
    FAILED = "failed"


class ContributorEnrichment(Base, TimestampMixin):
    __tablename__ = "contributor_enrichments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("github_users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # ==========================================================================
    # Social Media Handles - Major Platforms
    # ==========================================================================
    twitter_username: Mapped[str | None] = mapped_column(String(255))
    twitter_url: Mapped[str | None] = mapped_column(Text)
    twitter_followers: Mapped[int | None] = mapped_column()

    # LinkedIn
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    linkedin_title: Mapped[str | None] = mapped_column(String(255))
    linkedin_company: Mapped[str | None] = mapped_column(String(255))

    # Contact info
    personal_website: Mapped[str | None] = mapped_column(Text)
    personal_email: Mapped[str | None] = mapped_column(String(255))
    work_email: Mapped[str | None] = mapped_column(String(255))

    # Original other platforms
    discord_username: Mapped[str | None] = mapped_column(String(255))
    mastodon_handle: Mapped[str | None] = mapped_column(String(255))
    youtube_channel: Mapped[str | None] = mapped_column(Text)
    dev_to_username: Mapped[str | None] = mapped_column(String(255))
    medium_username: Mapped[str | None] = mapped_column(String(255))
    substack_url: Mapped[str | None] = mapped_column(Text)

    # ==========================================================================
    # Additional Social Platforms
    # ==========================================================================
    github_sponsors_url: Mapped[str | None] = mapped_column(Text)
    bluesky_handle: Mapped[str | None] = mapped_column(String(255))  # @user.bsky.social
    threads_username: Mapped[str | None] = mapped_column(String(255))
    instagram_username: Mapped[str | None] = mapped_column(String(255))
    facebook_url: Mapped[str | None] = mapped_column(Text)
    reddit_username: Mapped[str | None] = mapped_column(String(255))
    hackernews_username: Mapped[str | None] = mapped_column(String(255))
    stackoverflow_url: Mapped[str | None] = mapped_column(Text)
    kaggle_username: Mapped[str | None] = mapped_column(String(255))
    twitch_username: Mapped[str | None] = mapped_column(String(255))
    tiktok_username: Mapped[str | None] = mapped_column(String(255))

    # ==========================================================================
    # Professional/Developer Platforms
    # ==========================================================================
    npm_username: Mapped[str | None] = mapped_column(String(255))
    pypi_username: Mapped[str | None] = mapped_column(String(255))
    gitlab_username: Mapped[str | None] = mapped_column(String(255))
    bitbucket_username: Mapped[str | None] = mapped_column(String(255))
    codepen_username: Mapped[str | None] = mapped_column(String(255))
    dribbble_username: Mapped[str | None] = mapped_column(String(255))
    behance_username: Mapped[str | None] = mapped_column(String(255))

    # ==========================================================================
    # Contact/Communication Platforms
    # ==========================================================================
    telegram_username: Mapped[str | None] = mapped_column(String(255))
    signal_username: Mapped[str | None] = mapped_column(String(255))
    keybase_username: Mapped[str | None] = mapped_column(String(255))
    matrix_handle: Mapped[str | None] = mapped_column(String(255))  # @user:server.org
    slack_workspace: Mapped[str | None] = mapped_column(String(255))

    # ==========================================================================
    # Multiple values support (JSONB arrays)
    # ==========================================================================
    additional_emails: Mapped[list | None] = mapped_column(JSONB)
    additional_websites: Mapped[list | None] = mapped_column(JSONB)
    social_links_raw: Mapped[dict | None] = mapped_column(JSONB)

    # ==========================================================================
    # GitHub-specific extracted data
    # ==========================================================================
    github_bio: Mapped[str | None] = mapped_column(Text)
    github_company: Mapped[str | None] = mapped_column(String(255))
    github_location: Mapped[str | None] = mapped_column(String(255))
    github_hireable: Mapped[bool | None] = mapped_column(Boolean)
    github_followers: Mapped[int | None] = mapped_column(Integer)
    github_following: Mapped[int | None] = mapped_column(Integer)
    github_public_repos: Mapped[int | None] = mapped_column(Integer)
    github_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ==========================================================================
    # Enrichment metadata
    # ==========================================================================
    enrichment_status: Mapped[EnrichmentStatus] = mapped_column(
        String(50),
        default=EnrichmentStatus.PENDING,
    )
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrichment_sources: Mapped[dict | None] = mapped_column(JSONB)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)

    # Enrichment tracking
    enrichment_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    # Relationships
    user = relationship("GitHubUser", back_populates="enrichment")

    __table_args__ = (
        Index("idx_enrichment_status", "enrichment_status"),
        Index("idx_enrichment_last_enriched", "last_enriched_at"),
    )

    def __repr__(self) -> str:
        return f"<ContributorEnrichment user_id={self.user_id} status={self.enrichment_status}>"

    def count_sources_found(self) -> dict[str, int]:
        """Count how many contact sources have been found."""
        counts = {
            "social": 0,
            "professional": 0,
            "contact": 0,
            "total": 0,
        }

        # Social platforms
        social_fields = [
            self.twitter_username, self.linkedin_url, self.mastodon_handle,
            self.youtube_channel, self.bluesky_handle, self.threads_username,
            self.instagram_username, self.facebook_url, self.reddit_username,
            self.twitch_username, self.tiktok_username,
        ]
        counts["social"] = sum(1 for f in social_fields if f)

        # Professional platforms
        prof_fields = [
            self.dev_to_username, self.medium_username, self.substack_url,
            self.github_sponsors_url, self.hackernews_username, self.stackoverflow_url,
            self.kaggle_username, self.npm_username, self.pypi_username,
            self.gitlab_username, self.bitbucket_username, self.codepen_username,
            self.dribbble_username, self.behance_username,
        ]
        counts["professional"] = sum(1 for f in prof_fields if f)

        # Contact info
        contact_fields = [
            self.personal_website, self.personal_email, self.work_email,
            self.discord_username, self.telegram_username, self.signal_username,
            self.keybase_username, self.matrix_handle, self.slack_workspace,
        ]
        counts["contact"] = sum(1 for f in contact_fields if f)

        counts["total"] = counts["social"] + counts["professional"] + counts["contact"]
        return counts
