# GitHub Contributor Leaderboard

A comprehensive system for scraping, scoring, and ranking GitHub contributors across multiple repositories with social media enrichment capabilities.

![Dashboard Preview](docs/dashboard-preview.png)

## Features

- **Multi-Repository Tracking**: Track contribution activity across any number of public GitHub repositories
- **Weighted Scoring**: Configurable scoring system for commits, PRs, reviews, issues, and comments
- **Dual Leaderboards**: Per-repository rankings AND global master leaderboard aggregating all repos
- **Profile Enrichment**: Automatic discovery of contributor social media profiles and contact information
- **BigQuery Integration**: Efficient historical data retrieval from GitHub Archive (2011-present)
- **Real-time Monitoring Dashboard**: Live logs, job status, global & per-repo leaderboards
- **Background Processing**: Celery workers for async data ingestion and processing
- **Pagination**: All leaderboards support pagination to handle large datasets

## Architecture

See [docs/pipeline.md](docs/pipeline.md) for detailed Mermaid diagrams of the full data pipeline.

## Technology Stack

| Component | Technology |
|-----------|------------|
| API | Python FastAPI |
| Database | PostgreSQL 15+ |
| Cache/Queue | Redis |
| Job Processing | Celery |
| Historical Data | Google BigQuery (GitHub Archive) |
| Real-time Data | GitHub REST API |
| Monitoring | WebSocket-based live dashboard |

## Quick Start

### Prerequisites

- Python 3.11+
- Docker (for PostgreSQL and Redis)
- GitHub Personal Access Token
- Google Cloud Project with BigQuery access

### Installation

1. **Clone the repository:**
```bash
git clone https://github.com/MichaelTheMay/github-contributor-leaderboard.git
cd github-contributor-leaderboard
```

2. **Create a virtual environment:**
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. **Install dependencies:**
```bash
pip install -e ".[dev]"
```

4. **Set up environment variables:**
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. **Start PostgreSQL and Redis:**
```bash
docker run -d --name postgres-leaderboard \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=leaderboard \
  -p 5433:5432 postgres:15-alpine

docker run -d --name redis-leaderboard \
  -p 6379:6379 redis:7-alpine
```

6. **Initialize the database:**
```bash
python scripts/init_db.py
```

7. **Start the API server:**
```bash
uvicorn src.api.app:app --reload
```

8. **Open the dashboard:**
Navigate to http://localhost:8000 in your browser.

### Docker Deployment

```bash
cd docker
docker-compose up -d
```

### Cloud Deployment (GitHub Actions)

For fully automated operation via GitHub Actions:

1. **Set up a cloud PostgreSQL database** (see [docs/cloud-database-setup.md](docs/cloud-database-setup.md))
2. **Configure GitHub Secrets**:
   - `DATABASE_URL` - Cloud PostgreSQL connection string
   - `BIGQUERY_PROJECT` - Google Cloud project ID
   - `BIGQUERY_CREDENTIALS` - Service account JSON content
   - `GH_PAT` - GitHub Personal Access Token

The scheduled pipeline runs daily at 2 AM UTC and automatically:
- Refreshes stale repositories
- Recalculates leaderboards
- Enriches top 50 unenriched contributors

Manual actions available via **Actions > Scheduled Pipeline > Run workflow**:
- `full-pipeline` - Complete daily pipeline
- `enrich-top-contributors` - Enrich N users on demand
- `enrichment-backfill` - Backfill top N% of contributors

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `REDIS_URL` | Redis connection string | Yes |
| `GITHUB_TOKEN` | GitHub Personal Access Token | Yes |
| `BIGQUERY_PROJECT` | Google Cloud project ID | Yes |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to GCP service account JSON | Yes |

### GitHub Token Scopes

Create a Personal Access Token with these scopes:
- `repo` - Full control of private repositories
- `read:user` - Read user profile data
- `read:org` - Read organization membership

### BigQuery Setup

1. Create a Google Cloud project
2. Enable the BigQuery API
3. Create a service account with roles:
   - BigQuery User
   - BigQuery Job User
4. Download the service account JSON key

## Dashboards

### Monitoring Dashboard (`/dashboard`)

The monitoring dashboard provides real-time visibility into the system:

- **Live Statistics**: Active jobs, repository count, processed events, errors
- **Job Monitoring**: View all scrape jobs with status, progress, and timing
- **Repository List**: All tracked repositories with status indicators
- **Global Leaderboard**: View top contributors across all repositories
- **Live Logs**: WebSocket-powered real-time log streaming with filtering

### Pipeline Control (`/dashboard/pipeline`)

The pipeline control center lets you manage the entire data pipeline:

- **Add Repositories**: Track new GitHub repositories
- **Scrape Data**: Fetch contribution data from BigQuery
- **Calculate Scores**: Apply scoring formula to all entries
- **Aggregate Global**: Build master leaderboard from all repos
- **Enrichment**: Discover contributor social media profiles
- **Budget Tracking**: Monitor BigQuery usage and costs

### Quick Start Workflow

1. Navigate to **http://localhost:8000/dashboard/pipeline**
2. Add a repository (e.g., `pytorch/pytorch`)
3. Click **Scrape** to fetch historical data from BigQuery
4. Click **Aggregate Global** to build the master leaderboard
5. Go to **Contributor Enrichment** section
6. Click **Top 0.1%** to enrich top contributors
7. View enriched data in the interactive table

