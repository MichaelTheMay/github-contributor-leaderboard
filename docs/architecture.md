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

---

## Advanced System Diagrams

### 1. Complete Request Lifecycle with Caching

```mermaid
sequenceDiagram
    autonumber
    participant Client as Browser
    participant CDN as CloudFlare CDN
    participant LB as Load Balancer
    participant API as FastAPI
    participant Cache as Redis Cache
    participant DB as PostgreSQL
    participant BG as Celery Worker
    participant BQ as BigQuery

    rect rgb(240, 248, 255)
        Note over Client,API: Read Path (Cached)
        Client->>CDN: GET /api/v1/leaderboard/global
        CDN->>LB: Cache MISS
        LB->>API: Forward request
        API->>Cache: GET leaderboard:global:page:1
        alt Cache Hit
            Cache-->>API: Cached response
            API-->>LB: JSON (200)
            LB-->>CDN: Response
            CDN->>CDN: Store in edge cache
            CDN-->>Client: JSON (200)
        else Cache Miss
            API->>DB: SELECT FROM global_leaderboard
            DB-->>API: Result set
            API->>Cache: SET leaderboard:global:page:1 (TTL: 300s)
            API-->>Client: JSON (200)
        end
    end

    rect rgb(255, 240, 245)
        Note over Client,BQ: Write Path (Scrape)
        Client->>API: POST /repositories/{id}/scrape
        API->>DB: Check budget limits
        API->>DB: Create ScrapeJob (QUEUED)
        API->>BG: Enqueue task
        API-->>Client: 202 Accepted {job_id}

        BG->>DB: Update job: RUNNING
        BG->>BQ: Execute query
        BQ-->>BG: Results (paginated)

        loop Process in batches
            BG->>DB: Upsert users & scores
            BG->>DB: Commit batch
        end

        BG->>Cache: DELETE leaderboard:*
        BG->>DB: Update job: COMPLETED
        BG->>BG: Trigger global recalc
    end
```

---

### 2. Bot Filtering & User Deduplication Pipeline

```mermaid
flowchart TB
    subgraph Input["BigQuery Results"]
        Event["Event Record:\nuser_id: 12345\nusername: dependabot[bot]"]
    end

    subgraph BotCheck["Bot Detection"]
        Patterns["Check Patterns:\n- [bot] suffix\n- dependabot\n- github-actions\n- renovate\n- snyk-bot\n- codecov"]
        IsBot{Contains bot\npattern?}
    end

    subgraph UserLookup["User Resolution"]
        ByGitHubID["Query by github_id"]
        ByUsername["Query by username"]
        Found{User\nfound?}
        Conflict{Username\nconflict?}
    end

    subgraph Actions["Resolution Actions"]
        Skip["Skip event\n(bot filtered)"]
        Return["Return existing\nuser"]
        Create["Create new\nGitHubUser"]
        Rename["Rename conflicting\nuser: {name}_old_{id}"]
        Update["Update user:\nusername or github_id"]
    end

    subgraph Metrics["Tracking"]
        BotsFiltered["bots_filtered++"]
        UsersProcessed["users_processed++"]
    end

    Event --> Patterns
    Patterns --> IsBot
    IsBot -->|Yes| Skip
    Skip --> BotsFiltered

    IsBot -->|No| ByGitHubID
    ByGitHubID --> Found

    Found -->|Yes, same username| Return
    Found -->|Yes, different username| Conflict

    Conflict -->|Yes| Rename
    Rename --> Update
    Update --> Return

    Conflict -->|No| Update

    Found -->|No| ByUsername
    ByUsername -->|Found| Update
    ByUsername -->|Not found| Create
    Create --> Return

    Return --> UsersProcessed

    classDef skip fill:#ff6b6b,stroke:#333
    classDef success fill:#98fb98,stroke:#333
    classDef check fill:#ffd700,stroke:#333

    class Skip,BotsFiltered skip
    class Return,Create,UsersProcessed success
    class IsBot,Found,Conflict check
```

---

