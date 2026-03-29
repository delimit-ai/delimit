"""
Bridge to operational tools: releasepilot, costguard, datasteward, observabilityops.
Governance primitives + internal OS layer.
"""

import os
import sys
import json
import asyncio
import logging
import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional
from .async_utils import run_async

logger = logging.getLogger("delimit.ai.ops_bridge")

PACKAGES = Path(os.environ.get("DELIMIT_HOME", str(Path.home() / ".delimit"))) / "server" / "packages"

# Add PACKAGES dir so `from shared.base_server import BaseMCPServer` resolves
_packages = str(PACKAGES)
if _packages not in sys.path:
    sys.path.insert(0, _packages)

_servers = {}


def _call(pkg: str, factory_name: str, method: str, args: Dict, tool_label: str) -> Dict[str, Any]:
    try:
        srv = _servers.get(pkg)
        if srv is None:
            mod = importlib.import_module(f"{pkg}.server")
            factory = getattr(mod, factory_name)
            srv = factory()
            # Disable DSN requirement for observabilityops in bridge context
            if pkg == "observabilityops" and hasattr(srv, "require_dsn_validation"):
                srv.require_dsn_validation = False
            _servers[pkg] = srv
        fn = getattr(srv, method, None)
        if fn is None:
            return {"tool": tool_label, "status": "not_implemented", "error": f"Method {method} not found"}
        result = run_async(fn(args, None))
        return json.loads(result) if isinstance(result, str) else result
    except Exception as e:
        return {"tool": tool_label, "error": str(e)}


# ─── ReleasePilot (Governance Primitive) ────────────────────────────────

def release_plan(environment: str, version: str, repository: str, services: Optional[List[str]] = None) -> Dict[str, Any]:
    """Generate a release plan for the given environment and version."""
    return _call("releasepilot", "create_releasepilot_server", "_tool_plan",
                 {"environment": environment, "version": version, "repository": repository, "services": services or []}, "release.plan")


def release_validate(environment: str, version: str) -> Dict[str, Any]:
    """Validate release readiness by checking git tags, CHANGELOG, and package.json."""
    import subprocess
    checks = []
    try:
        tags = subprocess.run(["git", "tag", "-l"], capture_output=True, text=True, timeout=10)
        tag_list = tags.stdout.strip().splitlines() if tags.returncode == 0 else []
        has_tag = any(version in t for t in tag_list)
        checks.append({"check": "git_tag", "passed": has_tag, "detail": f"Tag for {version} {'found' if has_tag else 'not found'}"})
    except Exception:
        checks.append({"check": "git_tag", "passed": False, "detail": "git not available"})
    cl = Path("CHANGELOG.md")
    checks.append({"check": "changelog", "passed": cl.exists(), "detail": str(cl) if cl.exists() else "CHANGELOG.md not found"})
    pkg = Path("package.json")
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())
            pkg_ver = data.get("version", "")
            match = pkg_ver == version.lstrip("v")
            checks.append({"check": "package_version", "passed": match, "detail": f"package.json version={pkg_ver}"})
        except Exception:
            checks.append({"check": "package_version", "passed": False, "detail": "Failed to read package.json"})
    passed = all(c["passed"] for c in checks)
    return {"tool": "release.validate", "status": "pass" if passed else "fail", "environment": environment, "version": version, "checks": checks}


def release_status(environment: str) -> Dict[str, Any]:
    """Get current release status for the environment."""
    return _call("releasepilot", "create_releasepilot_server", "_tool_status",
                 {"environment": environment}, "release.status")


def release_rollback(environment: str, version: str, to_version: str) -> Dict[str, Any]:
    """Roll back to a previous version in the specified environment."""
    return _call("releasepilot", "create_releasepilot_server", "_tool_rollback",
                 {"environment": environment, "version": version, "to_version": to_version}, "release.rollback")


