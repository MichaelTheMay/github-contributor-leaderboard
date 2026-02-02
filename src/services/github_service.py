import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import settings

logger = structlog.get_logger()


class GitHubService:
    """Service for interacting with the GitHub API."""

    def __init__(self) -> None:
        self.base_url = settings.github_api_base_url
        self.headers = {
            "Authorization": f"token {settings.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def get_repository(self, owner: str, name: str) -> dict | None:
        """Fetch repository details from GitHub API."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/repos/{owner}/{name}",
                headers=self.headers,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def get_user(self, username: str) -> dict | None:
        """Fetch user details from GitHub API."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/users/{username}",
                headers=self.headers,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def get_user_readme(self, username: str) -> str | None:
        """Fetch user profile README content."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/repos/{username}/{username}/readme",
                headers={**self.headers, "Accept": "application/vnd.github.raw"},
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.text

    async def get_rate_limit(self) -> dict:
        """Check current rate limit status."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/rate_limit",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def get_commits(
        self,
        owner: str,
        name: str,
        author: str | None = None,
        since: str | None = None,
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict]:
        """Fetch commits for a repository."""
        params: dict = {"per_page": per_page, "page": page}
        if author:
            params["author"] = author
        if since:
            params["since"] = since

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/repos/{owner}/{name}/commits",
                headers=self.headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def get_pull_requests(
        self,
        owner: str,
        name: str,
        state: str = "all",
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict]:
        """Fetch pull requests for a repository."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/repos/{owner}/{name}/pulls",
                headers=self.headers,
                params={"state": state, "per_page": per_page, "page": page},
            )
            response.raise_for_status()
            return response.json()
