"""Event ingestion for dashboard real-time feed."""
import json
import time
from pathlib import Path
from datetime import datetime

EVENTS_DIR = Path.home() / ".delimit" / "events"


def emit(event_type: str, tool: str, model: str = "", detail: str = "", venture: str = ""):
    """Write an event to the daily events log."""
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    event = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "type": event_type,  # tool_call, governance_check, deliberation, deploy, error
        "tool": tool,
        "model": model,
        "detail": detail,
        "venture": venture,
    }
    with open(EVENTS_DIR / f"events-{today}.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")


def recent(limit: int = 50) -> list:
    """Get the most recent events across all days."""
    events = []
    if not EVENTS_DIR.exists():
        return events
    for f in sorted(EVENTS_DIR.glob("events-*.jsonl"), reverse=True):
        for line in reversed(f.read_text().splitlines()):
            try:
                events.append(json.loads(line))
            except Exception:
                pass
            if len(events) >= limit:
                return events
    return events
