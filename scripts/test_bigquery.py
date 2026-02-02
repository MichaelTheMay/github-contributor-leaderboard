#!/usr/bin/env python
"""Test BigQuery connection."""

import os
from google.cloud import bigquery

# Set credentials path
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"C:\dev\github-contributor-leaderboard\secrets\gcp-sa.json"

def test_connection():
    """Test basic BigQuery connection with GitHub Archive."""
    client = bigquery.Client(project="github-leaderboard")

    # Simple test query - get 5 recent events from a popular repo
    query = """
    SELECT
        type,
        actor.login as username,
        created_at
    FROM `githubarchive.day.20240101`
    WHERE repo.name = 'facebook/react'
    LIMIT 5
    """

    print("Testing BigQuery connection...")
    print(f"Project: {client.project}")

    try:
        query_job = client.query(query)
        results = query_job.result()

        print("\nSample GitHub events from facebook/react (Jan 1, 2024):")
        print("-" * 60)
        for row in results:
            print(f"  {row.type:30} by {row.username}")

        print("\nBigQuery connection successful!")
        return True
    except Exception as e:
        print(f"\nError: {e}")
        return False

if __name__ == "__main__":
    test_connection()
