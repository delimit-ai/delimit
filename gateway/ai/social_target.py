"""Social targeting engine -- discover engagement opportunities across platforms.

Scans X (via xAI Responses API), Reddit (via RapidAPI Reddit34), Hacker News
(Algolia API), and Dev.to for posts where Jamsons ventures can genuinely engage.
NamePros is flagged as manual_check_needed (no API).

Targets are deduplicated via fingerprint and stored in append-only JSONL.
Platform configuration is user-configurable via ~/.delimit/social_target_config.json.
"""

import copy
import json
import logging
import os
import subprocess
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("delimit.ai.social_target")

TARGETS_FILE = Path.home() / ".delimit" / "social_targets.jsonl"
SOCIAL_TARGET_CONFIG = Path.home() / ".delimit" / "social_target_config.json"

# -----------------------------------------------------------------------
#  User-configurable platform config
# -----------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "platforms": {
        "x": {"enabled": True, "provider": "twttr241"},
        "reddit": {"enabled": True, "provider": "proxy"},
        "github": {"enabled": True, "provider": "gh_cli"},
        "hn": {"enabled": True, "provider": "algolia"},
        "devto": {"enabled": True, "provider": "public_api"},
        "namepros": {"enabled": False, "provider": "manual"},
    },
    "subreddits": {},
    "github_queries": {},
    "scan_limit": 10,
    "min_engagement": {"score": 1, "comments": 2},
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override values win."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_config() -> Dict[str, Any]:
    """Load social target config from disk, merging with defaults.

    - Loads from SOCIAL_TARGET_CONFIG if it exists
    - Falls back to DEFAULT_CONFIG
    - Merges user overrides with defaults (user config wins)
    - Auto-detects available API keys and disables platforms with no access
    """
    config = copy.deepcopy(DEFAULT_CONFIG)

    if SOCIAL_TARGET_CONFIG.exists():
        try:
            user_config = json.loads(SOCIAL_TARGET_CONFIG.read_text())
            config = _deep_merge(config, user_config)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logger.warning("Failed to load social target config: %s", e)

    # Auto-detect available platforms and disable those without access
    detection = _detect_available_platforms()
    for platform, info in detection.items():
        if platform in config["platforms"]:
            # Only auto-disable if no user override exists
            if not SOCIAL_TARGET_CONFIG.exists():
                config["platforms"][platform]["enabled"] = info["available"]
            elif platform not in _load_user_platform_overrides():
                config["platforms"][platform]["enabled"] = info["available"]

    return config


def _load_user_platform_overrides() -> set:
    """Return the set of platform names explicitly set in user config."""
    if not SOCIAL_TARGET_CONFIG.exists():
        return set()
    try:
        user_config = json.loads(SOCIAL_TARGET_CONFIG.read_text())
        return set(user_config.get("platforms", {}).keys())
    except (json.JSONDecodeError, ValueError, OSError):
        return set()


def _detect_available_platforms() -> Dict[str, Dict[str, Any]]:
    """Check which platforms have the necessary credentials/access.

    Returns dict of platform -> {available: bool, provider: str, reason: str}.
    """
    result: Dict[str, Dict[str, Any]] = {}

    # X/Twttr241: RapidAPI key exists?
    rapidapi_key = _get_rapidapi_key()
    if rapidapi_key:
        result["x"] = {"available": True, "provider": "twttr241", "reason": "RapidAPI key found"}
    else:
        # Fallback: xAI API key?
        xai_key = _get_xai_api_key()
        if xai_key:
            result["x"] = {"available": True, "provider": "xai", "reason": "xAI API key found (fallback)"}
        else:
            result["x"] = {"available": False, "provider": "none", "reason": "No RapidAPI or xAI API key"}

    # Reddit: proxy or RapidAPI
    proxy_url = os.environ.get("DELIMIT_REDDIT_PROXY", "")
    if proxy_url:
        result["reddit"] = {"available": True, "provider": "proxy", "reason": "DELIMIT_REDDIT_PROXY env set"}
    elif _test_reddit_proxy():
        result["reddit"] = {"available": True, "provider": "proxy", "reason": "Local proxy responding"}
    elif rapidapi_key:
        result["reddit"] = {"available": True, "provider": "rapidapi", "reason": "RapidAPI key found (fallback)"}
    else:
        result["reddit"] = {"available": False, "provider": "none", "reason": "No proxy or RapidAPI key"}

    # GitHub: gh auth status
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            result["github"] = {"available": True, "provider": "gh_cli", "reason": "gh authenticated"}
        else:
            result["github"] = {"available": False, "provider": "gh_cli", "reason": "gh not authenticated"}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        result["github"] = {"available": False, "provider": "gh_cli", "reason": "gh CLI not found"}

    # HN: always available (public API, no auth)
    result["hn"] = {"available": True, "provider": "algolia", "reason": "Public API, no auth needed"}

    # Dev.to: always available (public API, no auth)
    result["devto"] = {"available": True, "provider": "public_api", "reason": "Public API, no auth needed"}

    # NamePros: manual only
    result["namepros"] = {"available": False, "provider": "manual", "reason": "No API, manual check only"}

    return result


def _save_config(config: Dict[str, Any]) -> None:
    """Write config to disk."""
    SOCIAL_TARGET_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    SOCIAL_TARGET_CONFIG.write_text(json.dumps(config, indent=2) + "\n")


def get_config_status() -> Dict[str, Any]:
    """Return current config and platform availability for the MCP tool."""
    config = _load_config()
    detection = _detect_available_platforms()
    return {
        "config": config,
        "platform_availability": detection,
        "config_file": str(SOCIAL_TARGET_CONFIG),
        "config_file_exists": SOCIAL_TARGET_CONFIG.exists(),
    }


