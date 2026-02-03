from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.base import Base, TimestampMixin


class EventType(str, Enum):
    COMMIT = "commit"
    PR_OPENED = "pr_opened"
    PR_MERGED = "pr_merged"
    PR_REVIEWED = "pr_reviewed"
    PR_REVIEW_COMMENT = "pr_review_comment"
    ISSUE_OPENED = "issue_opened"
    ISSUE_CLOSED = "issue_closed"
    COMMENT = "comment"
    RELEASE = "release"


class ContributionEvent(Base, TimestampMixin):
    __tablename__ = "contribution_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("github_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[EventType] = mapped_column(String(50), nullable=False)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_data: Mapped[dict | None] = mapped_column(JSONB)
    lines_added: Mapped[int] = mapped_column(default=0)
    lines_deleted: Mapped[int] = mapped_column(default=0)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    repository = relationship("Repository", back_populates="contribution_events")
    user = relationship("GitHubUser", back_populates="contribution_events")

    __table_args__ = (
        Index("idx_contribution_events_repo_user", "repository_id", "user_id"),
        Index("idx_contribution_events_event_id", "event_id", unique=True),
        Index("idx_contribution_events_type", "event_type"),
        Index("idx_contribution_events_timestamp", "event_timestamp"),
    )

    def __repr__(self) -> str:
        return f"<ContributionEvent {self.event_type} by user_id={self.user_id}>"
