"""
Delimit Cross-Model Audit — Trust through triangulation.

Run the same code review through 3 different AI models, each with a different
review lens (security, correctness, governance). A synthesis step merges their
findings: agreements become high-confidence, disagreements surface tradeoffs.

This is different from `delimit_deliberate` (which debates a question).
Cross-Model Audit reviews actual code/specs for specific issues.

Models are configured via ~/.delimit/models.json or ~/.delimit/secrets/hosted-models.json.
Uses the same infrastructure as deliberation.py.
"""

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("delimit.cross_model_audit")

AUDIT_DIR = Path.home() / ".delimit" / "audits"

# ═══════════════════════════════════════════════════════════════════════
#  Audit Lenses — each model gets a different review focus
# ═══════════════════════════════════════════════════════════════════════

AUDIT_LENSES = {
    "security": (
        "Review for security vulnerabilities: injection, auth bypass, data exposure, "
        "privilege escalation, secret leaks. Focus on exploitable issues."
    ),
    "correctness": (
        "Review for logical errors, edge cases, off-by-one, race conditions, "
        "null handling, error propagation. Focus on bugs that cause wrong behavior."
    ),
    "governance": (
        "Review for breaking changes, API contract violations, backward compatibility, "
        "schema drift, missing validation. Focus on issues that affect consumers."
    ),
}

# Severity levels for structured findings
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

MODEL_TIMEOUT = 60  # seconds


def _build_lens_prompt(lens_name: str, lens_description: str, target_code: str, target_type: str) -> str:
    """Build the prompt for a model with its assigned lens."""
    type_label = {
        "file": "source file",
        "diff": "git diff",
        "snippet": "code snippet",
    }.get(target_type, "code")

    return f"""You are a code auditor focused on **{lens_name}**.

{lens_description}

Analyze the following {type_label} and return your findings as a JSON array.
Each finding must be a JSON object with these fields:
- "severity": one of "critical", "high", "medium", "low", "info"
- "location": line number, function name, or description of where the issue is (e.g. "Line 42", "function validate_token", "JWT handling block")
- "finding": clear description of the issue
- "recommendation": what to do about it

Return ONLY a JSON array. No markdown fences, no explanatory text before or after.
If you find no issues, return an empty array: []

--- BEGIN CODE ---
{target_code}
--- END CODE ---"""


def _resolve_target(target: str, target_type: str) -> Tuple[str, Optional[str]]:
    """Resolve the target to actual code content.

    Returns (code_content, error_message).
    """
    if target_type == "file":
        path = Path(target).expanduser()
        if not path.exists():
            return "", f"File not found: {target}"
        if not path.is_file():
            return "", f"Not a file: {target}"
        try:
            content = path.read_text(errors="replace")
            if len(content) > 50000:
                content = content[:50000] + "\n\n[... truncated at 50,000 characters ...]"
            return content, None
        except Exception as e:
            return "", f"Failed to read file: {e}"
    elif target_type in ("diff", "snippet"):
        if not target.strip():
            return "", "Empty target provided."
        return target, None
    else:
        return "", f"Unknown target_type: {target_type}. Use 'file', 'diff', or 'snippet'."


def _parse_model_findings(raw_response: str, model_name: str) -> List[Dict[str, str]]:
    """Parse structured findings from a model response.

    Tries to extract a JSON array from the response. Handles markdown fences
    and other common formatting issues.
    """
    text = raw_response.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try direct parse
    try:
        findings = json.loads(text)
        if isinstance(findings, list):
            return _validate_findings(findings, model_name)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON array from text
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            findings = json.loads(match.group())
            if isinstance(findings, list):
                return _validate_findings(findings, model_name)
        except json.JSONDecodeError:
            pass

    # Could not parse — return the raw response as a single finding
    logger.warning("Could not parse structured findings from %s, wrapping raw response", model_name)
    return [{
        "severity": "info",
        "location": "general",
        "finding": f"[Unstructured response from {model_name}]: {raw_response[:500]}",
        "recommendation": "Review raw model output manually.",
    }]


def _validate_findings(findings: List, model_name: str) -> List[Dict[str, str]]:
    """Validate and normalize finding objects."""
    validated = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        validated.append({
            "severity": str(f.get("severity", "info")).lower(),
            "location": str(f.get("location", "unknown")),
            "finding": str(f.get("finding", "")),
            "recommendation": str(f.get("recommendation", "")),
        })
    return validated