### 3. Incremental vs Full Scrape Decision Matrix

```mermaid
flowchart TB
    Start([Scrape Triggered])

    subgraph JobType["Job Type Check"]
        CheckType{job_type?}
        Full["FULL_SCRAPE"]
        Incremental["INCREMENTAL"]
    end

    subgraph FullScrapeLogic["Full Scrape Logic"]
        FullWindow["Window: NOW - 2 years\nto NOW"]
        FullEstimate["Estimate: ~200MB-2GB\nCost: $0.001-$0.01"]
    end

    subgraph IncrementalLogic["Incremental Logic"]
        CheckHistory{Has scrape\nhistory?}

        subgraph HasHistory["With History"]
            LastWindow["Get last\nScrapeWindow"]
            CalcStart["start = window.end - 1 day\n(overlap for safety)"]
        end

        subgraph NoHistory["Without History"]
            CheckLatest{Has\nlatest_data_date?}
            UseLatest["start = latest_date - 1 day"]
            FirstTime["start = NOW - 2 years\n(first scrape)"]
        end

        IncrEstimate["Estimate: ~10-50MB\nCost: $0.00005-$0.00025"]
    end

    subgraph Constraints["Apply Constraints"]
        CheckNever{start <\nnever_rescrape_before?}
        AdjustStart["start = never_rescrape_before"]
        SetEnd["end = NOW"]
    end

    subgraph Output["Final Window"]
        Window["Scrape Window:\nstart_date → end_date"]
        Savings["Incremental savings:\n~95% cost reduction"]
    end

    Start --> CheckType
    CheckType -->|FULL| Full
    CheckType -->|INCREMENTAL| Incremental

    Full --> FullWindow
    FullWindow --> FullEstimate
    FullEstimate --> CheckNever

    Incremental --> CheckHistory
    CheckHistory -->|Yes| LastWindow
    LastWindow --> CalcStart
    CalcStart --> IncrEstimate

    CheckHistory -->|No| CheckLatest
    CheckLatest -->|Yes| UseLatest
    CheckLatest -->|No| FirstTime
    UseLatest --> IncrEstimate
    FirstTime --> IncrEstimate

    IncrEstimate --> CheckNever

    CheckNever -->|Yes| AdjustStart
    CheckNever -->|No| SetEnd
    AdjustStart --> SetEnd

    SetEnd --> Window
    Window --> Savings

    classDef full fill:#ff9999,stroke:#333
    classDef incr fill:#99ff99,stroke:#333
    classDef constraint fill:#ffff99,stroke:#333

    class Full,FullWindow,FullEstimate full
    class Incremental,LastWindow,CalcStart,UseLatest,IncrEstimate incr
    class CheckNever,AdjustStart constraint
```

---

### 4. Leaderboard Aggregation State Machine

```mermaid
stateDiagram-v2
    [*] --> Idle: System Ready

    state "Repository Leaderboard" as RepoLB {
        Idle --> Scraping: scrape_repository()
        Scraping --> Processing: BigQuery results
        Processing --> Scoring: For each user
        Scoring --> Ranking: All users scored
        Ranking --> Committed: Rankings assigned
        Committed --> Idle: Batch complete
    }

    state "Global Leaderboard" as GlobalLB {
        Triggered --> Aggregating: recalculate_global()
        Aggregating --> Clearing: Data aggregated
        Clearing --> Inserting: Old entries deleted
        Inserting --> GlobalDone: New rankings inserted
        GlobalDone --> [*]: Complete
    }

    Committed --> Triggered: Auto-trigger

    state Processing {
        [*] --> FilterBots
        FilterBots --> CreateUser: Not a bot
        FilterBots --> SkipEvent: Is a bot
        CreateUser --> CalcScore
        CalcScore --> UpsertEntry
        UpsertEntry --> [*]: Next user
    }

    state Scoring {
        [*] --> GetWeights
        GetWeights --> ApplyFormula
        ApplyFormula --> CapLineBonus
        CapLineBonus --> [*]: Score ready
    }

    state Aggregating {
        [*] --> GroupByUser
        GroupByUser --> SumScores
        SumScores --> CountRepos
        CountRepos --> SumMetrics
        SumMetrics --> [*]: Ready to insert
    }

    note right of Processing
        Batch size: 100
        Commit after each batch
    end note

    note right of GlobalLB
        DELETE + INSERT
        (not UPDATE for performance)
    end note
```

