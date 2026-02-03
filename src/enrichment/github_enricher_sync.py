"""Synchronous GitHub enricher for Celery workers.

This module provides a synchronous version of GitHubEnricher for use in Celery
workers, which run in separate processes without an asyncio event loop.
"""

from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import settings
from src.db.models.enrichment import ContributorEnrichment, EnrichmentStatus
from src.db.models.user import GitHubUser
from src.enrichment.readme_parser import ParsedSocialLinks, ReadmeParser

logger = structlog.get_logger()


class GitHubServiceSync:
    """Synchronous GitHub API client for Celery workers."""

    def __init__(self) -> None:
        self.base_url = settings.github_api_base_url
        self.headers = {
            "Authorization": f"token {settings.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        self.timeout = httpx.Timeout(30.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_user(self, username: str) -> dict | None:
        """Fetch user details from GitHub API."""
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(
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
    def get_user_readme(self, username: str) -> str | None:
        """Fetch user profile README content."""
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(
                f"{self.base_url}/repos/{username}/{username}/readme",
                headers={**self.headers, "Accept": "application/vnd.github.raw"},
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.text

    def get_rate_limit(self) -> dict:
        """Check current rate limit status."""
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(
                f"{self.base_url}/rate_limit",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()


class GitHubEnricherSync:
    """Synchronous enricher for use in Celery workers."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.github = GitHubServiceSync()
        self.readme_parser = ReadmeParser()

    def enrich_user(self, user: GitHubUser) -> ContributorEnrichment:
        """
        Enrich a user's profile with GitHub data.

        Steps:
        1. Fetch GitHub profile
        2. Fetch profile README
        3. Parse README for social links
        4. Update enrichment record
        """
        logger.info("Enriching user from GitHub (sync)", username=user.username)

        # Get or create enrichment record
        enrichment = (
            self.db.query(ContributorEnrichment)
            .filter(ContributorEnrichment.user_id == user.id)
            .first()
        )
        if not enrichment:
            enrichment = ContributorEnrichment(user_id=user.id)
            self.db.add(enrichment)
            self.db.flush()

        # Track enrichment attempts
        enrichment.enrichment_attempts = (enrichment.enrichment_attempts or 0) + 1
        enrichment.last_error = None

        sources_found = []

        try:
            # Fetch GitHub profile
            profile = self.github.get_user(user.username)
            if profile:
                sources_found.append("github_profile")
                self._update_from_profile(user, enrichment, profile)

            # Fetch and parse profile README
            readme = self.github.get_user_readme(user.username)
            if readme:
                sources_found.append("profile_readme")
                parsed = self.readme_parser.parse(readme)
                self._update_from_readme(enrichment, parsed)

            # Update enrichment status
            enrichment.enrichment_sources = {"sources": sources_found}
            enrichment.last_enriched_at = datetime.now(timezone.utc)

            if sources_found:
                # Check how many fields were populated
                counts = enrichment.count_sources_found()
                if counts["total"] >= 3:
                    enrichment.enrichment_status = EnrichmentStatus.COMPLETE
                else:
                    enrichment.enrichment_status = EnrichmentStatus.PARTIAL
            else:
                enrichment.enrichment_status = EnrichmentStatus.PENDING

            logger.info(
                "GitHub enrichment completed (sync)",
                username=user.username,
                sources=sources_found,
                fields_found=enrichment.count_sources_found(),
            )

        except Exception as e:
            logger.error(
                "GitHub enrichment failed (sync)",
                username=user.username,
                error=str(e),
            )
            enrichment.enrichment_status = EnrichmentStatus.FAILED
            enrichment.last_error = str(e)

        return enrichment

    def _update_from_profile(
        self,
        user: GitHubUser,
        enrichment: ContributorEnrichment,
        profile: dict,
    ) -> None:
        """Update user and enrichment from GitHub profile data."""
        # Update user record with fresh data
        user.display_name = profile.get("name")
        user.avatar_url = profile.get("avatar_url")
        user.profile_url = profile.get("html_url")
        user.email = profile.get("email")
        user.company = profile.get("company")
        user.location = profile.get("location")
        user.bio = profile.get("bio")
        user.followers = profile.get("followers", 0)
        user.public_repos = profile.get("public_repos", 0)

        # Store GitHub-specific data in enrichment
        enrichment.github_bio = profile.get("bio")
        enrichment.github_company = profile.get("company")
        enrichment.github_location = profile.get("location")
        enrichment.github_hireable = profile.get("hireable")
        enrichment.github_followers = profile.get("followers")
        enrichment.github_following = profile.get("following")
        enrichment.github_public_repos = profile.get("public_repos")

        # Parse created_at
        created_at_str = profile.get("created_at")
        if created_at_str:
            try:
                enrichment.github_created_at = datetime.fromisoformat(
                    created_at_str.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        # Extract Twitter from profile
        if profile.get("twitter_username"):
            enrichment.twitter_username = profile["twitter_username"]
            enrichment.twitter_url = f"https://twitter.com/{profile['twitter_username']}"

        # Extract blog/website
        if profile.get("blog"):
            enrichment.personal_website = profile["blog"]

        # Extract email from profile
        if profile.get("email") and not enrichment.personal_email:
            enrichment.personal_email = profile["email"]

    def _update_from_readme(
        self,
        enrichment: ContributorEnrichment,
        parsed: ParsedSocialLinks,
    ) -> None:
        """Update enrichment from parsed README data (don't overwrite existing)."""
        # Twitter
        if parsed.twitter and not enrichment.twitter_username:
            enrichment.twitter_username = parsed.twitter
            enrichment.twitter_url = f"https://twitter.com/{parsed.twitter}"

        # LinkedIn
        if parsed.linkedin and not enrichment.linkedin_url:
            enrichment.linkedin_url = parsed.linkedin

        # Website
        if parsed.website and not enrichment.personal_website:
            enrichment.personal_website = parsed.website

        # Email
        if parsed.email and not enrichment.personal_email:
            enrichment.personal_email = parsed.email

        # Additional emails
        if parsed.additional_emails:
            existing = enrichment.additional_emails or []
            new_emails = [e for e in parsed.additional_emails if e not in existing]
            if new_emails:
                enrichment.additional_emails = existing + new_emails

        # Discord
        if parsed.discord and not enrichment.discord_username:
            enrichment.discord_username = parsed.discord

        # Mastodon
        if parsed.mastodon and not enrichment.mastodon_handle:
            enrichment.mastodon_handle = parsed.mastodon

        # YouTube
        if parsed.youtube and not enrichment.youtube_channel:
            enrichment.youtube_channel = parsed.youtube

        # dev.to
        if parsed.dev_to and not enrichment.dev_to_username:
            enrichment.dev_to_username = parsed.dev_to

        # Medium
        if parsed.medium and not enrichment.medium_username:
            enrichment.medium_username = parsed.medium

        # Substack
        if parsed.substack and not enrichment.substack_url:
            enrichment.substack_url = parsed.substack

        # Bluesky
        if parsed.bluesky and not enrichment.bluesky_handle:
            enrichment.bluesky_handle = parsed.bluesky

        # Threads
        if parsed.threads and not enrichment.threads_username:
            enrichment.threads_username = parsed.threads

        # Instagram
        if parsed.instagram and not enrichment.instagram_username:
            enrichment.instagram_username = parsed.instagram

        # Facebook
        if parsed.facebook and not enrichment.facebook_url:
            enrichment.facebook_url = parsed.facebook

        # Reddit
        if parsed.reddit and not enrichment.reddit_username:
            enrichment.reddit_username = parsed.reddit

        # Hacker News
        if parsed.hackernews and not enrichment.hackernews_username:
            enrichment.hackernews_username = parsed.hackernews

        # Stack Overflow
        if parsed.stackoverflow and not enrichment.stackoverflow_url:
            enrichment.stackoverflow_url = parsed.stackoverflow

        # Kaggle
        if parsed.kaggle and not enrichment.kaggle_username:
            enrichment.kaggle_username = parsed.kaggle

        # Twitch
        if parsed.twitch and not enrichment.twitch_username:
            enrichment.twitch_username = parsed.twitch

        # TikTok
        if parsed.tiktok and not enrichment.tiktok_username:
            enrichment.tiktok_username = parsed.tiktok

        # npm
        if parsed.npm and not enrichment.npm_username:
            enrichment.npm_username = parsed.npm

        # PyPI
        if parsed.pypi and not enrichment.pypi_username:
            enrichment.pypi_username = parsed.pypi

        # GitLab
        if parsed.gitlab and not enrichment.gitlab_username:
            enrichment.gitlab_username = parsed.gitlab

        # Bitbucket
        if parsed.bitbucket and not enrichment.bitbucket_username:
            enrichment.bitbucket_username = parsed.bitbucket

        # CodePen
        if parsed.codepen and not enrichment.codepen_username:
            enrichment.codepen_username = parsed.codepen

        # Dribbble
        if parsed.dribbble and not enrichment.dribbble_username:
            enrichment.dribbble_username = parsed.dribbble

        # Behance
        if parsed.behance and not enrichment.behance_username:
            enrichment.behance_username = parsed.behance

        # Telegram
        if parsed.telegram and not enrichment.telegram_username:
            enrichment.telegram_username = parsed.telegram

        # Keybase
        if parsed.keybase and not enrichment.keybase_username:
            enrichment.keybase_username = parsed.keybase

        # Matrix
        if parsed.matrix and not enrichment.matrix_handle:
            enrichment.matrix_handle = parsed.matrix

        # GitHub Sponsors
        if parsed.sponsors and not enrichment.github_sponsors_url:
            enrichment.github_sponsors_url = f"https://github.com/sponsors/{parsed.sponsors}"

        # Additional websites
        if parsed.additional_websites:
            existing = enrichment.additional_websites or []
            new_sites = [s for s in parsed.additional_websites if s not in existing]
            if new_sites:
                enrichment.additional_websites = existing + new_sites

        # Store all parsed data in raw format
        enrichment.social_links_raw = parsed.to_dict()
