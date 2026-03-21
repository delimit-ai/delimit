"""
Delimit Deliberation Engine — Multi-round consensus with real model-to-model debate.

Passes each model's EXACT raw response to the other models for counter-arguments.
Rounds continue until unanimous agreement or max rounds reached.

Models are configured via ~/.delimit/models.json — users choose which AI models
to include in deliberations. Supports any OpenAI-compatible API.
"""

import json
import logging
import os
import shutil
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("delimit.deliberation")

DELIBERATION_DIR = Path.home() / ".delimit" / "deliberations"
MODELS_CONFIG = Path.home() / ".delimit" / "models.json"

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


def get_models_config() -> Dict[str, Any]:
    """Load model configuration. Auto-detects available API keys."""
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

    return config


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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = result.stdout.strip()
        if not output and result.stderr:
            return f"[{cli_command} error: {result.stderr[:300]}]"
        return output or f"[{cli_command} returned empty response]"
    except subprocess.TimeoutExpired:
        return f"[{cli_command} timed out after 120s]"
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
                # Explicitly set credentials path if not in env
                creds_path = "/root/.config/gcloud/application_default_credentials.json"
                if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and os.path.exists(creds_path):
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
                creds, project = google.auth.default()
                creds.refresh(google.auth.transport.requests.Request())
                actual_url = api_url.replace("{project}", project or os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
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

        with urllib.request.urlopen(req, timeout=120) as resp:
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
            "tip": "Set API key environment variables or create ~/.delimit/models.json",
        }

    model_ids = list(enabled_models.keys())

    # Dialogue mode uses more rounds with shorter responses
    if mode == "dialogue" and max_rounds == 3:
        max_rounds = 6

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

    # Round 1: Independent responses
    logger.info(f"Deliberation Round 1 ({mode} mode): Independent responses")
    round1 = {"round": 1, "type": "independent", "responses": {}}

    for model_id in model_ids:
        if mode == "dialogue":
            # Shorter initial prompt for dialogue
            r1_prompt = f"{full_prompt}\n\nGive your initial take in 2-4 sentences. Don't write an essay."
        else:
            r1_prompt = full_prompt
        response = _call_model(model_id, enabled_models[model_id], r1_prompt, system_prompt)
        round1["responses"][model_id] = response
        # Build flat thread
        transcript["thread"].append({"model": model_id, "round": 1, "text": response})
        logger.info(f"  {model_id}: {len(response)} chars")

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

            response = _call_model(model_id, enabled_models[model_id], cross_prompt, system_prompt)
            round_data["responses"][model_id] = response
            transcript["thread"].append({"model": model_id, "round": round_num, "text": response})

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

    # Save transcript
    save_to = save_path
    if not save_to:
        ts = time.strftime("%Y%m%d_%H%M%S")
        save_to = str(DELIBERATION_DIR / f"deliberation_{ts}.json")

    Path(save_to).parent.mkdir(parents=True, exist_ok=True)
    Path(save_to).write_text(json.dumps(transcript, indent=2))
    transcript["saved_to"] = save_to

    return transcript
