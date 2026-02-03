#!/usr/bin/env python
"""Clean up stale jobs and trigger scrapes for pending repositories."""

import asyncio
import sys

# Fix Windows asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add project to path
sys.path.insert(0, str(__file__).rsplit("\\", 2)[0])
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])


async def cleanup_and_scrape():
    """Clean up stale jobs and trigger new scrapes."""
    from datetime import datetime, timedelta
    from sqlalchemy import select, update

    from src.db.database import create_worker_session_maker
    from src.db.models.job import JobStatus, JobType, ScrapeJob
    from src.db.models.repository import Repository, RepositoryStatus
    from src.workers.tasks.scrape_tasks import scrape_repository

    print("=" * 60)
    print("CLEANUP AND SCRAPE")
    print("=" * 60)

    async with create_worker_session_maker()() as db:
        # Step 1: Clean up stale QUEUED/RUNNING jobs (older than 1 hour)
        cutoff = datetime.utcnow() - timedelta(hours=1)

        stale_jobs = await db.execute(
            select(ScrapeJob).where(
                ScrapeJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                ScrapeJob.created_at < cutoff,
            )
        )
        stale = stale_jobs.scalars().all()

        if stale:
            print(f"\n[Cleanup] Found {len(stale)} stale jobs to mark as failed")
            for job in stale:
                job.status = JobStatus.FAILED
                job.error_message = "Marked as failed - stale job"
                job.completed_at = datetime.utcnow()
                print(f"  - Job {job.id} for repo {job.repository_id}")
            await db.commit()
        else:
            print("\n[Cleanup] No stale jobs found")

        # Step 2: Reset repositories that are stuck in SCRAPING status
        stuck_repos = await db.execute(
            select(Repository).where(Repository.status == RepositoryStatus.SCRAPING)
        )
        stuck = stuck_repos.scalars().all()
        if stuck:
            print(f"\n[Cleanup] Found {len(stuck)} repositories stuck in SCRAPING status")
            for repo in stuck:
                repo.status = RepositoryStatus.PENDING
                print(f"  - {repo.owner}/{repo.name} reset to PENDING")
            await db.commit()

        # Step 3: Get pending repositories (not yet scraped successfully)
        pending = await db.execute(
            select(Repository).where(
                Repository.status.in_([RepositoryStatus.PENDING, RepositoryStatus.FAILED])
            )
        )
        pending_repos = pending.scalars().all()

        print(f"\n[Repositories] Found {len(pending_repos)} pending/failed repositories")

        # Step 4: Trigger scrapes for small/medium repos
        # Skip very large repos like pytorch/pytorch for now
        skip_repos = {"pytorch/pytorch", "facebook/react", "django/django"}

        for repo in pending_repos:
            full_name = f"{repo.owner}/{repo.name}"

            if full_name in skip_repos:
                print(f"  - Skipping {full_name} (too large)")
                continue

            # Check for existing pending jobs
            existing = await db.execute(
                select(ScrapeJob).where(
                    ScrapeJob.repository_id == repo.id,
                    ScrapeJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                )
            )
            if existing.scalar_one_or_none():
                print(f"  - Skipping {full_name} (job already queued)")
                continue

            # Create new job
            job = ScrapeJob(
                repository_id=repo.id,
                job_type=JobType.FULL_SCRAPE,
            )
            db.add(job)
            await db.flush()

            print(f"  - Queuing scrape for {full_name} (job {job.id})")

            # Trigger Celery task
            scrape_repository.delay(repo.id, job.id)

        await db.commit()
        print("\n[Done] Scrape jobs queued successfully!")


if __name__ == "__main__":
    asyncio.run(cleanup_and_scrape())
