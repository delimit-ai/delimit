"""
Vault bridge — file-based artifact and snapshot storage.
Stores vault entries as JSON files in ~/.delimit/vault/.
"""

import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("delimit.ai.vault_bridge")

VAULT_DIR = Path.home() / ".delimit" / "vault"


def _ensure_dir():
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    (VAULT_DIR / "snapshots").mkdir(exist_ok=True)
    (VAULT_DIR / "entries").mkdir(exist_ok=True)


def search(query: str) -> Dict[str, Any]:
    """Search vault entries by keyword."""
    _ensure_dir()
    query_lower = query.lower()
    results = []

    for f in sorted((VAULT_DIR / "entries").glob("*.json"), reverse=True):
        try:
            entry = json.loads(f.read_text())
            content = json.dumps(entry).lower()
            if query_lower in content:
                results.append({
                    "id": entry.get("id", f.stem),
                    "title": entry.get("title", f.stem),
                    "type": entry.get("type", "unknown"),
                    "created_at": entry.get("created_at", ""),
                    "preview": str(entry.get("content", ""))[:200],
                })
            if len(results) >= 10:
                break
        except Exception:
            pass

    return {"query": query, "results": results, "count": len(results)}


def snapshot(task_id: str = "vault-snapshot") -> Dict[str, Any]:
    """Create a vault snapshot."""
    _ensure_dir()
    ts = datetime.now(timezone.utc)
    snap_id = f"snap-{ts.strftime('%Y%m%d_%H%M%S')}"

    snapshot_data = {
        "id": snap_id,
        "task_id": task_id,
        "label": snap_id,
        "created_at": ts.isoformat(),
        "entries_count": len(list((VAULT_DIR / "entries").glob("*.json"))),
    }

    (VAULT_DIR / "snapshots" / f"{snap_id}.json").write_text(
        json.dumps(snapshot_data, indent=2)
    )

    return {"snapshot_id": snap_id, "created_at": ts.isoformat()}


def health() -> Dict[str, Any]:
    """Check vault health."""
    _ensure_dir()

    entries_count = len(list((VAULT_DIR / "entries").glob("*.json")))
    snapshots_count = len(list((VAULT_DIR / "snapshots").glob("*.json")))
    total_size = sum(f.stat().st_size for f in VAULT_DIR.rglob("*") if f.is_file())

    return {
        "status": "healthy",
        "entries": entries_count,
        "snapshots": snapshots_count,
        "total_size_bytes": total_size,
        "vault_path": str(VAULT_DIR),
    }
