import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    """Test health check endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_list_repositories_empty(client: AsyncClient) -> None:
    """Test listing repositories when none exist."""
    response = await client.get("/api/v1/repositories")
    assert response.status_code == 200
    data = response.json()
    assert data["repositories"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_global_leaderboard_empty(client: AsyncClient) -> None:
    """Test getting global leaderboard when empty."""
    response = await client.get("/api/v1/leaderboard/global")
    assert response.status_code == 200
    data = response.json()
    assert data["entries"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_repository_not_found(client: AsyncClient) -> None:
    """Test getting a non-existent repository."""
    response = await client.get("/api/v1/repositories/nonexistent/repo")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_contributor_not_found(client: AsyncClient) -> None:
    """Test getting a non-existent contributor."""
    response = await client.get("/api/v1/contributors/nonexistent_user")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_scoring_weights(client: AsyncClient) -> None:
    """Test getting scoring weights initializes defaults."""
    response = await client.get("/api/v1/config/scoring")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Should have default weights initialized
    assert len(data) > 0