---

### 5. Cost Tracking & Budget Enforcement Flow

```mermaid
flowchart TB
    subgraph Config["Budget Configuration"]
        DailyLimit["daily_limit_usd: $5.00"]
        MonthlyLimit["monthly_limit_usd: $50.00"]
        WarningPct["warning_threshold: 80%"]
        PricePerTB["price_per_tb: $5.00"]
    end

    subgraph PreJob["Pre-Job Validation"]
        EstimateBytes["Estimate bytes:\nrepo_size × date_range × factor"]
        EstimateCost["Estimate cost:\nbytes / 1TB × $5"]
        GetSpent["Get current spend:\nSUM(actual_cost) today/month"]
        CalcRemaining["remaining = limit - spent"]
    end

    subgraph Decision["Budget Decision"]
        CheckDaily{estimate ≤\ndaily_remaining?}
        CheckMonthly{estimate ≤\nmonthly_remaining?}
        CheckWarning{spent > 80%\nof limit?}
    end

    subgraph Actions["Actions"]
        Approve["✓ Approve job"]
        Reject["✗ Reject job\nBUDGET_EXCEEDED"]
        Warn["⚠ Log warning\nApproaching limit"]
        Alert["🔔 Send alert"]
    end

    subgraph PostJob["Post-Job Recording"]
        CaptureStats["Capture from BigQuery:\n- bytes_processed\n- bytes_billed\n- slot_millis"]
        CalcActual["actual_cost =\nbytes_billed / 1TB × $5"]
        CreateRecord["INSERT CostRecord"]
        UpdateSummary["UPDATE DailyCostSummary"]
        LogAudit["INSERT AuditLog"]
    end

    subgraph Monitoring["Dashboard Display"]
        DailyGauge["Daily: $X.XX / $5.00"]
        MonthlyGauge["Monthly: $XX.XX / $50.00"]
        CostHistory["Cost trend graph"]
        Forecast["Projected monthly cost"]
    end

    Config --> PreJob
    EstimateBytes --> EstimateCost
    EstimateCost --> GetSpent
    GetSpent --> CalcRemaining

    CalcRemaining --> CheckDaily
    CheckDaily -->|No| Reject
    CheckDaily -->|Yes| CheckMonthly
    CheckMonthly -->|No| Reject
    CheckMonthly -->|Yes| CheckWarning

    CheckWarning -->|Yes| Warn
    CheckWarning -->|No| Approve
    Warn --> Alert
    Alert --> Approve

    Approve --> CaptureStats
    CaptureStats --> CalcActual
    CalcActual --> CreateRecord
    CreateRecord --> UpdateSummary
    UpdateSummary --> LogAudit

    LogAudit --> DailyGauge
    DailyGauge --> MonthlyGauge
    MonthlyGauge --> CostHistory
    CostHistory --> Forecast

    classDef config fill:#87ceeb,stroke:#333
    classDef check fill:#ffd700,stroke:#333
    classDef approve fill:#98fb98,stroke:#333
    classDef reject fill:#ff6b6b,stroke:#333
    classDef warn fill:#ffcc00,stroke:#333

    class DailyLimit,MonthlyLimit,WarningPct,PricePerTB config
    class CheckDaily,CheckMonthly,CheckWarning check
    class Approve approve
    class Reject reject
    class Warn,Alert warn
```

---

### 6. Error Recovery & Circuit Breaker Pattern

