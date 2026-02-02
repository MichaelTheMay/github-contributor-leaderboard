# GitHub Contributor Leaderboard

A comprehensive system for scraping, scoring, and ranking GitHub contributors across multiple repositories with social media enrichment capabilities.

## Features

- **Multi-Repository Tracking**: Track contribution activity across any number of public GitHub repositories
- **Weighted Scoring**: Configurable scoring system for commits, PRs, reviews, issues, and comments
- **Dual Leaderboards**: Per-repository rankings and global aggregate leaderboard
- **Profile Enrichment**: Automatic discovery of contributor social media profiles and contact information
- **BigQuery Integration**: Efficient historical data retrieval from GitHub Archive
- **Real-time Updates**: Webhook support for instant contribution tracking

## Technology Stack

| Component | Technology |
|-----------|------------|
| API | Python FastAPI |
| Database | PostgreSQL 15+ |
| Cache/Queue | Redis |
| Job Processing | Celery |
| Historical Data | Google BigQuery |
| Real-time Data | GitHub REST API |

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- GitHub Personal Access Token
- Google Cloud Project with BigQuery access

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/github-contributor-leaderboard.git
cd github-contributor-leaderboard
```

2. Create a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -e ".[dev]"
```

4. Copy environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. Run database migrations:
```bash
alembic upgrade head
```

6. Start the development server:
```bash
uvicorn src.api.app:app --reload
```

### Docker Deployment

```bash
cd docker
docker-compose up -d
```

## API Endpoints

### Repository Management
- `POST /api/v1/repositories` - Add a repository to track
- `GET /api/v1/repositories` - List all tracked repositories
- `GET /api/v1/repositories/{owner}/{name}` - Get repository details
- `DELETE /api/v1/repositories/{owner}/{name}` - Remove repository
- `POST /api/v1/repositories/{owner}/{name}/refresh` - Trigger data refresh

### Leaderboards
- `GET /api/v1/leaderboard/global` - Global leaderboard
- `GET /api/v1/leaderboard/{owner}/{name}` - Repository leaderboard
- `GET /api/v1/leaderboard/compare` - Compare multiple repositories

### Contributors
- `GET /api/v1/contributors/{username}` - Full contributor profile
- `GET /api/v1/contributors/{username}/activity` - Contribution history
- `GET /api/v1/contributors/{username}/repositories` - Per-repo breakdown
- `POST /api/v1/contributors/{username}/enrich` - Trigger enrichment

### Configuration
- `GET /api/v1/config/scoring` - Get scoring weights
- `PUT /api/v1/config/scoring` - Update scoring weights

## Scoring System

Default scoring weights:

| Event Type | Points |
|------------|--------|
| Release Published | 30 |
| PR Merged | 25 |
| PR Reviewed | 20 |
| PR Opened | 15 |
| Commit | 10 + line bonus |
| Issue Opened | 8 |
| Issue Closed | 5 |
| Comment | 3 |

Line bonus: `+0.1` per line added, `+0.05` per line deleted

## Project Structure

```
github-contributor-leaderboard/
├── src/
│   ├── api/              # FastAPI application
│   │   ├── routes/       # API endpoints
│   │   └── schemas/      # Pydantic models
│   ├── core/             # Configuration
│   ├── db/               # Database layer
│   │   ├── models/       # SQLAlchemy models
│   │   └── repositories/ # Data access
│   ├── services/         # Business logic
│   ├── workers/          # Celery tasks
│   └── enrichment/       # Profile enrichment
├── tests/
│   ├── unit/
│   └── integration/
├── migrations/           # Alembic migrations
├── docker/               # Docker configuration
└── scripts/              # Utility scripts
```

## Development

### Running Tests

```bash
pytest
```

### Code Quality

```bash
# Linting
ruff check .

# Type checking
mypy src

# Format code
ruff format .
```

## License

MIT License - see LICENSE file for details.
