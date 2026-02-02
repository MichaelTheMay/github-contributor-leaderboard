from decimal import Decimal

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base, TimestampMixin


class ScoringWeight(Base, TimestampMixin):
    __tablename__ = "scoring_weights"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    base_points: Mapped[Decimal] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<ScoringWeight {self.event_type}={self.base_points}>"