```mermaid
flowchart TB
    subgraph Errors["Error Classification"]
        BQTimeout["BigQuery Timeout\n(recoverable)"]
        BQQuota["BigQuery Quota\n(recoverable, wait)"]
        DBConn["DB Connection Lost\n(recoverable)"]
        Constraint["Unique Constraint\n(skip item)"]
        Budget["Budget Exceeded\n(not recoverable)"]
        Unknown["Unknown Error\n(log & retry)"]
    end

    subgraph CircuitBreaker["Circuit Breaker State"]
        Closed["CLOSED\n(normal operation)"]
        Open["OPEN\n(fail fast)"]
        HalfOpen["HALF-OPEN\n(test recovery)"]

        Closed -->|"5 failures"| Open
        Open -->|"5 min timeout"| HalfOpen
        HalfOpen -->|"Success"| Closed
        HalfOpen -->|"Failure"| Open
    end

    subgraph RetryStrategy["Retry Strategy"]
        Attempt1["Attempt 1\nWait: 60s"]
        Attempt2["Attempt 2\nWait: 120s"]
        Attempt3["Attempt 3\nWait: 240s"]
        MaxRetries["Max retries\nexhausted"]
    end

    subgraph Recovery["Recovery Actions"]
        Retry["Retry operation"]
        Skip["Skip item,\ncontinue batch"]
        Abort["Abort job"]
        DLQ["Dead Letter Queue"]
        Notify["Notify admin"]
    end

    subgraph Metrics["Error Metrics"]
        Counter["error_count++"]
        LastError["last_error_time = now"]
        Severity["severity = HIGH/MED/LOW"]
    end

    BQTimeout --> Retry
    BQQuota --> Retry
    DBConn --> Retry
    Constraint --> Skip
    Budget --> Abort
    Unknown --> Retry

    Retry --> Attempt1
    Attempt1 -->|Fail| Attempt2
    Attempt2 -->|Fail| Attempt3
    Attempt3 -->|Fail| MaxRetries

    MaxRetries --> Abort
    Abort --> DLQ
    DLQ --> Notify

    Retry --> Counter
    Abort --> Counter
    Counter --> LastError
    LastError --> Severity

    Severity --> CircuitBreaker

    classDef recoverable fill:#98fb98,stroke:#333
    classDef nonrecoverable fill:#ff6b6b,stroke:#333
    classDef circuit fill:#87ceeb,stroke:#333
    classDef retry fill:#ffd700,stroke:#333

    class BQTimeout,BQQuota,DBConn,Constraint recoverable
    class Budget,Unknown nonrecoverable
    class Closed,Open,HalfOpen circuit
    class Attempt1,Attempt2,Attempt3 retry
```

---

### 7. Scheduled Pipeline Orchestration Detail

