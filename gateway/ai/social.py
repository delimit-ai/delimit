"""Automated social media — authentic engagement at scale.

Posts are value-first: tips, changelogs, governance insights.
Never spam, never generic marketing. Every post teaches something.

Multi-account support: credentials stored per handle in
~/.delimit/secrets/twitter-<handle>.json (e.g. twitter-delimit_ai.json).
Legacy twitter-full.json is treated as the default account.
"""
import json
import logging
import os
import random
import uuid
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger("delimit.ai.social")

SECRETS_DIR = Path.home() / ".delimit" / "secrets"
SOCIAL_LOG = Path.home() / ".delimit" / "social_log.jsonl"
DRAFTS_FILE = Path.home() / ".delimit" / "social_drafts.jsonl"
ACCOUNTS_FILE = SECRETS_DIR / "twitter-accounts.json"

# Platform-specific tone guidelines for draft generation
# Used by AI agents when drafting content — included in draft metadata
# so the agent (or human reviewer) can adjust tone before posting.
PLATFORM_TONE = {
    "twitter": {
        "max_length": 280,
        "tone": "confident technical brand, direct, professional",
        "identity": "@delimit_ai — verified, professional account",
        "conversion_targets": [
            "action: delimit-ai/delimit-action (GitHub Marketplace)",
            "mcp: delimit-mcp-server (Claude Code, Cursor, Gemini CLI)",
            "vscode: Delimit VS Code extension (Marketplace)",
            "install: npx delimit-cli setup",
        ],
        "rules": [
            "ALWAYS POSITIVE — celebrate wins, share progress, show momentum. Never complain, never air gaps or insecurities publicly",
            "Frame every metric as a win: '400 clones in 2 weeks' NOT '400 clones but 0 stars'",
            "If there's a problem to solve, handle it internally — don't tweet about it",
            "Confident technical brand voice — direct, clear, authoritative",
            "NOT a Reddit voice — no rough edges, no typos, no 'typing on phone' energy",
            "Proper capitalization and punctuation — we're a product account",
            "Lead with the insight, not the product",
            "One clear point per tweet",
            "No em dashes or en dashes — most people can't type them, so they look AI-generated. Use commas, periods, or hyphens instead",
            "Short punchy lines with line breaks for rhythm",
            "Include a link or install command when relevant",
            "Quote tweets: position Delimit relative to the quoted content, not as a generic response",
            "Replies: be genuinely helpful or insightful, not just 'cool project!'",
        ],
    },
    "reddit": {
        "max_length": 500,
        "tone": "proud builder, genuinely helpful, never salesy",
        "identity": "u/delimitdev — we're openly building Delimit, not hiding it",
        "conversion_targets": [
            "action: delimit-ai/delimit-action (GitHub Marketplace)",
            "mcp: delimit-mcp-server (Claude Code, Cursor, Gemini CLI)",
            "vscode: Delimit VS Code extension (Marketplace)",
        ],
        "subreddit_angles": {
            "r/vibecoding": {
                "angle": "founder was a non-technical vibe coder who kept breaking things — built Delimit as the safety net",
                "narrative": "'I was in your shoes' — fellow builder sharing what they made, not selling",
                "best_for": "threads about stability, breaking things, fear of AI-introduced bugs, QA loops",
                "conversion": "action or vscode",
            },
            "r/ClaudeAI": {
                "angle": "MCP power user — shared context across models, agent governance",
                "narrative": "deep practitioner who's built tooling on top of Claude's ecosystem",
                "best_for": "threads about MCP, multi-model workflows, context loss, agent tooling",
                "conversion": "mcp",
            },
            "r/devops": {
                "angle": "CI/CD governance — catch breaking API changes before merge",
                "narrative": "team that ships a GitHub Action for API compatibility checks",
                "best_for": "threads about API versioning, breaking changes, CI pipelines, OpenAPI",
                "conversion": "action",
            },
            "r/programming": {
                "angle": "developer tooling builder — 27 breaking change types, one YAML line",
                "narrative": "technical founder sharing what the engine detects and why",
                "best_for": "threads about API design, backward compatibility, schema evolution",
                "conversion": "action",
            },
        },
        "rules": [
            "We post as u/delimitdev — no need to hide that we build Delimit",
            "Mention Delimit ONLY when it genuinely helps the person's problem",
            "Be proud of our work, not promotional — 'we built X to solve this' not 'check out X!'",
            "NEVER post unsolicited promos — only mention our tools in direct response to a real problem",
            "If Delimit isn't relevant to the thread, just be helpful with no mention at all",
            "Confident builder energy — proud of what we've shipped, not cocky or boastful",
            "NEVER use bullet points or numbered lists — instant AI tell",
            "Keep it to 2-3 sentences max, not multi-paragraph essays",
            "Write like you're typing on your phone, not writing a blog post",
            "Use contractions, sentence fragments, rough edges",
            "One sharp point per comment — don't cover three topics",
            "ALWAYS POSITIVE — celebrate wins, share progress, show momentum. Never complain or air gaps publicly",
            "NEVER commiserate or self-deprecate — sound like someone who's figured it out",
            "A typo or two is fine — too polished = flagged as AI by mods",
            "NEVER use em dashes (—), en dashes (–), or fancy punctuation — use commas, 'and', or hyphens instead",
            "NEVER use semicolons, ellipsis (…), or curly quotes — type like a human on a phone keyboard",
            "NEVER structure responses with headers, bold text, or formatted lists",
            "r/devops mods actively flag LLM-generated content (learned 2026-03-27)",
        ],
    },
    "linkedin": {
        "max_length": 1300,
        "tone": "professional, concise, insight-driven",
        "rules": [
            "Lead with a hook question or surprising stat",
            "Keep paragraphs to 1-2 lines",
            "End with a clear CTA or question",
        ],
    },
}

