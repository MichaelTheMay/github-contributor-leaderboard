from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.leaderboard import (
    GlobalLeaderboardEntry,
    LeaderboardResponse,
    RepositoryLeaderboardEntry,
)
from src.db import get_db
from src.services.leaderboard_service import LeaderboardService

router = APIRouter()


@router.get(
    "/global",
    response_model=LeaderboardResponse,
    summary="Get global leaderboard",
)
async def get_global_leaderboard(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> LeaderboardResponse:
    """Get the master leaderboard across all tracked repositories."""
    service = LeaderboardService(db)
    entries, total = await service.get_global_leaderboard(page, page_size)
    return LeaderboardResponse(
        entries=[GlobalLeaderboardEntry.model_validate(e) for e in entries],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{owner}/{name}",
    response_model=LeaderboardResponse,
    summary="Get repository leaderboard",
)
async def get_repository_leaderboard(
    owner: str,
    name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> LeaderboardResponse:
    """Get the leaderboard for a specific repository."""
    service = LeaderboardService(db)
    result = await service.get_repository_leaderboard(owner, name, page, page_size)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {owner}/{name} not found",
        )
    entries, total = result
    return LeaderboardResponse(
        entries=[RepositoryLeaderboardEntry.model_validate(e) for e in entries],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/compare",
    response_model=dict,
    summary="Compare rankings across repositories",
)
async def compare_leaderboards(
    repos: list[str] = Query(..., description="List of repos in owner/name format"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Compare contributor rankings across multiple repositories."""
    service = LeaderboardService(db)
    comparison = await service.compare_repositories(repos, limit)
    return comparison
