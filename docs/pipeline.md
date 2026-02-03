# GitHub Contributor Leaderboard Pipeline

## System Architecture

```mermaid
flowchart TB
    subgraph Input["Data Sources"]
        GH[GitHub API]
        BQ[BigQuery GitHub Archive]
    end

    subgraph API["FastAPI Server"]
        REST[REST Endpoints]
        WS[WebSocket Logs]
        DASH[Dashboard UI]
    end

    subgraph Queue["Job Queue"]
        REDIS[(Redis)]
        CELERY[Celery Worker]
    end

    subgraph Database["PostgreSQL"]
        REPOS[(repositories)]
        USERS[(github_users)]
        REPO_LB[(repository_leaderboard)]
        GLOBAL_LB[(global_leaderboard)]
        JOBS[(scrape_jobs)]
    end

    %% User Flow
    USER([User]) --> REST
    USER --> DASH

    %% Add Repository Flow
    REST -->|POST /repositories| GH
    GH -->|Validate repo exists| REST
    REST -->|Create record| REPOS
    REST -->|Queue scrape job| REDIS

    %% Scrape Flow
    REDIS -->|Pick up job| CELERY
    CELERY -->|Fetch historical data| BQ
    BQ -->|Aggregated stats per user| CELERY
    CELERY -->|Upsert users| USERS
    CELERY -->|Calculate scores| REPO_LB
    CELERY -->|Update rankings| REPO_LB
    CELERY -->|Trigger aggregation| GLOBAL_LB
    CELERY -->|Update job status| JOBS
    CELERY -->|Broadcast logs| WS

    %% Dashboard Flow
    DASH -->|GET /leaderboard/global| GLOBAL_LB
    DASH -->|GET /leaderboard/:repo| REPO_LB
    DASH -->|GET /jobs| JOBS
    DASH -->|WS /ws/logs| WS
```

## Scrape Pipeline Detail

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant R as Redis Queue
    participant C as Celery Worker
    participant BQ as BigQuery
    participant DB as PostgreSQL

    U->>API: POST /repositories/{owner}/{name}/scrape
    API->>DB: Check repo exists
    API->>DB: Check no pending jobs
    API->>R: Queue trigger_repository_scrape task
    API-->>U: Return task_id

    R->>C: Pick up trigger task
    C->>DB: Create ScrapeJob record
    C->>R: Queue scrape_repository task

    R->>C: Pick up scrape task
    C->>DB: Update job status = RUNNING
    C->>BQ: Query aggregated stats (2 years)
    BQ-->>C: Return contributor stats

    loop For each contributor
        C->>DB: Get or create GitHubUser
        C->>DB: Calculate score
        C->>DB: Upsert RepositoryLeaderboard entry
    end

    C->>DB: Update repository rankings
    C->>DB: Job status = COMPLETED
    C->>R: Queue recalculate_global_leaderboard

    R->>C: Pick up global recalc task
    C->>DB: Aggregate all repo leaderboards
    C->>DB: Clear & rebuild GlobalLeaderboard
    C-->>U: Dashboard shows updated data
```

## Global Leaderboard Aggregation

```mermaid
flowchart LR
    subgraph PerRepo["Per-Repository Leaderboards"]
        R1[flask leaderboard]
        R2[httpx leaderboard]
        R3[requests leaderboard]
        R4[django leaderboard]
    end

    subgraph Aggregation["Aggregation Process"]
        AGG[SUM scores per user_id]
        RANK[ORDER BY total_score DESC]
        NUM[Assign global_rank 1,2,3...]
    end

    subgraph Master["Global Leaderboard"]
        GL[(global_leaderboard table)]
    end

    R1 --> AGG
    R2 --> AGG
    R3 --> AGG
    R4 --> AGG
    AGG --> RANK
    RANK --> NUM
    NUM -->|DELETE + INSERT| GL
```

## Scoring Formula

| Event Type | Points | Description |
|------------|--------|-------------|
| Commit | 10 | Direct code contribution |
| PR Opened | 15 | Initiative to contribute |
| PR Merged | 25 | Code successfully integrated |
| PR Reviewed | 20 | Code review contribution |
| Issue Opened | 8 | Bug reports, feature requests |
| Issue Closed | 5 | Resolution of issues |
| Comment | 3 | Discussion participation |
| Release | 30 | Major milestone |
| Lines Added | 0.01 | Minor bonus (capped) |
| Lines Deleted | 0.005 | Minor bonus (capped) |

**Line bonus capped at 1000 points max** to prevent large file additions from dominating scores.