# Content templates — each provides genuine value
CONTENT_TEMPLATES = {
    "tip": [
        "Tip: You can detect {count} types of breaking API changes with one line of YAML:\n\n- uses: delimit-ai/delimit-action@v1\n  with:\n    spec: api/openapi.yaml\n\nNo config needed. Advisory mode by default.",
        "Did you know? When you switch from Claude Code to Codex, you lose all context. With a shared ledger, say \"what's on the ledger?\" in any assistant and pick up exactly where you left off.",
        "API governance tip: The 3 most common breaking changes we catch:\n\n1. Endpoint removed without deprecation\n2. Required field added to request body\n3. Response field type changed\n\nAll detectable before merge.",
        "Quick tip: Run `npx delimit-cli doctor` in any project to check your governance setup. It checks for policies, specs, workflows, and git config in seconds.",
        "Pro tip: Use policy presets to match your team's risk tolerance:\n\n{bullet} strict — all violations are errors\n{bullet} default — balanced\n{bullet} relaxed — warnings only\n\n`npx delimit-cli init --preset strict`",
    ],
    "changelog": [
        "Just shipped: {feature}\n\n{detail}\n\nUpdate: npx delimit-cli@latest setup",
    ],
    "insight": [
        "We analyzed {count} API changes this week. {percent}% were breaking. The most common? {top_change}.\n\nAutomate this check: delimit.ai",
        "Hot take: In 2 years, unmanaged AI agents touching production code will be as unacceptable as unmanaged SSH keys.\n\nGovernance isn't optional. It's infrastructure.",
        "The problem with AI coding assistants isn't capability — it's context loss. Every time you switch models, you start from zero. That's the real productivity killer.",
    ],
    "engagement": [
        "What's the worst API breaking change you've shipped to production? We've seen some creative ones.",
        "How many AI coding assistants does your team use? We're seeing teams average 2-3, with context scattered across all of them.",
        "What's your API governance process today? Manual review? CI check? Nothing? (No judgment — that's why we built this.)",
    ],
}


def _resolve_creds_path(account: str = "") -> Path | None:
    """Resolve credentials file for a given account handle.

    Lookup order:
      1. ~/.delimit/secrets/twitter-<account>.json  (per-handle)
      2. ~/.delimit/secrets/twitter-full.json        (legacy default)
    """
    if account:
        per_handle = SECRETS_DIR / f"twitter-{account}.json"
        if per_handle.exists():
            return per_handle
    # Legacy fallback
    legacy = SECRETS_DIR / "twitter-full.json"
    if legacy.exists():
        return legacy
    return None