def _call_model_with_lens(
    model_id: str,
    model_config: Dict,
    lens_name: str,
    target_code: str,
    target_type: str,
) -> Dict[str, Any]:
    """Call a single model with its lens prompt. Returns result dict."""
    from ai.deliberation import _call_model

    lens_description = AUDIT_LENSES[lens_name]
    prompt = _build_lens_prompt(lens_name, lens_description, target_code, target_type)
    system_prompt = (
        f"You are a senior code auditor performing a {lens_name} review. "
        "Return findings as a JSON array. Be thorough but precise."
    )

    start = time.time()
    try:
        raw = _call_model(model_id, model_config, prompt, system_prompt)
        elapsed = round(time.time() - start, 1)
    except Exception as e:
        elapsed = round(time.time() - start, 1)
        return {
            "model_id": model_id,
            "model_name": model_config.get("name", model_id),
            "lens": lens_name,
            "status": "error",
            "error": str(e),
            "elapsed_seconds": elapsed,
            "findings": [],
        }

    # Check for model-level errors
    if raw.startswith("[") and "unavailable" in raw.lower() or "error" in raw.lower():
        if raw.startswith("[") and raw.endswith("]") and ("unavailable" in raw or "error:" in raw):
            return {
                "model_id": model_id,
                "model_name": model_config.get("name", model_id),
                "lens": lens_name,
                "status": "error",
                "error": raw,
                "elapsed_seconds": elapsed,
                "findings": [],
            }

    findings = _parse_model_findings(raw, model_config.get("name", model_id))

    return {
        "model_id": model_id,
        "model_name": model_config.get("name", model_id),
        "lens": lens_name,
        "status": "ok",
        "elapsed_seconds": elapsed,
        "findings": findings,
        "raw_response": raw,
    }


def _normalize_location(loc: str) -> str:
    """Normalize a location string for matching purposes."""
    loc = loc.lower().strip()
    # Extract line numbers
    line_match = re.search(r'line\s*(\d+)', loc)
    if line_match:
        return f"line_{line_match.group(1)}"
    # Extract function names
    func_match = re.search(r'function\s+(\w+)', loc)
    if func_match:
        return f"func_{func_match.group(1)}"
    # Fall back to cleaned string
    return re.sub(r'[^a-z0-9_]', '_', loc).strip('_')


def synthesize(audit_results: Dict[str, Any]) -> Dict[str, Any]:
    """Merge findings from multiple model audits.

    Returns:
        agreements: findings flagged by 2+ models (high confidence)
        unique_findings: flagged by only 1 model (review needed)
        disagreements: models contradict each other on severity/recommendation
        summary: one-paragraph synthesis
    """
    model_results = audit_results.get("model_results", [])
    if not model_results:
        return {
            "agreements": [],
            "unique_findings": [],
            "disagreements": [],
            "summary": "No model results to synthesize.",
        }

    # Collect all findings with their source lens
    all_findings: List[Dict[str, Any]] = []
    for result in model_results:
        if result.get("status") != "ok":
            continue
        lens = result["lens"]
        model_name = result["model_name"]
        for f in result.get("findings", []):
            all_findings.append({
                **f,
                "lens": lens,
                "model": model_name,
                "norm_location": _normalize_location(f.get("location", "")),
            })

    if not all_findings:
        return {
            "agreements": [],
            "unique_findings": [],
            "disagreements": [],
            "summary": "All models returned clean results. No issues found.",
        }

    # Group by normalized location
    location_groups: Dict[str, List[Dict]] = {}
    for f in all_findings:
        key = f["norm_location"]
        location_groups.setdefault(key, []).append(f)

    agreements = []
    unique_findings = []
    disagreements = []

    for loc_key, findings in location_groups.items():
        models_involved = set(f["model"] for f in findings)
        lenses_involved = set(f["lens"] for f in findings)

        if len(models_involved) >= 2:
            # Check for severity disagreements
            severities = set(f["severity"] for f in findings)
            if len(severities) > 1:
                # Models agree on location but disagree on severity
                disagreements.append({
                    "location": findings[0]["location"],
                    "models": {f["model"]: {
                        "lens": f["lens"],
                        "severity": f["severity"],
                        "finding": f["finding"],
                        "recommendation": f["recommendation"],
                    } for f in findings},
                    "type": "severity_disagreement",
                })
            else:
                # Full agreement
                agreements.append({
                    "location": findings[0]["location"],
                    "severity": findings[0]["severity"],
                    "models_agreed": list(models_involved),
                    "lenses": list(lenses_involved),
                    "findings": {f["lens"]: {
                        "finding": f["finding"],
                        "recommendation": f["recommendation"],
                    } for f in findings},
                })
        else:
            # Only one model flagged this
            f = findings[0]
            unique_findings.append({
                "location": f["location"],
                "severity": f["severity"],
                "lens": f["lens"],
                "model": f["model"],
                "finding": f["finding"],
                "recommendation": f["recommendation"],
            })

    # Sort by severity
    agreements.sort(key=lambda x: SEVERITY_ORDER.get(x["severity"], 5))
    unique_findings.sort(key=lambda x: SEVERITY_ORDER.get(x["severity"], 5))

    # Build summary
    total = len(agreements) + len(unique_findings) + len(disagreements)
    successful_models = [r for r in model_results if r.get("status") == "ok"]
    failed_models = [r for r in model_results if r.get("status") != "ok"]

    summary_parts = [
        f"{len(agreements)} high-confidence finding(s)",
        f"{len(unique_findings)} unique catch(es)",
        f"{len(disagreements)} tradeoff(s)",
    ]
    summary = f"{total} total findings across {len(successful_models)} models: " + ", ".join(summary_parts) + "."

    if failed_models:
        failed_names = [r.get("model_name", "unknown") for r in failed_models]
        summary += f" ({', '.join(failed_names)} failed — results are partial.)"

    if agreements:
        critical_count = sum(1 for a in agreements if a["severity"] == "critical")
        if critical_count:
            summary += f" {critical_count} CRITICAL issue(s) confirmed by multiple models."

    return {
        "agreements": agreements,
        "unique_findings": unique_findings,
        "disagreements": disagreements,
        "summary": summary,
    }


