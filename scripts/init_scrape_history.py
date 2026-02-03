#!/usr/bin/env python3
"""
Initialize scrape history tables and add migration columns.

This script:
1. Creates the scrape_windows table if not exists
2. Adds incremental scraping columns to repositories table
3. Adds unique constraint on contribution_events.event_id
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import async_session_maker


@asynccontextmanager
async def get_async_session():
    """Context manager for database sessions."""
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


MIGRATION_SQL = """
-- Create scrape_windows table if not exists
CREATE TABLE IF NOT EXISTS scrape_windows (
    id SERIAL PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    job_id INTEGER REFERENCES scrape_jobs(id) ON DELETE SET NULL,
    data_start_date TIMESTAMP WITH TIME ZONE NOT NULL,
    data_end_date TIMESTAMP WITH TIME ZONE NOT NULL,
    events_fetched INTEGER DEFAULT 0,
    contributors_found INTEGER DEFAULT 0,
    bytes_processed BIGINT DEFAULT 0,
    bytes_billed BIGINT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for scrape_windows
CREATE INDEX IF NOT EXISTS idx_scrape_windows_repo_dates
    ON scrape_windows(repository_id, data_end_date);

-- Add unique constraint for scrape windows
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_scrape_windows_repo_date_range'
    ) THEN
        ALTER TABLE scrape_windows
        ADD CONSTRAINT uq_scrape_windows_repo_date_range
        UNIQUE (repository_id, data_start_date, data_end_date);
    END IF;
END $$;

-- Add incremental scraping columns to repositories if not exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'repositories' AND column_name = 'first_scraped_at'
    ) THEN
        ALTER TABLE repositories ADD COLUMN first_scraped_at TIMESTAMP WITH TIME ZONE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'repositories' AND column_name = 'earliest_data_date'
    ) THEN
        ALTER TABLE repositories ADD COLUMN earliest_data_date TIMESTAMP WITH TIME ZONE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'repositories' AND column_name = 'latest_data_date'
    ) THEN
        ALTER TABLE repositories ADD COLUMN latest_data_date TIMESTAMP WITH TIME ZONE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'repositories' AND column_name = 'never_rescrape_before'
    ) THEN
        ALTER TABLE repositories ADD COLUMN never_rescrape_before TIMESTAMP WITH TIME ZONE;
    END IF;
END $$;

-- Add unique constraint on contribution_events.event_id if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE indexname = 'idx_contribution_events_event_id'
    ) THEN
        CREATE UNIQUE INDEX idx_contribution_events_event_id
            ON contribution_events(event_id);
    END IF;
END $$;

-- Add relationship column for scrape_jobs -> scrape_window (one-to-one)
DO $$
BEGIN
    -- Add back-reference if scrape_jobs exists and doesn't have the column
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'scrape_jobs')
       AND NOT EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_name = 'scrape_jobs' AND column_name = 'scrape_window_id'
       ) THEN
        -- Note: We don't actually need this column since scrape_window references job_id
        -- This is just for documentation
        NULL;
    END IF;
END $$;
"""


async def run_migration():
    """Run the migration to set up scrape history tables."""
    print("Running scrape history migration...")
    print("=" * 50)

    async with get_async_session() as db:
        try:
            # Execute migration SQL
            for statement in MIGRATION_SQL.split(';'):
                statement = statement.strip()
                if statement and not statement.startswith('--'):
                    try:
                        await db.execute(text(statement))
                    except Exception as e:
                        # Some statements may fail if already applied
                        print(f"Note: {str(e)[:100]}...")

            await db.commit()
            print("Migration completed successfully!")

            # Verify tables exist
            result = await db.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name IN ('scrape_windows', 'repositories', 'contribution_events')
            """))
            tables = [row[0] for row in result.fetchall()]
            print(f"\nVerified tables: {', '.join(tables)}")

            # Check new columns on repositories
            result = await db.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'repositories'
                AND column_name IN (
                    'first_scraped_at', 'earliest_data_date',
                    'latest_data_date', 'never_rescrape_before'
                )
            """))
            columns = [row[0] for row in result.fetchall()]
            print(f"Repository tracking columns: {', '.join(columns)}")

            # Check unique index on contribution_events
            result = await db.execute(text("""
                SELECT indexname FROM pg_indexes
                WHERE tablename = 'contribution_events'
                AND indexname = 'idx_contribution_events_event_id'
            """))
            idx = result.fetchone()
            if idx:
                print(f"Event deduplication index: {idx[0]}")

            print("\n" + "=" * 50)
            print("All scrape history infrastructure is ready!")

        except Exception as e:
            print(f"Migration failed: {e}")
            await db.rollback()
            raise


async def check_current_state():
    """Check current database state before migration."""
    print("Checking current database state...")
    print("=" * 50)

    async with get_async_session() as db:
        # Check if scrape_windows exists
        result = await db.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'scrape_windows'
            )
        """))
        scrape_windows_exists = result.scalar()
        print(f"scrape_windows table exists: {scrape_windows_exists}")

        # Check repository columns
        result = await db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'repositories'
            ORDER BY ordinal_position
        """))
        columns = [row[0] for row in result.fetchall()]
        print(f"Repository columns: {len(columns)}")

        tracking_cols = [c for c in columns if c in [
            'first_scraped_at', 'earliest_data_date',
            'latest_data_date', 'never_rescrape_before'
        ]]
        print(f"Tracking columns present: {tracking_cols or 'None'}")

        # Check contribution_events unique constraint
        result = await db.execute(text("""
            SELECT indexname, indexdef FROM pg_indexes
            WHERE tablename = 'contribution_events'
        """))
        indexes = result.fetchall()
        print(f"\nContribution events indexes:")
        for idx_name, idx_def in indexes:
            unique = "UNIQUE" if "unique" in idx_def.lower() else ""
            print(f"  - {idx_name} {unique}")

        print("=" * 50)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Initialize scrape history tables")
    parser.add_argument("--check", action="store_true", help="Only check current state")
    args = parser.parse_args()

    if args.check:
        asyncio.run(check_current_state())
    else:
        asyncio.run(run_migration())
