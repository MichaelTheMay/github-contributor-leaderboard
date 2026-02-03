#!/usr/bin/env python
"""Recalculate all leaderboard scores with the corrected formula."""

import asyncio
import sys
from decimal import Decimal

from sqlalchemy import select, func

# Fix Windows asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add project to path
sys.path.insert(0, str(__file__).rsplit("\\", 2)[0])
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])


def calculate_score(
    commits: int,
    prs_opened: int,
    prs_merged: int,
    prs_reviewed: int,
    issues_opened: int,
    issues_closed: int,
    comments: int,
    releases: int,
    lines_added: int,
    lines_deleted: int,
) -> Decimal:
    """
    Calculate score with CORRECTED formula.

    The key fix: line bonus is capped at 500 points maximum.
    Previously this was uncapped and could give 30,000+ points.
    """
    score = Decimal("0")

    # Core contribution scoring - these are the meaningful contributions
    score += Decimal(str(commits)) * Decimal("10")           # Commits
    score += Decimal(str(prs_opened)) * Decimal("15")        # PRs opened
    score += Decimal(str(prs_merged)) * Decimal("25")        # PRs merged (highest)
    score += Decimal(str(prs_reviewed)) * Decimal("20")      # PR reviews
    score += Decimal(str(issues_opened)) * Decimal("8")      # Issues opened
    score += Decimal(str(issues_closed)) * Decimal("5")      # Issues closed
    score += Decimal(str(comments)) * Decimal("3")           # Comments
    score += Decimal(str(releases)) * Decimal("30")          # Releases

    # Line bonus - HEAVILY reduced and CAPPED
    # Old formula: lines_added * 0.1 + lines_deleted * 0.05 (uncapped!)
    # New formula: lines_added * 0.01 + lines_deleted * 0.005, capped at 500
    line_bonus = (Decimal(str(lines_added)) * Decimal("0.01")) + \
                 (Decimal(str(lines_deleted)) * Decimal("0.005"))
    line_bonus = min(line_bonus, Decimal("500"))  # Cap at 500 points max
    score += line_bonus

    return score