def get_twitter_client(account: str = ""):
    """Get authenticated Twitter client via tweepy for a specific account.

    Returns:
        Tuple of (client, handle, error). On success error is None.
        On failure client and handle are None and error is a non-empty string
        that distinguishes between "not configured" and "auth failed".

    Args:
        account: Twitter handle (without @). Empty string = default account.
    """
    acct_label = account or "default"
    creds_path = _resolve_creds_path(account)
    if not creds_path:
        configured = list_twitter_accounts()
        if configured:
            handles = [a["handle"] for a in configured]
            return None, None, (
                f"Account '{acct_label}' is not configured. "
                f"Configured accounts: {handles}. "
                f"Place credentials in ~/.delimit/secrets/twitter-{account}.json"
            )
        return None, None, (
            f"No Twitter accounts configured. "
            f"Place credentials in ~/.delimit/secrets/twitter-<handle>.json"
        )
    try:
        import tweepy
        creds = json.loads(creds_path.read_text())
        client = tweepy.Client(
            consumer_key=creds["consumer_key"],
            consumer_secret=creds["consumer_secret"],
            access_token=creds["access_token"],
            access_token_secret=creds["access_token_secret"],
        )
        handle = creds.get("handle", account or "delimit_ai")
        return client, handle, None
    except KeyError as e:
        msg = (
            f"Account '{acct_label}' is configured ({creds_path.name}) "
            f"but missing credential field {e}"
        )
        logger.error(msg)
        return None, None, msg
    except ImportError:
        msg = "tweepy is not installed. Run: pip install tweepy"
        logger.error(msg)
        return None, None, msg
    except json.JSONDecodeError as e:
        msg = (
            f"Account '{acct_label}' credentials file ({creds_path.name}) "
            f"contains invalid JSON: {e}"
        )
        logger.error(msg)
        return None, None, msg
    except Exception as e:
        msg = (
            f"Account '{acct_label}' is configured ({creds_path.name}) "
            f"but authentication failed: {e}"
        )
        logger.error(msg, exc_info=True)
        return None, None, msg


def list_twitter_accounts() -> list[dict]:
    """List all configured Twitter accounts, deduplicated by handle.

    When multiple credential files resolve to the same handle,
    the per-handle file (twitter-<handle>.json) wins over legacy files.
    """
    accounts = []
    seen_handles: set[str] = set()
    if not SECRETS_DIR.exists():
        return accounts
    for f in sorted(SECRETS_DIR.glob("twitter-*.json")):
        name = f.stem  # e.g. "twitter-delimit_ai"
        if name == "twitter-accounts":
            continue
        # Skip legacy twitter-full.json in this pass (handled below)
        if name == "twitter-full":
            continue
        try:
            creds = json.loads(f.read_text())
            handle = creds.get("handle", name.removeprefix("twitter-"))
            if handle in seen_handles:
                continue
            seen_handles.add(handle)
            accounts.append({"handle": handle, "file": f.name})
        except (json.JSONDecodeError, ValueError):
            pass
    # Include legacy twitter-full.json only if its handle is not already covered
    legacy = SECRETS_DIR / "twitter-full.json"
    if legacy.exists():
        try:
            creds = json.loads(legacy.read_text())
            handle = creds.get("handle", "default")
            if handle not in seen_handles:
                seen_handles.add(handle)
                accounts.append({"handle": handle, "file": "twitter-full.json", "default": True})
        except (json.JSONDecodeError, ValueError):
            pass
    return accounts


def post_tweet(text: str, account: str = "", quote_tweet_id: str = "",
               reply_to_id: str = "") -> dict:
    """Post a tweet via the Twitter API.

    Args:
        text: Tweet text content.
        account: Twitter handle (without @) to post from. Empty = default.
        quote_tweet_id: Tweet ID to quote. Creates a quote tweet.
        reply_to_id: Tweet ID to reply to. Creates a reply.
    """
    client, handle, init_error = get_twitter_client(account)
    if not client:
        # Always return the specific error from get_twitter_client.
        # Previous code fell through to a misleading "not found" message
        # when init_error was empty, even though the account was configured.
        if init_error:
            return {"error": init_error}
        # Fallback: should not be reachable, but be explicit
        return {"error": f"Failed to initialize Twitter client for account '{account or 'default'}'. "
                f"Check credentials in ~/.delimit/secrets/twitter-{account or 'full'}.json"}
    try:
        kwargs = {"text": text}
        if quote_tweet_id:
            kwargs["quote_tweet_id"] = quote_tweet_id
        if reply_to_id:
            kwargs["in_reply_to_tweet_id"] = reply_to_id
        result = client.create_tweet(**kwargs)
        tweet_id = result.data["id"]
        log_post("twitter", text, tweet_id, handle=handle,
                 quote_tweet_id=quote_tweet_id, reply_to_id=reply_to_id)
        return {
            "posted": True,
            "id": tweet_id,
            "handle": handle,
            "url": f"https://x.com/{handle}/status/{tweet_id}",
            "type": "quote_tweet" if quote_tweet_id else "reply" if reply_to_id else "tweet",
        }
    except Exception as e:
        return {"error": str(e), "handle": handle}