def format_audit_output(audit_results: Dict[str, Any], synthesis: Dict[str, Any]) -> str:
    """Format audit results as human-readable text."""
    lines = []
    lines.append("=== CROSS-MODEL AUDIT ===")

    target_display = audit_results.get("target_display", audit_results.get("target", "unknown"))
    lines.append(f"Target: {target_display}")

    # Model assignments
    model_parts = []
    for r in audit_results.get("model_results", []):
        name = r.get("model_name", r.get("model_id", "?"))
        lens = r.get("lens", "?")
        status = "" if r.get("status") == "ok" else " [FAILED]"
        model_parts.append(f"{name} ({lens}){status}")
    lines.append(f"Models: {' | '.join(model_parts)}")
    lines.append("")

    # High confidence
    agreements = synthesis.get("agreements", [])
    if agreements:
        lines.append("HIGH CONFIDENCE (2+ models agree):")
        for a in agreements:
            sev = a["severity"].upper()
            loc = a["location"]
            lines.append(f"  [{sev}] {loc}")
            for lens, detail in a.get("findings", {}).items():
                lines.append(f"    {lens.title()}: {detail['finding']}")
            # Show first recommendation
            recs = [d["recommendation"] for d in a.get("findings", {}).values() if d.get("recommendation")]
            if recs:
                lines.append(f"    Action: {recs[0]}")
            lines.append("")
    else:
        lines.append("HIGH CONFIDENCE: None (no multi-model agreement)")
        lines.append("")

    # Unique findings
    unique = synthesis.get("unique_findings", [])
    if unique:
        lines.append("UNIQUE FINDINGS (single model):")
        for u in unique:
            sev = u["severity"].upper()
            loc = u["location"]
            lens = u["lens"].title()
            lines.append(f"  [{sev}] {loc} ({lens})")
            lines.append(f"    {u['finding']}")
            if u.get("recommendation"):
                lines.append(f"    Recommendation: {u['recommendation']}")
            lines.append("")
    else:
        lines.append("UNIQUE FINDINGS: None")
        lines.append("")

    # Disagreements
    disagreements = synthesis.get("disagreements", [])
    if disagreements:
        lines.append("DISAGREEMENTS:")
        for d in disagreements:
            loc = d["location"]
            lines.append(f"  {loc}:")
            for model_name, detail in d.get("models", {}).items():
                lines.append(f"    {detail['lens'].title()} ({model_name}): {detail['finding']} [severity: {detail['severity']}]")
            lines.append(f"    Tradeoff: review and decide based on your risk tolerance.")
            lines.append("")
    else:
        lines.append("DISAGREEMENTS: None")
        lines.append("")

    lines.append(f"Summary: {synthesis.get('summary', 'No summary available.')}")

    return "\n".join(lines)


