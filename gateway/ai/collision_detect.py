"""Duplicate work detection — prevent two AI models from editing the same file (STR-051).

Tracks which model is working on which files. Alerts before collision.
Adjacent problem nobody else solves.

Storage: ~/.delimit/agents/file_locks.json
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

AGENTS_DIR = Path.home() / ".delimit" / "agents"
LOCKS_FILE = AGENTS_DIR / "file_locks.json"

# Lock expires after 30 minutes of inactivity
LOCK_TTL_SECONDS = 1800


def _ensure_dir():
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_locks() -> Dict[str, Any]:
    if not LOCKS_FILE.exists():
        return {}
    try:
        return json.loads(LOCKS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_locks(locks: Dict[str, Any]):
    _ensure_dir()
    LOCKS_FILE.write_text(json.dumps(locks, indent=2))


def _cleanup_expired(locks: Dict[str, Any]) -> Dict[str, Any]:
    now = time.time()
    return {
        path: lock for path, lock in locks.items()
        if now - lock.get("ts", 0) < LOCK_TTL_SECONDS
    }


def claim_file(
    file_path: str,
    model: str,
    task_id: str = "",
) -> Dict[str, Any]:
    """Claim a file for editing. Returns collision info if another model holds it."""
    if not file_path or not model:
        return {"error": "file_path and model are required"}

    file_path = str(Path(file_path).resolve())
    model = model.lower().strip()

    locks = _cleanup_expired(_load_locks())

    existing = locks.get(file_path)
    if existing and existing["model"] != model:
        return {
            "status": "collision",
            "file": file_path,
            "held_by": existing["model"],
            "held_since": existing.get("claimed_at", "unknown"),
            "task_id": existing.get("task_id", ""),
            "your_model": model,
            "message": f"COLLISION: {existing['model']} is already editing {Path(file_path).name}",
            "recommendation": "Coordinate with the other model or wait for them to finish.",
        }

    locks[file_path] = {
        "model": model,
        "task_id": task_id,
        "ts": time.time(),
        "claimed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _save_locks(locks)

    return {
        "status": "claimed",
        "file": file_path,
        "model": model,
        "message": f"{model} claimed {Path(file_path).name}",
    }


def release_file(file_path: str, model: str = "") -> Dict[str, Any]:
    """Release a file lock."""
    file_path = str(Path(file_path).resolve())
    locks = _load_locks()

    if file_path in locks:
        if model and locks[file_path]["model"] != model.lower():
            return {"error": f"File held by {locks[file_path]['model']}, not {model}"}
        del locks[file_path]
        _save_locks(locks)
        return {"status": "released", "file": file_path}

    return {"status": "ok", "message": "File was not locked"}


def check_collisions(model: str = "") -> Dict[str, Any]:
    """Check for active file locks and potential collisions."""
    locks = _cleanup_expired(_load_locks())
    _save_locks(locks)

    active = []
    by_model = {}
    for path, lock in locks.items():
        entry = {
            "file": Path(path).name,
            "full_path": path,
            "model": lock["model"],
            "claimed_at": lock.get("claimed_at", ""),
            "task_id": lock.get("task_id", ""),
        }
        active.append(entry)
        by_model.setdefault(lock["model"], []).append(entry)

    # Detect overlapping directories (two models in same folder)
    dir_models = {}
    for path, lock in locks.items():
        parent = str(Path(path).parent)
        dir_models.setdefault(parent, set()).add(lock["model"])

    hotspots = [
        {"directory": d, "models": list(models), "risk": "high"}
        for d, models in dir_models.items() if len(models) > 1
    ]

    return {
        "status": "ok",
        "active_locks": len(active),
        "locks": active,
        "by_model": {m: len(files) for m, files in by_model.items()},
        "hotspots": hotspots,
        "message": f"{len(active)} active lock(s), {len(hotspots)} hotspot(s)" if active else "No active locks",
    }
