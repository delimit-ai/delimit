"""
Delimit Deliberation Engine — Multi-round consensus with real model-to-model debate.

Passes each model's EXACT raw response to the other models for counter-arguments.
Rounds continue until unanimous agreement or max rounds reached.

Models are configured via ~/.delimit/models.json — users choose which AI models
to include in deliberations. Supports any OpenAI-compatible API.

## Hosted (Free Tier) vs BYOK
##
## Users without their own API keys get up to 3 free deliberations using Delimit's
## hosted keys (STR-066). After that, they must configure their own keys (BYOK) for
## unlimited use. Hosted calls are content-moderated and rate-limited.

## Design: Tool-Augmented Deliberation (LED-069, in_progress)
##
## Goal: Allow models to call Delimit tools during debate rounds so deliberations
## are grounded in real data instead of guesses.
##
## Approach:
## 1. Before each deliberation round, run a "context gather" pass that executes
##    relevant Delimit tools (ledger status, governance health, repo analysis)
##    and includes the results in the prompt context.
## 2. Models receive a "Tool Results" section in their prompt showing real data:
##    - Ledger: "70 open items, 12 blocked, 3 overdue"
##    - Governance: "2 repos failing, policy score 87/100"
##    - Spec diff: "5 breaking changes in v2.3.0"
## 3. This makes statements like "I checked the ledger and there are 70 open items"
##    factual rather than hallucinated.
## 4. Implementation phases:
##    a. Static context injection: pre-gather tool results, include in all prompts
##    b. On-demand tool calls: models request specific tool calls via structured
##       output, engine executes them between rounds
##    c. Full function-calling: models use native tool_use/function_calling APIs
##       where supported (OpenAI, Anthropic, Gemini)
## 5. Security: only whitelisted read-only tools are available during deliberation.
##    No write operations (ledger_add, deploy, etc.) to prevent side effects.
"""

import json
import logging
import os
import re
import shutil
import time
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("delimit.deliberation")

DELIBERATION_DIR = Path.home() / ".delimit" / "deliberations"
MODELS_CONFIG = Path.home() / ".delimit" / "models.json"
HOSTED_MODELS_CONFIG = Path.home() / ".delimit" / "secrets" / "hosted-models.json"
HOSTED_USAGE_FILE = Path.home() / ".delimit" / "deliberation_usage.json"
HOSTED_DAILY_FILE = Path.home() / ".delimit" / "hosted_usage_daily.json"

HOSTED_MAX_PER_INSTALL = 3
HOSTED_DAILY_CAP_DEFAULT = 100

# --- Content moderation keyword lists for hosted tier ---
# These are checked case-insensitively against question + context text.
# Intentionally broad — false positives just mean "use your own keys".
_MODERATION_EXPLICIT = [
    "porn", "hentai", "nsfw", "xxx", "nude", "naked", "sex act",
    "erotic", "fetish", "orgasm", "genital", "masturbat",
]
_MODERATION_VIOLENCE = [
    "how to kill", "how to murder", "make a bomb", "build a weapon",
    "synthesize poison", "manufacture explosive", "how to harm",
    "torture method", "assassination", "mass shooting",
]
_MODERATION_ILLEGAL = [
    "how to hack into", "steal credit card", "forge identity",
    "launder money", "cook meth", "make drugs", "child exploit",
    "bypass security", "crack password", "phishing attack",
    "ddos attack", "ransomware",
]
_MODERATION_TOS = [
    "ignore previous instructions", "ignore your system prompt",
    "you are now", "jailbreak", "dan mode", "pretend you have no rules",
    "act as an unrestricted", "bypass your filters",
    "override safety", "disregard all instructions",
]


def _get_install_id() -> str:
    """Get or create a stable install ID for usage tracking."""
    id_file = Path.home() / ".delimit" / "install_id"
    if id_file.exists():
        try:
            return id_file.read_text().strip()
        except Exception:
            pass
    install_id = str(uuid.uuid4())
    id_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        id_file.write_text(install_id)
    except Exception:
        pass
    return install_id


