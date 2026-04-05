"""Supabase sync -- writes gateway data to cloud for dashboard access.

Writes are fire-and-forget (never blocks tool execution).
If Supabase is unreachable, data stays in local files (always the source of truth).
"""
import json
import os
import logging
import uuid
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("delimit.supabase_sync")

_client = None
_init_attempted = False
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# Also check local secrets file
if not SUPABASE_URL:
    secrets_file = Path.home() / ".delimit" / "secrets" / "supabase.json"
    if secrets_file.exists():
        try:
            creds = json.loads(secrets_file.read_text())
            SUPABASE_URL = creds.get("url", "")
            SUPABASE_KEY = creds.get("service_role_key", "")
        except Exception:
            pass


def _get_client():
    """Lazy-init Supabase client. Returns the SDK client, 'http' for fallback, or None."""
    global _client, _init_attempted
    if _client is not None:
        return _client
    if _init_attempted:
        return _client  # Already tried and failed, return cached result (may be None or "http")
    _init_attempted = True
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        return _client
    except ImportError:
        logger.debug("supabase-py not installed, using HTTP fallback")
        _client = "http"
        return _client
    except Exception as e:
        logger.warning(f"Supabase init failed: {e}")
        _client = "http"  # Fall back to HTTP rather than giving up entirely
        return _client


def _http_post(table: str, data: dict, headers_extra: Optional[Dict] = None) -> bool:
    """POST to Supabase REST API without the SDK."""
    import urllib.request
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("apikey", SUPABASE_KEY)
        req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
        req.add_header("Prefer", "return=minimal")
        if headers_extra:
            for k, v in headers_extra.items():
                req.add_header(k, v)
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception as e:
        logger.debug(f"Supabase HTTP POST to {table} failed: {e}")
        return False


def _http_patch(table: str, query: str, data: dict) -> bool:
    """PATCH to Supabase REST API without the SDK."""
    import urllib.request
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table}?{query}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method="PATCH")
        req.add_header("Content-Type", "application/json")
        req.add_header("apikey", SUPABASE_KEY)
        req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
        req.add_header("Prefer", "return=minimal")
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception as e:
        logger.debug(f"Supabase HTTP PATCH to {table} failed: {e}")
        return False


def sync_event(event: dict):
    """Sync an event to Supabase (fire-and-forget).

    Maps the gateway event dict to the Supabase events table schema:
      id (uuid, required), type (text, required), tool (text, required),
      ts, model, status, venture, detail, user_id, session_id
    """
    try:
        client = _get_client()
        if client is None:
            return
        row = {
            "id": str(uuid.uuid4()),
            "type": event.get("type", "tool_call"),
            "tool": event.get("tool", "unknown"),
            "ts": event.get("ts", ""),
            "model": event.get("model", ""),
            "status": event.get("status", "ok"),
            "venture": event.get("venture", ""),
            "session_id": event.get("session_id", ""),
            "user_id": event.get("user_id", ""),
        }
        # Include risk_level and trace info in detail field
        detail_parts = []
        if event.get("risk_level"):
            detail_parts.append(f"risk={event['risk_level']}")
        if event.get("trace_id"):
            detail_parts.append(f"trace={event['trace_id']}")
        if event.get("span_id"):
            detail_parts.append(f"span={event['span_id']}")
        if detail_parts:
            row["detail"] = " ".join(detail_parts)

        if client == "http":
            _http_post("events", row)
        else:
            client.table("events").insert(row).execute()
    except Exception as e:
        logger.debug(f"Event sync failed: {e}")


def sync_ledger_item(item: dict):
    """Sync a ledger item to Supabase (upsert).

    Maps the gateway ledger item to the Supabase ledger_items table schema:
      id (text, required), title (text, required), priority, venture,
      status, description, source, note, assignee
    """
    try:
        client = _get_client()
        if client is None:
            return
        row = {
            "id": item.get("id", ""),
            "title": item.get("title", ""),
            "priority": item.get("priority", "P1"),
            "venture": item.get("venture", ""),
            "status": item.get("status", "open"),
            "description": item.get("description", ""),
            "source": item.get("source", "mcp"),
        }
        if not row["id"] or not row["title"]:
            return  # Required fields missing
        if client == "http":
            _http_post(
                "ledger_items",
                row,
                headers_extra={
                    "Prefer": "resolution=merge-duplicates,return=minimal",
                },
            )
        else:
            client.table("ledger_items").upsert(row).execute()
    except Exception as e:
        logger.debug(f"Ledger item sync failed: {e}")


def sync_ledger_update(item_id: str, status: str, note: str = ""):
    """Sync a ledger status update to Supabase."""
    try:
        client = _get_client()
        if client is None:
            return
        update = {"status": status}
        if note:
            update["note"] = note
        if status == "done":
            from datetime import datetime, timezone
            update["completed_at"] = datetime.now(timezone.utc).isoformat()

        if client == "http":
            _http_patch("ledger_items", f"id=eq.{item_id}", update)
        else:
            client.table("ledger_items").update(update).eq("id", item_id).execute()
    except Exception as e:
        logger.debug(f"Ledger update sync failed: {e}")