def update_platform_config(
    platform: str,
    enabled: Optional[bool] = None,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a single platform's config and save."""
    config = _load_config()
    if platform not in config["platforms"]:
        config["platforms"][platform] = {"enabled": True, "provider": ""}

    if enabled is not None:
        config["platforms"][platform]["enabled"] = enabled
    if provider:
        config["platforms"][platform]["provider"] = provider

    _save_config(config)
    return {"updated": True, "platform": platform, "config": config["platforms"][platform]}


def add_subreddits(venture: str, subreddits: List[str]) -> Dict[str, Any]:
    """Add subreddits to scan for a venture."""
    config = _load_config()
    existing = config.get("subreddits", {}).get(venture, [])
    new_subs = [s for s in subreddits if s not in existing]
    if venture not in config.get("subreddits", {}):
        config["subreddits"][venture] = []
    config["subreddits"][venture].extend(new_subs)
    _save_config(config)
    return {"venture": venture, "added": new_subs, "total": config["subreddits"][venture]}

# -----------------------------------------------------------------------
#  Per-venture routing config
# -----------------------------------------------------------------------

VENTURE_CONFIG = {
    "delimit": {
        "topics": [
            "API governance", "breaking changes", "OpenAPI", "API linting",
            "MCP server", "MCP tools", "CLAUDE.md", "claude code",
            "AI coding", "vibe coding", "semver",
        ],
        "exclude_terms": ["delimit_ai"],
        "owned_accounts": ["delimit_ai", "delimitdev"],
        "priority": "P0",
    },
    "domainvested": {
        "topics": [
            "domain investing", "domain appraisal", "domain flipping",
            "expired domains", "brandable domains", "domain valuation", "NamePros",
        ],
        "exclude_terms": ["domainvested"],
        "owned_accounts": ["domainvested"],
        "priority": "P0",
    },
    "wirereport": {
        "topics": [
            "sports API", "live sports data", "sports scores API",
            "sports news automation",
        ],
        "exclude_terms": ["wire_report", "wirereport"],
        "owned_accounts": ["wirereporthq"],
        "priority": "P2",
    },
    "livetube": {
        "topics": [
            "live streaming aggregator", "multi-stream",
            "twitch alternatives", "live stream discovery",
        ],
        "exclude_terms": ["livetube"],
        "owned_accounts": ["livetube_ai"],
        "priority": "P2",
    },
    "stakeone": {
        "topics": [
            "Harmony ONE", "harmony validator", "ONE staking",
            "harmony blockchain",
        ],
        "exclude_terms": ["validatorone", "stake_one"],
        "owned_accounts": ["validatorone"],
        "priority": "P1",
    },
}


# -----------------------------------------------------------------------
#  GitHub-specific config
# -----------------------------------------------------------------------

VENTURE_GITHUB_QUERIES = {
    "delimit": [
        "openapi breaking changes",
        "API governance CI",
        "MCP server claude code",
        "API linting github action",
    ],
    "domainvested": [
        "domain appraisal tool",
        "domain valuation API",
    ],
    "stakeone": [
        "harmony one validator",
        "harmony staking",
    ],
}

OWN_REPOS = [
    "delimit-ai/delimit-mcp-server",
    "delimit-ai/delimit-action",
    "delimit-ai/delimit-quickstart",
]

INTERNAL_USERS = {"infracore", "crypttrx"}


# -----------------------------------------------------------------------
#  JSONL persistence helpers
# -----------------------------------------------------------------------

def _load_known_fingerprints() -> set:
    """Load all fingerprints from the targets file for dedup."""
    fps: set = set()
    if not TARGETS_FILE.exists():
        return fps
    try:
        for line in TARGETS_FILE.read_text().splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                fp = entry.get("fingerprint", "")
                if fp:
                    fps.add(fp)
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception:
        pass
    return fps


def _append_target(target: Dict[str, Any]) -> None:
    """Append a single target to the JSONL file."""
    TARGETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TARGETS_FILE, "a") as f:
        f.write(json.dumps(target) + "\n")


# -----------------------------------------------------------------------
#  Venture routing
# -----------------------------------------------------------------------

def _route_venture(text: str) -> tuple:
    """Match text against venture topics. Returns (venture, confidence, rationale)."""
    text_lower = text.lower()
    best_venture = None
    best_score = 0
    best_matches: List[str] = []

    for venture, config in VENTURE_CONFIG.items():
        # Check exclude terms first
        if any(ex.lower() in text_lower for ex in config.get("exclude_terms", [])):
            continue
        matches = [t for t in config["topics"] if t.lower() in text_lower]
        score = len(matches)
        if score > best_score:
            best_score = score
            best_venture = venture
            best_matches = matches

    if not best_venture:
        return None, 0.0, "No venture topic match"

    confidence = min(0.95, 0.5 + (best_score * 0.15))
    rationale = f"Matched topics: {', '.join(best_matches[:3])}"
    return best_venture, confidence, rationale


def _classify_target(text: str, author_followers: int = 0) -> str:
    """Classify a target as reply, strategic, or both."""
    is_question = any(q in text.lower() for q in ["?", "how do", "anyone", "looking for", "recommendations"])
    high_reach = author_followers > 5000

    if is_question and high_reach:
        return "both"
    if high_reach:
        return "strategic"
    if is_question:
        return "reply"
    return "reply"


# -----------------------------------------------------------------------
#  xAI API key resolution
# -----------------------------------------------------------------------

def _get_xai_api_key() -> str:
    """Resolve xAI API key from env or .mcp.json."""
    key = os.environ.get("XAI_API_KEY", "")
    if key:
        return key
    # Try .mcp.json
    mcp_path = Path.home() / ".mcp.json"
    if not mcp_path.exists():
        mcp_path = Path("/root/.mcp.json")
    if mcp_path.exists():
        try:
            cfg = json.loads(mcp_path.read_text())
            key = (cfg.get("mcpServers", {})
                   .get("xai", {})
                   .get("env", {})
                   .get("XAI_API_KEY", ""))
            if key:
                return key
            # Also check delimit server env
            key = (cfg.get("mcpServers", {})
                   .get("delimit", {})
                   .get("env", {})
                   .get("XAI_API_KEY", ""))
        except Exception:
            pass
    return key


# -----------------------------------------------------------------------
#  Platform scanners
# -----------------------------------------------------------------------