def _load_hosted_models() -> Dict[str, Any]:
    """Load hosted (Delimit-subsidized) model keys from secrets.

    Supports API-key-based providers (xAI, OpenAI, Google Generative AI)
    and Vertex AI (using service account credentials on the host).
    """
    if not HOSTED_MODELS_CONFIG.exists():
        return {}
    try:
        raw = json.loads(HOSTED_MODELS_CONFIG.read_text())
        # Convert hosted config to model configs compatible with _call_model
        result = {}
        for provider, cfg in raw.items():
            api_key = cfg.get("api_key", "")
            model = cfg.get("model", "")
            if provider == "xai":
                if not api_key:
                    continue
                result["grok"] = {
                    "name": "Grok (hosted)",
                    "api_url": "https://api.x.ai/v1/chat/completions",
                    "model": model or "grok-4-0709",
                    "api_key": api_key,
                    "enabled": True,
                    "backend": "api",
                    "hosted": True,
                }
            elif provider == "gemini":
                if api_key:
                    # Use Google Generative AI (API key) format
                    result["gemini"] = {
                        "name": "Gemini (hosted)",
                        "api_url": f"https://generativelanguage.googleapis.com/v1beta/models/{model or 'gemini-2.5-flash'}:generateContent",
                        "model": model or "gemini-2.5-flash",
                        "api_key": api_key,
                        "enabled": True,
                        "backend": "api",
                        "format": "google",
                        "hosted": True,
                    }
                elif cfg.get("vertex_ai"):
                    # Use Vertex AI with service account
                    result["gemini"] = {
                        "name": "Gemini (hosted)",
                        "api_url": "https://us-central1-aiplatform.googleapis.com/v1/projects/{project}/locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent",
                        "model": model or "gemini-2.5-flash",
                        "enabled": True,
                        "backend": "api",
                        "format": "vertex_ai",
                        "hosted": True,
                    }
            elif provider == "codex":
                if not api_key:
                    continue
                result["openai"] = {
                    "name": "Codex (hosted)",
                    "api_url": "https://api.openai.com/v1/chat/completions",
                    "model": model or "codex-mini-latest",
                    "api_key": api_key,
                    "enabled": True,
                    "backend": "api",
                    "hosted": True,
                }
        return result
    except Exception as e:
        logger.warning("Failed to load hosted models: %s", e)
        return {}


def _check_hosted_quota(install_id: str) -> Tuple[bool, int]:
    """Check if install is under the per-install hosted quota.

    Returns (allowed, used_count).
    """
    if not HOSTED_USAGE_FILE.exists():
        return True, 0
    try:
        data = json.loads(HOSTED_USAGE_FILE.read_text())
    except Exception:
        return True, 0
    entry = data.get(install_id, {})
    used = entry.get("hosted_count", 0)
    return used < HOSTED_MAX_PER_INSTALL, used


def _increment_hosted_usage(install_id: str) -> Dict[str, Any]:
    """Increment hosted usage for an install. Returns updated entry."""
    HOSTED_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(HOSTED_USAGE_FILE.read_text()) if HOSTED_USAGE_FILE.exists() else {}
    except Exception:
        data = {}

    entry = data.get(install_id, {
        "install_id": install_id,
        "hosted_count": 0,
        "total_count": 0,
        "last_used": None,
    })
    entry["hosted_count"] = entry.get("hosted_count", 0) + 1
    entry["total_count"] = entry.get("total_count", 0) + 1
    entry["last_used"] = datetime.now(timezone.utc).isoformat()
    data[install_id] = entry

    try:
        HOSTED_USAGE_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.warning("Failed to write hosted usage: %s", e)
    return entry


def _increment_total_usage(install_id: str) -> None:
    """Increment only total_count (for BYOK calls) without touching hosted_count."""
    HOSTED_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(HOSTED_USAGE_FILE.read_text()) if HOSTED_USAGE_FILE.exists() else {}
    except Exception:
        data = {}

    entry = data.get(install_id, {
        "install_id": install_id,
        "hosted_count": 0,
        "total_count": 0,
        "last_used": None,
    })
    entry["total_count"] = entry.get("total_count", 0) + 1
    entry["last_used"] = datetime.now(timezone.utc).isoformat()
    data[install_id] = entry

    try:
        HOSTED_USAGE_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.warning("Failed to write usage: %s", e)


def _check_global_daily_cap() -> Tuple[bool, int]:
    """Check if global daily hosted cap has been reached.

    Returns (allowed, used_today).
    """
    cap = int(os.environ.get("DELIMIT_HOSTED_DAILY_CAP", str(HOSTED_DAILY_CAP_DEFAULT)))

    if not HOSTED_DAILY_FILE.exists():
        return 0 < cap, 0
    try:
        data = json.loads(HOSTED_DAILY_FILE.read_text())
    except Exception:
        return 0 < cap, 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if data.get("date") != today:
        return 0 < cap, 0

    used = data.get("count", 0)
    return used < cap, used


