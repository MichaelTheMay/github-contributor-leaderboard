#!/usr/bin/env python3
"""Migration script to add new enrichment columns to contributor_enrichments table.

This script adds all the new social media, professional platform, and contact
fields to the enrichment table for comprehensive contributor data collection.

Usage:
    python scripts/migrate_enrichment_schema.py

Note: Run this AFTER updating the model but BEFORE running the application
with the new schema.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.core.config import settings


# New columns to add (column_name, data_type, nullable)
NEW_COLUMNS = [
    # Additional Social Platforms
    ("github_sponsors_url", "TEXT", True),
    ("bluesky_handle", "VARCHAR(255)", True),
    ("threads_username", "VARCHAR(255)", True),
    ("instagram_username", "VARCHAR(255)", True),
    ("facebook_url", "TEXT", True),
    ("reddit_username", "VARCHAR(255)", True),
    ("hackernews_username", "VARCHAR(255)", True),
    ("stackoverflow_url", "TEXT", True),
    ("kaggle_username", "VARCHAR(255)", True),
    ("twitch_username", "VARCHAR(255)", True),
    ("tiktok_username", "VARCHAR(255)", True),

    # Professional/Developer Platforms
    ("npm_username", "VARCHAR(255)", True),
    ("pypi_username", "VARCHAR(255)", True),
    ("gitlab_username", "VARCHAR(255)", True),
    ("bitbucket_username", "VARCHAR(255)", True),
    ("codepen_username", "VARCHAR(255)", True),
    ("dribbble_username", "VARCHAR(255)", True),
    ("behance_username", "VARCHAR(255)", True),

    # Contact/Communication Platforms
    ("telegram_username", "VARCHAR(255)", True),
    ("signal_username", "VARCHAR(255)", True),
    ("keybase_username", "VARCHAR(255)", True),
    ("matrix_handle", "VARCHAR(255)", True),
    ("slack_workspace", "VARCHAR(255)", True),

    # Multiple values support (JSONB arrays)
    ("additional_emails", "JSONB", True),
    ("additional_websites", "JSONB", True),
    ("social_links_raw", "JSONB", True),

    # GitHub-specific extracted data
    ("github_bio", "TEXT", True),
    ("github_company", "VARCHAR(255)", True),
    ("github_location", "VARCHAR(255)", True),
    ("github_hireable", "BOOLEAN", True),
    ("github_followers", "INTEGER", True),
    ("github_following", "INTEGER", True),
    ("github_public_repos", "INTEGER", True),
    ("github_created_at", "TIMESTAMP WITH TIME ZONE", True),

    # Enrichment tracking
    ("enrichment_attempts", "INTEGER DEFAULT 0", True),
    ("last_error", "TEXT", True),
]

# New indexes to create
NEW_INDEXES = [
    ("idx_enrichment_last_enriched", "last_enriched_at"),
]


async def column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check if a column already exists in a table."""
    result = await conn.execute(
        text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = :table_name
            AND column_name = :column_name
        """),
        {"table_name": table_name, "column_name": column_name}
    )
    return result.fetchone() is not None


async def index_exists(conn, index_name: str) -> bool:
    """Check if an index already exists."""
    result = await conn.execute(
        text("""
            SELECT indexname
            FROM pg_indexes
            WHERE indexname = :index_name
        """),
        {"index_name": index_name}
    )
    return result.fetchone() is not None


async def migrate():
    """Run the migration to add new columns."""
    print("=" * 60)
    print("Enrichment Schema Migration")
    print("=" * 60)
    print(f"Database: {settings.database_url}")
    print()

    engine = create_async_engine(str(settings.database_url), echo=False)

    async with engine.begin() as conn:
        # Add new columns
        print("Adding new columns...")
        added = 0
        skipped = 0

        for column_name, data_type, nullable in NEW_COLUMNS:
            if await column_exists(conn, "contributor_enrichments", column_name):
                print(f"  [SKIP] {column_name} (already exists)")
                skipped += 1
            else:
                null_clause = "" if nullable else " NOT NULL"
                sql = f'ALTER TABLE contributor_enrichments ADD COLUMN "{column_name}" {data_type}{null_clause}'
                try:
                    await conn.execute(text(sql))
                    print(f"  [ADD]  {column_name} ({data_type})")
                    added += 1
                except Exception as e:
                    print(f"  [ERR]  {column_name}: {e}")

        print()
        print(f"Columns: {added} added, {skipped} skipped")
        print()

        # Add new indexes
        print("Adding new indexes...")
        for index_name, column_name in NEW_INDEXES:
            if await index_exists(conn, index_name):
                print(f"  [SKIP] {index_name} (already exists)")
            else:
                try:
                    await conn.execute(
                        text(f'CREATE INDEX "{index_name}" ON contributor_enrichments ("{column_name}")')
                    )
                    print(f"  [ADD]  {index_name} on {column_name}")
                except Exception as e:
                    print(f"  [ERR]  {index_name}: {e}")

        print()
        print("Migration completed successfully!")

    await engine.dispose()


async def show_current_schema():
    """Show the current schema of the enrichment table."""
    print("=" * 60)
    print("Current Enrichment Table Schema")
    print("=" * 60)

    engine = create_async_engine(str(settings.database_url), echo=False)

    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = 'contributor_enrichments'
                ORDER BY ordinal_position
            """)
        )
        columns = result.fetchall()

        if not columns:
            print("Table 'contributor_enrichments' does not exist!")
            return

        print(f"{'Column':<30} {'Type':<25} {'Nullable':<10} {'Default':<20}")
        print("-" * 85)
        for col in columns:
            name, dtype, nullable, default = col
            default_str = str(default)[:20] if default else ""
            print(f"{name:<30} {dtype:<25} {nullable:<10} {default_str:<20}")

        print()
        print(f"Total columns: {len(columns)}")

    await engine.dispose()


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Migrate enrichment schema to add new columns"
    )
    parser.add_argument(
        "--show-schema",
        action="store_true",
        help="Show current table schema without making changes"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )

    args = parser.parse_args()

    if args.show_schema:
        await show_current_schema()
    elif args.dry_run:
        print("DRY RUN - No changes will be made")
        print()
        print("Columns to add:")
        for col_name, col_type, nullable in NEW_COLUMNS:
            print(f"  - {col_name}: {col_type}")
        print()
        print("Indexes to add:")
        for idx_name, col_name in NEW_INDEXES:
            print(f"  - {idx_name} on {col_name}")
    else:
        await migrate()


if __name__ == "__main__":
    asyncio.run(main())