def _select_models_and_lenses(
    lenses: Optional[List[str]] = None,
    models: Optional[List[str]] = None,
) -> Tuple[List[Tuple[str, Dict, str]], Optional[str]]:
    """Select which models get which lenses.

    Returns (assignments, error).
    Each assignment is (model_id, model_config, lens_name).
    """
    from ai.deliberation import get_models_config

    # Resolve lenses
    active_lenses = list(lenses) if lenses else list(AUDIT_LENSES.keys())
    for lens in active_lenses:
        if lens not in AUDIT_LENSES:
            return [], f"Unknown lens: {lens}. Available: {', '.join(AUDIT_LENSES.keys())}"

    # Get available models
    config = get_models_config(allow_hosted_fallback=True)
    enabled = {k: v for k, v in config.items() if v.get("enabled")}

    if not enabled:
        return [], (
            "No models available for audit. Configure API keys in ~/.delimit/models.json "
            "or ensure hosted models are available."
        )

    # If specific models requested, filter
    if models:
        filtered = {}
        for m in models:
            m_lower = m.lower()
            if m_lower in enabled:
                filtered[m_lower] = enabled[m_lower]
            else:
                # Try partial match
                for k, v in enabled.items():
                    if m_lower in k.lower() or m_lower in v.get("name", "").lower():
                        filtered[k] = v
                        break
        if not filtered:
            return [], f"None of the requested models ({', '.join(models)}) are available."
        enabled = filtered

    # Assign lenses to models round-robin
    model_ids = list(enabled.keys())
    assignments = []
    for i, lens in enumerate(active_lenses):
        model_id = model_ids[i % len(model_ids)]
        assignments.append((model_id, enabled[model_id], lens))

    return assignments, None


def audit(
    target: str,
    target_type: str = "file",
    lenses: Optional[List[str]] = None,
    models: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run cross-model audit on a target.

    Args:
        target: File path, diff text, or code snippet.
        target_type: "file", "diff", or "snippet".
        lenses: Which lenses to apply (default: all 3).
        models: Which models to use (default: auto-detect).

    Returns:
        Full audit results with model_results, synthesis, and formatted output.
    """
    start_time = time.time()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Resolve target
    target_code, err = _resolve_target(target, target_type)
    if err:
        return {"status": "error", "error": err}

    # Select models and assign lenses
    assignments, err = _select_models_and_lenses(lenses, models)
    if err:
        return {"status": "error", "error": err}

    # Target display name
    if target_type == "file":
        target_display = target
    elif target_type == "diff":
        first_line = target.strip().split("\n")[0][:80]
        target_display = f"diff: {first_line}..."
    else:
        target_display = f"snippet ({len(target_code)} chars)"

    # Call models in parallel
    results: List[Dict[str, Any]] = [None] * len(assignments)  # type: ignore
    threads = []

    def _run(index: int, model_id: str, config: Dict, lens: str):
        results[index] = _call_model_with_lens(model_id, config, lens, target_code, target_type)

    for i, (model_id, config, lens) in enumerate(assignments):
        t = threading.Thread(target=_run, args=(i, model_id, config, lens), daemon=True)
        threads.append(t)
        t.start()

    # Wait with timeout
    for t in threads:
        t.join(timeout=MODEL_TIMEOUT)

    # Replace any None results (timed out threads)
    for i, r in enumerate(results):
        if r is None:
            model_id, config, lens = assignments[i]
            results[i] = {
                "model_id": model_id,
                "model_name": config.get("name", model_id),
                "lens": lens,
                "status": "error",
                "error": "Timed out after 60 seconds",
                "elapsed_seconds": MODEL_TIMEOUT,
                "findings": [],
            }

    audit_results = {
        "status": "ok",
        "target": target if target_type != "file" else str(target),
        "target_type": target_type,
        "target_display": target_display,
        "timestamp": timestamp,
        "model_results": results,
        "elapsed_seconds": round(time.time() - start_time, 1),
    }

    # Synthesize
    synthesis_result = synthesize(audit_results)
    audit_results["synthesis"] = synthesis_result

    # Format output
    audit_results["formatted"] = format_audit_output(audit_results, synthesis_result)

    # Save to disk
    _save_audit(audit_results, timestamp)

    return audit_results


def _save_audit(audit_results: Dict[str, Any], timestamp: str) -> Optional[str]:
    """Save audit results to ~/.delimit/audits/."""
    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        path = AUDIT_DIR / f"{timestamp}.json"
        # Remove raw_response before saving (can be large)
        save_data = json.loads(json.dumps(audit_results, default=str))
        for r in save_data.get("model_results", []):
            r.pop("raw_response", None)
        path.write_text(json.dumps(save_data, indent=2, default=str))
        audit_results["saved_to"] = str(path)
        return str(path)
    except Exception as e:
        logger.warning("Failed to save audit results: %s", e)
        return None