def _increment_global_daily() -> None:
    """Increment global daily hosted usage counter."""
    HOSTED_DAILY_FILE.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        data = json.loads(HOSTED_DAILY_FILE.read_text()) if HOSTED_DAILY_FILE.exists() else {}
    except Exception:
        data = {}

    if data.get("date") != today:
        data = {"date": today, "count": 0}

    data["count"] = data.get("count", 0) + 1

    try:
        HOSTED_DAILY_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.warning("Failed to write daily cap: %s", e)


def _moderate_content(question: str, context: str = "") -> Optional[str]:
    """Keyword-based content moderation for hosted deliberations.

    Returns None if clean, or an error message string if flagged.
    """
    text = f"{question} {context}".lower()

    for term in _MODERATION_EXPLICIT:
        if term in text:
            return (
                "This prompt was flagged by content moderation. "
                "Hosted deliberations are for technical questions only. "
                "Configure your own API keys for unrestricted use."
            )

    for term in _MODERATION_VIOLENCE:
        if term in text:
            return (
                "This prompt was flagged by content moderation. "
                "Hosted deliberations are for technical questions only. "
                "Configure your own API keys for unrestricted use."
            )

    for term in _MODERATION_ILLEGAL:
        if term in text:
            return (
                "This prompt was flagged by content moderation. "
                "Hosted deliberations are for technical questions only. "
                "Configure your own API keys for unrestricted use."
            )

    for term in _MODERATION_TOS:
        if term in text:
            return (
                "This prompt was flagged by content moderation. "
                "Hosted deliberations are for technical questions only. "
                "Configure your own API keys for unrestricted use."
            )

    return None


def get_deliberation_status() -> Dict[str, Any]:
    """Return current deliberation usage and mode info."""
    install_id = _get_install_id()

    # Check if user has their own keys
    user_config = get_models_config()
    user_enabled = {k: v for k, v in user_config.items() if v.get("enabled") and not v.get("hosted")}
    has_byok = len(user_enabled) >= 2

    # Check hosted availability
    hosted_models = _load_hosted_models()
    has_hosted = len(hosted_models) >= 2

    # Usage stats
    allowed, hosted_used = _check_hosted_quota(install_id)
    hosted_remaining = max(0, HOSTED_MAX_PER_INSTALL - hosted_used)

    # Total usage
    try:
        data = json.loads(HOSTED_USAGE_FILE.read_text()) if HOSTED_USAGE_FILE.exists() else {}
        entry = data.get(install_id, {})
        total_count = entry.get("total_count", 0)
    except Exception:
        total_count = 0

    mode = "byok" if has_byok else ("hosted" if has_hosted else "none")

    result = {
        "mode": mode,
        "install_id": install_id,
        "hosted_used": hosted_used,
        "hosted_remaining": hosted_remaining,
        "hosted_limit": HOSTED_MAX_PER_INSTALL,
        "total_deliberations": total_count,
    }

    if mode == "byok":
        result["note"] = "Using your own API keys. Unlimited deliberations."
        result["byok_models"] = list(user_enabled.keys())
    elif mode == "hosted":
        if hosted_remaining > 0:
            result["note"] = f"{hosted_remaining} free deliberation(s) remaining. Configure ~/.delimit/models.json for unlimited."
        else:
            result["note"] = "Free deliberations used. Configure your own API keys in ~/.delimit/models.json for unlimited deliberations."
    else:
        result["note"] = "No models available. Configure API keys in ~/.delimit/models.json or hosted keys will be used when available."

    return result


DEFAULT_MODELS = {
    "grok": {
        "name": "Grok",
        "api_url": "https://api.x.ai/v1/chat/completions",
        "model": "grok-4-0709",
        "env_key": "XAI_API_KEY",
        "enabled": False,
    },
    "gemini": {
        "name": "Gemini",
        "api_url": "https://us-central1-aiplatform.googleapis.com/v1/projects/{project}/locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent",
        "model": "gemini-2.5-flash",
        "env_key": "GOOGLE_APPLICATION_CREDENTIALS",
        "enabled": False,
        "format": "vertex_ai",
        "prefer_cli": True,  # Use gemini CLI if available (Ultra plan), fall back to Vertex AI
        "cli_command": "gemini",
    },
    "openai": {
        "name": "OpenAI",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o",
        "env_key": "OPENAI_API_KEY",
        "enabled": False,
        "prefer_cli": True,  # Use Codex CLI if available, fall back to API
    },
    "anthropic": {
        "name": "Claude",
        "api_url": "https://api.anthropic.com/v1/messages",
        "model": "claude-sonnet-4-5-20250514",
        "env_key": "ANTHROPIC_API_KEY",
        "enabled": False,
        "format": "anthropic",
        "prefer_cli": True,  # Use claude CLI if available (Pro/Max), fall back to API
        "cli_command": "claude",
    },
}