```mermaid
flowchart TB
    subgraph Trigger["Pipeline Triggers"]
        Cron["⏰ Cron: 0 2 * * *\n(2 AM UTC daily)"]
        Manual["👆 Manual Dispatch\n(GitHub Actions)"]
        Webhook["🔗 External Webhook"]
    end

    subgraph Preflight["Preflight Checks"]
        ValidateSecrets["Validate Secrets:\n- DATABASE_URL ✓\n- BIGQUERY_CREDENTIALS ✓\n- REDIS_URL ✓"]
        HealthCheck["Health Checks:\n- DB ping ✓\n- Redis ping ✓\n- BigQuery auth ✓"]
        BudgetCheck["Budget Check:\n- Daily remaining\n- Monthly remaining"]
    end

    subgraph Discovery["Stage 1: Discovery"]
        FindStale["Find stale repos:\nlast_scraped < 24h ago\nOR never scraped"]
        Prioritize["Prioritize by:\n1. Never scraped\n2. Most stale\n3. Highest stars"]
        SelectBatch["Select batch:\nmax 5 repos per run"]
    end

    subgraph Execution["Stage 2: Execution"]
        CreateJobs["Create ScrapeJobs\nfor each repo"]
        QueueTasks["Queue Celery tasks\n(parallel execution)"]
        MonitorProgress["Monitor progress:\n- Events processed\n- Errors encountered\n- Cost accumulated"]
    end

    subgraph Calculation["Stage 3: Calculation"]
        WaitComplete["Wait for all\njobs to complete"]
        RepoLeaderboards["Update repository\nleaderboards"]
        GlobalLeaderboard["Recalculate global\nleaderboard"]
    end

    subgraph Reporting["Stage 4: Reporting"]
        GenerateSummary["Generate summary:\n- Repos scraped: X\n- Users processed: Y\n- Cost: $Z.ZZ"]
        AuditLog["Log to audit:\nPIPELINE_COMPLETED"]
        UpdateMetrics["Update Prometheus\nmetrics"]
    end

    subgraph PostPipeline["Post-Pipeline"]
        Success{All stages\nsucceeded?}
        SuccessPath["✓ Exit 0\nLog success"]
        FailPath["✗ Exit 1\nCreate issue"]
        Cleanup["Cleanup:\n- Remove temp files\n- Clear credentials"]
    end

    Cron & Manual & Webhook --> ValidateSecrets
    ValidateSecrets -->|Invalid| Abort["❌ Abort"]
    ValidateSecrets -->|Valid| HealthCheck
    HealthCheck -->|Unhealthy| Abort
    HealthCheck -->|Healthy| BudgetCheck
    BudgetCheck -->|Exceeded| SkipExpensive["⚠ Skip scraping"]
    BudgetCheck -->|OK| FindStale

    FindStale --> Prioritize
    Prioritize --> SelectBatch
    SelectBatch --> CreateJobs
    CreateJobs --> QueueTasks
    QueueTasks --> MonitorProgress
    MonitorProgress --> WaitComplete

    SkipExpensive --> GlobalLeaderboard

    WaitComplete --> RepoLeaderboards
    RepoLeaderboards --> GlobalLeaderboard
    GlobalLeaderboard --> GenerateSummary
    GenerateSummary --> AuditLog
    AuditLog --> UpdateMetrics
    UpdateMetrics --> Success

    Success -->|Yes| SuccessPath
    Success -->|No| FailPath
    SuccessPath --> Cleanup
    FailPath --> Cleanup

    classDef trigger fill:#ffd700,stroke:#333
    classDef preflight fill:#87ceeb,stroke:#333
    classDef stage fill:#98fb98,stroke:#333
    classDef error fill:#ff6b6b,stroke:#333
    classDef success fill:#90ee90,stroke:#333

    class Cron,Manual,Webhook trigger
    class ValidateSecrets,HealthCheck,BudgetCheck preflight
    class FindStale,Prioritize,SelectBatch,CreateJobs,QueueTasks,MonitorProgress,WaitComplete,RepoLeaderboards,GlobalLeaderboard,GenerateSummary,AuditLog,UpdateMetrics stage
    class Abort,SkipExpensive,FailPath error
    class SuccessPath success
```

---

### 8. Data Consistency & Transaction Boundaries

