"""Async GitHub enricher for FastAPI routes.

This module provides an asynchronous version of GitHubEnricher for use in
FastAPI routes with asyncpg.
"""

import contextlib
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.enrichment import ContributorEnrichment, EnrichmentStatus
from src.db.models.user import GitHubUser
from src.enrichment.readme_parser import ParsedSocialLinks, ReadmeParser
from src.services.github_service import GitHubService

logger = structlog.get_logger()


class GitHubEnricher:
    """Enricher that extracts data from GitHub profiles and READMEs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.github = GitHubService()
        self.readme_parser = ReadmeParser()

    async def enrich_user(self, user: GitHubUser) -> ContributorEnrichment:
        """
        Enrich a user's profile with GitHub data.

        Steps:
        1. Fetch GitHub profile
        2. Fetch profile README
        3. Parse README for social links
        4. Update enrichment record
        """
        logger.info("Enriching user from GitHub", username=user.username)

        # Get or create enrichment record
        enrichment = user.enrichment
        if not enrichment:
            enrichment = ContributorEnrichment(user_id=user.id)
            self.db.add(enrichment)

        # Track enrichment attempts
        enrichment.enrichment_attempts = (enrichment.enrichment_attempts or 0) + 1
        enrichment.last_error = None

        sources_found = []

        try:
            # Fetch GitHub profile
            profile = await self.github.get_user(user.username)
            if profile:
                sources_found.append("github_profile")
                self._update_from_profile(user, enrichment, profile)

            # Fetch and parse profile README
            readme = await self.github.get_user_readme(user.username)
            if readme:
                sources_found.append("profile_readme")
                parsed = self.readme_parser.parse(readme)
                self._update_from_readme(enrichment, parsed)

            # Update enrichment status
            enrichment.enrichment_sources = {"sources": sources_found}
            enrichment.last_enriched_at = datetime.now(UTC)

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
                "GitHub enrichment completed",
                username=user.username,
                sources=sources_found,
                fields_found=enrichment.count_sources_found(),
            )

        except Exception as e:
            logger.error(
                "GitHub enrichment failed",
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
            with contextlib.suppress(ValueError, TypeError):
                enrichment.github_created_at = datetime.fromisoformat(
                    created_at_str.replace("Z", "+00:00")
                )

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
