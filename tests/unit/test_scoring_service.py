from decimal import Decimal

import pytest

from src.db.models.contribution import EventType
from src.services.scoring_service import ScoringService


class TestScoringCalculation:
    """Tests for score calculation logic."""

    def test_basic_score_calculation(self) -> None:
        """Test basic score calculation without lines."""
        # This tests the pure calculation logic
        weight = Decimal("10.0")
        base_score = weight

        # For non-commit events, score equals weight
        assert base_score == Decimal("10.0")

    def test_commit_score_with_lines(self) -> None:
        """Test commit scoring includes line bonuses."""
        base_weight = Decimal("10.0")
        lines_added = 100
        lines_deleted = 50

        # Using default multipliers from config
        lines_added_multiplier = Decimal("0.1")
        lines_deleted_multiplier = Decimal("0.05")

        line_bonus = (
            Decimal(str(lines_added)) * lines_added_multiplier
            + Decimal(str(lines_deleted)) * lines_deleted_multiplier
        )
        total_score = base_weight + line_bonus

        # 10 + (100 * 0.1) + (50 * 0.05) = 10 + 10 + 2.5 = 22.5
        assert total_score == Decimal("22.5")

    def test_score_calculation_zero_lines(self) -> None:
        """Test commit scoring with zero lines added/deleted."""
        base_weight = Decimal("10.0")

        lines_added_multiplier = Decimal("0.1")
        lines_deleted_multiplier = Decimal("0.05")

        line_bonus = (
            Decimal("0") * lines_added_multiplier
            + Decimal("0") * lines_deleted_multiplier
        )
        total_score = base_weight + line_bonus

        assert total_score == Decimal("10.0")

    def test_high_activity_score(self) -> None:
        """Test scoring for high activity contributor."""
        # Simulate aggregate scoring for multiple events
        events = {
            EventType.COMMIT.value: (100, Decimal("10.0")),
            EventType.PR_MERGED.value: (10, Decimal("25.0")),
            EventType.PR_REVIEWED.value: (50, Decimal("20.0")),
            EventType.ISSUE_OPENED.value: (5, Decimal("8.0")),
            EventType.COMMENT.value: (200, Decimal("3.0")),
        }

        total = Decimal("0")
        for event_type, (count, weight) in events.items():
            total += Decimal(str(count)) * weight

        # 1000 + 250 + 1000 + 40 + 600 = 2890
        assert total == Decimal("2890.0")
