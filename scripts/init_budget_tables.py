#!/usr/bin/env python
"""Initialize budget tracking tables."""

import asyncio
import sys

# Fix Windows asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add project to path
sys.path.insert(0, str(__file__).rsplit("\\", 2)[0])
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])


async def init_budget_tables():
    """Create budget tracking tables."""
    from sqlalchemy import text
    from src.db.database import engine

    print("=" * 60)
    print("INITIALIZING BUDGET TRACKING TABLES")
    print("=" * 60)

    async with engine.begin() as conn:
        # Add new columns to scrape_jobs table if they don't exist
        print("\n[1] Adding cost tracking columns to scrape_jobs...")
        columns_to_add = [
            ("estimated_cost", "NUMERIC(10, 6) DEFAULT 0"),
            ("actual_cost", "NUMERIC(10, 6) DEFAULT 0"),
            ("bytes_processed", "BIGINT DEFAULT 0"),
            ("bytes_billed", "BIGINT DEFAULT 0"),
        ]
        for col_name, col_def in columns_to_add:
            try:
                await conn.execute(text(f"ALTER TABLE scrape_jobs ADD COLUMN IF NOT EXISTS {col_name} {col_def}"))
                print(f"  Added column {col_name}")
            except Exception as e:
                print(f"  Note for {col_name}: {e}")

        # Create budget_config table
        print("\n[2] Creating budget_config table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS budget_config (
                id SERIAL PRIMARY KEY,
                monthly_budget_limit NUMERIC(10, 4) DEFAULT 50.00,
                daily_budget_limit NUMERIC(10, 4) DEFAULT 10.00,
                per_job_limit NUMERIC(10, 4) DEFAULT 5.00,
                alert_threshold_warning INTEGER DEFAULT 70,
                alert_threshold_critical INTEGER DEFAULT 90,
                auto_pause_on_budget_exceeded BOOLEAN DEFAULT TRUE,
                bigquery_price_per_tb NUMERIC(10, 4) DEFAULT 5.00,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        print("  Created budget_config table")

        # Create cost_records table
        print("\n[3] Creating cost_records table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cost_records (
                id SERIAL PRIMARY KEY,
                job_id INTEGER REFERENCES scrape_jobs(id) ON DELETE SET NULL,
                repository_id INTEGER REFERENCES repositories(id) ON DELETE SET NULL,
                category VARCHAR(50) NOT NULL,
                description VARCHAR(500),
                estimated_cost NUMERIC(10, 6) DEFAULT 0,
                actual_cost NUMERIC(10, 6) DEFAULT 0,
                bytes_processed BIGINT DEFAULT 0,
                bytes_billed BIGINT DEFAULT 0,
                started_at TIMESTAMP WITH TIME ZONE,
                completed_at TIMESTAMP WITH TIME ZONE,
                duration_seconds INTEGER DEFAULT 0,
                metadata JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        print("  Created cost_records table")

        # Create indices for cost_records
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cost_records_category ON cost_records(category)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cost_records_created ON cost_records(created_at)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cost_records_job ON cost_records(job_id)"))
        print("  Created indices for cost_records")

        # Create daily_cost_summaries table
        print("\n[4] Creating daily_cost_summaries table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_cost_summaries (
                id SERIAL PRIMARY KEY,
                date TIMESTAMP WITH TIME ZONE UNIQUE,
                bigquery_cost NUMERIC(10, 4) DEFAULT 0,
                github_api_cost NUMERIC(10, 4) DEFAULT 0,
                enrichment_cost NUMERIC(10, 4) DEFAULT 0,
                infrastructure_cost NUMERIC(10, 4) DEFAULT 0,
                total_cost NUMERIC(10, 4) DEFAULT 0,
                total_bytes_processed BIGINT DEFAULT 0,
                jobs_completed INTEGER DEFAULT 0,
                jobs_failed INTEGER DEFAULT 0,
                repositories_scraped INTEGER DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        print("  Created daily_cost_summaries table")

        # Create audit_logs table
        print("\n[5] Creating audit_logs table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
                action VARCHAR(50) NOT NULL,
                category VARCHAR(50) NOT NULL,
                description TEXT,
                job_id INTEGER REFERENCES scrape_jobs(id) ON DELETE SET NULL,
                repository_id INTEGER REFERENCES repositories(id) ON DELETE SET NULL,
                user_id INTEGER REFERENCES github_users(id) ON DELETE SET NULL,
                estimated_cost NUMERIC(10, 6),
                actual_cost NUMERIC(10, 6),
                bytes_processed BIGINT,
                success BOOLEAN DEFAULT TRUE,
                error_message TEXT,
                metadata JSONB,
                source VARCHAR(50) DEFAULT 'system',
                ip_address VARCHAR(45)
            )
        """))
        print("  Created audit_logs table")

        # Create indices for audit_logs
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_logs(category)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_job ON audit_logs(job_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_repository ON audit_logs(repository_id)"))
        print("  Created indices for audit_logs")

        # Insert default budget config if not exists
        print("\n[6] Inserting default budget configuration...")
        result = await conn.execute(text("SELECT COUNT(*) FROM budget_config"))
        count = result.scalar()
        if count == 0:
            await conn.execute(text("""
                INSERT INTO budget_config (
                    monthly_budget_limit, daily_budget_limit, per_job_limit,
                    alert_threshold_warning, alert_threshold_critical,
                    auto_pause_on_budget_exceeded, bigquery_price_per_tb, is_active
                ) VALUES (50.00, 10.00, 5.00, 70, 90, TRUE, 5.00, TRUE)
            """))
            print("  Inserted default budget config")
        else:
            print("  Budget config already exists")

    print("\n" + "=" * 60)
    print("BUDGET TABLES INITIALIZED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(init_budget_tables())
