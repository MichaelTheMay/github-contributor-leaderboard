from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
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

    # Social media handles
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

    # Other platforms
    discord_username: Mapped[str | None] = mapped_column(String(255))
    mastodon_handle: Mapped[str | None] = mapped_column(String(255))
    youtube_channel: Mapped[str | None] = mapped_column(Text)
    dev_to_username: Mapped[str | None] = mapped_column(String(255))
    medium_username: Mapped[str | None] = mapped_column(String(255))
    substack_url: Mapped[str | None] = mapped_column(Text)

    # Enrichment metadata
    enrichment_status: Mapped[EnrichmentStatus] = mapped_column(
        String(50),
        default=EnrichmentStatus.PENDING,
    )
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrichment_sources: Mapped[dict | None] = mapped_column(JSONB)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)

    # Relationships
    user = relationship("GitHubUser", back_populates="enrichment")

    __table_args__ = (Index("idx_enrichment_status", "enrichment_status"),)

    def __repr__(self) -> str:
        return f"<ContributorEnrichment user_id={self.user_id} status={self.enrichment_status}>"
