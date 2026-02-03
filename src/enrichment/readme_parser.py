import re
from dataclasses import dataclass, field


@dataclass
class ParsedSocialLinks:
    """Parsed social links extracted from README content."""

    # Original fields
    twitter: str | None = None
    linkedin: str | None = None
    website: str | None = None
    email: str | None = None
    discord: str | None = None
    mastodon: str | None = None
    youtube: str | None = None
    dev_to: str | None = None
    medium: str | None = None
    substack: str | None = None

    # Additional social platforms
    bluesky: str | None = None
    threads: str | None = None
    instagram: str | None = None
    facebook: str | None = None
    reddit: str | None = None
    hackernews: str | None = None
    stackoverflow: str | None = None
    kaggle: str | None = None
    twitch: str | None = None
    tiktok: str | None = None

    # Professional/developer platforms
    npm: str | None = None
    pypi: str | None = None
    gitlab: str | None = None
    bitbucket: str | None = None
    codepen: str | None = None
    dribbble: str | None = None
    behance: str | None = None

    # Communication platforms
    telegram: str | None = None
    keybase: str | None = None
    matrix: str | None = None

    # GitHub-specific
    sponsors: str | None = None

    # Multiple values
    additional_emails: list[str] = field(default_factory=list)
    additional_websites: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary, excluding None values and empty lists."""
        result = {}
        for key, value in self.__dict__.items():
            if value is not None:
                if isinstance(value, list) and len(value) == 0:
                    continue
                result[key] = value
        return result

    def count_found(self) -> int:
        """Count how many links were found."""
        count = 0
        for key, value in self.__dict__.items():
            if key.startswith("additional_"):
                continue
            if value is not None:
                count += 1
        count += len(self.additional_emails)
        count += len(self.additional_websites)
        return count


class ReadmeParser:
    """Parser for extracting social links from GitHub profile READMEs."""

    # Patterns for common badge formats and social links
    PATTERNS = {
        # Twitter/X
        "twitter": [
            r"twitter\.com/([a-zA-Z0-9_]+)",
            r"x\.com/([a-zA-Z0-9_]+)",
            r"\[.*twitter.*\]\(https?://(?:twitter|x)\.com/([a-zA-Z0-9_]+)\)",
        ],
        # LinkedIn
        "linkedin": [
            r"linkedin\.com/in/([a-zA-Z0-9_-]+)",
            r"\[.*linkedin.*\]\(https?://(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_-]+)\)",
        ],
        # Website/blog
        "website": [
            r"\[(?:website|blog|portfolio|homepage|site)\]\((https?://[^\)]+)\)",
            r"(?:website|blog|portfolio|homepage):\s*(https?://\S+)",
        ],
        # Email
        "email": [
            r"[\w\.-]+@[\w\.-]+\.\w+",
            r"mailto:([\w\.-]+@[\w\.-]+\.\w+)",
        ],
        # Discord
        "discord": [
            r"discord(?:\.gg|app\.com/users)/([a-zA-Z0-9_]+)",
            r"discord:\s*([a-zA-Z0-9_#]+)",
        ],
        # Mastodon
        "mastodon": [
            r"@([a-zA-Z0-9_]+)@([a-zA-Z0-9_.-]+\.[a-zA-Z]+)",
            r"(https?://[a-zA-Z0-9_.-]+/@[a-zA-Z0-9_]+)",
        ],
        # YouTube
        "youtube": [
            r"youtube\.com/(?:c/|channel/|@)([a-zA-Z0-9_-]+)",
            r"\[.*youtube.*\]\((https?://(?:www\.)?youtube\.com/[^\)]+)\)",
        ],
        # dev.to
        "dev_to": [
            r"dev\.to/([a-zA-Z0-9_]+)",
        ],
        # Medium
        "medium": [
            r"medium\.com/@([a-zA-Z0-9_]+)",
            r"([a-zA-Z0-9_]+)\.medium\.com",
        ],
        # Substack
        "substack": [
            r"([a-zA-Z0-9_-]+)\.substack\.com",
        ],
        # Bluesky
        "bluesky": [
            r"bsky\.app/profile/([a-zA-Z0-9_.-]+)",
            r"@([a-zA-Z0-9_.-]+)\.bsky\.social",
            r"([a-zA-Z0-9_.-]+)\.bsky\.social",
        ],
        # Threads
        "threads": [
            r"threads\.net/@?([a-zA-Z0-9_]+)",
        ],
        # Instagram
        "instagram": [
            r"instagram\.com/([a-zA-Z0-9_\.]+)",
        ],
        # Facebook
        "facebook": [
            r"facebook\.com/([a-zA-Z0-9_.]+)",
            r"fb\.com/([a-zA-Z0-9_.]+)",
        ],
        # Reddit
        "reddit": [
            r"reddit\.com/u(?:ser)?/([a-zA-Z0-9_-]+)",
        ],
        # Hacker News
        "hackernews": [
            r"news\.ycombinator\.com/user\?id=([a-zA-Z0-9_]+)",
        ],
        # Stack Overflow
        "stackoverflow": [
            r"stackoverflow\.com/users/(\d+(?:/[a-zA-Z0-9_-]+)?)",
        ],
        # Kaggle
        "kaggle": [
            r"kaggle\.com/([a-zA-Z0-9_]+)",
        ],
        # Twitch
        "twitch": [
            r"twitch\.tv/([a-zA-Z0-9_]+)",
        ],
        # TikTok
        "tiktok": [
            r"tiktok\.com/@([a-zA-Z0-9_\.]+)",
        ],
        # npm
        "npm": [
            r"npmjs\.com/~([a-zA-Z0-9_-]+)",
            r"npm\.im/([a-zA-Z0-9_-]+)",
        ],
        # PyPI
        "pypi": [
            r"pypi\.org/user/([a-zA-Z0-9_-]+)",
        ],
        # GitLab
        "gitlab": [
            r"gitlab\.com/([a-zA-Z0-9_-]+)",
        ],
        # Bitbucket
        "bitbucket": [
            r"bitbucket\.org/([a-zA-Z0-9_-]+)",
        ],
        # CodePen
        "codepen": [
            r"codepen\.io/([a-zA-Z0-9_-]+)",
        ],
        # Dribbble
        "dribbble": [
            r"dribbble\.com/([a-zA-Z0-9_-]+)",
        ],
        # Behance
        "behance": [
            r"behance\.net/([a-zA-Z0-9_-]+)",
        ],
        # Telegram
        "telegram": [
            r"t\.me/([a-zA-Z0-9_]+)",
            r"telegram\.me/([a-zA-Z0-9_]+)",
        ],
        # Keybase
        "keybase": [
            r"keybase\.io/([a-zA-Z0-9_]+)",
        ],
        # Matrix
        "matrix": [
            r"matrix\.to/#/@([a-zA-Z0-9_]+:[a-zA-Z0-9_.-]+)",
            r"@([a-zA-Z0-9_]+:[a-zA-Z0-9_.-]+)",
        ],
        # GitHub Sponsors
        "sponsors": [
            r"github\.com/sponsors/([a-zA-Z0-9_-]+)",
        ],
        # Generic URL extraction for additional websites
        "generic_url": [
            r"\[(?:website|blog|homepage|portfolio|site)\]\((https?://[^\)]+)\)",
            r"(?:^|\s)(https?://(?!(?:github|twitter|linkedin|facebook|instagram|youtube|medium|dev\.to)[^\s]*)[^\s]+)",
        ],
    }

    # Exclude common false positives
    EMAIL_EXCLUDES = [
        "noreply@github.com",
        "action@github.com",
        "notifications@github.com",
        "example@example.com",
        "your@email.com",
        "email@example.com",
        "test@test.com",
    ]

    # URL excludes for generic website extraction
    URL_EXCLUDES = [
        "shields.io",
        "img.shields.io",
        "badge",
        "github.com",
        "githubusercontent.com",
        "twitter.com",
        "linkedin.com",
        "facebook.com",
        "instagram.com",
        "youtube.com",
        "medium.com",
        "dev.to",
        "discord",
    ]

    def parse(self, readme_content: str) -> ParsedSocialLinks:
        """Parse README content for social media links."""
        if not readme_content:
            return ParsedSocialLinks()

        result = ParsedSocialLinks()

        # Twitter/X
        result.twitter = self._extract_first("twitter", readme_content)

        # LinkedIn
        linkedin = self._extract_first("linkedin", readme_content)
        if linkedin:
            result.linkedin = f"https://linkedin.com/in/{linkedin}"

        # Website
        result.website = self._extract_first("website", readme_content)

        # Email (with filtering)
        emails = self._extract_all_emails(readme_content)
        if emails:
            result.email = emails[0]
            if len(emails) > 1:
                result.additional_emails = emails[1:]

        # Discord
        result.discord = self._extract_first("discord", readme_content)

        # Mastodon (special handling for format)
        result.mastodon = self._extract_mastodon(readme_content)

        # YouTube
        result.youtube = self._extract_first("youtube", readme_content)

        # dev.to
        result.dev_to = self._extract_first("dev_to", readme_content)

        # Medium
        result.medium = self._extract_first("medium", readme_content)

        # Substack
        substack = self._extract_first("substack", readme_content)
        if substack:
            result.substack = f"https://{substack}.substack.com"

        # Bluesky
        result.bluesky = self._extract_first("bluesky", readme_content)

        # Threads
        result.threads = self._extract_first("threads", readme_content)

        # Instagram
        result.instagram = self._extract_first("instagram", readme_content)

        # Facebook
        facebook = self._extract_first("facebook", readme_content)
        if facebook:
            result.facebook = f"https://facebook.com/{facebook}"

        # Reddit
        result.reddit = self._extract_first("reddit", readme_content)

        # Hacker News
        result.hackernews = self._extract_first("hackernews", readme_content)

        # Stack Overflow
        so = self._extract_first("stackoverflow", readme_content)
        if so:
            result.stackoverflow = f"https://stackoverflow.com/users/{so}"

        # Kaggle
        result.kaggle = self._extract_first("kaggle", readme_content)

        # Twitch
        result.twitch = self._extract_first("twitch", readme_content)

        # TikTok
        result.tiktok = self._extract_first("tiktok", readme_content)

        # npm
        result.npm = self._extract_first("npm", readme_content)

        # PyPI
        result.pypi = self._extract_first("pypi", readme_content)

        # GitLab
        result.gitlab = self._extract_first("gitlab", readme_content)

        # Bitbucket
        result.bitbucket = self._extract_first("bitbucket", readme_content)

        # CodePen
        result.codepen = self._extract_first("codepen", readme_content)

        # Dribbble
        result.dribbble = self._extract_first("dribbble", readme_content)

        # Behance
        result.behance = self._extract_first("behance", readme_content)

        # Telegram
        result.telegram = self._extract_first("telegram", readme_content)

        # Keybase
        result.keybase = self._extract_first("keybase", readme_content)

        # Matrix
        result.matrix = self._extract_first("matrix", readme_content)

        # GitHub Sponsors
        result.sponsors = self._extract_first("sponsors", readme_content)

        # Extract additional websites
        result.additional_websites = self._extract_additional_websites(readme_content)

        return result

    def _extract_first(self, platform: str, content: str) -> str | None:
        """Extract first match for a platform."""
        patterns = self.PATTERNS.get(platform, [])
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _extract_all_emails(self, content: str) -> list[str]:
        """Extract all valid emails from content."""
        emails = []
        for pattern in self.PATTERNS["email"]:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for email in matches:
                email_lower = email.lower()
                if email_lower not in self.EMAIL_EXCLUDES and email_lower not in emails:
                    emails.append(email)
        return emails

    def _extract_mastodon(self, content: str) -> str | None:
        """Extract Mastodon handle with special formatting."""
        for pattern in self.PATTERNS["mastodon"]:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                if match.lastindex and match.lastindex >= 2:
                    return f"@{match.group(1)}@{match.group(2)}"
                else:
                    return match.group(1)
        return None

    def _extract_additional_websites(self, content: str) -> list[str]:
        """Extract additional website URLs that don't match known platforms."""
        websites = []
        # Find all URLs in markdown links
        url_pattern = r"https?://[^\s\)\]<>\"']+"
        all_urls = re.findall(url_pattern, content, re.IGNORECASE)

        for url in all_urls:
            url_lower = url.lower()
            # Skip if it matches any exclude pattern
            if any(exclude in url_lower for exclude in self.URL_EXCLUDES):
                continue
            # Skip if already in list
            if url not in websites:
                websites.append(url)

        # Limit to first 10 to avoid noise
        return websites[:10]