### Log Levels

- **Debug**: Verbose debugging information
- **Info**: General operational messages
- **Warning**: Potential issues that don't stop operation
- **Error**: Failures that require attention

## API Endpoints

### Repository Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/repositories` | Add a repository to track |
| `GET` | `/api/v1/repositories` | List all tracked repositories |
| `GET` | `/api/v1/repositories/{owner}/{name}` | Get repository details |
| `DELETE` | `/api/v1/repositories/{owner}/{name}` | Remove repository |
| `POST` | `/api/v1/repositories/{owner}/{name}/refresh` | Trigger data refresh |

### Leaderboards
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/leaderboard/global` | Global leaderboard |
| `GET` | `/api/v1/leaderboard/{owner}/{name}` | Repository leaderboard |
| `GET` | `/api/v1/leaderboard/compare` | Compare multiple repositories |

### Contributors
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/contributors/{username}` | Full contributor profile |
| `GET` | `/api/v1/contributors/{username}/activity` | Contribution history |
| `GET` | `/api/v1/contributors/{username}/repositories` | Per-repo breakdown |
| `POST` | `/api/v1/contributors/{username}/enrich` | Trigger enrichment |

### Configuration
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/config/scoring` | Get scoring weights |
| `PUT` | `/api/v1/config/scoring` | Update scoring weights |

### Dashboard
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard` | Monitoring dashboard UI |
| `GET` | `/dashboard/stats` | Current system statistics |
| `GET` | `/dashboard/errors` | Recent error list |
| `WS` | `/ws/logs` | WebSocket for live logs |

## Scoring System

Default scoring weights:

| Event Type | Points | Description |
|------------|--------|-------------|
| Release Published | 30 | Major milestone |
| PR Merged | 25 | Code successfully integrated |
| PR Reviewed | 20 | Code review contribution |
| PR Opened | 15 | Initiative to contribute |
| Commit | 10 + line bonus | Direct code contribution |
| Issue Opened | 8 | Bug reports, feature requests |
| Issue Closed | 5 | Resolution of issues |
| PR Review Comment | 5 | Detailed feedback |
| Comment | 3 | Discussion participation |

**Line bonus**: `+0.1` per line added, `+0.05` per line deleted

## Project Structure

```
github-contributor-leaderboard/
├── src/
│   ├── api/              # FastAPI application
│   │   ├── routes/       # API endpoints + dashboard
│   │   ├── schemas/      # Pydantic models
│   │   └── templates/    # Dashboard HTML
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
├── scripts/              # Utility scripts
└── secrets/              # Credentials (gitignored)
```

## Background Workers

Start Celery workers for background processing:

```bash
# Start worker
celery -A src.workers.celery_app worker --loglevel=info

# Start scheduler (for periodic tasks)
celery -A src.workers.celery_app beat --loglevel=info
```

### Worker Tasks

- **scrape_repository**: Full historical data ingestion from BigQuery
- **incremental_scrape**: Fetch new events since last scrape
- **recalculate_leaderboard**: Recompute rankings after new data
- **enrich_contributor**: Gather social media profiles

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

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Data Sources

### GitHub Archive (BigQuery)

The primary data source for historical contribution data. Contains all public GitHub events since 2011.

- **Dataset**: `githubarchive.day.*`
- **Cost**: ~$5-20 per large query
- **Delay**: ~1 hour from real-time

### GitHub REST API

Used for:
- Repository validation and metadata
- User profile information
- Real-time data when needed
- Profile README parsing for enrichment

**Rate Limit**: 5,000 requests/hour with authentication

## Pipeline Control Dashboard

The Pipeline Control dashboard at `/dashboard/pipeline` provides a unified interface for managing the entire data pipeline:

### Contributor Enrichment

Enrich contributor profiles with social media and contact information:

- **Single User Enrichment**: Enrich a specific GitHub user by username
- **Batch Enrichment**: Enrich top N contributors by global score
- **Quick Actions**: One-click buttons for top 0.1%, 0.5%, 1%, 5%
- **Progress Tracking**: Real-time stats showing enrichment coverage

### Supported Platforms

The enrichment system extracts data from 30+ platforms:

| Category | Platforms |
|----------|-----------|
| Social Media | Twitter/X, LinkedIn, Bluesky, Mastodon, Threads, Instagram, Facebook |
| Developer | GitHub Sponsors, GitLab, npm, PyPI, CodePen, Dribbble, Behance |
| Video/Streaming | YouTube, Twitch, TikTok |
| Community | Reddit, Hacker News, Stack Overflow, Discord, Telegram, Keybase |
| Professional | Personal websites, Substack, Medium, dev.to, Kaggle |

### Data Sources

1. **GitHub Profile API**: Email, Twitter, company, website, bio, location
2. **Profile README**: Badges, links, shields.io badges, social icons
3. **Fallback APIs** (optional): LinkedIn enrichment via Proxycurl

### Enrichment Statistics

The dashboard shows real-time coverage statistics:
- Total users enriched vs. unenriched
- Breakdown by status (complete, partial, pending, failed)
- Count of each social platform found
- Last 24h activity metrics

### Exporting Data

Export enriched contributor data to CSV with all social columns for external analysis.

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

## Support

- **Issues**: https://github.com/MichaelTheMay/github-contributor-leaderboard/issues
- **Discussions**: https://github.com/MichaelTheMay/github-contributor-leaderboard/discussions
