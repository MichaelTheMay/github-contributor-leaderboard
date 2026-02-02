from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.base import Base, TimestampMixin


class RepositoryLeaderboard(Base, TimestampMixin):
    __tablename__ = "repository_leaderboards"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("github_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # Contribution counts
    commit_count: Mapped[int] = mapped_column(default=0)
    pr_opened_count: Mapped[int] = mapped_column(default=0)
    pr_merged_count: Mapped[int] = mapped_column(default=0)
    pr_reviewed_count: Mapped[int] = mapped_column(default=0)
    issues_opened_count: Mapped[int] = mapped_column(default=0)
    issues_closed_count: Mapped[int] = mapped_column(default=0)
    comments_count: Mapped[int] = mapped_column(default=0)

    # Code metrics
    lines_added: Mapped[int] = mapped_column(default=0)
    lines_deleted: Mapped[int] = mapped_column(default=0)

    # Timestamps
    first_contribution_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_contribution_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    repository = relationship("Repository", back_populates="leaderboard_entries")
    user = relationship("GitHubUser", back_populates="repository_leaderboard_entries")

    __table_args__ = (
        Index("idx_repo_leaderboard_repo_rank", "repository_id", "rank"),
        Index("idx_repo_leaderboard_repo_user", "repository_id", "user_id", unique=True),
        Index("idx_repo_leaderboard_score", "total_score", postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        return f"<RepositoryLeaderboard repo_id={self.repository_id} rank={self.rank}>"


class GlobalLeaderboard(Base, TimestampMixin):
    __tablename__ = "global_leaderboard"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("github_users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    global_rank: Mapped[int] = mapped_column(nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    # Aggregate statistics
    repositories_contributed: Mapped[int] = mapped_column(default=0)
    total_commits: Mapped[int] = mapped_column(default=0)
    total_prs_merged: Mapped[int] = mapped_column(default=0)
    total_prs_reviewed: Mapped[int] = mapped_column(default=0)
    total_issues_opened: Mapped[int] = mapped_column(default=0)
    total_comments: Mapped[int] = mapped_column(default=0)
    total_lines_added: Mapped[int] = mapped_column(BigInteger, default=0)

    # Timestamps
    first_contribution_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_contribution_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    user = relationship("GitHubUser", back_populates="global_leaderboard_entry")

    __table_args__ = (
        Index("idx_global_leaderboard_rank", "global_rank"),
        Index("idx_global_leaderboard_score", "total_score", postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        return f"<GlobalLeaderboard user_id={self.user_id} rank={self.global_rank}>"
