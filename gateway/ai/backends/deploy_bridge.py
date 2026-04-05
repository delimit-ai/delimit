"""
Bridge to deploy tracking — file-based deploy plan management.
Tier 3 Extended — tracks deploy plans, builds, and rollbacks locally.

No external server required. Plans stored at ~/.delimit/deploys/.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("delimit.ai.deploy_bridge")

DEPLOY_DIR = Path.home() / ".delimit" / "deploys"


def _ensure_dir():
    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)


def _list_plans(app: Optional[str] = None, env: Optional[str] = None) -> List[Dict]:
    """List all deploy plans, optionally filtered by app and/or env."""
    _ensure_dir()
    plans = []
    for f in sorted(DEPLOY_DIR.glob("PLAN-*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            if app and data.get("app") != app:
                continue
            if env and data.get("env") != env:
                continue
            plans.append(data)
        except Exception:
            continue
    return plans


def plan(app: str, env: str, git_ref: Optional[str] = None) -> Dict[str, Any]:
    """Create a deploy plan."""
    _ensure_dir()
    plan_id = f"PLAN-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "plan_id": plan_id,
        "app": app,
        "env": env,
        "git_ref": git_ref or "HEAD",
        "status": "planned",
        "created_at": now,
        "updated_at": now,
        "history": [{"status": "planned", "at": now}],
    }
    (DEPLOY_DIR / f"{plan_id}.json").write_text(json.dumps(data, indent=2))
    return data


def status(app: str, env: str) -> Dict[str, Any]:
    """Get latest deploy status for an app+env."""
    plans = _list_plans(app=app, env=env)
    if not plans:
        return {
            "app": app,
            "env": env,
            "status": "no_deploys",
            "message": f"No deploy plans found for {app} in {env}.",
        }
    latest = plans[0]
    return {
        "app": app,
        "env": env,
        "latest_plan": latest["plan_id"],
        "status": latest["status"],
        "git_ref": latest.get("git_ref"),
        "updated_at": latest.get("updated_at"),
        "total_plans": len(plans),
    }


def build(app: str, git_ref: Optional[str] = None) -> Dict[str, Any]:
    """Check if a Dockerfile exists and return build info."""
    dockerfile = Path.cwd() / "Dockerfile"
    if not dockerfile.exists():
        # Check app-specific paths
        for candidate in [Path.home() / app / "Dockerfile", Path(f"./{app}/Dockerfile")]:
            if candidate.exists():
                dockerfile = candidate
                break

    if dockerfile.exists():
        return {
            "app": app,
            "git_ref": git_ref or "HEAD",
            "dockerfile": str(dockerfile),
            "status": "ready",
            "message": f"Dockerfile found at {dockerfile}. Ready to build.",
        }
    return {
        "app": app,
        "git_ref": git_ref or "HEAD",
        "status": "no_dockerfile",
        "message": f"No Dockerfile found for {app}. Create one to enable Docker builds.",
    }


def publish(app: str, git_ref: Optional[str] = None) -> Dict[str, Any]:
    """Update latest plan status to published after basic readiness checks."""
    plans = _list_plans(app=app)
    if not plans:
        return {"error": f"No deploy plans found for {app}"}
    latest = plans[0]
    current_status = latest.get("status", "unknown")
    if current_status == "published":
        return {
            "app": app,
            "plan_id": latest["plan_id"],
            "status": "already_published",
            "message": f"Latest plan {latest['plan_id']} is already published.",
        }
    if current_status == "rolled_back":
        return {
            "app": app,
            "plan_id": latest["plan_id"],
            "status": "invalid_state",
            "message": f"Latest plan {latest['plan_id']} was rolled back and cannot be republished.",
            "current_status": current_status,
        }
    if current_status not in {"planned", "built", "verified"}:
        return {
            "app": app,
            "plan_id": latest["plan_id"],
            "status": "invalid_state",
            "message": f"Latest plan {latest['plan_id']} is not ready to publish from status '{current_status}'.",
            "current_status": current_status,
        }

    build_result = build(app=app, git_ref=git_ref or latest.get("git_ref"))
    if build_result.get("status") != "ready":
        return {
            "app": app,
            "plan_id": latest["plan_id"],
            "status": "not_ready",
            "message": build_result.get("message", "Build prerequisites are not satisfied."),
            "build_status": build_result.get("status"),
        }

    now = datetime.now(timezone.utc).isoformat()
    latest["status"] = "published"
    latest["updated_at"] = now
    latest["history"].append({"status": "published", "at": now})
    (DEPLOY_DIR / f"{latest['plan_id']}.json").write_text(json.dumps(latest, indent=2))
    return latest


DEPLOY_TARGETS = [
    {"name": "delimit.ai", "url": "https://delimit.ai", "kind": "vercel"},
    {"name": "electricgrill.com", "url": "https://electricgrill.com", "kind": "vercel"},
    {"name": "robotax.com", "url": "https://robotax.com", "kind": "vercel"},
    {"name": "npm:delimit-cli", "url": "https://www.npmjs.com/package/delimit-cli", "kind": "npm"},
    {"name": "github:delimit-mcp-server", "url": "https://github.com/delimit-ai/delimit-mcp-server", "kind": "github"},
]


def _check_http_health(url: str, timeout: int = 10) -> Dict[str, Any]:
    """Check HTTP health for a single URL. Returns status, response time, headers."""
    import ssl
    import time
    import urllib.request

    result: Dict[str, Any] = {"url": url, "healthy": False}
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "delimit-deploy-verify/1.0"})
        start = time.monotonic()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            elapsed_ms = round((time.monotonic() - start) * 1000)
            result["status_code"] = resp.status
            result["response_time_ms"] = elapsed_ms
            result["healthy"] = 200 <= resp.status < 400
    except Exception as exc:
        result["error"] = str(exc)
        result["status_code"] = None
        result["response_time_ms"] = None
    return result


def _check_ssl_cert(hostname: str, port: int = 443, warn_days: int = 30) -> Dict[str, Any]:
    """Validate SSL certificate for a hostname. Checks expiry within warn_days."""
    import socket
    import ssl

    result: Dict[str, Any] = {"hostname": hostname, "ssl_valid": False}
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                if not cert:
                    result["error"] = "No certificate returned"
                    return result
                not_after_str = cert.get("notAfter", "")
                # Python ssl cert dates: 'Mon DD HH:MM:SS YYYY GMT'
                not_after = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                days_remaining = (not_after - now).days
                result["ssl_valid"] = True
                result["expires"] = not_after.isoformat()
                result["days_remaining"] = days_remaining
                result["expiry_warning"] = days_remaining < warn_days
                if days_remaining < warn_days:
                    result["warning"] = f"SSL certificate expires in {days_remaining} days (threshold: {warn_days})"
                # Extract issuer for diagnostics
                issuer = dict(x[0] for x in cert.get("issuer", ()))
                result["issuer"] = issuer.get("organizationName", issuer.get("commonName", "unknown"))
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _check_npm_version(expected_version: Optional[str] = None) -> Dict[str, Any]:
    """Check the published npm version of delimit-cli."""
    import subprocess

    result: Dict[str, Any] = {"package": "delimit-cli", "healthy": False}
    try:
        proc = subprocess.run(
            ["npm", "view", "delimit-cli", "version"],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode == 0:
            published = proc.stdout.strip()
            result["published_version"] = published
            result["healthy"] = True
            if expected_version:
                result["expected_version"] = expected_version
                result["version_match"] = published == expected_version
                if published != expected_version:
                    result["warning"] = f"Version mismatch: published={published}, expected={expected_version}"
        else:
            result["error"] = proc.stderr.strip() or "npm view returned non-zero"
    except FileNotFoundError:
        result["error"] = "npm not found on PATH"
    except subprocess.TimeoutExpired:
        result["error"] = "npm view timed out after 15s"
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _extract_hostname(url: str) -> str:
    """Extract hostname from a URL."""
    from urllib.parse import urlparse
    return urlparse(url).hostname or ""


def verify(app: str, env: str, git_ref: Optional[str] = None) -> Dict[str, Any]:
    """Verify deployment health with real HTTP checks, SSL validation, and npm version.

    Checks every deployment target for:
    - HTTP 2xx reachability and response time
    - SSL certificate validity (warns if expiring within 30 days)
    - npm published version (for npm targets)

    Also cross-references local deploy plan status when available.
    """
    now = datetime.now(timezone.utc).isoformat()
    checks: List[Dict[str, Any]] = []
    all_healthy = True
    warnings: List[str] = []

    for target in DEPLOY_TARGETS:
        entry: Dict[str, Any] = {"name": target["name"], "kind": target["kind"]}

        # HTTP health
        http = _check_http_health(target["url"])
        entry["http"] = http
        if not http.get("healthy"):
            all_healthy = False

        # SSL cert check
        hostname = _extract_hostname(target["url"])
        if hostname:
            ssl_result = _check_ssl_cert(hostname)
            entry["ssl"] = ssl_result
            if ssl_result.get("expiry_warning"):
                warnings.append(ssl_result.get("warning", f"SSL expiry warning for {hostname}"))
            if not ssl_result.get("ssl_valid"):
                all_healthy = False

        # npm version check (only for npm targets)
        if target["kind"] == "npm":
            npm_result = _check_npm_version()
            entry["npm"] = npm_result
            if not npm_result.get("healthy"):
                all_healthy = False

        checks.append(entry)

    # Cross-reference deploy plan if one exists
    plan_info: Optional[Dict[str, Any]] = None
    plans = _list_plans(app=app or None, env=env or None)
    if plans:
        latest = plans[0]
        plan_info = {
            "plan_id": latest["plan_id"],
            "plan_status": latest["status"],
            "updated_at": latest.get("updated_at"),
        }

    result: Dict[str, Any] = {
        "app": app or "all",
        "env": env or "production",
        "verified_at": now,
        "healthy": all_healthy,
        "targets_checked": len(checks),
        "targets_healthy": sum(1 for c in checks if c.get("http", {}).get("healthy")),
        "checks": checks,
    }
    if warnings:
        result["warnings"] = warnings
    if plan_info:
        result["deploy_plan"] = plan_info
    return result


def rollback(app: str, env: str, to_sha: Optional[str] = None) -> Dict[str, Any]:
    """Mark latest published plan as rolled back."""
    plans = _list_plans(app=app, env=env)
    if not plans:
        return {"error": f"No deploy plans found for {app} in {env}"}
    latest = plans[0]
    current_status = latest.get("status", "unknown")
    if current_status == "rolled_back":
        return {
            "app": app,
            "env": env,
            "plan_id": latest["plan_id"],
            "status": "already_rolled_back",
            "rolled_back_to": latest.get("rolled_back_to"),
        }
    if current_status != "published":
        return {
            "app": app,
            "env": env,
            "plan_id": latest["plan_id"],
            "status": "not_ready",
            "message": f"Cannot roll back plan {latest['plan_id']} from status '{current_status}'. Publish it first.",
            "current_status": current_status,
        }

    now = datetime.now(timezone.utc).isoformat()
    latest["status"] = "rolled_back"
    latest["updated_at"] = now
    latest["rolled_back_to"] = to_sha
    latest["history"].append({"status": "rolled_back", "at": now, "to_sha": to_sha})
    (DEPLOY_DIR / f"{latest['plan_id']}.json").write_text(json.dumps(latest, indent=2))
    return latest