def generate_post(category: str = "", custom: str = "") -> dict:
    """Generate a post. If custom is provided, use that. Otherwise pick from templates."""
    if custom:
        return {"text": custom, "category": "custom"}

    if not category or category not in CONTENT_TEMPLATES:
        category = random.choice(list(CONTENT_TEMPLATES.keys()))

    templates = CONTENT_TEMPLATES[category]
    template = random.choice(templates)

    # Fill in template variables with realistic data
    text = template.format(
        count=27,
        percent=random.randint(15, 35),
        top_change=random.choice([
            "endpoint removed",
            "type changed",
            "required field added",
        ]),
        feature="(specify feature name)",
        detail="(specify feature details)",
        bullet="\u2022",
    )

    return {"text": text, "category": category}


def get_post_history(limit: int = 20, platform: str = "",
                     user: str = "", subreddit: str = "") -> list:
    """Get recent post history from the JSONL log.

    Args:
        limit: Max entries to return.
        platform: Filter by platform (e.g. "twitter", "reddit").
        user: Filter by Reddit user we replied to (replying_to_user field).
        subreddit: Filter by subreddit (e.g. "r/vibecoding").
    """
    if not SOCIAL_LOG.exists():
        return []
    posts = []
    for line in reversed(SOCIAL_LOG.read_text().splitlines()):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        # Apply filters
        if platform and entry.get("platform") != platform:
            continue
        if user and user.lower() not in (entry.get("replying_to_user") or "").lower():
            continue
        if subreddit and subreddit.lower() not in (entry.get("subreddit") or "").lower():
            continue
        posts.append(entry)
        if len(posts) >= limit:
            break
    return posts


def log_post(platform: str, text: str, post_id: str = "", handle: str = "",
             quote_tweet_id: str = "", reply_to_id: str = "",
             subreddit: str = "", thread_url: str = "",
             thread_title: str = "", replying_to_user: str = "",
             conversion_target: str = ""):
    """Log a social media post to the JSONL log.

    For Reddit comments, include subreddit, thread context, and the user
    being replied to so we can recall full conversation threads later.
    """
    SOCIAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "handle": handle,
        "text": text[:500] if platform == "reddit" else text[:200],
        "post_id": post_id,
    }
    if quote_tweet_id:
        entry["quote_tweet_id"] = quote_tweet_id
    if reply_to_id:
        entry["reply_to_id"] = reply_to_id
    # Reddit-specific fields
    if subreddit:
        entry["subreddit"] = subreddit
    if thread_url:
        entry["thread_url"] = thread_url
    if thread_title:
        entry["thread_title"] = thread_title
    if replying_to_user:
        entry["replying_to_user"] = replying_to_user
    if conversion_target:
        entry["conversion_target"] = conversion_target
    with open(SOCIAL_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def should_post_today() -> bool:
    """Check if we've hit the daily posting limit.

    Limit is configurable via DELIMIT_DAILY_TWEETS env var (default 8).
    Uses US Eastern Time for day boundaries since the posting schedule
    targets 9am/3pm ET.
    """
    from zoneinfo import ZoneInfo

    daily_limit = int(os.environ.get("DELIMIT_DAILY_TWEETS", "8"))
    et_now = datetime.now(ZoneInfo("America/New_York"))
    today_et = et_now.strftime("%Y-%m-%d")
    history = get_post_history(100)
    today_posts = []
    for p in history:
        ts_str = p.get("ts", "")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str).astimezone(ZoneInfo("America/New_York"))
                if ts.strftime("%Y-%m-%d") == today_et:
                    today_posts.append(p)
            except (ValueError, TypeError):
                continue
    return len(today_posts) < daily_limit


