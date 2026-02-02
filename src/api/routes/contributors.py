from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.contributor import (
    ContributorActivity,
    ContributorDetail,
    ContributorRepository,
)
from src.db import get_db
from src.services.contributor_service import ContributorService

router = APIRouter()


@router.get(
    "/{username}",
    response_model=ContributorDetail,
    summary="Get contributor profile",
)
async def get_contributor(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> ContributorDetail:
    """Get full contributor profile with enrichment data."""
    service = ContributorService(db)
    contributor = await service.get_contributor(username)
    if not contributor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contributor {username} not found",
        )
    return contributor


@router.get(
    "/{username}/activity",
    response_model=list[ContributorActivity],
    summary="Get contribution history",
)
async def get_contributor_activity(
    username: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[ContributorActivity]:
    """Get contribution history timeline for a contributor."""
    service = ContributorService(db)
    activities = await service.get_activity(username, page, page_size)
    if activities is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contributor {username} not found",
        )
    return activities


@router.get(
    "/{username}/repositories",
    response_model=list[ContributorRepository],
    summary="Get per-repository breakdown",
)
async def get_contributor_repositories(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> list[ContributorRepository]:
    """Get per-repository contribution breakdown for a contributor."""
    service = ContributorService(db)
    repositories = await service.get_repositories(username)
    if repositories is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contributor {username} not found",
        )
    return repositories


@router.post(
    "/{username}/enrich",
    response_model=dict,
    summary="Trigger profile enrichment",
)
async def enrich_contributor(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger enrichment pipeline for a specific contributor."""
    service = ContributorService(db)
    result = await service.trigger_enrichment(username)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contributor {username} not found",
        )
    return {"message": "Enrichment job queued", "username": username}
