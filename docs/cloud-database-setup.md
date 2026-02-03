# Cloud Database Setup for GitHub Actions

This guide explains how to set up a cloud-hosted PostgreSQL database for the scheduled pipeline to run via GitHub Actions.

## Recommended Providers

| Provider | Free Tier | Best For |
|----------|-----------|----------|
| [Supabase](https://supabase.com) | 500MB, 2 projects | Easy setup, great UI |
| [Neon](https://neon.tech) | 512MB, unlimited projects | Serverless, auto-scaling |
| [Railway](https://railway.app) | $5/month credit | Simple deployment |
| [Render](https://render.com) | 90 days free | Full PaaS solution |

## Setup with Supabase (Recommended)

### 1. Create Account & Project

1. Go to [supabase.com](https://supabase.com) and sign up
2. Create a new project
3. Choose a region close to GitHub's servers (US East recommended)
4. Set a secure database password

### 2. Get Connection String

1. Go to **Settings > Database**
2. Under **Connection string**, copy the URI format:
   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
   ```

### 3. Configure for GitHub Actions

For GitHub Actions, use the **Session pooler** connection (port 5432) to avoid connection timeouts:

```
postgresql://postgres.[PROJECT-REF]:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres
```

## Setup with Neon

### 1. Create Account & Project

1. Go to [neon.tech](https://neon.tech) and sign up
2. Create a new project
3. Create a database named `leaderboard`

### 2. Get Connection String

1. Go to **Dashboard > Connection Details**
2. Copy the connection string:
   ```
   postgresql://[user]:[password]@[host]/leaderboard?sslmode=require
   ```

## Configure GitHub Secrets

Add these secrets to your repository:

1. Go to **Settings > Secrets and variables > Actions**
2. Add the following secrets:

| Secret Name | Description |
|-------------|-------------|
| `DATABASE_URL` | PostgreSQL connection string from cloud provider |
| `REDIS_URL` | Redis URL (optional for GitHub Actions - can omit) |
| `BIGQUERY_PROJECT` | Your Google Cloud project ID |
| `BIGQUERY_CREDENTIALS` | Full JSON content of service account key |
| `GH_PAT` | GitHub Personal Access Token (for API calls) |

### Example DATABASE_URL Format

```
# Supabase (pooled)
postgresql://postgres.[ref]:[password]@aws-0-us-east-1.pooler.supabase.com:5432/postgres

# Neon
postgresql://[user]:[password]@[endpoint].neon.tech/leaderboard?sslmode=require

# Railway
postgresql://[user]:[password]@[host].railway.app:5432/railway
```

## Initialize Database

After setting up the cloud database, run the initialization:

### Option 1: Local Initialization

```bash
# Set the cloud DATABASE_URL locally
export DATABASE_URL="postgresql://..."

# Run init script
python scripts/init_db.py
```

### Option 2: GitHub Actions Initialization

Run the workflow manually:

1. Go to **Actions > Scheduled Pipeline**
2. Click **Run workflow**
3. Select `full-pipeline` action

The pipeline will create tables if they don't exist.

## Testing the Connection

### Local Test

```python
import asyncio
from src.db.database import create_worker_session_maker

async def test():
    async with create_worker_session_maker()() as db:
        result = await db.execute("SELECT 1")
        print("Connection successful!")

asyncio.run(test())
```

### GitHub Actions Test

Run a dry-run of the pipeline:

1. Go to **Actions > Scheduled Pipeline**
2. Click **Run workflow**
3. Set `dry_run` to `true`
4. Check the logs for connection success

## Migrating Existing Data

If you have existing local data to migrate:

```bash
# Export from local PostgreSQL
pg_dump -h localhost -p 5433 -U postgres -d leaderboard > backup.sql

# Import to cloud (modify connection details)
psql "postgresql://user:pass@cloud-host/database" < backup.sql
```

## Cost Considerations

| Provider | Free Limit | When to Upgrade |
|----------|------------|-----------------|
| Supabase | 500MB | ~50k contributors |
| Neon | 512MB | ~50k contributors |
| Railway | $5/mo credit | Heavy usage |

Current database size estimate:
- ~1KB per contributor (enriched)
- ~82k contributors = ~80MB
- Well within free tier limits

## Troubleshooting

### Connection Timeout

- Use pooled connections (Supabase: `pooler.supabase.com`)
- Set `statement_timeout` in DATABASE_URL: `?statement_timeout=60000`

### SSL Required

Most cloud providers require SSL:
```
?sslmode=require
```

### Permission Denied

Ensure database user has:
- CREATE TABLE
- SELECT, INSERT, UPDATE, DELETE
- USAGE on schema

## Security Best Practices

1. **Never commit credentials** - Use GitHub Secrets only
2. **Use service accounts** - Don't use personal credentials
3. **Restrict IP access** - If possible, allow only GitHub Actions IPs
4. **Rotate secrets** - Change passwords periodically
5. **Monitor usage** - Set up alerts for unusual activity
