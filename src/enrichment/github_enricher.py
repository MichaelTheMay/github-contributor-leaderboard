import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.enrichment import ContributorEnrichment, EnrichmentStatus
from src.db.models.user import GitHubUser
from src.enrichment.readme_parser import ReadmeParser
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

        sources_found = []

        try:
            # Fetch GitHub profile
            profile = await self.github.get_user(user.username)
            if profile:
                sources_found.append("github_profile")

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

                # Extract Twitter from profile
                if profile.get("twitter_username"):
                    enrichment.twitter_username = profile["twitter_username"]
                    enrichment.twitter_url = (
                        f"https://twitter.com/{profile['twitter_username']}"
                    )

                # Extract blog/website
                if profile.get("blog"):
                    enrichment.personal_website = profile["blog"]

            # Fetch and parse profile README
            readme = await self.github.get_user_readme(user.username)
            if readme:
                sources_found.append("profile_readme")

                parsed = self.readme_parser.parse(readme)

                # Update enrichment with parsed data (don't overwrite existing)
                if parsed.twitter and not enrichment.twitter_username:
                    enrichment.twitter_username = parsed.twitter
                    enrichment.twitter_url = f"https://twitter.com/{parsed.twitter}"

                if parsed.linkedin and not enrichment.linkedin_url:
                    enrichment.linkedin_url = parsed.linkedin

                if parsed.website and not enrichment.personal_website:
                    enrichment.personal_website = parsed.website

                if parsed.email and not enrichment.personal_email:
                    enrichment.personal_email = parsed.email

                if parsed.discord and not enrichment.discord_username:
                    enrichment.discord_username = parsed.discord

                if parsed.mastodon and not enrichment.mastodon_handle:
                    enrichment.mastodon_handle = parsed.mastodon

                if parsed.youtube and not enrichment.youtube_channel:
                    enrichment.youtube_channel = parsed.youtube

                if parsed.dev_to and not enrichment.dev_to_username:
                    enrichment.dev_to_username = parsed.dev_to

                if parsed.medium and not enrichment.medium_username:
                    enrichment.medium_username = parsed.medium

                if parsed.substack and not enrichment.substack_url:
                    enrichment.substack_url = parsed.substack

            # Update enrichment status
            enrichment.enrichment_sources = {"sources": sources_found}
            enrichment.enrichment_status = (
                EnrichmentStatus.PARTIAL if sources_found else EnrichmentStatus.PENDING
            )

            logger.info(
                "GitHub enrichment completed",
                username=user.username,
                sources=sources_found,
            )

        except Exception as e:
            logger.error(
                "GitHub enrichment failed",
                username=user.username,
                error=str(e),
            )
            enrichment.enrichment_status = EnrichmentStatus.FAILED

        return enrichment
