"""Prompt drift detection — same task behaves differently across models (STR-052).

Detects when the same prompt produces inconsistent results across
Claude, Codex, and Gemini. Flags divergence and suggests model-specific
adaptations.

Focus group (Indie): "Prompt drift — same task behaves differently
in Claude vs Codex vs Gemini."
"""

import json
import time
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

DRIFT_DIR = Path.home() / ".delimit" / "prompt_drift"
HISTORY_FILE = DRIFT_DIR / "history.jsonl"


def _ensure_dir():
    DRIFT_DIR.mkdir(parents=True, exist_ok=True)


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]


def record_result(
    prompt: str,
    model: str,
    result_summary: str,
    success: bool = True,
    task_type: str = "",
    duration_ms: int = 0,
) -> Dict[str, Any]:
    """Record a prompt execution result for drift analysis."""
    if not prompt or not model:
        return {"error": "prompt and model are required"}

    _ensure_dir()
    prompt_hash = _hash_prompt(prompt)

    entry = {
        "prompt_hash": prompt_hash,
        "prompt_preview": prompt[:100],
        "model": model.lower().strip(),
        "result_summary": result_summary[:200],
        "success": success,
        "task_type": task_type,
        "duration_ms": duration_ms,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return {
        "status": "recorded",
        "prompt_hash": prompt_hash,
        "model": model,
        "message": f"Result recorded for {model}",
    }


def check_drift(
    prompt: str = "",
    task_type: str = "",
    threshold: float = 0.3,
) -> Dict[str, Any]:
    """Check for prompt drift — inconsistent results across models.

    Args:
        prompt: Specific prompt to check (by hash). Empty = check all recent.
        task_type: Filter by task type.
        threshold: Drift threshold (0-1). Higher = more tolerant.
    """
    if not HISTORY_FILE.exists():
        return {
            "status": "no_data",
            "drift_detected": False,
            "message": "No prompt history. Use record_result() to start tracking.",
        }

    entries: List[Dict] = []
    try:
        for line in HISTORY_FILE.read_text().strip().split("\n"):
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except OSError:
        return {"status": "error", "message": "Could not read history"}

    # Filter
    if prompt:
        prompt_hash = _hash_prompt(prompt)
        entries = [e for e in entries if e.get("prompt_hash") == prompt_hash]
    if task_type:
        entries = [e for e in entries if e.get("task_type") == task_type]

    if not entries:
        return {
            "status": "no_matches",
            "drift_detected": False,
            "message": "No matching prompt history found.",
        }

    # Group by prompt hash
    by_prompt: Dict[str, List[Dict]] = {}
    for e in entries:
        by_prompt.setdefault(e["prompt_hash"], []).append(e)

    drift_findings = []
    for ph, results in by_prompt.items():
        models = set(r["model"] for r in results)
        if len(models) < 2:
            continue  # Need at least 2 models to compare

        # Check success rate divergence
        model_success = {}
        for r in results:
            m = r["model"]
            model_success.setdefault(m, []).append(r["success"])

        success_rates = {
            m: sum(s) / len(s) for m, s in model_success.items()
        }

        # Check for significant divergence
        rates = list(success_rates.values())
        if max(rates) - min(rates) > threshold:
            best = max(success_rates, key=success_rates.get)
            worst = min(success_rates, key=success_rates.get)
            drift_findings.append({
                "prompt_hash": ph,
                "prompt_preview": results[0].get("prompt_preview", ""),
                "models_compared": list(models),
                "success_rates": success_rates,
                "best_model": best,
                "worst_model": worst,
                "divergence": round(max(rates) - min(rates), 2),
                "recommendation": f"Use {best} for this task. {worst} has {round(success_rates[worst]*100)}% success rate.",
            })

    return {
        "status": "ok",
        "drift_detected": len(drift_findings) > 0,
        "findings": drift_findings,
        "total_prompts_analyzed": len(by_prompt),
        "total_entries": len(entries),
        "message": f"{len(drift_findings)} drift(s) detected across {len(by_prompt)} prompt(s)" if drift_findings else "No significant drift detected",
    }


def get_model_rankings(task_type: str = "") -> Dict[str, Any]:
    """Rank models by success rate and speed for a task type."""
    if not HISTORY_FILE.exists():
        return {"status": "no_data", "rankings": []}

    entries: List[Dict] = []
    try:
        for line in HISTORY_FILE.read_text().strip().split("\n"):
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except OSError:
        return {"status": "error", "rankings": []}

    if task_type:
        entries = [e for e in entries if e.get("task_type") == task_type]

    if not entries:
        return {"status": "no_data", "rankings": [], "task_type": task_type}

    # Aggregate per model
    model_stats: Dict[str, Dict] = {}
    for e in entries:
        m = e["model"]
        if m not in model_stats:
            model_stats[m] = {"successes": 0, "total": 0, "durations": []}
        model_stats[m]["total"] += 1
        if e.get("success"):
            model_stats[m]["successes"] += 1
        if e.get("duration_ms"):
            model_stats[m]["durations"].append(e["duration_ms"])

    rankings = []
    for model, stats in model_stats.items():
        avg_duration = sum(stats["durations"]) / len(stats["durations"]) if stats["durations"] else 0
        success_rate = stats["successes"] / stats["total"] if stats["total"] > 0 else 0
        rankings.append({
            "model": model,
            "success_rate": round(success_rate * 100, 1),
            "avg_duration_ms": round(avg_duration),
            "total_tasks": stats["total"],
        })

    rankings.sort(key=lambda r: (-r["success_rate"], r["avg_duration_ms"]))

    return {
        "status": "ok",
        "rankings": rankings,
        "task_type": task_type or "all",
        "total_entries": len(entries),
    }