def release_history(environment: str, limit: int = 10) -> Dict[str, Any]:
    """Show recent release history from git log."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--decorate", f"-{limit}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return {"tool": "release.history", "status": "error", "error": result.stderr.strip()}
        commits = result.stdout.strip().splitlines()
        tags = subprocess.run(["git", "tag", "-l", "--sort=-creatordate"], capture_output=True, text=True, timeout=10)
        tag_list = tags.stdout.strip().splitlines()[:limit] if tags.returncode == 0 else []
        return {"tool": "release.history", "status": "ok", "environment": environment,
                "recent_commits": commits, "tags": tag_list, "total_commits": len(commits)}
    except Exception as e:
        return {"tool": "release.history", "status": "error", "error": str(e)}


# ─── CostGuard (Governance Primitive) ──────────────────────────────────

def cost_analyze(target: str = ".", options: Optional[Dict] = None) -> Dict[str, Any]:
    """Analyze cloud infrastructure costs for the target path."""
    result = _call("costguard", "create_costguard_server", "_tool_analyze",
                   {"target": target, **(options or {})}, "cost.analyze")
    # Guard against hardcoded fake AWS cost data from stub implementation
    if result.get("total_cost") == 1247.83 or result.get("total_cost") == "1247.83":
        return {"tool": "cost.analyze", "status": "not_configured",
                "error": "No cloud provider configured. Cost analyzer returned placeholder data. Set cloud credentials to enable real cost analysis."}
    return result


def cost_optimize(target: str = ".", options: Optional[Dict] = None) -> Dict[str, Any]:
    """Identify cost optimization opportunities for the target infrastructure."""
    return _call("costguard", "create_costguard_server", "_tool_optimize",
                 {"target": target, **(options or {})}, "cost.optimize")


def cost_alert(action: str = "list", options: Optional[Dict] = None) -> Dict[str, Any]:
    """Manage cost alerts (list, create, delete)."""
    return _call("costguard", "create_costguard_server", "_tool_alerts",
                 {"action": action, **(options or {})}, "cost.alert")


# ─── DataSteward (Governance Primitive) ────────────────────────────────

def data_validate(target: str = ".", options: Optional[Dict] = None) -> Dict[str, Any]:
    """Run data integrity and validation checks on the target database."""
    result = _call("datasteward", "create_datasteward_server", "_tool_integrity_check",
                   {"database_url": target, **(options or {})}, "data.validate")
    # Guard against stub that returns "passed" with 0 tables checked
    if result.get("tables_checked", -1) == 0 and result.get("integrity_status") == "passed":
        return {"tool": "data.validate", "status": "not_configured",
                "error": "No database configured for validation. Provide a database_url or configure a data source."}
    return result


def data_migrate(target: str = ".", options: Optional[Dict] = None) -> Dict[str, Any]:
    """Check for pending database migrations and reporting status."""
    return _call("datasteward", "create_datasteward_server", "_tool_migration_status",
                 {"database_url": target, **(options or {})}, "data.migrate")


def data_backup(target: str = ".", options: Optional[Dict] = None) -> Dict[str, Any]:
    """Create a backup plan or execute backup for the target database."""
    return _call("datasteward", "create_datasteward_server", "_tool_backup_plan",
                 {"database_url": target, **(options or {})}, "data.backup")


# ─── ObservabilityOps (Internal OS) ────────────────────────────────────

def obs_metrics(query: str, time_range: str = "1h", source: Optional[str] = None) -> Dict[str, Any]:
    """Query live system metrics (CPU, memory, disk, network)."""
    return _call("observabilityops", "create_observabilityops_server", "_tool_metrics",
                 {"query": query, "time_range": time_range, "source": source}, "obs.metrics")


def obs_logs(query: str, time_range: str = "1h", source: Optional[str] = None) -> Dict[str, Any]:
    """Search and retrieve system or application logs."""
    return _call("observabilityops", "create_observabilityops_server", "_tool_logs",
                 {"query": query, "time_range": time_range, "source": source}, "obs.logs")


def obs_alerts(action: str, alert_rule: Optional[Dict] = None, rule_id: Optional[str] = None) -> Dict[str, Any]:
    """File-based alert management using ~/.delimit/alerts/."""
    alerts_dir = Path(os.environ.get("DELIMIT_HOME", str(Path.home() / ".delimit"))) / "alerts"
    alerts_dir.mkdir(parents=True, exist_ok=True)
    if action == "list":
        alerts = []
        for fp in sorted(alerts_dir.glob("*.json")):
            try:
                alerts.append(json.loads(fp.read_text()))
            except Exception:
                pass
        return {"tool": "obs.alerts", "status": "ok", "action": "list", "alerts": alerts, "total": len(alerts)}
    elif action == "create" and alert_rule:
        import time as _time
        aid = f"alert-{int(_time.time())}"
        alert_rule["id"] = aid
        alert_rule["created_at"] = _time.time()
        (alerts_dir / f"{aid}.json").write_text(json.dumps(alert_rule, indent=2))
        return {"tool": "obs.alerts", "status": "created", "alert": alert_rule}
    elif action == "delete" and rule_id:
        fp = alerts_dir / f"{rule_id}.json"
        if fp.exists():
            fp.unlink()
            return {"tool": "obs.alerts", "status": "deleted", "rule_id": rule_id}
        return {"tool": "obs.alerts", "status": "not_found", "rule_id": rule_id}
    return {"tool": "obs.alerts", "status": "unknown_action", "action": action}


def obs_status() -> Dict[str, Any]:
    """Get overall system health and observability status."""
    return _call("observabilityops", "create_observabilityops_server", "_tool_status",
                 {}, "obs.status")
