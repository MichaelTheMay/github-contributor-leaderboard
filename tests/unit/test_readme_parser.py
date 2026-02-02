import pytest

from src.enrichment.readme_parser import ReadmeParser


class TestReadmeParser:
    """Tests for README social link parsing."""

    @pytest.fixture
    def parser(self) -> ReadmeParser:
        return ReadmeParser()

    def test_parse_twitter_handle(self, parser: ReadmeParser) -> None:
        readme = "Follow me on Twitter: https://twitter.com/johndoe"
        result = parser.parse(readme)
        assert result.twitter == "johndoe"

    def test_parse_x_handle(self, parser: ReadmeParser) -> None:
        readme = "Follow me on X: https://x.com/janedoe"
        result = parser.parse(readme)
        assert result.twitter == "janedoe"

    def test_parse_linkedin_url(self, parser: ReadmeParser) -> None:
        readme = "Connect on LinkedIn: https://linkedin.com/in/john-doe-123"
        result = parser.parse(readme)
        assert result.linkedin == "https://linkedin.com/in/john-doe-123"

    def test_parse_email(self, parser: ReadmeParser) -> None:
        readme = "Contact me at: hello@example.com"
        result = parser.parse(readme)
        assert result.email == "hello@example.com"

    def test_exclude_github_noreply_email(self, parser: ReadmeParser) -> None:
        readme = "Email: noreply@github.com"
        result = parser.parse(readme)
        assert result.email is None

    def test_parse_website_from_badge(self, parser: ReadmeParser) -> None:
        readme = "[website](https://johndoe.dev)"
        result = parser.parse(readme)
        assert result.website == "https://johndoe.dev"

    def test_parse_mastodon_handle(self, parser: ReadmeParser) -> None:
        readme = "Find me on Mastodon: @john@mastodon.social"
        result = parser.parse(readme)
        assert result.mastodon == "@john@mastodon.social"

    def test_parse_dev_to_username(self, parser: ReadmeParser) -> None:
        readme = "Read my posts: https://dev.to/johndoe"
        result = parser.parse(readme)
        assert result.dev_to == "johndoe"

    def test_parse_youtube_channel(self, parser: ReadmeParser) -> None:
        readme = "Watch: https://youtube.com/@coding_channel"
        result = parser.parse(readme)
        assert result.youtube == "coding_channel"

    def test_parse_substack(self, parser: ReadmeParser) -> None:
        readme = "Subscribe: https://johndoe.substack.com"
        result = parser.parse(readme)
        assert result.substack == "https://johndoe.substack.com"

    def test_empty_readme(self, parser: ReadmeParser) -> None:
        result = parser.parse("")
        assert result.twitter is None
        assert result.linkedin is None
        assert result.email is None

    def test_multiple_links(self, parser: ReadmeParser) -> None:
        readme = """
        # John Doe

        - Twitter: https://twitter.com/johndoe
        - LinkedIn: https://linkedin.com/in/johndoe
        - Blog: https://johndoe.dev
        - Email: john@example.com
        """
        result = parser.parse(readme)
        assert result.twitter == "johndoe"
        assert result.linkedin == "https://linkedin.com/in/johndoe"
        assert result.website == "https://johndoe.dev"
        assert result.email == "john@example.com"
