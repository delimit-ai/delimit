"""SQLite-based caching and dedup layer for social sensing.

Provides:
- seen_posts table: dedup + relevance scoring for Reddit (and future platforms)
- scan_meta table: per-subreddit scan timestamps and high-water marks
- Relevance scoring with keyword/subreddit boosting
- Lazy DB creation on first use (thread-safe)

Cache location: ~/.delimit/social_cache.db
"""

import logging
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("delimit.ai.social_cache")

CACHE_DB_PATH = Path.home() / ".delimit" / "social_cache.db"

# Thread-local storage for SQLite connections (sqlite3 objects are not
# safe to share across threads).
_local = threading.local()
_init_lock = threading.Lock()
_db_initialized = False


# ── Relevance keywords and weights ─────────────────────────────────────

# High-value keywords strongly associated with Delimit's core domain
RELEVANCE_KEYWORDS_HIGH: Dict[str, float] = {
    "openapi": 0.35,
    "swagger": 0.30,
    "breaking change": 0.40,
    "breaking changes": 0.40,
    "api governance": 0.45,
    "api contract": 0.40,
    "api contracts": 0.40,
    "api versioning": 0.35,
    "semver": 0.35,
    "mcp server": 0.30,
    "mcp tool": 0.30,
    "model context protocol": 0.30,
}

# Medium-value keywords: AI coding tools, adjacent territory
RELEVANCE_KEYWORDS_MED: Dict[str, float] = {
    "claude code": 0.25,
    "codex": 0.20,
    "gemini cli": 0.25,
    "cursor": 0.15,
    "api diff": 0.30,
    "api lint": 0.30,
    "api migration": 0.25,
    "schema validation": 0.20,
    "backward compatible": 0.25,
    "backwards compatible": 0.25,
    "backward compatibility": 0.25,
    "backwards compatibility": 0.25,
}

# Subreddit relevance boosts
SUBREDDIT_BOOSTS: Dict[str, float] = {
    "claudeai": 0.20,
    "chatgptcoding": 0.20,
    "devops": 0.15,
    "webdev": 0.10,
    "experienceddevs": 0.15,
    "programming": 0.05,
    "vibecoding": 0.15,
    "ai_agents": 0.15,
    "contextengineering": 0.20,
}

# Subreddits that get penalized unless they mention dev tools
GENERIC_SUBREDDITS: set = {
    "entrepreneur", "startups", "sideproject", "saas",
}

DEV_TOOL_TERMS: set = {
    "api", "developer", "dev tool", "devtool", "sdk", "cli",
    "cicd", "ci/cd", "pipeline", "openapi", "swagger", "github action",
}


def _get_conn() -> sqlite3.Connection:
    """Get a thread-local SQLite connection, creating the DB lazily."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn

    global _db_initialized
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(CACHE_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # Lazy schema creation (idempotent)
    with _init_lock:
        if not _db_initialized:
            _create_schema(conn)
            _db_initialized = True

    _local.conn = conn
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS seen_posts (
            post_id          TEXT PRIMARY KEY,
            subreddit        TEXT NOT NULL DEFAULT '',
            title            TEXT NOT NULL DEFAULT '',
            score            INTEGER NOT NULL DEFAULT 0,
            num_comments     INTEGER NOT NULL DEFAULT 0,
            first_seen       TEXT NOT NULL,
            last_seen        TEXT NOT NULL,
            relevance_score  REAL NOT NULL DEFAULT 0.0,
            actioned         INTEGER NOT NULL DEFAULT 0,
            venture          TEXT NOT NULL DEFAULT '',
            fingerprint      TEXT NOT NULL DEFAULT '',
            canonical_url    TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_seen_posts_subreddit
            ON seen_posts(subreddit);
        CREATE INDEX IF NOT EXISTS idx_seen_posts_relevance
            ON seen_posts(relevance_score);
        CREATE INDEX IF NOT EXISTS idx_seen_posts_first_seen
            ON seen_posts(first_seen);

        CREATE TABLE IF NOT EXISTS scan_meta (
            subreddit        TEXT PRIMARY KEY,
            last_scan        TEXT NOT NULL,
            high_water_mark  TEXT NOT NULL DEFAULT '',
            posts_seen       INTEGER NOT NULL DEFAULT 0,
            posts_new        INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()


def compute_relevance_score(
    title: str,
    body: str,
    subreddit: str,
    score: int = 0,
    num_comments: int = 0,
) -> float:
    """Compute a 0.0-1.0 relevance score for a Reddit post.

    Scoring layers:
    1. Keyword matching (high + medium value terms)
    2. Subreddit boost/penalty
    3. Engagement signal (mild boost for proven discussion)
    """
    text_lower = f"{title} {body}".lower()
    sub_lower = subreddit.lower().lstrip("r/")

    relevance = 0.0

    # Layer 1: keyword matching
    for keyword, weight in RELEVANCE_KEYWORDS_HIGH.items():
        if keyword in text_lower:
            relevance += weight

    for keyword, weight in RELEVANCE_KEYWORDS_MED.items():
        if keyword in text_lower:
            relevance += weight

    # Layer 2: subreddit boost
    boost = SUBREDDIT_BOOSTS.get(sub_lower, 0.0)
    relevance += boost

    # Penalty for generic subreddits without dev tool mentions
    if sub_lower in GENERIC_SUBREDDITS:
        has_dev_term = any(term in text_lower for term in DEV_TOOL_TERMS)
        if not has_dev_term:
            relevance -= 0.20

    # Layer 3: engagement signal (mild, caps at +0.10)
    if score > 10 or num_comments > 5:
        relevance += 0.05
    if score > 50 or num_comments > 20:
        relevance += 0.05

    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, relevance))


def is_post_seen(post_id: str) -> bool:
    """Check if a post_id is already in the cache."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM seen_posts WHERE post_id = ?", (post_id,)
    ).fetchone()
    return row is not None