```mermaid
flowchart TB
    subgraph Transaction1["Transaction 1: Job Setup"]
        T1_Start["BEGIN"]
        T1_CreateJob["INSERT ScrapeJob\n(status=QUEUED)"]
        T1_UpdateRepo["UPDATE Repository\n(status=SCRAPING)"]
        T1_Commit["COMMIT"]
    end

    subgraph Transaction2["Transaction 2: Batch Processing"]
        T2_Start["BEGIN"]
        T2_Loop["FOR i IN batch:"]
        T2_User["UPSERT GitHubUser"]
        T2_Entry["UPSERT RepositoryLeaderboard"]
        T2_Check{i % 100 == 0?}
        T2_Commit["COMMIT"]
        T2_Continue["CONTINUE"]
    end

    subgraph Transaction3["Transaction 3: Finalization"]
        T3_Start["BEGIN"]
        T3_Rankings["UPDATE rankings\n(ORDER BY score)"]
        T3_Window["INSERT ScrapeWindow"]
        T3_Cost["INSERT CostRecord"]
        T3_Job["UPDATE ScrapeJob\n(status=COMPLETED)"]
        T3_Repo["UPDATE Repository\n(status=COMPLETED,\nlatest_data_date)"]
        T3_Commit["COMMIT"]
    end

    subgraph Transaction4["Transaction 4: Global Recalc"]
        T4_Start["BEGIN"]
        T4_Delete["DELETE FROM\nglobal_leaderboard"]
        T4_Aggregate["SELECT aggregated\nscores per user"]
        T4_Insert["INSERT ranked\nentries"]
        T4_Commit["COMMIT"]
    end

    subgraph Rollback["Error Handling"]
        Error["Exception raised"]
        Rollback_Action["ROLLBACK"]
        Retry{Retry\navailable?}
        RetryAction["Wait & retry"]
        FailJob["Mark job FAILED"]
    end

    T1_Start --> T1_CreateJob --> T1_UpdateRepo --> T1_Commit
    T1_Commit --> T2_Start

    T2_Start --> T2_Loop --> T2_User --> T2_Entry --> T2_Check
    T2_Check -->|Yes| T2_Commit --> T2_Continue --> T2_Loop
    T2_Check -->|No| T2_Continue
    T2_Loop -->|Done| T3_Start

    T3_Start --> T3_Rankings --> T3_Window --> T3_Cost --> T3_Job --> T3_Repo --> T3_Commit
    T3_Commit --> T4_Start

    T4_Start --> T4_Delete --> T4_Aggregate --> T4_Insert --> T4_Commit

    T2_User -.->|Error| Error
    T2_Entry -.->|Error| Error
    T3_Rankings -.->|Error| Error

    Error --> Rollback_Action --> Retry
    Retry -->|Yes| RetryAction --> T2_Start
    Retry -->|No| FailJob

    classDef tx fill:#e1f5fe,stroke:#01579b
    classDef commit fill:#c8e6c9,stroke:#2e7d32
    classDef error fill:#ffcdd2,stroke:#c62828

    class T1_Start,T2_Start,T3_Start,T4_Start tx
    class T1_Commit,T2_Commit,T3_Commit,T4_Commit commit
    class Error,Rollback_Action,FailJob error
```

---

### 9. WebSocket Real-Time Log Streaming

```mermaid
sequenceDiagram
    autonumber
    participant Browser as Browser Client
    participant WS as WebSocket Server
    participant PubSub as Redis PubSub
    participant Worker as Celery Worker
    participant Logger as structlog

    Note over Browser,Logger: Connection Establishment
    Browser->>WS: WS Connect /ws/logs
    WS->>WS: Authenticate (optional)
    WS->>PubSub: SUBSCRIBE logs:*
    WS-->>Browser: Connection established

    Note over Browser,Logger: Log Streaming
    Worker->>Logger: logger.info("scrape_started", repo="owner/name")
    Logger->>PubSub: PUBLISH logs:scrape {json}
    PubSub-->>WS: Message received
    WS->>WS: Format for display
    WS-->>Browser: {"type": "log", "level": "INFO", ...}
    Browser->>Browser: Append to log panel

    Note over Browser,Logger: Error Event
    Worker->>Logger: logger.error("bigquery_timeout", error="...")
    Logger->>PubSub: PUBLISH logs:error {json}
    PubSub-->>WS: Message received
    WS-->>Browser: {"type": "log", "level": "ERROR", ...}
    Browser->>Browser: Highlight in red

    Note over Browser,Logger: Job Completion
    Worker->>Logger: logger.info("job_completed", stats={...})
    Logger->>PubSub: PUBLISH logs:job {json}
    PubSub-->>WS: Message received
    WS-->>Browser: {"type": "job_complete", ...}
    Browser->>Browser: Update job status card

    Note over Browser,Logger: Heartbeat
    loop Every 30s
        WS-->>Browser: {"type": "ping"}
        Browser-->>WS: {"type": "pong"}
    end

    Note over Browser,Logger: Disconnection
    Browser->>WS: Close connection
    WS->>PubSub: UNSUBSCRIBE logs:*
    WS-->>Browser: Connection closed
```

