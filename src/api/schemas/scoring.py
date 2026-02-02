from decimal import Decimal

from pydantic import BaseModel, Field


class ScoringWeightCreate(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=50)
    base_points: Decimal = Field(..., ge=0)
    description: str | None = None


class ScoringWeightResponse(BaseModel):
    id: int
    event_type: str
    base_points: Decimal
    description: str | None

    model_config = {"from_attributes": True}


class ScoringWeightList(BaseModel):
    weights: list[ScoringWeightResponse]
