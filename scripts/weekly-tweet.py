#!/usr/bin/env python3
"""
Weekly Activity Tweet for @delimit_ai.

Gathers GitHub activity stats across delimit-ai repos and npm download
counts, then posts a summary tweet via the Twitter API.

Reads Twitter credentials from environment variables (for GitHub Actions).
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone

import requests
import tweepy

ORG = "delimit-ai"
NPM_PACKAGE = "delimit-cli"
GITHUB_API = "https://api.github.com"
NPM_API = "https://api.npmjs.org"


def get_org_repos():
    """Fetch all public repos for the org."""
    repos = []
    page = 1
    while True:
        resp = requests.get(
            f"{GITHUB_API}/orgs/{ORG}/repos",
            params={"type": "public", "per_page": 100, "page": page},
        )
        if resp.status_code != 200:
            break
        batch = resp.json()
        if not batch:
            break
        repos.extend(batch)
        page += 1
    return repos


def get_total_stars(repos):
    """Sum stargazers across all repos."""
    return sum(r.get("stargazers_count", 0) for r in repos)


def get_commits_last_week(repos):
    """Count commits in the last 7 days across all repos."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    total = 0
    for repo in repos:
        name = repo["full_name"]
        page = 1
        while True:
            resp = requests.get(
                f"{GITHUB_API}/repos/{name}/commits",
                params={"since": since, "per_page": 100, "page": page},
            )
            if resp.status_code != 200:
                break
            batch = resp.json()
            if not batch:
                break
            total += len(batch)
            if len(batch) < 100:
                break
            page += 1
    return total


def get_prs_merged_last_week(repos):
    """Count PRs merged in the last 7 days."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    total = 0
    for repo in repos:
        name = repo["full_name"]
        resp = requests.get(
            f"{GITHUB_API}/repos/{name}/pulls",
            params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 100},
        )
        if resp.status_code != 200:
            continue
        for pr in resp.json():
            if pr.get("merged_at") and pr["merged_at"] >= since:
                total += 1
    return total


def get_issues_stats(repos):
    """Count issues opened and closed in the last 7 days."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    opened = 0
    closed = 0
    for repo in repos:
        name = repo["full_name"]
        # Opened
        resp = requests.get(
            f"{GITHUB_API}/repos/{name}/issues",
            params={"state": "all", "since": since, "per_page": 100},
        )
        if resp.status_code == 200:
            for issue in resp.json():
                if issue.get("pull_request"):
                    continue
                if issue.get("created_at", "") >= since:
                    opened += 1
                if issue.get("closed_at") and issue["closed_at"] >= since:
                    closed += 1
    return opened, closed


def get_npm_downloads():
    """Get npm download count for the last week."""
    resp = requests.get(f"{NPM_API}/downloads/point/last-week/{NPM_PACKAGE}")
    if resp.status_code != 200:
        return 0
    return resp.json().get("downloads", 0)


def format_tweet(npm_downloads, total_stars, prs_merged, commits):
    """Format the weekly summary tweet."""
    lines = ["This week at Delimit:", ""]
    if npm_downloads > 0:
        lines.append(f"\U0001f4e6 {npm_downloads:,} npm downloads")
    if total_stars > 0:
        lines.append(f"\u2b50 {total_stars:,} stars")
    if prs_merged > 0:
        lines.append(f"\U0001f500 {prs_merged:,} PRs merged")
    if commits > 0:
        lines.append(f"\U0001f6e0\ufe0f {commits:,} commits")
    lines.append("")
    lines.append("Keep Building.")
    lines.append("")
    lines.append("delimit.ai")
    return "\n".join(lines)


def post_tweet(text):
    """Post tweet using tweepy with OAuth 1.0a credentials from env vars."""
    consumer_key = os.environ.get("TWITTER_CONSUMER_KEY")
    consumer_secret = os.environ.get("TWITTER_CONSUMER_SECRET")
    access_token = os.environ.get("TWITTER_ACCESS_TOKEN")
    access_token_secret = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET")

    if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
        print("ERROR: Missing Twitter credentials in environment variables.")
        sys.exit(1)

    client = tweepy.Client(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )
    response = client.create_tweet(text=text)
    print(f"Tweet posted: https://x.com/delimit_ai/status/{response.data['id']}")


def main():
    print("Gathering weekly stats for delimit-ai...")

    repos = get_org_repos()
    print(f"  Found {len(repos)} public repos")

    npm_downloads = get_npm_downloads()
    print(f"  npm downloads (last week): {npm_downloads}")

    total_stars = get_total_stars(repos)
    print(f"  Total stars: {total_stars}")

    prs_merged = get_prs_merged_last_week(repos)
    print(f"  PRs merged (last week): {prs_merged}")

    commits = get_commits_last_week(repos)
    print(f"  Commits (last week): {commits}")

    # Don't tweet if there's nothing to report
    if npm_downloads == 0 and total_stars == 0 and prs_merged == 0 and commits == 0:
        print("No activity this week. Skipping tweet.")
        return

    tweet_text = format_tweet(npm_downloads, total_stars, prs_merged, commits)
    print(f"\nTweet ({len(tweet_text)} chars):\n{tweet_text}\n")

    post_tweet(tweet_text)


if __name__ == "__main__":
    main()
