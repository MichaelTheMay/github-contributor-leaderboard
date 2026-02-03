# GitHub Contributor Leaderboard - Complete System Architecture

## Table of Contents
1. [System Overview](#system-overview)
2. [Data Flow Pipeline](#data-flow-pipeline)
3. [Automated Task Pipeline](#automated-task-pipeline)
4. [Database Schema](#database-schema)
5. [API Endpoints](#api-endpoints)
6. [Scoring System](#scoring-system)

---

## System Overview

```mermaid
flowchart TB
    subgraph External["External Data Sources"]
        BQ[("BigQuery\nGitHub Archive")]
        GH["GitHub REST API"]
    end

    subgraph Infrastructure["Infrastructure Layer"]
        REDIS[("Redis\nQueue + Cache")]
        PG[("PostgreSQL\nDatabase")]
    end

    subgraph Workers["Background Workers"]
        CELERY["Celery Worker Pool"]
        SCRAPE["Scrape Tasks"]
        ENRICH["Enrichment Tasks"]
        LEADER["Leaderboard Tasks"]
    end

    subgraph API["FastAPI Application"]
        REST["REST Endpoints"]
        WS["WebSocket\nLog Streaming"]
        DASH["Dashboard UI"]
    end

    subgraph Services["Service Layer"]
        BQ_SVC["BigQueryService"]
        GH_SVC["GitHubService"]
        REPO_SVC["RepositoryService"]
        LB_SVC["LeaderboardService"]
        CONTRIB_SVC["ContributorService"]
        SCORE_SVC["ScoringService"]
        JOB_SVC["JobService"]
    end

    %% External connections
    BQ --> BQ_SVC
    GH --> GH_SVC

    %% Service to Infrastructure
    BQ_SVC --> CELERY
    GH_SVC --> CELERY
    REPO_SVC --> PG
    LB_SVC --> PG
    CONTRIB_SVC --> PG
    JOB_SVC --> PG
    SCORE_SVC --> PG

    %% Workers
    CELERY --> SCRAPE
    CELERY --> ENRICH
    CELERY --> LEADER
    REDIS <--> CELERY
    SCRAPE --> PG
    ENRICH --> PG
    LEADER --> PG

    %% API connections
    REST --> REPO_SVC
    REST --> LB_SVC
    REST --> CONTRIB_SVC
    REST --> SCORE_SVC
    REST --> JOB_SVC
    DASH --> REST
    DASH --> WS

    %% User
    USER([User/Browser]) --> DASH
    USER --> REST

    classDef external fill:#e1f5fe,stroke:#01579b
    classDef infra fill:#fff3e0,stroke:#e65100
    classDef worker fill:#f3e5f5,stroke:#7b1fa2
    classDef api fill:#e8f5e9,stroke:#2e7d32
    classDef service fill:#fce4ec,stroke:#c2185b

    class BQ,GH external
    class REDIS,PG infra
    class CELERY,SCRAPE,ENRICH,LEADER worker
    class REST,WS,DASH api
    class BQ_SVC,GH_SVC,REPO_SVC,LB_SVC,CONTRIB_SVC,SCORE_SVC,JOB_SVC service
```

---

## Data Flow Pipeline

### Complete Scrape Pipeline

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant API as FastAPI
    participant R as Redis Queue
    participant C as Celery Worker
    participant BQ as BigQuery
    participant DB as PostgreSQL

    Note over U,DB: Repository Addition & Scrape Flow

    U->>API: POST /repositories
    API->>DB: Check if repo exists
    API->>DB: Create Repository (PENDING)
    API->>DB: Create ScrapeJob (QUEUED)
    API-->>U: Return repository details

    U->>API: POST /repositories/{owner}/{name}/scrape
    API->>DB: Check no pending jobs
    API->>R: Queue scrape_repository task
    API-->>U: Return task_id

    R->>C: Pick up scrape task
    C->>DB: Update job status = RUNNING
    C->>DB: Update repo status = SCRAPING

    C->>BQ: Query aggregated stats (2 years)
    Note over BQ: SELECT user_id, username,<br/>COUNT(commits), COUNT(prs),<br/>SUM(lines_added)...<br/>FROM githubarchive.month.*

    BQ-->>C: Return contributor stats

    loop For each contributor (batches of 100)
        C->>DB: Get or create GitHubUser
        C->>DB: Calculate score with weights
        C->>DB: Upsert RepositoryLeaderboard
        C->>DB: Commit batch
    end

    C->>DB: Update repository rankings
    C->>DB: Job status = COMPLETED
    C->>DB: Repo status = COMPLETED

    C->>R: Queue recalculate_global_leaderboard
    R->>C: Pick up global recalc task

    C->>DB: Aggregate all repo leaderboards
    C->>DB: DELETE FROM global_leaderboard
    C->>DB: INSERT new ranked entries

    Note over DB: Global leaderboard updated!

    U->>API: GET /leaderboard/global
    API->>DB: Query GlobalLeaderboard
    API-->>U: Return ranked contributors
```

### Scoring Calculation Flow

```mermaid
flowchart LR
    subgraph Input["Raw BigQuery Stats"]
        COMMITS["commits: 50"]
        PRS_O["prs_opened: 10"]
        PRS_M["prs_merged: 8"]
        PRS_R["prs_reviewed: 15"]
        ISSUES["issues_opened: 5"]
        COMMENTS["comments: 30"]
        LINES["lines_added: 10000"]
    end

    subgraph Weights["Scoring Weights"]
        W1["x10"]
        W2["x15"]
        W3["x25"]
        W4["x20"]
        W5["x8"]
        W6["x3"]
        W7["x0.01 (capped 500)"]
    end

    subgraph Calculation["Score Calculation"]
        S1["500"]
        S2["150"]
        S3["200"]
        S4["300"]
        S5["40"]
        S6["90"]
        S7["100"]
        SUM["TOTAL: 1380 pts"]
    end

    COMMITS --> W1 --> S1
    PRS_O --> W2 --> S2
    PRS_M --> W3 --> S3
    PRS_R --> W4 --> S4
    ISSUES --> W5 --> S5
    COMMENTS --> W6 --> S6
    LINES --> W7 --> S7

    S1 --> SUM
    S2 --> SUM
    S3 --> SUM
    S4 --> SUM
    S5 --> SUM
    S6 --> SUM
    S7 --> SUM
```

---

## Automated Task Pipeline

### Scheduled Tasks

```mermaid
flowchart TB
    subgraph Triggers["Task Triggers"]
        MANUAL["Manual API Call"]
        SCHEDULE_1H["Every 1 Hour"]
        SCHEDULE_30M["Every 30 Minutes"]
        AUTO["Auto (After Scrape)"]
    end

    subgraph Tasks["Celery Tasks"]
        SCRAPE["scrape_repository\n(repository_id, job_id)"]
        REFRESH["refresh_stale_repositories"]
        GLOBAL["recalculate_global_leaderboard"]
        ENRICH["enrich_contributor\n(user_id)"]
    end

    subgraph Effects["Database Effects"]
        REPO_LB["RepositoryLeaderboard\nUpdated"]
        GLOBAL_LB["GlobalLeaderboard\nRebuild"]
        ENRICHMENT["ContributorEnrichment\nUpdated"]
    end

    MANUAL -->|POST /scrape| SCRAPE
    SCHEDULE_1H --> REFRESH
    REFRESH -->|Queues tasks| SCRAPE
    SCHEDULE_30M --> GLOBAL

    SCRAPE --> REPO_LB
    SCRAPE -->|triggers| AUTO
    AUTO --> GLOBAL
    GLOBAL --> GLOBAL_LB

    MANUAL -->|POST /enrich| ENRICH
    ENRICH --> ENRICHMENT

    style SCRAPE fill:#c8e6c9
    style GLOBAL fill:#bbdefb
    style REFRESH fill:#fff9c4
    style ENRICH fill:#f8bbd9
```

### Task Dependency Chain

```mermaid
flowchart LR
    subgraph Chain1["Repository Scrape Chain"]
        T1["trigger_repository_scrape"]
        T2["scrape_repository"]
        T3["recalculate_global_leaderboard"]
    end

    subgraph Chain2["Enrichment Chain"]
        E1["batch_enrich_top_contributors"]
        E2["enrich_contributor"]
        E3["fetch_twitter_profile"]
        E4["fetch_linkedin_profile"]
    end

    T1 -->|"creates job"| T2
    T2 -->|"on success"| T3

    E1 -->|"spawns many"| E2
    E2 -.->|"optional"| E3
    E2 -.->|"optional"| E4
```

### Retry & Error Handling

```mermaid
stateDiagram-v2
    [*] --> QUEUED: Job Created
    QUEUED --> RUNNING: Worker Picks Up
    RUNNING --> COMPLETED: Success
    RUNNING --> RETRYING: Error (retries < 3)
    RETRYING --> RUNNING: Backoff Complete
    RETRYING --> FAILED: Max Retries
    COMPLETED --> [*]
    FAILED --> [*]

    note right of RETRYING
        Exponential backoff:
        Retry 1: 60s
        Retry 2: 120s
        Retry 3: 180s
    end note
```

---

## Database Schema

```mermaid
erDiagram
    Repository ||--o{ RepositoryLeaderboard : has
    Repository ||--o{ ContributionEvent : contains
    Repository ||--o{ ScrapeJob : tracked_by

    GitHubUser ||--o{ RepositoryLeaderboard : appears_in
    GitHubUser ||--o{ ContributionEvent : authored
    GitHubUser ||--o| GlobalLeaderboard : has_entry
    GitHubUser ||--o| ContributorEnrichment : enriched_by

    Repository {
        int id PK
        string owner
        string name
        bigint github_id UK
        string description
        int stars
        int forks
        enum status
        datetime last_scraped_at
    }

    GitHubUser {
        int id PK
        bigint github_id UK
        string username UK
        string display_name
        string avatar_url
        string profile_url
        string email
        string company
        string location
    }

    RepositoryLeaderboard {
        int id PK
        int repository_id FK
        int user_id FK
        int rank
        decimal total_score
        int commit_count
        int pr_opened_count
        int pr_merged_count
        int pr_reviewed_count
        int issues_opened_count
        int issues_closed_count
        int comments_count
        int lines_added
        int lines_deleted
        datetime first_contribution_at
        datetime last_contribution_at
    }

    GlobalLeaderboard {
        int id PK
        int user_id FK,UK
        int global_rank
        decimal total_score
        int repositories_contributed
        int total_commits
        int total_prs_merged
        int total_prs_reviewed
        int total_issues_opened
        int total_comments
        bigint total_lines_added
    }

    ContributionEvent {
        bigint id PK
        int repository_id FK
        int user_id FK
        enum event_type
        string event_id UK
        jsonb event_data
        int lines_added
        int lines_deleted
        datetime event_timestamp
    }

    ScrapeJob {
        int id PK
        int repository_id FK
        enum job_type
        enum status
        datetime started_at
        datetime completed_at
        int events_processed
        string error_message
    }

    ContributorEnrichment {
        int id PK
        int user_id FK,UK
        string twitter_username
        string linkedin_url
        string personal_website
        string personal_email
        enum enrichment_status
        datetime last_enriched_at
        jsonb enrichment_sources
    }

    ScoringWeight {
        int id PK
        string event_type UK
        decimal base_points
        string description
    }
```

---

## API Endpoints

### Complete Endpoint Map

```mermaid
flowchart TB
    subgraph Repositories["/api/v1/repositories"]
        R1["POST / - Add repository"]
        R2["GET / - List repositories"]
        R3["GET /{owner}/{name} - Get details"]
        R4["DELETE /{owner}/{name} - Remove"]
        R5["POST /{owner}/{name}/refresh - Incremental"]
        R6["POST /{owner}/{name}/scrape - Full scrape"]
    end

    subgraph Leaderboards["/api/v1/leaderboard"]
        L1["GET /global - Master leaderboard"]
        L2["GET /{owner}/{name} - Repo leaderboard"]
        L3["GET /compare - Compare repos"]
    end

    subgraph Contributors["/api/v1/contributors"]
        C1["GET /{username} - Profile"]
        C2["GET /{username}/activity - Timeline"]
        C3["GET /{username}/repositories - Repos"]
        C4["POST /{username}/enrich - Enrich"]
    end

    subgraph Config["/api/v1/config"]
        S1["GET /scoring - Get weights"]
        S2["PUT /scoring - Update weights"]
    end

    subgraph Jobs["/api/v1/jobs"]
        J1["GET / - List jobs"]
    end

    subgraph Dashboard["/dashboard"]
        D1["GET / - UI"]
        D2["WS /ws/logs - Live logs"]
        D3["GET /stats - Statistics"]
        D4["GET /errors - Recent errors"]
    end

    R6 -->|triggers| CELERY["Celery Worker"]
    C4 -->|triggers| CELERY

    style Repositories fill:#e3f2fd
    style Leaderboards fill:#e8f5e9
    style Contributors fill:#fff3e0
    style Config fill:#fce4ec
    style Jobs fill:#f3e5f5
    style Dashboard fill:#e0f2f1
```

---

## Scoring System

### Event Type Weights

| Event Type | Base Points | Description |
|------------|-------------|-------------|
| `RELEASE` | 30 | Publishing a release (highest single event) |
| `PR_MERGED` | 25 | Code successfully integrated |
| `PR_REVIEWED` | 20 | Code review contribution |
| `PR_OPENED` | 15 | Initiative to contribute |
| `COMMIT` | 10 | Direct code contribution |
| `ISSUE_OPENED` | 8 | Bug reports, feature requests |
| `ISSUE_CLOSED` | 5 | Resolution of issues |
| `PR_REVIEW_COMMENT` | 5 | Detailed review feedback |
| `COMMENT` | 3 | Discussion participation |
| `LINES_ADDED` | 0.01/line | Capped at 500 points total |
| `LINES_DELETED` | 0.005/line | Capped at 500 points total |

### Score Formula

```
total_score = (commits × 10)
            + (prs_opened × 15)
            + (prs_merged × 25)
            + (prs_reviewed × 20)
            + (issues_opened × 8)
            + (issues_closed × 5)
            + (comments × 3)
            + (releases × 30)
            + min(line_bonus, 500)

where line_bonus = (lines_added × 0.01) + (lines_deleted × 0.005)
```

---

## Technology Stack Summary

| Layer | Technology | Purpose |
|-------|------------|---------|
| **API** | FastAPI | Async REST API framework |
| **Database** | PostgreSQL 15+ | Primary data store |
| **ORM** | SQLAlchemy 2.0 | Async database access |
| **Queue** | Redis | Message broker + result backend |
| **Workers** | Celery | Background task processing |
| **Data Source** | BigQuery | GitHub Archive historical data |
| **Real-time** | WebSocket | Live log streaming |
| **HTTP Client** | httpx | Async HTTP requests |
| **Logging** | structlog | Structured logging |

---

## Deployment Architecture

```mermaid
flowchart TB
    subgraph Docker["Docker Compose"]
        subgraph Services
            API["FastAPI\n:8000"]
            CELERY_W["Celery Worker\n--pool=solo"]
            CELERY_B["Celery Beat\n(Scheduler)"]
        end

        subgraph Data
            PG[("PostgreSQL\n:5433")]
            REDIS[("Redis\n:6379")]
        end
    end

    subgraph External
        GCP["Google Cloud\nBigQuery"]
        GITHUB["GitHub API"]
    end

    API --> PG
    API --> REDIS
    CELERY_W --> PG
    CELERY_W --> REDIS
    CELERY_B --> REDIS
    CELERY_W --> GCP
    CELERY_W --> GITHUB

    USER([Browser]) --> API
```

---

## Quick Reference Commands

```bash
# Start infrastructure
docker run -d --name postgres-leaderboard -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=leaderboard -p 5433:5432 postgres:15-alpine
docker run -d --name redis-leaderboard -p 6379:6379 redis:7-alpine

# Start API server
uvicorn src.api.app:app --reload

# Start Celery worker (Windows)
celery -A src.workers.celery_app worker --loglevel=info --pool=solo

# Start Celery beat (scheduler)
celery -A src.workers.celery_app beat --loglevel=info

# Trigger a scrape
curl -X POST http://localhost:8000/api/v1/repositories/owner/name/scrape

# Recalculate scores
python scripts/recalculate_scores.py

# View dashboard
open http://localhost:8000/dashboard
```
