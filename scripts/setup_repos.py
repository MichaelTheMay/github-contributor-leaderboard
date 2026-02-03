#!/usr/bin/env python
"""Clean up stale jobs and add popular repositories."""
import asyncio
import sys
sys.path.insert(0, ".")

from sqlalchemy import select, delete
from src.db.database import create_worker_session_maker
from src.db.models.job import JobStatus, ScrapeJob
from src.db.models.repository import Repository, RepositoryStatus
from src.services.github_service import GitHubService

# Popular repositories to track
REPOS_TO_ADD = [
    ("pallets", "flask"),
    ("tiangolo", "fastapi"),
    ("psf", "requests"),
    ("django", "django"),
    ("pytorch", "pytorch"),
]


async def cleanup_stale_jobs():
    """Remove old queued jobs that were never processed."""
    session_maker = create_worker_session_maker()
    async with session_maker() as db:
        # Delete all queued jobs (they're stale)
        result = await db.execute(
            delete(ScrapeJob).where(ScrapeJob.status == JobStatus.QUEUED)
        )
        deleted = result.rowcount
        await db.commit()
        print(f"Deleted {deleted} stale queued jobs")


async def add_repositories():
    """Add popular repositories."""
    session_maker = create_worker_session_maker()
    github = GitHubService()

    async with session_maker() as db:
        for owner, name in REPOS_TO_ADD:
            # Check if already exists
            result = await db.execute(
                select(Repository).where(
                    Repository.owner == owner,
                    Repository.name == name,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"Repository {owner}/{name} already exists")
                continue

            # Fetch from GitHub
            try:
                github_repo = await github.get_repository(owner, name)
                if not github_repo:
                    print(f"Repository {owner}/{name} not found on GitHub")
                    continue

                repo = Repository(
                    owner=owner,
                    name=name,
                    github_id=github_repo["id"],
                    description=github_repo.get("description"),
                    stars=github_repo.get("stargazers_count", 0),
                    forks=github_repo.get("forks_count", 0),
                    status=RepositoryStatus.PENDING,
                )
                db.add(repo)
                await db.commit()
                print(f"Added repository {owner}/{name} ({github_repo.get('stargazers_count', 0)} stars)")
            except Exception as e:
                print(f"Error adding {owner}/{name}: {e}")
                await db.rollback()


async def main():
    print("=== Cleaning up stale jobs ===")
    await cleanup_stale_jobs()

    print("\n=== Adding repositories ===")
    await add_repositories()

    print("\n=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