def get_models_config(allow_hosted_fallback: bool = True) -> Dict[str, Any]:
    """Load model configuration. Auto-detects available API keys.

    If the user has a models.json, it is always respected (explicit config).
    If no models.json exists and auto-detect finds < 2 enabled models,
    falls back to Delimit's hosted keys for the free tier (STR-066).
    """
    if MODELS_CONFIG.exists():
        try:
            return json.loads(MODELS_CONFIG.read_text())
        except Exception:
            pass

    # Auto-detect from environment
    config = {}
    for model_id, defaults in DEFAULT_MODELS.items():
        key = os.environ.get(defaults.get("env_key", ""), "")

        if defaults.get("prefer_cli"):
            # Prefer CLI (uses existing subscription) over API (extra cost)
            import shutil
            cli_cmd = defaults.get("cli_command", "codex")
            cli_path = shutil.which(cli_cmd)
            if cli_path:
                config[model_id] = {
                    **defaults,
                    "format": "codex_cli",
                    "enabled": True,
                    "codex_path": cli_path,
                    "backend": "cli",
                }
            elif key:
                config[model_id] = {
                    **defaults,
                    "api_key": key,
                    "enabled": True,
                    "backend": "api",
                }
            else:
                config[model_id] = {**defaults, "enabled": False}
        else:
            config[model_id] = {
                **defaults,
                "api_key": key,
                "enabled": bool(key),
            }

    # Check if user has any models at all
    enabled_user = {k: v for k, v in config.items() if v.get("enabled")}
    if enabled_user:
        # User has at least one model configured — respect their setup.
        # If < 2, deliberate() will return a clear error.
        return config

    # No user models at all — fall back to hosted keys (free tier)
    if allow_hosted_fallback:
        hosted = _load_hosted_models()
        if len(hosted) >= 2:
            logger.info("No user API keys found. Using hosted (free tier) models.")
            return hosted

    return config


