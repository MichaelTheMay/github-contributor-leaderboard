from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.scoring import ScoringWeightCreate, ScoringWeightResponse
from src.db import get_db
from src.services.scoring_service import ScoringService

router = APIRouter()


@router.get(
    "/scoring",
    response_model=list[ScoringWeightResponse],
    summary="Get current scoring weights",
)
async def get_scoring_weights(
    db: AsyncSession = Depends(get_db),
) -> list[ScoringWeightResponse]:
    """Get the current scoring weights for all event types."""
    service = ScoringService(db)
    weights = await service.get_all_weights()
    return [ScoringWeightResponse.model_validate(w) for w in weights]


@router.put(
    "/scoring",
    response_model=list[ScoringWeightResponse],
    summary="Update scoring weights",
)
async def update_scoring_weights(
    weights: list[ScoringWeightCreate],
    db: AsyncSession = Depends(get_db),
) -> list[ScoringWeightResponse]:
    """Update scoring weights. This will trigger leaderboard recalculation."""
    service = ScoringService(db)
    updated = await service.update_weights(weights)
    return [ScoringWeightResponse.model_validate(w) for w in updated]
