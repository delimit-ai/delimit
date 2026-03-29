"""Prompt Playbook — versioned, reusable prompt templates (STR-048).

Save prompts as named commands that work across any AI assistant.
Share them with your team. Version them per model.

Storage: ~/.delimit/playbooks/
Format: YAML files with name, prompt, variables, model hints.

Focus group origin: "Prompt management is a total disaster.
Slack channels, Notion docs, personal text files."
"""

import json
import time
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

PLAYBOOKS_DIR = Path.home() / ".delimit" / "playbooks"


def _ensure_dir():
    PLAYBOOKS_DIR.mkdir(parents=True, exist_ok=True)


def _playbook_path(name: str) -> Path:
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', name.lower().strip())
    return PLAYBOOKS_DIR / f"{safe}.json"


def save_playbook(
    name: str,
    prompt: str,
    description: str = "",
    variables: Optional[List[str]] = None,
    model_hint: str = "",
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Save a named prompt template.

    Variables use {{var_name}} syntax in the prompt text.
    Example: "Generate tests for {{file_path}} using {{framework}}"
    """
    if not name or not name.strip():
        return {"error": "name is required"}
    if not prompt or not prompt.strip():
        return {"error": "prompt is required"}

    name = name.strip()
    _ensure_dir()

    # Auto-detect variables from {{var}} patterns
    detected_vars = re.findall(r'\{\{(\w+)\}\}', prompt)
    all_vars = list(set((variables or []) + detected_vars))

    playbook = {
        "name": name,
        "prompt": prompt,
        "description": description or f"Playbook: {name}",
        "variables": all_vars,
        "model_hint": model_hint,
        "tags": tags or [],
        "version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    pb_path = _playbook_path(name)

    # If exists, increment version
    if pb_path.exists():
        try:
            existing = json.loads(pb_path.read_text())
            playbook["version"] = existing.get("version", 0) + 1
            playbook["created_at"] = existing.get("created_at", playbook["created_at"])
        except (json.JSONDecodeError, OSError):
            pass

    pb_path.write_text(json.dumps(playbook, indent=2))

    return {
        "status": "saved",
        "name": name,
        "version": playbook["version"],
        "variables": all_vars,
        "path": str(pb_path),
        "message": f"Playbook '{name}' saved (v{playbook['version']})",
    }


def run_playbook(
    name: str,
    variables: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Load and render a named playbook with variables filled in.

    Returns the rendered prompt ready to send to an AI model.
    """
    if not name or not name.strip():
        return {"error": "name is required"}

    pb_path = _playbook_path(name.strip())
    if not pb_path.exists():
        # Try fuzzy match
        matches = list(PLAYBOOKS_DIR.glob("*.json"))
        suggestions = []
        for m in matches:
            try:
                pb = json.loads(m.read_text())
                suggestions.append(pb["name"])
            except:
                pass
        return {
            "error": f"Playbook '{name}' not found",
            "available": suggestions[:10],
        }

    try:
        playbook = json.loads(pb_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"Failed to read playbook: {e}"}

    prompt = playbook["prompt"]
    vars_used = variables or {}

    # Fill in variables
    missing = []
    for var in playbook.get("variables", []):
        if var in vars_used:
            prompt = prompt.replace(f"{{{{{var}}}}}", vars_used[var])
        else:
            missing.append(var)

    return {
        "status": "ready",
        "name": playbook["name"],
        "version": playbook["version"],
        "rendered_prompt": prompt,
        "model_hint": playbook.get("model_hint", ""),
        "missing_variables": missing,
        "message": f"Playbook '{name}' ready" + (f" (missing: {', '.join(missing)})" if missing else ""),
    }


def list_playbooks(tag: str = "") -> Dict[str, Any]:
    """List all saved playbooks, optionally filtered by tag."""
    _ensure_dir()
    playbooks = []

    for pb_file in sorted(PLAYBOOKS_DIR.glob("*.json")):
        try:
            pb = json.loads(pb_file.read_text())
            if tag and tag not in pb.get("tags", []):
                continue
            playbooks.append({
                "name": pb["name"],
                "description": pb.get("description", ""),
                "version": pb.get("version", 1),
                "variables": pb.get("variables", []),
                "model_hint": pb.get("model_hint", ""),
                "tags": pb.get("tags", []),
            })
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "status": "ok",
        "playbooks": playbooks,
        "total": len(playbooks),
    }


def delete_playbook(name: str) -> Dict[str, Any]:
    """Delete a named playbook."""
    if not name:
        return {"error": "name is required"}

    pb_path = _playbook_path(name.strip())
    if not pb_path.exists():
        return {"error": f"Playbook '{name}' not found"}

    pb_path.unlink()
    return {
        "status": "deleted",
        "name": name,
        "message": f"Playbook '{name}' deleted",
    }
