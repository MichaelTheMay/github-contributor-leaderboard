from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.base import Base, TimestampMixin


class GitHubUser(Base, TimestampMixin):
    __tablename__ = "github_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    profile_url: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(255))
    company: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    bio: Mapped[str | None] = mapped_column(Text)
    followers: Mapped[int] = mapped_column(default=0)
    public_repos: Mapped[int] = mapped_column(default=0)

    # Relationships
    contribution_events = relationship(
        "ContributionEvent",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    repository_leaderboard_entries = relationship(
        "RepositoryLeaderboard",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    global_leaderboard_entry = relationship(
        "GlobalLeaderboard",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    enrichment = relationship(
        "ContributorEnrichment",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_github_users_username", "username"),
        Index("idx_github_users_github_id", "github_id"),
    )

    def __repr__(self) -> str:
        return f"<GitHubUser {self.username}>"
