"""
Bridge to delimit-os MCP server.
Tier 2 Platform tools — pass-through to the OS orchestration layer.

These do NOT re-implement OS logic. They translate requests
and forward to the running delimit-os server via direct import.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("delimit.ai.os_bridge")

OS_PACKAGE = Path(os.environ.get("DELIMIT_HOME", str(Path.home() / ".delimit"))) / "server" / "packages" / "delimit-os"

_NOT_INIT_MSG = (
    "Project not initialized for governance. "
    "Say 'initialize governance for this project' "
    "or run the delimit_init tool with your project path."
)

_DEPENDENCY_MSG = "delimit-os backend is not installed or not available in this environment."


def _is_initialized(path: str = ".") -> bool:
    """A project is initialized if .delimit/policies.yml exists."""
    return (Path(path).resolve() / ".delimit" / "policies.yml").is_file()


def _ensure_os_path():
    if str(OS_PACKAGE) not in sys.path:
        sys.path.insert(0, str(OS_PACKAGE))


def _backend_unavailable(path: Optional[str] = None) -> Dict[str, Any]:
    """Return a truthful error for missing OS backend support."""
    if path and not _is_initialized(path):
        return {"error": _NOT_INIT_MSG, "fallback": True}
    return {"error": _DEPENDENCY_MSG, "fallback": True}


def create_plan(operation: str, target: str, parameters: Optional[Dict] = None, require_approval: bool = True) -> Dict[str, Any]:
    """Create an execution plan via delimit-os."""
    if not OS_PACKAGE.exists():
        return _backend_unavailable(target)
    _ensure_os_path()
    try:
        from server import PLANS
        import uuid, time

        plan_id = f"PLAN-{str(uuid.uuid4())[:8].upper()}"
        risk_level = "LOW"
        if any(x in operation.lower() for x in ["prod", "delete", "drop", "rm"]):
            risk_level = "HIGH"
        elif any(x in operation.lower() for x in ["deploy", "restart", "update"]):
            risk_level = "MEDIUM"

        plan = {
            "plan_id": plan_id,
            "operation": operation,
            "target": target,
            "parameters": parameters or {},
            "risk_level": risk_level,
            "status": "PENDING_APPROVAL" if require_approval else "READY",
            "created_at": time.time(),
        }
        PLANS[plan_id] = plan
        return plan
    except ImportError:
        return _backend_unavailable(target)


def get_status() -> Dict[str, Any]:
    """Get current OS status."""
    if not OS_PACKAGE.exists():
        return {"status": "unavailable", "error": _DEPENDENCY_MSG}
    _ensure_os_path()
    try:
        from server import PLANS, TASKS, TOKENS
        return {
            "status": "operational",
            "plans": len(PLANS),
            "tasks": len(TASKS),
            "tokens": len(TOKENS),
        }
    except ImportError:
        return {"status": "unavailable", "error": _DEPENDENCY_MSG}


def check_gates(plan_id: str) -> Dict[str, Any]:
    """Check governance gates for a plan."""
    if not OS_PACKAGE.exists():
        return {"error": _DEPENDENCY_MSG}
    _ensure_os_path()
    try:
        from server import PLANS
        plan = PLANS.get(plan_id)
        if not plan:
            return {"error": f"Plan {plan_id} not found"}
        return {
            "plan_id": plan_id,
            "gates_passed": plan.get("status") in ("READY", "APPROVED"),
            "status": plan.get("status"),
        }
    except ImportError:
        return {"error": _DEPENDENCY_MSG}
