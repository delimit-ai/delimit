"""Local API server — serves ~/.delimit/ data over HTTP for dashboard access.

Runs on localhost:7823. The dashboard connects here to show local data.
No auth needed (localhost only). CORS enabled for app.delimit.ai.
"""
import json
import os
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

def _get_delimit_home() -> Path:
    return Path(os.environ.get("DELIMIT_HOME", str(Path.home() / ".delimit")))

DELIMIT_HOME = _get_delimit_home()  # Default, can be overridden
PORT = int(os.environ.get("DELIMIT_LOCAL_PORT", 7823))

ALLOWED_ORIGINS = {
    "https://app.delimit.ai",
    "http://localhost:3000",
    "http://localhost:3001",
}


class DelimitHandler(BaseHTTPRequestHandler):
    """HTTP handler for the local Delimit API."""

    def _get_origin(self):
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            return origin
        return ""

    def _send_cors_headers(self):
        origin = self._get_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")

    def do_GET(self):
        path = self.path.split("?")[0]

        routes = {
            "/api/health": self.handle_health,
            "/api/ledger": self.handle_ledger,
            "/api/events": self.handle_events,
            "/api/governance": self.handle_governance,
            "/api/daemon": self.handle_daemon,
            "/api/sessions": self.handle_sessions,
        }

        handler = routes.get(path)
        if handler:
            try:
                data = handler()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def log_message(self, format, *args):
        """Suppress default stderr logging."""
        pass

    # ── Route handlers ──────────────────────────────────────────────

    @staticmethod
    def _home() -> Path:
        """Read DELIMIT_HOME dynamically for testability."""
        return Path(os.environ.get("DELIMIT_HOME", str(Path.home() / ".delimit")))

    def handle_health(self):
        return {
            "status": "ok",
            "port": PORT,
            "home": str(self._home()),
        }

    def handle_ledger(self):
        items = []
        for fname in ["operations.jsonl", "strategy.jsonl"]:
            fpath = self._home() / "ledger" / fname
            if not fpath.exists():
                continue
            latest = {}
            for line in fpath.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry_id = entry.get("id")
                    if not entry_id:
                        continue
                    if entry.get("type") == "update" and entry_id in latest:
                        latest[entry_id].update(entry)
                    elif entry.get("type") != "update":
                        latest[entry_id] = entry
                except (json.JSONDecodeError, TypeError):
                    pass
            items.extend(latest.values())

        open_items = [i for i in items if i.get("status") == "open"]
        done_items = [i for i in items if i.get("status") == "done"]
        return {
            "items": items,
            "summary": {
                "total": len(items),
                "open": len(open_items),
                "done": len(done_items),
            },
        }

    def handle_events(self):
        events_dir = self._home() / "events"
        if not events_dir.exists():
            return {"events": []}
        events = []
        for f in sorted(events_dir.glob("events-*.jsonl"), reverse=True):
            for line in reversed(f.read_text().splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except (json.JSONDecodeError, TypeError):
                    pass
                if len(events) >= 50:
                    break
            if len(events) >= 50:
                break
        return {"events": events}

    def handle_governance(self):
        gov_dir = self._home() / "governance"
        if not gov_dir.exists():
            return {"checks": [], "overall": "unknown"}
        checks = []
        for f in gov_dir.glob("*.json"):
            try:
                checks.append(json.loads(f.read_text()))
            except (json.JSONDecodeError, TypeError):
                pass
        overall = "pass" if checks and all(
            c.get("status") == "pass" for c in checks
        ) else "warn"
        return {"checks": checks, "overall": overall}

    def handle_daemon(self):
        state_file = self._home() / "daemon" / "state.json"
        if state_file.exists():
            try:
                return json.loads(state_file.read_text())
            except (json.JSONDecodeError, TypeError):
                pass
        return {"status": "not_running", "loops": 0}

    def handle_sessions(self):
        sessions_dir = self._home() / "sessions"
        if not sessions_dir.exists():
            return {"sessions": []}
        sessions = []
        for f in sessions_dir.glob("*.json"):
            try:
                sessions.append(json.loads(f.read_text()))
            except (json.JSONDecodeError, TypeError):
                pass
        return {"sessions": sessions}


def start_server(port=None, background=True):
    """Start the local API server.

    Args:
        port: Port to bind (default: DELIMIT_LOCAL_PORT env or 7823).
        background: If True, run in a daemon thread and return the server.
                    If False, block forever with serve_forever().

    Returns:
        The HTTPServer instance (background=True) or never returns (background=False).
    """
    if port is None:
        port = PORT
    server = HTTPServer(("127.0.0.1", port), DelimitHandler)
    print(f"Delimit local server running on http://localhost:{port}")
    if background:
        import threading
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server
    else:
        server.serve_forever()


if __name__ == "__main__":
    start_server(background=False)
