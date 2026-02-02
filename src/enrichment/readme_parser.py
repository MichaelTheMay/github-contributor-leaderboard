import re
from dataclasses import dataclass


@dataclass
class ParsedSocialLinks:
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


class ReadmeParser:
    """Parser for extracting social links from GitHub profile READMEs."""

    # Patterns for common badge formats
    PATTERNS = {
        "twitter": [
            r"twitter\.com/([a-zA-Z0-9_]+)",
            r"x\.com/([a-zA-Z0-9_]+)",
            r"\[.*twitter.*\]\(https?://(?:twitter|x)\.com/([a-zA-Z0-9_]+)\)",
        ],
        "linkedin": [
            r"linkedin\.com/in/([a-zA-Z0-9_-]+)",
            r"\[.*linkedin.*\]\(https?://(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_-]+)\)",
        ],
        "website": [
            r"\[(?:website|blog|portfolio)\]\((https?://[^\)]+)\)",
            r"(?:website|blog|portfolio):\s*(https?://\S+)",
        ],
        "email": [
            r"[\w\.-]+@[\w\.-]+\.\w+",
            r"mailto:([\w\.-]+@[\w\.-]+\.\w+)",
        ],
        "discord": [
            r"discord(?:\.gg|app\.com/users)/([a-zA-Z0-9_]+)",
            r"discord:\s*([a-zA-Z0-9_#]+)",
        ],
        "mastodon": [
            r"@([a-zA-Z0-9_]+)@([a-zA-Z0-9_.-]+\.[a-zA-Z]+)",
            r"(https?://[a-zA-Z0-9_.-]+/@[a-zA-Z0-9_]+)",
        ],
        "youtube": [
            r"youtube\.com/(?:c/|channel/|@)([a-zA-Z0-9_-]+)",
            r"\[.*youtube.*\]\((https?://(?:www\.)?youtube\.com/[^\)]+)\)",
        ],
        "dev_to": [
            r"dev\.to/([a-zA-Z0-9_]+)",
        ],
        "medium": [
            r"medium\.com/@([a-zA-Z0-9_]+)",
            r"([a-zA-Z0-9_]+)\.medium\.com",
        ],
        "substack": [
            r"([a-zA-Z0-9_-]+)\.substack\.com",
        ],
    }

    # Exclude common false positives
    EMAIL_EXCLUDES = [
        "noreply@github.com",
        "action@github.com",
        "notifications@github.com",
        "example@example.com",
    ]

    def parse(self, readme_content: str) -> ParsedSocialLinks:
        """Parse README content for social media links."""
        if not readme_content:
            return ParsedSocialLinks()

        content_lower = readme_content.lower()
        result = ParsedSocialLinks()

        # Twitter/X
        for pattern in self.PATTERNS["twitter"]:
            match = re.search(pattern, readme_content, re.IGNORECASE)
            if match:
                result.twitter = match.group(1)
                break

        # LinkedIn
        for pattern in self.PATTERNS["linkedin"]:
            match = re.search(pattern, readme_content, re.IGNORECASE)
            if match:
                result.linkedin = f"https://linkedin.com/in/{match.group(1)}"
                break

        # Website
        for pattern in self.PATTERNS["website"]:
            match = re.search(pattern, readme_content, re.IGNORECASE)
            if match:
                result.website = match.group(1)
                break

        # Email (with filtering)
        for pattern in self.PATTERNS["email"]:
            matches = re.findall(pattern, readme_content, re.IGNORECASE)
            for email in matches:
                if email.lower() not in self.EMAIL_EXCLUDES:
                    result.email = email
                    break
            if result.email:
                break

        # Discord
        for pattern in self.PATTERNS["discord"]:
            match = re.search(pattern, readme_content, re.IGNORECASE)
            if match:
                result.discord = match.group(1)
                break

        # Mastodon
        for pattern in self.PATTERNS["mastodon"]:
            match = re.search(pattern, readme_content, re.IGNORECASE)
            if match:
                if match.lastindex and match.lastindex >= 2:
                    result.mastodon = f"@{match.group(1)}@{match.group(2)}"
                else:
                    result.mastodon = match.group(1)
                break

        # YouTube
        for pattern in self.PATTERNS["youtube"]:
            match = re.search(pattern, readme_content, re.IGNORECASE)
            if match:
                result.youtube = match.group(1)
                break

        # dev.to
        for pattern in self.PATTERNS["dev_to"]:
            match = re.search(pattern, readme_content, re.IGNORECASE)
            if match:
                result.dev_to = match.group(1)
                break

        # Medium
        for pattern in self.PATTERNS["medium"]:
            match = re.search(pattern, readme_content, re.IGNORECASE)
            if match:
                result.medium = match.group(1)
                break

        # Substack
        for pattern in self.PATTERNS["substack"]:
            match = re.search(pattern, readme_content, re.IGNORECASE)
            if match:
                result.substack = f"https://{match.group(1)}.substack.com"
                break

        return result