def _scan_x_twttr(queries: List[str], limit: int, known_fps: set) -> List[Dict]:
    """Scan X/Twitter via RapidAPI Twttr241 (free, structured data)."""
    api_key = _get_rapidapi_key()
    if not api_key:
        return []

    targets: List[Dict] = []
    combined_query = " OR ".join(queries[:5])
    encoded_q = urllib.parse.quote(combined_query)
    url = f"https://twitter241.p.rapidapi.com/search-v2?query={encoded_q}&type=Latest&count={limit}"

    req = urllib.request.Request(
        url,
        headers={
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": "twitter241.p.rapidapi.com",
            "User-Agent": "Delimit/3.11.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())

        # Navigate: result.timeline.instructions[].entries[].content.itemContent.tweet_results.result
        instructions = (
            result.get("result", {})
            .get("timeline", {})
            .get("instructions", [])
        )

        for instruction in instructions:
            for entry in instruction.get("entries", []):
                tweet_result = (
                    entry.get("content", {})
                    .get("itemContent", {})
                    .get("tweet_results", {})
                    .get("result", {})
                )
                if not tweet_result:
                    continue

                legacy = tweet_result.get("legacy", {})
                core = tweet_result.get("core", {})
                user_legacy = (
                    core.get("user_results", {})
                    .get("result", {})
                    .get("legacy", {})
                )

                tweet_id = legacy.get("id_str", "")
                screen_name = user_legacy.get("screen_name", "")
                followers = user_legacy.get("followers_count", 0) or 0
                full_text = legacy.get("full_text", "")
                likes = legacy.get("favorite_count", 0) or 0
                retweets = legacy.get("retweet_count", 0) or 0

                if not tweet_id or not full_text:
                    continue

                fp = f"x:{tweet_id}"
                if fp in known_fps:
                    continue

                venture, confidence, rationale = _route_venture(full_text)
                if not venture:
                    continue

                author = f"@{screen_name}" if screen_name else ""
                target = {
                    "fingerprint": fp,
                    "platform": "x",
                    "source_id": tweet_id,
                    "canonical_url": f"https://x.com/{screen_name}/status/{tweet_id}" if screen_name else f"https://x.com/i/status/{tweet_id}",
                    "author": author,
                    "author_followers": followers,
                    "content_snippet": full_text[:300],
                    "venture": venture,
                    "classification": _classify_target(full_text, followers),
                    "confidence": confidence,
                    "rationale": rationale,
                    "manual_check_needed": False,
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                    "status": "new",
                }
                targets.append(target)
                known_fps.add(fp)

                if len(targets) >= limit:
                    break
            if len(targets) >= limit:
                break

    except Exception as e:
        logger.warning("Twttr241 scan failed: %s", e)
        return []

    return targets


def _scan_x(queries: List[str], limit: int, known_fps: set, config: Optional[Dict] = None) -> List[Dict]:
    """Scan X/Twitter -- uses config to determine provider, falls back to xAI x_search."""
    platform_config = (config or {}).get("platforms", {}).get("x", {})
    provider = platform_config.get("provider", "twttr241")

    # Try Twttr241 first if configured (or default)
    if provider in ("twttr241", ""):
        targets = _scan_x_twttr(queries, limit, known_fps)
        if targets:
            return targets

    # Fallback or explicit xAI provider: xAI Responses API with x_search
    api_key = _get_xai_api_key()
    if not api_key:
        return [{"error": "No X scanner available (Twttr241 failed, XAI_API_KEY not configured)", "platform": "x"}]

    targets: List[Dict] = []
    # Batch queries to avoid too many API calls
    combined_query = " OR ".join(f'"{q}"' for q in queries[:5])
    prompt = (
        f"Search X/Twitter for recent posts about: {combined_query}. "
        f"Find up to {limit} posts from the last 24 hours that are asking questions, "
        f"sharing problems, or discussing these topics. "
        f"For each post, return the tweet ID, author handle, author follower count, "
        f"and a snippet of the content. Format as JSON array."
    )

    data = json.dumps({
        "model": "grok-4-0709",
        "tools": [{"type": "x_search"}],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4096,
    }).encode()

    req = urllib.request.Request(
        "https://api.x.ai/v1/responses",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Delimit/3.11.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())

        # Parse the response -- xAI Responses API returns output array
        response_text = ""
        if isinstance(result, dict):
            # Responses API format: result has "output" array
            for item in result.get("output", []):
                if item.get("type") == "message":
                    for content in item.get("content", []):
                        if content.get("type") == "output_text":
                            response_text = content.get("text", "")
                            break
            # Fallback: chat completions format
            if not response_text:
                for choice in result.get("choices", []):
                    msg = choice.get("message", {})
                    response_text = msg.get("content", "")
                    if response_text:
                        break

        if not response_text:
            logger.warning("xAI returned empty response for social targeting")
            return targets

        # Try to extract JSON from response
        parsed_tweets = _extract_json_array(response_text)
        for tweet in parsed_tweets[:limit]:
            tweet_id = str(tweet.get("id", tweet.get("tweet_id", "")))
            author = tweet.get("author", tweet.get("handle", tweet.get("username", "")))
            if author and not author.startswith("@"):
                author = f"@{author}"
            snippet = tweet.get("content", tweet.get("text", tweet.get("snippet", "")))
            followers = int(tweet.get("followers", tweet.get("author_followers", tweet.get("follower_count", 0))))

            fp = f"x:{tweet_id}"
            if fp in known_fps or not tweet_id:
                continue

            venture, confidence, rationale = _route_venture(snippet)
            if not venture:
                continue

            target = {
                "fingerprint": fp,
                "platform": "x",
                "source_id": tweet_id,
                "canonical_url": f"https://x.com/{author.lstrip('@')}/status/{tweet_id}" if author else f"https://x.com/i/status/{tweet_id}",
                "author": author,
                "author_followers": followers,
                "content_snippet": snippet[:300],
                "venture": venture,
                "classification": _classify_target(snippet, followers),
                "confidence": confidence,
                "rationale": rationale,
                "manual_check_needed": False,
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "status": "new",
            }
            targets.append(target)
            known_fps.add(fp)

    except urllib.error.HTTPError as e:
        logger.error("xAI API error: %s %s", e.code, e.reason)
        # Try to read error body for details
        try:
            err_body = e.read().decode()[:200]
            logger.error("xAI error body: %s", err_body)
        except Exception:
            pass
        targets.append({"error": f"xAI API error: {e.code} {e.reason}", "platform": "x"})
    except urllib.error.URLError as e:
        logger.error("xAI connection error: %s", e.reason)
        targets.append({"error": f"xAI connection error: {e.reason}", "platform": "x"})
    except Exception as e:
        logger.error("xAI scan failed: %s", e)
        targets.append({"error": f"xAI scan error: {e}", "platform": "x"})

    return targets


def _scan_hn(queries: List[str], limit: int, known_fps: set) -> List[Dict]:
    """Scan Hacker News via Algolia API."""
    targets: List[Dict] = []

    for query in queries[:3]:  # Limit query count
        encoded_q = urllib.parse.quote(query)
        url = f"https://hn.algolia.com/api/v1/search_by_date?tags=story&query={encoded_q}&hitsPerPage={limit}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Delimit/3.11.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            for hit in data.get("hits", [])[:limit]:
                story_id = str(hit.get("objectID", ""))
                fp = f"hn:{story_id}"
                if fp in known_fps or not story_id:
                    continue

                title = hit.get("title", "")
                author = hit.get("author", "")
                points = hit.get("points", 0) or 0
                snippet = title

                venture, confidence, rationale = _route_venture(title)
                if not venture:
                    continue

                target = {
                    "fingerprint": fp,
                    "platform": "hn",
                    "source_id": story_id,
                    "canonical_url": f"https://news.ycombinator.com/item?id={story_id}",
                    "author": author,
                    "author_followers": points,  # Use points as proxy for reach
                    "content_snippet": snippet[:300],
                    "venture": venture,
                    "classification": _classify_target(snippet, points),
                    "confidence": confidence,
                    "rationale": rationale,
                    "manual_check_needed": False,
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                    "status": "new",
                }
                targets.append(target)
                known_fps.add(fp)

                if len(targets) >= limit:
                    break

        except Exception as e:
            logger.error("HN scan error for query '%s': %s", query, e)
            continue

        if len(targets) >= limit:
            break

    return targets


def _scan_devto(queries: List[str], limit: int, known_fps: set) -> List[Dict]:
    """Scan Dev.to for recent articles matching venture topics."""
    targets: List[Dict] = []

    for query in queries[:3]:
        # Dev.to API uses tag-based search
        tag = query.lower().replace(" ", "").replace("-", "")[:20]
        url = f"https://dev.to/api/articles?tag={urllib.parse.quote(tag)}&top=1&per_page={limit}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Delimit/3.11.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                articles = json.loads(resp.read())

            if not isinstance(articles, list):
                continue

            for article in articles[:limit]:
                article_id = str(article.get("id", ""))
                fp = f"devto:{article_id}"
                if fp in known_fps or not article_id:
                    continue

                title = article.get("title", "")
                description = article.get("description", "")
                author = article.get("user", {}).get("username", "")
                reactions = article.get("positive_reactions_count", 0) or 0
                snippet = f"{title} - {description}"

                venture, confidence, rationale = _route_venture(snippet)
                if not venture:
                    continue

                target = {
                    "fingerprint": fp,
                    "platform": "devto",
                    "source_id": article_id,
                    "canonical_url": article.get("url", f"https://dev.to/{author}/{article.get('slug', article_id)}"),
                    "author": author,
                    "author_followers": reactions,
                    "content_snippet": snippet[:300],
                    "venture": venture,
                    "classification": _classify_target(snippet, reactions),
                    "confidence": confidence,
                    "rationale": rationale,
                    "manual_check_needed": False,
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                    "status": "new",
                }
                targets.append(target)
                known_fps.add(fp)

                if len(targets) >= limit:
                    break

        except Exception as e:
            logger.error("Dev.to scan error for tag '%s': %s", tag, e)
            continue

        if len(targets) >= limit:
            break

    return targets


def _gh_api(endpoint: str) -> Any:
    """Call GitHub API via the gh CLI. Returns parsed JSON or None on failure."""
    try:
        proc = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            logger.warning("gh api %s failed: %s", endpoint, proc.stderr[:200])
            return None
        return json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        logger.error("gh api %s timed out", endpoint)
        return None
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error("gh api %s error: %s", endpoint, e)
        return None


def _scan_github(queries: List[str], limit: int, known_fps: set, config: Optional[Dict] = None) -> List[Dict]:
    """Scan GitHub for repos and issues matching venture topics via gh CLI."""
    targets: List[Dict] = []

    # Phase 1: Repository search
    for query in queries[:5]:
        if len(targets) >= limit:
            break
        encoded_q = urllib.parse.quote(query)
        endpoint = f"search/repositories?q={encoded_q}&sort=updated&per_page={min(limit, 10)}"
        data = _gh_api(endpoint)
        if not data or not isinstance(data, dict):
            continue

        for repo in data.get("items", []):
            full_name = repo.get("full_name", "")
            fp = f"github:repo:{full_name}"
            if fp in known_fps or not full_name:
                continue

            stars = repo.get("stargazers_count", 0) or 0
            description = repo.get("description", "") or ""

            # Skip noise: 0 stars and no description
            if stars == 0 and not description:
                continue

            snippet = f"{full_name}: {description}"
            venture, confidence, rationale = _route_venture(snippet)
            if not venture:
                continue

            target = {
                "fingerprint": fp,
                "platform": "github",
                "source_id": full_name,
                "canonical_url": repo.get("html_url", f"https://github.com/{full_name}"),
                "author": repo.get("owner", {}).get("login", ""),
                "author_followers": stars,
                "content_snippet": snippet[:300],
                "venture": venture,
                "classification": _classify_target(snippet, stars),
                "confidence": confidence,
                "rationale": f"repo search: {rationale}",
                "manual_check_needed": False,
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "status": "new",
            }
            targets.append(target)
            known_fps.add(fp)

            if len(targets) >= limit:
                break

    # Phase 2: Issue/discussion search
    for query in queries[:3]:
        if len(targets) >= limit:
            break
        encoded_q = urllib.parse.quote(query)
        endpoint = f"search/issues?q={encoded_q}&sort=created&per_page={min(limit, 10)}"
        data = _gh_api(endpoint)
        if not data or not isinstance(data, dict):
            continue

        for issue in data.get("items", []):
            number = issue.get("number", "")
            html_url = issue.get("html_url", "")
            # Extract repo from URL: https://github.com/owner/repo/issues/123
            repo_name = "/".join(html_url.split("/")[3:5]) if html_url else ""
            fp = f"github:issue:{repo_name}:{number}"
            if fp in known_fps or not number:
                continue

            title = issue.get("title", "")
            body = (issue.get("body") or "")[:200]
            author = issue.get("user", {}).get("login", "")
            reactions = issue.get("reactions", {}).get("total_count", 0) or 0
            snippet = f"{title} {body}".strip()

            venture, confidence, rationale = _route_venture(snippet)
            if not venture:
                continue

            target = {
                "fingerprint": fp,
                "platform": "github",
                "source_id": f"{repo_name}#{number}",
                "canonical_url": html_url,
                "author": author,
                "author_followers": reactions,
                "content_snippet": snippet[:300],
                "venture": venture,
                "classification": _classify_target(snippet, reactions),
                "confidence": confidence,
                "rationale": f"issue search: {rationale}",
                "manual_check_needed": False,
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "status": "new",
            }
            targets.append(target)
            known_fps.add(fp)

            if len(targets) >= limit:
                break

    return targets


def _monitor_own_repos(known_fps: set) -> List[Dict]:
    """Monitor our own repos for external engagement (forks, stars, issues, PRs)."""
    targets: List[Dict] = []

    for repo in OWN_REPOS:
        # Check forks
        forks_data = _gh_api(f"repos/{repo}/forks?sort=newest&per_page=10")
        if isinstance(forks_data, list):
            for fork in forks_data:
                user = fork.get("owner", {}).get("login", "")
                if user in INTERNAL_USERS or not user:
                    continue
                fp = f"github:fork:{user}:{repo.split('/')[-1]}"
                if fp in known_fps:
                    continue

                targets.append({
                    "fingerprint": fp,
                    "platform": "github",
                    "source_id": fork.get("full_name", ""),
                    "canonical_url": fork.get("html_url", ""),
                    "author": user,
                    "author_followers": fork.get("stargazers_count", 0) or 0,
                    "content_snippet": f"{user} forked {repo}",
                    "venture": "delimit",
                    "classification": "strategic",
                    "confidence": 0.7,
                    "rationale": f"External fork of {repo}",
                    "manual_check_needed": False,
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                    "status": "new",
                })
                known_fps.add(fp)

        # Check stargazers (with timestamps)
        stars_data = _gh_api(
            f"repos/{repo}/stargazers?per_page=10"
            "&-H='Accept: application/vnd.github.star+json'"
        )
        # gh api may return list of user objects or star+json objects
        if isinstance(stars_data, list):
            for star in stars_data:
                # star+json format has "user" key; plain format is the user directly
                user_obj = star.get("user", star) if isinstance(star, dict) else {}
                user = user_obj.get("login", "")
                if user in INTERNAL_USERS or not user:
                    continue
                fp = f"github:star:{user}:{repo.split('/')[-1]}"
                if fp in known_fps:
                    continue

                targets.append({
                    "fingerprint": fp,
                    "platform": "github",
                    "source_id": f"{user}/star/{repo}",
                    "canonical_url": f"https://github.com/{user}",
                    "author": user,
                    "author_followers": 0,
                    "content_snippet": f"{user} starred {repo}",
                    "venture": "delimit",
                    "classification": "strategic",
                    "confidence": 0.6,
                    "rationale": f"External star on {repo}",
                    "manual_check_needed": False,
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                    "status": "new",
                })
                known_fps.add(fp)

        # Check issues and PRs from external users
        issues_data = _gh_api(f"repos/{repo}/issues?state=all&sort=created&direction=desc&per_page=10")
        if isinstance(issues_data, list):
            for issue in issues_data:
                user = issue.get("user", {}).get("login", "")
                if user in INTERNAL_USERS or not user:
                    continue
                number = issue.get("number", "")
                fp = f"github:issue:{repo}:{number}"
                if fp in known_fps or not number:
                    continue

                title = issue.get("title", "")
                is_pr = "pull_request" in issue
                kind = "PR" if is_pr else "issue"

                targets.append({
                    "fingerprint": fp,
                    "platform": "github",
                    "source_id": f"{repo}#{number}",
                    "canonical_url": issue.get("html_url", ""),
                    "author": user,
                    "author_followers": issue.get("reactions", {}).get("total_count", 0) or 0,
                    "content_snippet": f"{user} opened {kind}: {title}"[:300],
                    "venture": "delimit",
                    "classification": "reply",
                    "confidence": 0.8,
                    "rationale": f"External {kind} on {repo}",
                    "manual_check_needed": False,
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                    "status": "new",
                })
                known_fps.add(fp)

    return targets


def _get_rapidapi_key() -> str:
    """Load RapidAPI key from secrets broker or env."""
    import base64
    # Primary: delimit secrets broker
    secrets_file = Path.home() / ".delimit" / "secrets" / "rapidapi-reddit.json"
    if secrets_file.exists():
        try:
            data = json.loads(secrets_file.read_text())
            encrypted = data.get("encrypted_value", "")
            if encrypted:
                return base64.b64decode(encrypted).decode()
            return data.get("value", "")
        except Exception:
            pass
    # Fallback: wire report env
    wr_env = Path("/home/jamsons/ventures/wire-report/.wr_env")
    if wr_env.exists():
        try:
            for line in wr_env.read_text().splitlines():
                if line.startswith("RAPIDAPI_KEY="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            pass
    return os.environ.get("RAPIDAPI_KEY", "")


# Subreddits to scan per venture
# Keep total under 30 subs to stay well under rate limits (~1 req/sub/scan)
VENTURE_SUBREDDITS = {
    "delimit": [
        "ClaudeAI", "vibecoding", "devops", "programming",
        "AI_Agents", "ContextEngineering", "cursor",
        "LocalLLaMA", "SaaS", "opensource",
        # "ChatGPTCoding",  # requires high karma to post
    ],
    "domainvested": [
        "Domains", "flipping", "Entrepreneur", "SideProject",
    ],
    "wirereport": [
        "sportsbook", "sportsbetting",
    ],
    "livetube": [
        "Twitch", "livestreaming",
    ],
    "stakeone": [
        "harmony_one", "CryptoCurrency", "defi",
    ],
}


# Internal-only Reddit proxy via SSH tunnel to residential IP.
# This is NOT shipped to external users — it only runs on the founder's gateway server.
# External users would configure their own Reddit API credentials.
REDDIT_PROXY = os.environ.get("DELIMIT_REDDIT_PROXY", "http://127.0.0.1:4819/reddit-fetch")


def _scan_reddit(queries: List[str], limit: int, known_fps: set, config: Optional[Dict] = None) -> List[Dict]:
    """Scan Reddit via residential proxy (SSH tunnel) or RapidAPI fallback.

    Provider selection via config:
    - "proxy": try residential proxy first, fall back to RapidAPI
    - "rapidapi": use RapidAPI Reddit34 directly
    - "json_api": always try direct JSON (may fail from datacenter IPs)
    """
    platform_config = (config or {}).get("platforms", {}).get("reddit", {})
    provider = platform_config.get("provider", "proxy")

    # Merge subreddits from config with defaults
    config_subreddits = (config or {}).get("subreddits", {})
    if config_subreddits:
        # Temporarily override VENTURE_SUBREDDITS for this scan
        merged = dict(VENTURE_SUBREDDITS)
        for venture, subs in config_subreddits.items():
            if venture in merged:
                merged[venture] = list(set(merged[venture] + subs))
            else:
                merged[venture] = subs
        # We pass the merged subs to the proxy/rapidapi scanners via the module-level dict
        # This is safe since scans are single-threaded
        _original_subs = dict(VENTURE_SUBREDDITS)
        VENTURE_SUBREDDITS.update(merged)

    try:
        if provider == "rapidapi":
            api_key = _get_rapidapi_key()
            if not api_key:
                return _manual_check_targets("reddit", queries, limit)
            return _scan_reddit_rapidapi(queries, limit, known_fps, api_key)

        # Default: try proxy first, fall back to RapidAPI
        proxy_available = _test_reddit_proxy()
        if not proxy_available:
            api_key = _get_rapidapi_key()
            if not api_key:
                logger.warning("No Reddit access -- proxy down, no RapidAPI key")
                return _manual_check_targets("reddit", queries, limit)
            return _scan_reddit_rapidapi(queries, limit, known_fps, api_key)

        return _scan_reddit_proxy(queries, limit, known_fps)
    finally:
        # Restore original subreddits if we merged
        if config_subreddits:
            VENTURE_SUBREDDITS.clear()
            VENTURE_SUBREDDITS.update(_original_subs)


def _test_reddit_proxy() -> bool:
    """Check if residential Reddit proxy is available."""
    try:
        req = urllib.request.Request(f"{REDDIT_PROXY.rsplit('/reddit-fetch', 1)[0]}/health", headers={"User-Agent": "Delimit"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            return data.get("reddit_proxy", False)
    except Exception:
        return False


def _scan_reddit_proxy(queries: List[str], limit: int, known_fps: set) -> List[Dict]:
    """Scan Reddit via residential IP proxy (free, unlimited)."""
    targets: List[Dict] = []

    scanned_subs: set = set()
    for venture, subs in VENTURE_SUBREDDITS.items():
        for sub in subs:
            if sub in scanned_subs or len(targets) >= limit:
                break
            scanned_subs.add(sub)

            # Scan both /new and /hot to catch high-engagement older posts
            for sort in ("new", "hot"):
                if len(targets) >= limit:
                    break
                reddit_url = f"https://www.reddit.com/r/{sub}/{sort}.json?limit={min(limit, 10)}"
                proxy_url = f"{REDDIT_PROXY}?url={urllib.parse.quote(reddit_url, safe='')}"
                req = urllib.request.Request(proxy_url, headers={"User-Agent": "Delimit/3.11.0"})
                try:
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        result = json.loads(resp.read())

                    posts = result.get("data", {}).get("children", [])
                    for post_wrapper in posts:
                        post = post_wrapper.get("data", {})
                        post_id = post.get("id", "")
                        fp = f"reddit:{post_id}"
                        if fp in known_fps or not post_id:
                            continue

                        title = post.get("title", "")
                        selftext = post.get("selftext", "")[:200]
                        author = post.get("author", "")
                        score = post.get("score", 0) or 0
                        num_comments = post.get("num_comments", 0) or 0
                        permalink = post.get("permalink", "")
                        snippet = f"{title} {selftext}".strip()

                        venture_match, confidence, rationale = _route_venture(snippet)
                        if not venture_match:
                            continue
                        if score < 1 and num_comments < 2:
                            continue

                        target = {
                            "fingerprint": fp,
                            "platform": "reddit",
                            "source_id": post_id,
                            "canonical_url": f"https://reddit.com{permalink}" if permalink else "",
                            "author": f"u/{author}",
                            "author_followers": score,
                            "content_snippet": snippet[:300],
                            "venture": venture_match,
                            "classification": _classify_target(snippet, num_comments),
                            "confidence": confidence,
                            "rationale": f"r/{sub}/{sort}: {rationale}",
                            "manual_check_needed": False,
                            "first_seen": datetime.now(timezone.utc).isoformat(),
                            "status": "new",
                        }
                        targets.append(target)
                        known_fps.add(fp)

                        if len(targets) >= limit:
                            break

                except Exception as e:
                    logger.error("Reddit proxy scan error for r/%s/%s: %s", sub, sort, e)
                    continue

    return targets


def _scan_reddit_rapidapi(queries: List[str], limit: int, known_fps: set, api_key: str) -> List[Dict]:
    """Fallback: Scan Reddit via RapidAPI Reddit34."""

    targets: List[Dict] = []

    # Scan subreddits mapped to ventures
    scanned_subs: set = set()
    for venture, subs in VENTURE_SUBREDDITS.items():
        for sub in subs:
            if sub in scanned_subs or len(targets) >= limit:
                break
            scanned_subs.add(sub)

            url = f"https://reddit34.p.rapidapi.com/getPostsBySubreddit?subreddit={urllib.parse.quote(sub)}&sort=new&limit={min(limit, 10)}"
            req = urllib.request.Request(
                url,
                headers={
                    "X-RapidAPI-Key": api_key,
                    "X-RapidAPI-Host": "reddit34.p.rapidapi.com",
                    "User-Agent": "Delimit/3.11.0",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    result = json.loads(resp.read())

                if not result.get("success"):
                    logger.warning("Reddit34 returned success=false for r/%s", sub)
                    continue

                posts = result.get("data", {}).get("posts", [])
                for post_wrapper in posts:
                    post = post_wrapper.get("data", post_wrapper)
                    post_id = post.get("id", "")
                    fp = f"reddit:{post_id}"
                    if fp in known_fps or not post_id:
                        continue

                    title = post.get("title", "")
                    selftext = post.get("selftext", "")[:200]
                    author = post.get("author", "")
                    score = post.get("score", 0) or 0
                    num_comments = post.get("num_comments", 0) or 0
                    permalink = post.get("permalink", "")
                    snippet = f"{title} {selftext}".strip()

                    venture_match, confidence, rationale = _route_venture(snippet)
                    if not venture_match:
                        continue

                    # Skip low-engagement posts
                    if score < 1 and num_comments < 2:
                        continue

                    target = {
                        "fingerprint": fp,
                        "platform": "reddit",
                        "source_id": post_id,
                        "canonical_url": f"https://reddit.com{permalink}" if permalink else "",
                        "author": f"u/{author}",
                        "author_followers": score,
                        "content_snippet": snippet[:300],
                        "venture": venture_match,
                        "classification": _classify_target(snippet, num_comments),
                        "confidence": confidence,
                        "rationale": f"r/{sub}: {rationale}",
                        "manual_check_needed": False,
                        "first_seen": datetime.now(timezone.utc).isoformat(),
                        "status": "new",
                    }
                    targets.append(target)
                    known_fps.add(fp)

                    if len(targets) >= limit:
                        break

            except Exception as e:
                logger.error("Reddit scan error for r/%s: %s", sub, e)
                continue

    # Phase 2: keyword search across all of Reddit via getSearchPosts
    if len(targets) < limit:
        search_queries = queries[:3]  # Top 3 venture topic queries
        for query in search_queries:
            if len(targets) >= limit:
                break
            search_url = (
                f"https://reddit34.p.rapidapi.com/getSearchPosts"
                f"?query={urllib.parse.quote(query)}&sort=new&limit={min(limit, 5)}"
            )
            req = urllib.request.Request(
                search_url,
                headers={
                    "X-RapidAPI-Key": api_key,
                    "X-RapidAPI-Host": "reddit34.p.rapidapi.com",
                    "User-Agent": "Delimit/3.11.0",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    result = json.loads(resp.read())

                if not result.get("success"):
                    continue

                posts = result.get("data", {}).get("posts", [])
                for post_wrapper in posts:
                    post = post_wrapper.get("data", post_wrapper)
                    post_id = post.get("id", "")
                    fp = f"reddit:{post_id}"
                    if fp in known_fps or not post_id:
                        continue

                    title = post.get("title", "")
                    selftext = post.get("selftext", "")[:200]
                    author = post.get("author", "")
                    sub = post.get("subreddit", "")
                    score = post.get("score", 0) or 0
                    num_comments = post.get("num_comments", 0) or 0
                    permalink = post.get("permalink", "")
                    snippet = f"{title} {selftext}".strip()

                    venture_match, confidence, rationale = _route_venture(snippet)
                    if not venture_match:
                        continue
                    if score < 1 and num_comments < 2:
                        continue

                    target = {
                        "fingerprint": fp,
                        "platform": "reddit",
                        "source_id": post_id,
                        "canonical_url": f"https://reddit.com{permalink}" if permalink else "",
                        "author": f"u/{author}",
                        "author_followers": score,
                        "content_snippet": snippet[:300],
                        "venture": venture_match,
                        "classification": _classify_target(snippet, num_comments),
                        "confidence": confidence,
                        "rationale": f"search:{query}: {rationale}",
                        "manual_check_needed": False,
                        "first_seen": datetime.now(timezone.utc).isoformat(),
                        "status": "new",
                    }
                    targets.append(target)
                    known_fps.add(fp)

                    if len(targets) >= limit:
                        break
            except Exception as e:
                logger.error("Reddit search error for '%s': %s", query, e)
                continue

    return targets


def _manual_check_targets(platform: str, queries: List[str], limit: int) -> List[Dict]:
    """Return manual_check_needed placeholders for platforms we cannot scrape."""
    targets = []
    for query in queries[:3]:
        venture, confidence, rationale = _route_venture(query)
        targets.append({
            "fingerprint": f"{platform}:manual:{query[:30]}",
            "platform": platform,
            "source_id": "",
            "canonical_url": "",
            "author": "",
            "author_followers": 0,
            "content_snippet": f"Search '{query}' on {platform}",
            "venture": venture or "unknown",
            "classification": "reply",
            "confidence": 0.0,
            "rationale": f"Manual check needed -- {platform} cannot be scanned server-side",
            "manual_check_needed": True,
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "status": "manual_check_needed",
        })
    return targets[:limit]


# -----------------------------------------------------------------------
#  JSON extraction helper
# -----------------------------------------------------------------------

def _extract_json_array(text: str) -> list:
    """Best-effort extraction of a JSON array from LLM response text."""
    # Try the whole text first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except (json.JSONDecodeError, ValueError):
        pass
    # Try to find [...] in the text
    start = text.find("[")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except (json.JSONDecodeError, ValueError):
                        break
    return []


# -----------------------------------------------------------------------
#  Public API
# -----------------------------------------------------------------------

def scan_targets(
    platforms: List[str],
    ventures: Optional[List[str]] = None,
    keywords: Optional[List[str]] = None,
    limit: int = 10,
) -> List[Dict]:
    """Discover engagement opportunities across platforms.

    Args:
        platforms: List of platform names to scan (x, hn, devto, reddit, namepros).
        ventures: Filter to specific ventures. None = all.
        keywords: Extra keywords beyond venture topics.
        limit: Max targets per platform.

    Returns:
        List of target dicts with fingerprint, classification, and routing.
    """
    scan_config = _load_config()
    known_fps = _load_known_fingerprints()

    # Use config scan_limit as default if limit not explicitly overridden
    effective_limit = limit or scan_config.get("scan_limit", 10)

    # Build query list from venture topics + extra keywords
    queries: List[str] = []
    active_ventures = ventures or list(VENTURE_CONFIG.keys())
    for v in active_ventures:
        vc = VENTURE_CONFIG.get(v)
        if vc:
            queries.extend(vc["topics"])
    if keywords:
        queries.extend(keywords)

    # Deduplicate queries
    seen_q: set = set()
    unique_queries: List[str] = []
    for q in queries:
        q_lower = q.lower()
        if q_lower not in seen_q:
            seen_q.add(q_lower)
            unique_queries.append(q)

    all_targets: List[Dict] = []
    platform_configs = scan_config.get("platforms", {})

    for platform in platforms:
        platform = platform.strip().lower()

        # Check if platform is enabled in config
        plat_cfg = platform_configs.get(platform, {})
        if not plat_cfg.get("enabled", True):
            logger.info("Platform '%s' is disabled in config, skipping", platform)
            continue

        try:
            if platform == "x":
                targets = _scan_x(unique_queries, effective_limit, known_fps, config=scan_config)
            elif platform == "hn":
                targets = _scan_hn(unique_queries, effective_limit, known_fps)
            elif platform == "devto":
                targets = _scan_devto(unique_queries, effective_limit, known_fps)
            elif platform == "reddit":
                targets = _scan_reddit(unique_queries, effective_limit, known_fps, config=scan_config)
            elif platform == "github":
                targets = _scan_github(unique_queries, effective_limit, known_fps, config=scan_config)
                targets.extend(_monitor_own_repos(known_fps))
            elif platform == "namepros":
                targets = _manual_check_targets(platform, unique_queries, effective_limit)
            else:
                logger.warning("Unknown platform: %s", platform)
                continue

            # Filter by venture if specified
            if ventures:
                targets = [t for t in targets if t.get("venture") in ventures or t.get("error")]

            all_targets.extend(targets)
        except Exception as e:
            logger.error("Platform scan error (%s): %s", platform, e)
            all_targets.append({"error": f"Scan failed for {platform}: {e}", "platform": platform})

    # Persist new non-error targets
    for t in all_targets:
        if not t.get("error") and not t.get("manual_check_needed"):
            _append_target(t)

    return all_targets


def process_targets(
    targets: List[Dict],
    draft_replies: bool = False,
    create_ledger: bool = False,
) -> Dict[str, Any]:
    """Process discovered targets: draft social replies and/or create ledger items.

    Args:
        targets: List of target dicts from scan_targets.
        draft_replies: If True, auto-draft social posts for "reply" targets.
        create_ledger: If True, return ledger item dicts for "strategic" targets.

    Returns:
        Dict with drafted and ledger_items lists.
    """
    result: Dict[str, Any] = {"drafted": [], "ledger_items": []}

    for target in targets:
        if target.get("error") or target.get("manual_check_needed"):
            continue

        classification = target.get("classification", "reply")

        if draft_replies and classification in ("reply", "both"):
            try:
                from ai.social import save_draft
                venture = target.get("venture", "delimit")
                url = target.get("canonical_url", "")
                snippet = target.get("content_snippet", "")
                author = target.get("author", "")

                draft_text = (
                    f"[DRAFT - needs human writing] "
                    f"Engagement opportunity for {venture}: "
                    f"{author} posted about {snippet[:100]}... "
                    f"URL: {url}"
                )

                # Determine platform and account
                platform = target.get("platform", "x")
                if platform == "x":
                    social_platform = "twitter"
                    reply_to = target.get("source_id", "")
                else:
                    social_platform = "twitter"  # Drafts go to Twitter by default
                    reply_to = ""

                config = VENTURE_CONFIG.get(venture, {})
                account = config.get("owned_accounts", ["delimit_ai"])[0]

                entry = save_draft(
                    draft_text,
                    platform=social_platform,
                    account=account,
                    reply_to_id=reply_to,
                    context=f"Social target: {target.get('rationale', '')}",
                )
                result["drafted"].append({
                    "draft_id": entry.get("draft_id"),
                    "fingerprint": target.get("fingerprint"),
                    "venture": venture,
                })
            except Exception as e:
                logger.error("Failed to draft reply for %s: %s", target.get("fingerprint"), e)

        if create_ledger and classification in ("strategic", "both"):
            venture = target.get("venture", "delimit")
            ledger_item = {
                "title": f"[{venture.upper()}] Engage: {target.get('author', 'unknown')} on {target.get('platform', '?')}",
                "description": (
                    f"Source: {target.get('canonical_url', 'N/A')}\n"
                    f"Author: {target.get('author', 'unknown')} ({target.get('author_followers', 0)} followers)\n"
                    f"Snippet: {target.get('content_snippet', '')[:200]}\n"
                    f"Rationale: {target.get('rationale', '')}"
                ),
                "priority": VENTURE_CONFIG.get(venture, {}).get("priority", "P1"),
                "tags": [venture, "social-target", target.get("platform", "")],
            }
            result["ledger_items"].append(ledger_item)

    return result


def list_targets(limit: int = 20) -> Dict[str, Any]:
    """List recent targets from the JSONL store.

    Args:
        limit: Max targets to return.

    Returns:
        Dict with targets list and count.
    """
    if not TARGETS_FILE.exists():
        return {"targets": [], "count": 0}

    targets: List[Dict] = []
    lines = TARGETS_FILE.read_text().splitlines()
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            targets.append(entry)
            if len(targets) >= limit:
                break
        except (json.JSONDecodeError, ValueError):
            continue

    return {"targets": targets, "count": len(targets), "total_stored": len(lines)}


def get_stats() -> Dict[str, Any]:
    """Get aggregate stats on discovered targets.

    Returns:
        Dict with counts by platform, venture, classification, and status.
    """
    if not TARGETS_FILE.exists():
        return {"total": 0, "by_platform": {}, "by_venture": {}, "by_classification": {}, "by_status": {}}

    by_platform: Dict[str, int] = {}
    by_venture: Dict[str, int] = {}
    by_classification: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    total = 0

    for line in TARGETS_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            total += 1
            p = entry.get("platform", "unknown")
            v = entry.get("venture", "unknown")
            c = entry.get("classification", "unknown")
            s = entry.get("status", "unknown")
            by_platform[p] = by_platform.get(p, 0) + 1
            by_venture[v] = by_venture.get(v, 0) + 1
            by_classification[c] = by_classification.get(c, 0) + 1
            by_status[s] = by_status.get(s, 0) + 1
        except (json.JSONDecodeError, ValueError):
            continue

    return {
        "total": total,
        "by_platform": by_platform,
        "by_venture": by_venture,
        "by_classification": by_classification,
        "by_status": by_status,
    }