def _gather_tool_context() -> str:
    """LED-069: Gather real data from Delimit tools to ground deliberation.

    Runs whitelisted read-only tools and formats results as context.
    Only includes data that's available — silently skips failures.
    """
    sections = []

    # 1. Ledger status
    try:
        from ai.ledger_manager import get_context
        ledger = get_context()
        open_count = ledger.get("open_items", 0)
        if open_count > 0:
            top = ledger.get("next_up", [])
            top_str = ", ".join(f"{i.get('id', '')} ({i.get('title', '')[:40]})" for i in top[:3])
            sections.append(f"**Ledger**: {open_count} open items. Top: {top_str}")
        else:
            sections.append("**Ledger**: No open items.")
    except Exception:
        pass

    # 2. Governance health
    try:
        from ai.governance import govern
        # Quick check — don't actually run full governance, just read state
        delimit_dir = Path(".") / ".delimit"
        if delimit_dir.is_dir():
            policies = (delimit_dir / "policies.yml").is_file()
            ledger_dir = (delimit_dir / "ledger").is_dir()
            sections.append(f"**Governance**: initialized={delimit_dir.is_dir()}, policies={policies}, ledger={ledger_dir}")
    except Exception:
        pass

    # 3. Model configuration
    try:
        config = get_models_config()
        enabled = [v.get("name", k) for k, v in config.items() if v.get("enabled")]
        sections.append(f"**Models**: {len(enabled)} enabled — {', '.join(enabled)}")
    except Exception:
        pass

    # 4. Git status (if in a repo)
    try:
        import subprocess
        r = subprocess.run(["git", "log", "--oneline", "-1"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            sections.append(f"**Git**: latest commit — {r.stdout.strip()}")
        r2 = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=5)
        if r2.returncode == 0:
            changes = len([l for l in r2.stdout.strip().splitlines() if l.strip()])
            if changes:
                sections.append(f"**Working tree**: {changes} uncommitted change(s)")
    except Exception:
        pass

    return "\n".join(sections)


def configure_models() -> Dict[str, Any]:
    """Return current model configuration and what's available."""
    config = get_models_config()
    available = {k: v for k, v in config.items() if v.get("enabled")}
    missing = {k: v for k, v in config.items() if not v.get("enabled")}

    model_details = {}
    for k, v in available.items():
        backend = v.get("backend", "api")
        if v.get("format") == "codex_cli":
            backend = "cli"
        model_details[k] = {"name": v.get("name", k), "backend": backend, "model": v.get("model", "")}

    return {
        "configured_models": list(available.keys()),
        "model_details": model_details,
        "missing_models": {k: f"Set {v.get('env_key', 'key')} or install {v.get('cli_command', '')} CLI" for k, v in missing.items()},
        "config_path": str(MODELS_CONFIG),
        "note": "CLI backends use your existing subscription (no extra API cost). "
                "API backends require separate API keys.",
    }


def _call_cli(prompt: str, system_prompt: str = "", cli_path: str = "", cli_command: str = "codex") -> str:
    """Call an AI CLI tool (codex or claude) via subprocess. Uses existing subscription — no API cost."""
    import subprocess

    if not cli_path:
        cli_path = shutil.which(cli_command) or ""
    if not cli_path:
        return f"[{cli_command} unavailable — CLI not found in PATH]"

    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

    # Build command based on which CLI
    if "claude" in cli_command:
        cmd = [cli_path, "--print", "--dangerously-skip-permissions", full_prompt]
    else:
        # codex
        cmd = [cli_path, "exec", "--dangerously-bypass-approvals-and-sandbox", full_prompt]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        output = result.stdout.strip()
        if not output and result.stderr:
            return f"[{cli_command} error: {result.stderr[:300]}]"
        return output or f"[{cli_command} returned empty response]"
    except subprocess.TimeoutExpired:
        return f"[{cli_command} timed out after 300s]"
    except Exception as e:
        return f"[{cli_command} error: {e}]"


def _call_model(model_id: str, config: Dict, prompt: str, system_prompt: str = "") -> str:
    """Call any supported model — OpenAI-compatible API, Vertex AI, or CLI (codex/claude)."""
    fmt = config.get("format", "openai")

    # CLI-based models (codex, claude) — uses existing subscription, no API cost
    if fmt == "codex_cli":
        cli_path = config.get("codex_path", "")
        cli_command = config.get("cli_command", "codex")
        return _call_cli(prompt, system_prompt, cli_path=cli_path, cli_command=cli_command)

    api_key = config.get("api_key") or os.environ.get(config.get("env_key", ""), "")
    # Vertex AI uses service account auth, not API key
    if not api_key and fmt != "vertex_ai":
        return f"[{config.get('name', model_id)} unavailable — {config.get('env_key')} not set]"

    api_url = config["api_url"]
    model = config.get("model", "")

    try:
        if fmt == "vertex_ai":
            # Vertex AI format — use google-auth for access token
            try:
                import google.auth
                import google.auth.transport.requests
                # Prefer application default credentials (gcloud auth login)
                # over service accounts — ADC works with Vertex AI out of the box.
                adc_path = str(Path.home() / ".config/gcloud/application_default_credentials.json")
                sa_path = str(Path.home() / ".delimit" / "secrets" / "gcp-delimit-sa.json")
                for candidate in [adc_path, sa_path]:
                    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and os.path.exists(candidate):
                        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = candidate
                        break
                # Explicit scopes needed for service accounts; ADC also accepts them
                VERTEX_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
                creds, detected_project = google.auth.default(scopes=VERTEX_SCOPES)
                creds.refresh(google.auth.transport.requests.Request())
                # Use GOOGLE_CLOUD_PROJECT if set, then detected project
                project = os.environ.get("GOOGLE_CLOUD_PROJECT", "") or detected_project or ""
                # If project still empty, try to read from ADC file
                if not project:
                    try:
                        adc_data = json.loads(Path(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", adc_path)).read_text())
                        project = adc_data.get("quota_project_id", "") or adc_data.get("project_id", "")
                    except Exception:
                        pass
                if not project:
                    return f"[Gemini unavailable — set GOOGLE_CLOUD_PROJECT env var]"
                actual_url = api_url.replace("{project}", project)
                data = json.dumps({
                    "contents": [{"role": "user", "parts": [{"text": f"{system_prompt}\n\n{prompt}" if system_prompt else prompt}]}],
                    "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.7},
                }).encode()
                req = urllib.request.Request(
                    actual_url,
                    data=data,
                    headers={
                        "Authorization": f"Bearer {creds.token}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
            except ImportError:
                return f"[Gemini unavailable — install google-auth: pip install google-auth]"
        elif fmt == "google":
            # Google Generative AI format (API key)
            data = json.dumps({
                "contents": [{"role": "user", "parts": [{"text": f"{system_prompt}\n\n{prompt}" if system_prompt else prompt}]}],
                "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.7},
            }).encode()
            req = urllib.request.Request(
                f"{api_url}?key={api_key}",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        elif fmt == "anthropic":
            # Anthropic Messages API
            data = json.dumps({
                "model": model,
                "max_tokens": 4096,
                "system": system_prompt or "You are a helpful assistant participating in a multi-model deliberation.",
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                api_url,
                data=data,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                    "User-Agent": "Delimit/3.6.0",
                },
                method="POST",
            )
        else:
            # OpenAI-compatible format (works for xAI, OpenAI, etc.)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            data = json.dumps({
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 4096,
            }).encode()
            req = urllib.request.Request(
                api_url,
                data=data,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Delimit/3.6.0",
                },
                method="POST",
            )

        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read())

        if fmt in ("google", "vertex_ai"):
            return result["candidates"][0]["content"]["parts"][0]["text"]
        elif fmt == "anthropic":
            return result["content"][0]["text"]
        else:
            return result["choices"][0]["message"]["content"]

    except Exception as e:
        return f"[{config.get('name', model_id)} error: {e}]"


def deliberate(
    question: str,
    context: str = "",
    max_rounds: int = 3,
    mode: str = "dialogue",
    require_unanimous: bool = True,
    save_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run a multi-round deliberation across all configured AI models.

    Modes:
      - "debate": Long-form essays, models respond to each other's full arguments (3 rounds default)
      - "dialogue": Short conversational turns, models build on each other like a group chat (6 rounds default)

    Returns the full deliberation transcript + final verdict.
    """
    DELIBERATION_DIR.mkdir(parents=True, exist_ok=True)

    config = get_models_config()
    enabled_models = {k: v for k, v in config.items() if v.get("enabled")}

    if len(enabled_models) < 2:
        return {
            "error": "Need at least 2 AI models for deliberation.",
            "configured": list(enabled_models.keys()),
            "missing": {k: f"Set {v.get('env_key', 'key')}" for k, v in config.items() if not v.get("enabled")},
            "tip": "Set API key environment variables or create ~/.delimit/models.json. "
                   "Or use the free tier (up to 3 deliberations) with hosted keys.",
        }

    # Determine if this is a hosted (free tier) deliberation
    is_hosted = any(v.get("hosted") for v in enabled_models.values())
    install_id = _get_install_id()

    if is_hosted:
        # Content moderation for hosted calls
        mod_result = _moderate_content(question, context)
        if mod_result:
            return {"error": mod_result, "mode": "hosted", "moderation": "flagged"}

        # Check per-install quota
        allowed, used = _check_hosted_quota(install_id)
        if not allowed:
            return {
                "error": "Free deliberations used. Configure your own API keys in "
                         "~/.delimit/models.json for unlimited deliberations.",
                "mode": "hosted",
                "hosted_used": used,
                "hosted_limit": HOSTED_MAX_PER_INSTALL,
            }

        # Check global daily cap
        daily_allowed, daily_used = _check_global_daily_cap()
        if not daily_allowed:
            return {
                "error": "Daily hosted deliberation limit reached. Configure your own "
                         "API keys for unlimited use.",
                "mode": "hosted",
                "daily_used": daily_used,
            }

    model_ids = list(enabled_models.keys())

    # Dialogue mode uses more rounds with shorter responses
    # Capped at 4 to stay within MCP timeout (LED-167)
    if mode == "dialogue" and max_rounds == 3:
        max_rounds = 4

    # LED-106: Estimate cost before deliberation starts
    # Rough token estimates per model call (prompt + completion)
    COST_PER_1K_TOKENS = {
        "grok": 0.005,      # xAI Grok
        "gemini": 0.00,     # Vertex AI (free tier / included in GCP)
        "openai": 0.005,    # GPT-4o
        "anthropic": 0.003, # Claude Sonnet
        "codex": 0.00,      # CLI-based, uses subscription
    }
    AVG_TOKENS_PER_CALL = {"debate": 2000, "dialogue": 800}
    est_tokens_per_call = AVG_TOKENS_PER_CALL.get(mode, 1500)
    est_total_calls = len(model_ids) * max_rounds
    est_total_tokens = est_tokens_per_call * est_total_calls

    cost_estimate = {}
    total_est_cost = 0.0
    for mid in model_ids:
        backend = enabled_models[mid].get("backend", "api")
        if backend == "cli":
            cost_estimate[mid] = {"backend": "cli", "cost": 0.0, "note": "Uses existing subscription"}
        else:
            rate = COST_PER_1K_TOKENS.get(mid, 0.005)
            model_cost = (est_tokens_per_call * max_rounds * rate) / 1000
            cost_estimate[mid] = {"backend": "api", "cost_usd": round(model_cost, 4), "rate_per_1k": rate}
            total_est_cost += model_cost

    start_time = time.time()

    # LED-069: Tool-augmented deliberation — gather real data before rounds
    tool_context = _gather_tool_context()
    if tool_context:
        context = f"{context}\n\n## Live Tool Results (gathered automatically)\n{tool_context}" if context else f"## Live Tool Results (gathered automatically)\n{tool_context}"

    transcript = {
        "question": question,
        "context": context,
        "mode": mode,
        "models": model_ids,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rounds": [],
        "thread": [],  # flat conversation thread for dialogue mode
        "unanimous": False,
        "final_verdict": None,
        "cost_estimate": {
            "models": cost_estimate,
            "total_estimated_usd": round(total_est_cost, 4),
            "estimated_calls": est_total_calls,
            "estimated_tokens": est_total_tokens,
        },
        "timing": {},  # populated during execution
    }

    if mode == "dialogue":
        system_prompt = (
            "You are in a group chat with other AI models. Keep responses to 2-4 sentences. "
            "Be direct and conversational — this is a discussion, not an essay. "
            "Build on what others said. Disagree specifically if you disagree. "
            "When you're ready to agree, say VERDICT: AGREE. "
            "If you disagree, say VERDICT: DISAGREE — [why in one sentence]."
        )
    else:
        system_prompt = (
            "You are participating in a structured multi-model deliberation with other AI models. "
            "You will see other models' exact responses and must engage with their specific arguments. "
            "At the END of your response, you MUST include exactly one of these lines:\n"
            "VERDICT: AGREE\n"
            "VERDICT: DISAGREE — [one sentence reason]\n"
            "VERDICT: AGREE WITH MODIFICATIONS — [one sentence modification]\n"
            "Do not hedge. Take a clear position."
        )

    full_prompt = f"{context}\n\nQUESTION:\n{question}" if context else question

    # Round 1: Independent responses — run ALL models in parallel (LED-167)
    logger.info(f"Deliberation Round 1 ({mode} mode): Independent responses (parallel)")
    round1 = {"round": 1, "type": "independent", "responses": {}}

    if mode == "dialogue":
        r1_prompt = f"{full_prompt}\n\nGive your initial take in 2-4 sentences. Don't write an essay."
    else:
        r1_prompt = full_prompt

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _call_r1(mid):
        t0 = time.time()
        resp = _call_model(mid, enabled_models[mid], r1_prompt, system_prompt)
        ms = int((time.time() - t0) * 1000)
        return mid, resp, ms

    with ThreadPoolExecutor(max_workers=len(model_ids)) as pool:
        futures = {pool.submit(_call_r1, mid): mid for mid in model_ids}
        for future in as_completed(futures):
            mid, response, call_ms = future.result()
            round1["responses"][mid] = response
            transcript["timing"].setdefault(mid, []).append({"round": 1, "ms": call_ms, "chars": len(response)})
            logger.info(f"  {mid}: {len(response)} chars, {call_ms}ms")

    # Build thread in consistent model order
    for mid in model_ids:
        transcript["thread"].append({"model": mid, "round": 1, "text": round1["responses"][mid]})

    transcript["rounds"].append(round1)

    # Subsequent rounds: Models see each other's responses
    for round_num in range(2, max_rounds + 1):
        logger.info(f"Deliberation Round {round_num} ({mode})")
        round_data = {"round": round_num, "type": "deliberation", "responses": {}}
        prev = transcript["rounds"][-1]["responses"]

        for model_id in model_ids:
            if mode == "dialogue":
                # Dialogue: show the full conversation thread so far
                thread_text = f"Topic: {question}\n\nConversation so far:\n"
                for entry in transcript["thread"]:
                    name = enabled_models.get(entry["model"], {}).get("name", entry["model"])
                    thread_text += f"\n[{name}]: {entry['text']}\n"
                thread_text += (
                    f"\nYour turn ({enabled_models[model_id]['name']}). "
                    f"Respond in 2-4 sentences to the conversation above. "
                    f"If you agree with the emerging consensus, say VERDICT: AGREE. "
                    f"If not, push back specifically."
                )
                cross_prompt = thread_text
            else:
                # Debate: show other models' full responses from last round
                others_text = ""
                for other_id in model_ids:
                    if other_id != model_id:
                        others_text += (
                            f"\n=== {enabled_models[other_id]['name'].upper()}'S EXACT RESPONSE "
                            f"(Round {round_num - 1}) ===\n"
                            f"{prev[other_id]}\n"
                        )
                cross_prompt = (
                    f"DELIBERATION ROUND {round_num}\n\n"
                    f"Original question: {question}\n"
                    f"{others_text}\n"
                    f"Respond to the other models' SPECIFIC arguments. "
                    f"Quote them directly if you disagree. "
                    f"End with VERDICT: AGREE / DISAGREE / AGREE WITH MODIFICATIONS."
                )

            call_start = time.time()
            response = _call_model(model_id, enabled_models[model_id], cross_prompt, system_prompt)
            call_ms = int((time.time() - call_start) * 1000)
            round_data["responses"][model_id] = response
            transcript["thread"].append({"model": model_id, "round": round_num, "text": response})
            transcript["timing"].setdefault(model_id, []).append({"round": round_num, "ms": call_ms, "chars": len(response)})

        transcript["rounds"].append(round_data)

        # Check for unanimous agreement
        all_agree = True
        for model_id in model_ids:
            resp = round_data["responses"][model_id].upper()
            if "VERDICT:" in resp:
                verdict_part = resp.split("VERDICT:")[-1].strip()
                agrees = verdict_part.startswith("AGREE")
                if not agrees:
                    all_agree = False
            else:
                all_agree = False  # No verdict = no agreement

        if all_agree:
            transcript["unanimous"] = True
            transcript["final_verdict"] = "UNANIMOUS AGREEMENT"
            transcript["agreed_at_round"] = round_num
            break
    else:
        # Max rounds reached
        transcript["final_verdict"] = "MAX ROUNDS REACHED"
        for model_id in model_ids:
            resp = transcript["rounds"][-1]["responses"][model_id].upper()
            verdict = "unknown"
            if "VERDICT:" in resp:
                verdict_part = resp.split("VERDICT:")[-1].strip()
                verdict = "agree" if verdict_part.startswith("AGREE") else "disagree"
            transcript[f"{model_id}_final"] = verdict

    transcript["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    total_elapsed_ms = int((time.time() - start_time) * 1000)

    # LED-106: Compute actual cost and timing summary
    actual_calls = sum(len(calls) for calls in transcript["timing"].values())
    actual_chars = sum(c["chars"] for calls in transcript["timing"].values() for c in calls)
    model_summaries = {}
    for mid, calls in transcript["timing"].items():
        total_ms = sum(c["ms"] for c in calls)
        total_chars = sum(c["chars"] for c in calls)
        est_tokens = total_chars // 4  # rough char-to-token ratio
        rate = COST_PER_1K_TOKENS.get(mid, 0.005)
        backend = enabled_models.get(mid, {}).get("backend", "api")
        actual_cost = 0.0 if backend == "cli" else (est_tokens * rate) / 1000
        model_summaries[mid] = {
            "calls": len(calls),
            "total_ms": total_ms,
            "avg_ms": total_ms // max(len(calls), 1),
            "total_chars": total_chars,
            "est_tokens": est_tokens,
            "actual_cost_usd": round(actual_cost, 4),
        }

    total_actual_cost = sum(s["actual_cost_usd"] for s in model_summaries.values())
    transcript["cost_actual"] = {
        "models": model_summaries,
        "total_actual_usd": round(total_actual_cost, 4),
        "total_calls": actual_calls,
        "total_chars": actual_chars,
        "total_elapsed_ms": total_elapsed_ms,
    }

    # Track usage
    transcript["mode"] = "hosted" if is_hosted else "byok"
    if is_hosted:
        _increment_hosted_usage(install_id)
        _increment_global_daily()
        remaining = max(0, HOSTED_MAX_PER_INSTALL - (used + 1))
        transcript["hosted_remaining"] = remaining
        if remaining == 0:
            transcript["hosted_note"] = (
                "This was your last free deliberation. Configure your own API keys "
                "in ~/.delimit/models.json for unlimited deliberations."
            )
        else:
            transcript["hosted_note"] = f"{remaining} free deliberation(s) remaining."
    else:
        _increment_total_usage(install_id)

    # Save transcript
    save_to = save_path
    if not save_to:
        ts = time.strftime("%Y%m%d_%H%M%S")
        save_to = str(DELIBERATION_DIR / f"deliberation_{ts}.json")

    Path(save_to).parent.mkdir(parents=True, exist_ok=True)
    Path(save_to).write_text(json.dumps(transcript, indent=2))
    transcript["saved_to"] = save_to

    return transcript
