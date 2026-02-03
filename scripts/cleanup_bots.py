#!/usr/bin/env python3
"""
Clean up bot accounts from the database.

This script:
1. Identifies bot accounts in github_users table
2. Removes their leaderboard entries
3. Removes their contribution events
4. Removes the bot user records
5. Recalculates affected leaderboards
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from contextlib import asynccontextmanager

from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import async_session_maker
from src.db.models.contribution import ContributionEvent
from src.db.models.leaderboard import GlobalLeaderboard, RepositoryLeaderboard
from src.db.models.user import GitHubUser


@asynccontextmanager
async def get_async_session():
    """Context manager for database sessions."""
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

# Bot account patterns to filter out
BOT_PATTERNS = [
    "[bot]",
    "-bot",
    "dependabot",
    "github-actions",
    "renovate",
    "greenkeeper",
    "snyk-bot",
    "codecov",
    "coveralls",
    "semantic-release",
    "release-drafter",
    "allcontributors",
    "imgbot",
    "stale",
]


def is_bot_account(username: str) -> bool:
    """Check if a username appears to be a bot account."""
    if not username:
        return True
    username_lower = username.lower()
    return any(pattern in username_lower for pattern in BOT_PATTERNS)


async def find_bot_accounts(db: AsyncSession) -> list[GitHubUser]:
    """Find all bot accounts in the database."""
    result = await db.execute(select(GitHubUser))
    all_users = result.scalars().all()

    bots = [user for user in all_users if is_bot_account(user.username)]
    return bots


async def cleanup_bot_accounts(db: AsyncSession, dry_run: bool = True) -> dict:
    """Remove bot accounts and their associated data."""
    stats = {
        "bots_found": 0,
        "leaderboard_entries_removed": 0,
        "global_entries_removed": 0,
        "events_removed": 0,
        "users_removed": 0,
    }

    # Find bot accounts
    bots = await find_bot_accounts(db)
    stats["bots_found"] = len(bots)

    if not bots:
        print("No bot accounts found!")
        return stats

    print(f"\nFound {len(bots)} bot accounts:")
    for bot in bots[:20]:  # Show first 20
        print(f"  - {bot.username} (id={bot.id}, github_id={bot.github_id})")
    if len(bots) > 20:
        print(f"  ... and {len(bots) - 20} more")

    bot_ids = [bot.id for bot in bots]

    if dry_run:
        # Count affected records without deleting
        lb_result = await db.execute(
            select(func.count(RepositoryLeaderboard.id)).where(
                RepositoryLeaderboard.user_id.in_(bot_ids)
            )
        )
        stats["leaderboard_entries_removed"] = lb_result.scalar() or 0

        global_result = await db.execute(
            select(func.count(GlobalLeaderboard.id)).where(
                GlobalLeaderboard.user_id.in_(bot_ids)
            )
        )
        stats["global_entries_removed"] = global_result.scalar() or 0

        events_result = await db.execute(
            select(func.count(ContributionEvent.id)).where(
                ContributionEvent.user_id.in_(bot_ids)
            )
        )
        stats["events_removed"] = events_result.scalar() or 0

        stats["users_removed"] = len(bots)

        print(f"\n[DRY RUN] Would remove:")
        print(f"  - {stats['leaderboard_entries_removed']} repository leaderboard entries")
        print(f"  - {stats['global_entries_removed']} global leaderboard entries")
        print(f"  - {stats['events_removed']} contribution events")
        print(f"  - {stats['users_removed']} bot user records")

    else:
        # Actually delete records
        print("\nDeleting bot data...")

        # Delete repository leaderboard entries
        result = await db.execute(
            delete(RepositoryLeaderboard).where(
                RepositoryLeaderboard.user_id.in_(bot_ids)
            )
        )
        stats["leaderboard_entries_removed"] = result.rowcount
        print(f"  Deleted {result.rowcount} repository leaderboard entries")

        # Delete global leaderboard entries
        result = await db.execute(
            delete(GlobalLeaderboard).where(
                GlobalLeaderboard.user_id.in_(bot_ids)
            )
        )
        stats["global_entries_removed"] = result.rowcount
        print(f"  Deleted {result.rowcount} global leaderboard entries")

        # Delete contribution events
        result = await db.execute(
            delete(ContributionEvent).where(
                ContributionEvent.user_id.in_(bot_ids)
            )
        )
        stats["events_removed"] = result.rowcount
        print(f"  Deleted {result.rowcount} contribution events")

        # Delete user records
        result = await db.execute(
            delete(GitHubUser).where(
                GitHubUser.id.in_(bot_ids)
            )
        )
        stats["users_removed"] = result.rowcount
        print(f"  Deleted {result.rowcount} bot user records")

        await db.commit()
        print("\nCleanup committed!")

    return stats


async def show_user_stats(db: AsyncSession) -> None:
    """Show current user statistics."""
    # Total users
    total_result = await db.execute(select(func.count(GitHubUser.id)))
    total_users = total_result.scalar() or 0

    # Global leaderboard entries
    global_result = await db.execute(select(func.count(GlobalLeaderboard.id)))
    global_entries = global_result.scalar() or 0

    # Repository leaderboard entries
    repo_result = await db.execute(select(func.count(RepositoryLeaderboard.id)))
    repo_entries = repo_result.scalar() or 0

    # Unique users in leaderboards
    unique_result = await db.execute(
        select(func.count(func.distinct(RepositoryLeaderboard.user_id)))
    )
    unique_in_leaderboards = unique_result.scalar() or 0

    print("\n=== Current User Statistics ===")
    print(f"Total GitHub users in database: {total_users:,}")
    print(f"Global leaderboard entries: {global_entries:,}")
    print(f"Repository leaderboard entries: {repo_entries:,}")
    print(f"Unique users with leaderboard entries: {unique_in_leaderboards:,}")

    # Check for discrepancies
    if total_users != global_entries:
        print(f"\n[!] Discrepancy: {total_users - global_entries} users without global leaderboard entries")

    # Find potential bot patterns
    bots = await find_bot_accounts(db)
    if bots:
        print(f"\n[!] Found {len(bots)} potential bot accounts that should be cleaned up")


async def main(dry_run: bool = True):
    """Main cleanup function."""
    print("=" * 60)
    print("Bot Account Cleanup Script")
    print("=" * 60)

    async with get_async_session() as db:
        # Show current stats
        await show_user_stats(db)

        # Run cleanup
        print("\n" + "=" * 60)
        if dry_run:
            print("Running in DRY RUN mode (no changes will be made)")
        else:
            print("Running in LIVE mode (changes will be committed)")
        print("=" * 60)

        stats = await cleanup_bot_accounts(db, dry_run=dry_run)

        if not dry_run:
            # Show updated stats
            print("\n" + "=" * 60)
            print("After cleanup:")
            await show_user_stats(db)

        return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Clean up bot accounts from the database")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute the cleanup (default is dry run)"
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Only show statistics, don't run cleanup"
    )
    args = parser.parse_args()

    if args.stats_only:
        async def show_stats():
            async with get_async_session() as db:
                await show_user_stats(db)
        asyncio.run(show_stats())
    else:
        asyncio.run(main(dry_run=not args.execute))