def cache_post(
    post_id: str,
    subreddit: str,
    title: str,
    score: int,
    num_comments: int,
    relevance_score: float,
    venture: str = "",
    fingerprint: str = "",
    canonical_url: str = "",
) -> bool:
    """Insert a new post into the cache. Returns True if inserted (new), False if already exists."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            """INSERT INTO seen_posts
               (post_id, subreddit, title, score, num_comments,
                first_seen, last_seen, relevance_score, venture,
                fingerprint, canonical_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (post_id, subreddit, title, score, num_comments,
             now, now, relevance_score, venture, fingerprint, canonical_url),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Already exists -- update last_seen and score
        conn.execute(
            """UPDATE seen_posts
               SET last_seen = ?, score = ?, num_comments = ?
               WHERE post_id = ?""",
            (now, score, num_comments, post_id),
        )
        conn.commit()
        return False


def mark_actioned(post_id: str) -> None:
    """Mark a post as actioned (won't be returned in future scans)."""
    conn = _get_conn()
    conn.execute(
        "UPDATE seen_posts SET actioned = 1 WHERE post_id = ?", (post_id,)
    )
    conn.commit()


def update_scan_meta(subreddit: str, posts_seen: int, posts_new: int, high_water_mark: str = "") -> None:
    """Record scan metadata for a subreddit."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO scan_meta (subreddit, last_scan, high_water_mark, posts_seen, posts_new)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(subreddit) DO UPDATE SET
               last_scan = excluded.last_scan,
               high_water_mark = CASE
                   WHEN excluded.high_water_mark != '' THEN excluded.high_water_mark
                   ELSE scan_meta.high_water_mark
               END,
               posts_seen = excluded.posts_seen,
               posts_new = excluded.posts_new""",
        (subreddit, now, high_water_mark, posts_seen, posts_new),
    )
    conn.commit()


def get_scan_stats() -> Dict[str, Any]:
    """Get aggregate cache statistics."""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM seen_posts").fetchone()[0]
    actioned = conn.execute("SELECT COUNT(*) FROM seen_posts WHERE actioned = 1").fetchone()[0]
    high_relevance = conn.execute(
        "SELECT COUNT(*) FROM seen_posts WHERE relevance_score > 0.8"
    ).fetchone()[0]
    medium_relevance = conn.execute(
        "SELECT COUNT(*) FROM seen_posts WHERE relevance_score > 0.3 AND relevance_score <= 0.8"
    ).fetchone()[0]
    low_relevance = conn.execute(
        "SELECT COUNT(*) FROM seen_posts WHERE relevance_score <= 0.3"
    ).fetchone()[0]

    subreddit_counts = {}
    for row in conn.execute(
        "SELECT subreddit, COUNT(*) as cnt FROM seen_posts GROUP BY subreddit ORDER BY cnt DESC LIMIT 10"
    ):
        subreddit_counts[row["subreddit"]] = row["cnt"]

    return {
        "total_cached": total,
        "actioned": actioned,
        "high_relevance": high_relevance,
        "medium_relevance": medium_relevance,
        "low_relevance": low_relevance,
        "top_subreddits": subreddit_counts,
    }


def get_high_priority_posts(min_score: float = 0.8, limit: int = 20) -> List[Dict]:
    """Get high-priority posts that haven't been actioned yet."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT post_id, subreddit, title, score, num_comments,
                  relevance_score, venture, fingerprint, canonical_url, first_seen
           FROM seen_posts
           WHERE relevance_score >= ? AND actioned = 0
           ORDER BY relevance_score DESC, score DESC
           LIMIT ?""",
        (min_score, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def prune_old_posts(days: int = 30) -> int:
    """Remove posts older than N days that were never actioned. Returns count removed."""
    conn = _get_conn()
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cursor = conn.execute(
        "DELETE FROM seen_posts WHERE actioned = 0 AND first_seen < ?",
        (cutoff,),
    )
    conn.commit()
    return cursor.rowcount


def close_connection() -> None:
    """Close the thread-local connection if open."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None