---

### 10. Complete Data Lifecycle

```mermaid
flowchart TB
    subgraph Sources["Data Sources"]
        BigQuery["BigQuery\ngithubarchive.*"]
        GitHubAPI["GitHub API\n(metadata)"]
    end

    subgraph Ingestion["Data Ingestion"]
        Fetch["Fetch from\nBigQuery"]
        Parse["Parse & Map\nevent types"]
        Filter["Filter bots\n& duplicates"]
        Validate["Validate\ndata integrity"]
    end

    subgraph Storage["Data Storage"]
        subgraph Primary["Primary Tables"]
            Users["github_users\n(identity)"]
            Events["contribution_events\n(raw data)"]
            RepoLB["repository_leaderboards\n(per-repo scores)"]
            GlobalLB["global_leaderboard\n(aggregated)"]
        end

        subgraph Tracking["Tracking Tables"]
            Jobs["scrape_jobs\n(job history)"]
            Windows["scrape_windows\n(scrape history)"]
            Costs["cost_records\n(billing)"]
            Audit["audit_log\n(actions)"]
        end

        subgraph Config["Configuration"]
            Weights["scoring_weights"]
            Budget["budget_config"]
        end
    end

    subgraph Processing["Data Processing"]
        Score["Calculate\nscores"]
        Rank["Assign\nrankings"]
        Aggregate["Aggregate\nglobal stats"]
    end

    subgraph Access["Data Access"]
        API["REST API\n/api/v1/*"]
        Dashboard["Dashboard\n/dashboard"]
        Export["Export\n(future)"]
    end

    subgraph Maintenance["Data Maintenance"]
        Cleanup["Cleanup old\naudit logs"]
        Vacuum["VACUUM\nANALYZE"]
        Backup["pg_dump\nbackup"]
    end

    BigQuery --> Fetch
    GitHubAPI --> Fetch
    Fetch --> Parse
    Parse --> Filter
    Filter --> Validate

    Validate --> Users
    Validate --> Events
    Events --> Score
    Score --> RepoLB
    RepoLB --> Rank
    Rank --> Aggregate
    Aggregate --> GlobalLB

    Validate --> Jobs
    Validate --> Windows
    Validate --> Costs
    Validate --> Audit

    Users --> API
    RepoLB --> API
    GlobalLB --> API
    API --> Dashboard

    Audit --> Cleanup
    Events --> Vacuum
    Users --> Backup
    GlobalLB --> Backup

    classDef source fill:#e1f5fe,stroke:#01579b
    classDef ingest fill:#fff3e0,stroke:#e65100
    classDef primary fill:#e8f5e9,stroke:#2e7d32
    classDef tracking fill:#f3e5f5,stroke:#7b1fa2
    classDef process fill:#fce4ec,stroke:#c2185b
    classDef access fill:#e0f2f1,stroke:#00695c
    classDef maintain fill:#fafafa,stroke:#616161

    class BigQuery,GitHubAPI source
    class Fetch,Parse,Filter,Validate ingest
    class Users,Events,RepoLB,GlobalLB primary
    class Jobs,Windows,Costs,Audit tracking
    class Score,Rank,Aggregate process
    class API,Dashboard,Export access
    class Cleanup,Vacuum,Backup maintain
```

---

## Diagram Legend

| Symbol | Meaning |
|--------|---------|
| 🟢 Green | Success / Approved / Healthy |
| 🔴 Red | Error / Rejected / Failed |
| 🟡 Yellow | Warning / Decision Point |
| 🔵 Blue | Information / Configuration |
| 🟣 Purple | Tracking / Monitoring |
| ⬜ Gray | Maintenance / Background |

---

## Viewing Notes

These Mermaid diagrams render best in:
- **GitHub** - Native markdown preview
- **VS Code** - With Mermaid extension
- **Mermaid Live Editor** - https://mermaid.live
- **GitBook/Docusaurus** - Documentation platforms

For complex diagrams, zoom controls may be needed in some viewers.