# ═════════════════════════════════════════════════════════════════════
#  DRAFT MODE — Queue content for review before posting
# ═════════════════════════════════════════════════════════════════════


def get_platform_tone(platform: str = "twitter") -> dict:
    """Return tone guidelines for a platform.

    AI agents should call this before drafting content to get
    platform-specific rules for voice, length, and formatting.
    """
    return PLATFORM_TONE.get(platform, PLATFORM_TONE.get("twitter", {}))


def save_draft(text: str, platform: str = "twitter", account: str = "",
               quote_tweet_id: str = "", reply_to_id: str = "",
               conversion_target: str = "", thread_url: str = "",
               context: str = "") -> dict:
    """Save a social media post as a draft for later approval.

    Returns the draft entry with a unique draft_id and platform tone guidelines.

    Args:
        conversion_target: For Reddit — "action", "mcp", "vscode", or "" (no promo, just helpful).
        thread_url: URL of the Reddit thread being replied to.
        context: WHY this post should be made — strategic reasoning shown in the email.
    """
    DRAFTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    draft_id = uuid.uuid4().hex[:12]
    tone = get_platform_tone(platform)
    entry = {
        "draft_id": draft_id,
        "text": text,
        "platform": platform,
        "account": account,
        "quote_tweet_id": quote_tweet_id,
        "reply_to_id": reply_to_id,
        "conversion_target": conversion_target,
        "thread_url": thread_url,
        "context": context,
        "status": "pending",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # Check tone violations
    warnings = []
    if tone.get("max_length") and len(text) > tone["max_length"]:
        warnings.append(f"Text exceeds {platform} max length ({len(text)}/{tone['max_length']})")
    # Fancy AI punctuation checks — applies to ALL platforms
    # Most people can't type em dashes, curly quotes, etc. on a keyboard, so they look AI-generated
    _fancy_chars = {
        "\u2014": "em dash",
        "\u2013": "en dash",
        "\u2026": "ellipsis (...)",
        "\u201c": "curly left quote",
        "\u201d": "curly right quote",
        "\u2018": "curly left single quote",
        "\u2019": "curly right single quote",
    }
    _found_fancy = [name for char, name in _fancy_chars.items() if char in text]
    if _found_fancy:
        warnings.append(f"AI TELL WARNING: Fancy punctuation detected: {', '.join(_found_fancy)} — use plain keyboard characters only")
    # Negativity check — applies to ALL platforms
    _lower_text = text.lower()
    _negative_patterns = [
        "zero stars", "no stars", "0 stars", "nobody cared",
        "no one noticed", "nobody noticed", "crickets",
        "the challenge is", "the problem is", "the hard part is",
        "but zero", "but no one", "but nobody",
        "struggling to", "failing to", "can't seem to",
        "not working", "isn't working",
    ]
    if any(p in _lower_text for p in _negative_patterns):
        warnings.append("NEGATIVITY WARNING: Post sounds negative or self-defeating. Reframe as a win or celebration. If there's a problem, handle it internally — don't tweet about it.")
    if platform == "reddit":
        if any(line.strip().startswith(("- ", "* ", "1.", "2.", "3.")) for line in text.split("\n")):
            warnings.append("REDDIT WARNING: Contains bullet/numbered lists — high risk of mod removal as AI content")
        if text.count("\n\n") >= 3:
            warnings.append("REDDIT WARNING: Multi-paragraph essay format — shorten to 2-3 sentences")
        if "**" in text:
            warnings.append("REDDIT WARNING: Contains bold formatting — too polished for Reddit")
        if ";" in text:
            warnings.append("REDDIT WARNING: Contains semicolon — too formal, use a comma or period instead")
        # Self-deprecating / commiserating tone check
        _lower = text.lower()
        _commiserate_patterns = [
            "same issue here", "i've been hitting", "i struggle with",
            "yeah i have this", "me too", "same problem",
            "i've been dealing with", "drives me nuts too",
            "i'm stuck on", "can't figure out", "been struggling",
        ]
        if any(p in _lower for p in _commiserate_patterns):
            warnings.append("REDDIT WARNING: Self-deprecating/commiserating tone detected — rewrite with confident practitioner voice")
        # Unsolicited promo check — mention Delimit only when genuinely helpful
        _promo_patterns = [
            "check out", "you should try", "give it a try",
            "we just launched", "just shipped", "shameless plug",
            "i'd recommend delimit", "you need delimit",
        ]
        _mentions_delimit = "delimit" in _lower
        _is_salesy = any(p in _lower for p in _promo_patterns)
        if _mentions_delimit and _is_salesy:
            warnings.append("REDDIT WARNING: Looks like an unsolicited promo — mention Delimit only in direct response to a real problem, never as a pitch")
        if _mentions_delimit and not conversion_target:
            warnings.append("REDDIT NOTE: Mentions Delimit but no conversion_target set — specify 'action', 'mcp', or 'vscode' so the email shows the funnel intent")
    if warnings:
        entry["tone_warnings"] = warnings
    with open(DRAFTS_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def store_draft_message_id(draft_id: str, message_id: str) -> bool:
    """Store the outbound notification Message-ID on a draft record.

    This enables In-Reply-To header matching for auto-approval via the
    inbox polling daemon (Consensus 116).

    Args:
        draft_id: The 12-char hex draft ID.
        message_id: The Message-ID header from the sent notification email.

    Returns:
        True if the draft was found and updated, False otherwise.
    """
    all_entries = _load_all_drafts()
    for entry in all_entries:
        if entry.get("draft_id") == draft_id:
            entry["notification_message_id"] = message_id
            _rewrite_drafts(all_entries)
            return True
    return False


def list_drafts(status: str = "pending") -> list[dict]:
    """List drafts filtered by status (pending, approved, rejected)."""
    if not DRAFTS_FILE.exists():
        return []
    drafts = []
    for line in DRAFTS_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if entry.get("status") == status:
                drafts.append(entry)
        except (json.JSONDecodeError, ValueError):
            pass
    return drafts


def _rewrite_drafts(all_entries: list[dict]) -> None:
    """Rewrite the drafts file with updated entries."""
    DRAFTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DRAFTS_FILE, "w") as f:
        for entry in all_entries:
            f.write(json.dumps(entry) + "\n")


def _load_all_drafts() -> list[dict]:
    """Load all draft entries from the JSONL file."""
    if not DRAFTS_FILE.exists():
        return []
    entries = []
    for line in DRAFTS_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            pass
    return entries


def approve_draft(draft_id: str) -> dict:
    """Approve a draft — marks it approved and emails the final text to the founder.

    Auto-posting via Twitter API is disabled. Founder posts manually from their device.
    """
    all_entries = _load_all_drafts()
    target = None
    for entry in all_entries:
        if entry.get("draft_id") == draft_id:
            target = entry
            break
    if not target:
        return {"error": f"Draft '{draft_id}' not found"}
    if target.get("status") != "pending":
        return {"error": f"Draft '{draft_id}' is already {target.get('status')}"}

    # Mark approved but do NOT auto-post — email to founder for manual posting
    target["status"] = "approved"
    target["approved_at"] = datetime.now(timezone.utc).isoformat()
    _rewrite_drafts(all_entries)

    # Email the approved text for manual posting
    try:
        from ai.notify import send_email
        qt = target.get("quote_tweet_id", "")
        rt = target.get("reply_to_id", "")
        context_lines = []
        if qt:
            context_lines.append(f"Quote tweet: https://x.com/i/status/{qt}")
        if rt:
            context_lines.append(f"Reply to: https://x.com/i/status/{rt}")
        context = "\n".join(context_lines)
        body = f"APPROVED — post this manually:\n\n---\n{target['text']}\n---\n\n{context}"
        send_email(
            subject=f"APPROVED X Post: {draft_id}",
            body=body,
        )
    except Exception:
        pass

    return {"draft_id": draft_id, "status": "approved", "mode": "manual_post", "message": "Emailed to founder for manual posting. Auto-posting is disabled."}


def reject_draft(draft_id: str) -> dict:
    """Reject a draft. It will not be posted."""
    all_entries = _load_all_drafts()
    target = None
    for entry in all_entries:
        if entry.get("draft_id") == draft_id:
            target = entry
            break
    if not target:
        return {"error": f"Draft '{draft_id}' not found"}
    if target.get("status") != "pending":
        return {"error": f"Draft '{draft_id}' is already {target.get('status')}"}

    target["status"] = "rejected"
    target["rejected_at"] = datetime.now(timezone.utc).isoformat()
    _rewrite_drafts(all_entries)
    return {"draft_id": draft_id, "status": "rejected"}
