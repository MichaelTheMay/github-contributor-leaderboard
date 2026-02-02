from datetime import datetime

from pydantic import BaseModel, Field

from src.db.models.repository import RepositoryStatus


class RepositoryCreate(BaseModel):
    owner: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)


class RepositoryDetail(BaseModel):
    id: int
    owner: str
    name: str
    full_name: str
    github_id: int
    description: str | None
    stars: int
    forks: int
    status: RepositoryStatus
    last_scraped_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RepositoryList(BaseModel):
    repositories: list[RepositoryDetail]
    total: int
    page: int
    page_size: int