async def recalculate_all_scores():
    """Recalculate all repository and global leaderboard scores."""
    from src.core.config import settings
    from src.db.database import create_worker_session_maker
    from src.db.models.leaderboard import GlobalLeaderboard, RepositoryLeaderboard

    print("=" * 60)
    print("RECALCULATING ALL LEADERBOARD SCORES")
    print("=" * 60)
    print("\nUsing CORRECTED scoring formula:")
    print("  - Commits: 10 pts each")
    print("  - PRs opened: 15 pts each")
    print("  - PRs merged: 25 pts each")
    print("  - PRs reviewed: 20 pts each")
    print("  - Issues opened: 8 pts each")
    print("  - Issues closed: 5 pts each")
    print("  - Comments: 3 pts each")
    print("  - Releases: 30 pts each")
    print("  - Line bonus: 0.01/line added, 0.005/line deleted (CAPPED at 500 pts)")
    print()

    async with create_worker_session_maker()() as db:
        # Step 1: Recalculate all repository leaderboard scores
        print("[Step 1] Recalculating repository leaderboard scores...")

        result = await db.execute(select(RepositoryLeaderboard))
        entries = result.scalars().all()

        count = 0
        for entry in entries:
            old_score = entry.total_score

            # Recalculate with corrected formula
            new_score = calculate_score(
                commits=entry.commit_count,
                prs_opened=entry.pr_opened_count,
                prs_merged=entry.pr_merged_count,
                prs_reviewed=entry.pr_reviewed_count,
                issues_opened=entry.issues_opened_count,
                issues_closed=entry.issues_closed_count,
                comments=entry.comments_count,
                releases=0,  # Releases not stored per-repo currently
                lines_added=entry.lines_added,
                lines_deleted=entry.lines_deleted,
            )

            entry.total_score = new_score
            count += 1

            if count % 1000 == 0:
                print(f"  Processed {count} entries...")

        await db.commit()
        print(f"  Updated {count} repository leaderboard entries")

        # Step 2: Update rankings within each repository
        print("\n[Step 2] Updating repository rankings...")

        # Get distinct repository IDs
        repo_result = await db.execute(
            select(RepositoryLeaderboard.repository_id).distinct()
        )
        repo_ids = [r[0] for r in repo_result.all()]

        for repo_id in repo_ids:
            # Get all entries for this repo, sorted by score
            result = await db.execute(
                select(RepositoryLeaderboard)
                .where(RepositoryLeaderboard.repository_id == repo_id)
                .order_by(RepositoryLeaderboard.total_score.desc())
            )
            repo_entries = result.scalars().all()

            # Update ranks
            for rank, entry in enumerate(repo_entries, start=1):
                entry.rank = rank

        await db.commit()
        print(f"  Updated rankings for {len(repo_ids)} repositories")

        # Step 3: Recalculate global leaderboard
        print("\n[Step 3] Recalculating global leaderboard...")

        # Aggregate scores per user across all repositories
        result = await db.execute(
            select(
                RepositoryLeaderboard.user_id,
                func.sum(RepositoryLeaderboard.total_score).label("total_score"),
                func.count(RepositoryLeaderboard.repository_id).label("repos"),
                func.sum(RepositoryLeaderboard.commit_count).label("commits"),
                func.sum(RepositoryLeaderboard.pr_opened_count).label("prs_opened"),
                func.sum(RepositoryLeaderboard.pr_merged_count).label("prs_merged"),
                func.sum(RepositoryLeaderboard.pr_reviewed_count).label("prs_reviewed"),
                func.sum(RepositoryLeaderboard.issues_opened_count).label("issues_opened"),
                func.sum(RepositoryLeaderboard.issues_closed_count).label("issues_closed"),
                func.sum(RepositoryLeaderboard.comments_count).label("comments"),
                func.sum(RepositoryLeaderboard.lines_added).label("lines_added"),
                func.sum(RepositoryLeaderboard.lines_deleted).label("lines_deleted"),
                func.min(RepositoryLeaderboard.first_contribution_at).label("first"),
                func.max(RepositoryLeaderboard.last_contribution_at).label("last"),
            )
            .group_by(RepositoryLeaderboard.user_id)
            .order_by(func.sum(RepositoryLeaderboard.total_score).desc())
        )
        aggregates = result.all()

        # Clear existing global leaderboard
        await db.execute(GlobalLeaderboard.__table__.delete())

        # Insert new rankings
        for rank, agg in enumerate(aggregates, start=1):
            entry = GlobalLeaderboard(
                user_id=agg.user_id,
                global_rank=rank,
                total_score=agg.total_score or Decimal("0"),
                repositories_contributed=agg.repos or 0,
                total_commits=agg.commits or 0,
                total_prs_merged=agg.prs_merged or 0,
                total_prs_reviewed=agg.prs_reviewed or 0,
                total_issues_opened=agg.issues_opened or 0,
                total_comments=agg.comments or 0,
                total_lines_added=agg.lines_added or 0,
                first_contribution_at=agg.first,
                last_contribution_at=agg.last,
            )
            db.add(entry)

        await db.commit()

        print(f"  Rebuilt global leaderboard with {len(aggregates)} contributors")

        # Step 4: Show top 10 with new scores
        print("\n[Step 4] Top 10 contributors (NEW scores):")
        print("-" * 80)
        print(f"{'Rank':<6}{'Username':<25}{'Score':<12}{'Commits':<10}{'PRs':<8}{'Reviews':<10}")
        print("-" * 80)

        from sqlalchemy.orm import joinedload
        result = await db.execute(
            select(GlobalLeaderboard)
            .options(joinedload(GlobalLeaderboard.user))
            .order_by(GlobalLeaderboard.global_rank)
            .limit(10)
        )
        top_entries = result.scalars().all()

        for entry in top_entries:
            print(
                f"{entry.global_rank:<6}"
                f"{entry.user.username:<25}"
                f"{float(entry.total_score):<12.2f}"
                f"{entry.total_commits:<10}"
                f"{entry.total_prs_merged:<8}"
                f"{entry.total_prs_reviewed:<10}"
            )

        print("-" * 80)
        print("\nScore recalculation complete!")


if __name__ == "__main__":
    asyncio.run(recalculate_all_scores())
