"""
Memory bridge — file-based semantic memory store.
Stores memories as JSON files in ~/.delimit/memory/.
"""

import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("delimit.ai.memory_bridge")

MEMORY_DIR = Path.home() / ".delimit" / "memory"


def _ensure_dir():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def store(content: str, tags: Optional[list] = None, context: Optional[str] = None) -> Dict[str, Any]:
    """Store a memory entry."""
    _ensure_dir()

    # Generate ID from content hash
    mem_id = "mem-" + hashlib.sha256(content[:100].encode()).hexdigest()[:12]
    ts = datetime.now(timezone.utc).isoformat()

    entry = {
        "id": mem_id,
        "content": content,
        "tags": tags or [],
        "context": context or "",
        "created_at": ts,
    }

    path = MEMORY_DIR / f"{mem_id}.json"
    path.write_text(json.dumps(entry, indent=2))

    return {"stored": mem_id, "path": str(path), "created_at": ts}


def search(query: str, limit: int = 10) -> Dict[str, Any]:
    """Search memories by keyword matching."""
    _ensure_dir()
    query_lower = query.lower()
    results = []

    for f in sorted(MEMORY_DIR.glob("*.json"), reverse=True):
        try:
            entry = json.loads(f.read_text())
            content = entry.get("content", "").lower()
            tags = " ".join(entry.get("tags", [])).lower()
            context = entry.get("context", "").lower()

            # Simple keyword matching
            if query_lower in content or query_lower in tags or query_lower in context:
                results.append({
                    "id": entry.get("id", f.stem),
                    "content": entry.get("content", "")[:500],
                    "tags": entry.get("tags", []),
                    "created_at": entry.get("created_at", ""),
                    "relevance": content.count(query_lower),
                })

            if len(results) >= limit:
                break
        except Exception:
            pass

    results.sort(key=lambda r: r.get("relevance", 0), reverse=True)
    return {"query": query, "results": results, "count": len(results)}


def get_recent(limit: int = 5) -> Dict[str, Any]:
    """Get recent memory entries."""
    _ensure_dir()
    entries = []

    for f in sorted(MEMORY_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if len(entries) >= limit:
            break
        try:
            entry = json.loads(f.read_text())
            entries.append({
                "id": entry.get("id", f.stem),
                "content": entry.get("content", "")[:500],
                "tags": entry.get("tags", []),
                "created_at": entry.get("created_at", ""),
            })
        except Exception:
            pass

    return {"results": entries, "count": len(entries)}
