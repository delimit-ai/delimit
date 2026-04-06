"""Governed Executor for Continuous Build (LED-239).

Requirements (Consensus 123):
- root ledger in /root/.delimit is authoritative
- select only build-safe open items (feat, fix, task)
- resolve venture + repo before dispatch
- use Delimit swarm/governance as control plane
- every iteration must update ledger, audit trail, and session state
- no deploy/secrets/destructive actions without explicit gate
- enforce max-iteration, max-error, and max-cost safeguards
"""

import json
import logging
from datetime import datetime, timezone
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("delimit.ai.loop_engine")

# ── Configuration ────────────────────────────────────────────────────
ROOT_LEDGER_PATH = Path("/root/.delimit")
BUILD_SAFE_TYPES = ["feat", "fix", "task"]
MAX_ITERATIONS_DEFAULT = 10
MAX_COST_DEFAULT = 2.0
MAX_ERRORS_DEFAULT = 2

# ── Session State ────────────────────────────────────────────────────
SESSION_DIR = Path.home() / ".delimit" / "loop" / "sessions"

def _ensure_session_dir():
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

def _save_session(session: Dict[str, Any]):
    _ensure_session_dir()
    path = SESSION_DIR / f"{session['session_id']}.json"
    path.write_text(json.dumps(session, indent=2))

def create_governed_session() -> Dict[str, Any]:
    session_id = f"build-{uuid.uuid4().hex[:8]}"
    session = {
        "session_id": session_id,
        "type": "governed_build",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "iterations": 0,
        "max_iterations": MAX_ITERATIONS_DEFAULT,
        "cost_incurred": 0.0,
        "cost_cap": MAX_COST_DEFAULT,
        "errors": 0,
        "error_threshold": MAX_ERRORS_DEFAULT,
        "tasks_completed": [],
        "status": "running"
    }
    _save_session(session)
    return session

# ── Venture & Repo Resolution ─────────────────────────────────────────

def resolve_venture_context(venture_name: str) -> Dict[str, str]:
    """Resolve a venture name to its project path and repo URL."""
    from ai.ledger_manager import list_ventures
    
    ventures = list_ventures().get("ventures", {})
    context = {"path": ".", "repo": "", "name": venture_name or "root"}
    
    if not venture_name or venture_name == "root":
        context["path"] = str(ROOT_LEDGER_PATH)
        return context

    if venture_name in ventures:
        v = ventures[venture_name]
        context["path"] = v.get("path", ".")
        context["repo"] = v.get("repo", "")
        return context
    
    # Fallback to fuzzy match
    for name, info in ventures.items():
        if venture_name.lower() in name.lower():
            context["path"] = info.get("path", ".")
            context["repo"] = info.get("repo", "")
            context["name"] = name
            return context
            
    return context

# ── Governed Selection ───────────────────────────────────────────────

def next_task(venture: str = "", max_risk: str = "", session_id: str = "") -> Dict[str, Any]:
    """Get the next task to work on. Wrapper for server.py compatibility."""
    session = create_governed_session() if not session_id else {"session_id": session_id, "status": "running", "iterations": 0, "max_iterations": 50, "cost_incurred": 0, "cost_cap": 5, "errors": 0, "error_threshold": 3, "tasks_done": 0, "auto_consensus": False}
    task = get_next_build_task(session)
    if task is None:
        from ai.ledger_manager import list_items
        result = list_items(status="open", project_path=str(ROOT_LEDGER_PATH))
        open_count = sum(len(v) for v in result.get("items", {}).values())
        return {"action": "CONSENSUS", "reason": f"No build-safe items found ({open_count} open items, none actionable)", "remaining_items": open_count, "session": session}
    return {"action": "BUILD", "task": task, "remaining_items": 0, "session": session}


def get_next_build_task(session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Select the next build-safe item from the authoritative root ledger."""
    from ai.ledger_manager import list_items
    
    # Authoritative root ledger check
    result = list_items(status="open", project_path=str(ROOT_LEDGER_PATH))
    items = []
    for ledger_items in result.get("items", {}).values():
        items.extend(ledger_items)
        
    # Filter build-safe items only
    actionable = []
    for item in items:
        if item.get("type") not in BUILD_SAFE_TYPES:
            continue
        # Skip items that explicitly require owner action or are not for AI
        tags = item.get("tags", [])
        if "owner-action" in tags or "manual" in tags:
            continue
        actionable.append(item)
        
    if not actionable:
        return None
        
    # Sort by priority
    priority_map = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    actionable.sort(key=lambda x: priority_map.get(x.get("priority", "P2"), 9))
    
    return actionable[0]

# ── Swarm Dispatch & Execution ───────────────────────────────────────

def loop_config(session_id: str = "", max_iterations: int = 0,
                cost_cap: float = 0.0, auto_consensus: bool = False,
                error_threshold: int = 0, status: str = "",
                require_approval_for: list = None) -> Dict[str, Any]:
    """Configure or create a loop session with safeguards."""
    _ensure_session_dir()

    # Load existing or create new
    if session_id:
        path = SESSION_DIR / f"{session_id}.json"
        if path.exists():
            session = json.loads(path.read_text())
        else:
            session = {
                "session_id": session_id,
                "type": "governed_build",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "iterations": 0,
                "max_iterations": max_iterations or MAX_ITERATIONS_DEFAULT,
                "cost_incurred": 0.0,
                "cost_cap": cost_cap or MAX_COST_DEFAULT,
                "errors": 0,
                "error_threshold": error_threshold or MAX_ERRORS_DEFAULT,
                "tasks_completed": [],
                "status": status or "running",
            }
    else:
        session = create_governed_session()

    # Apply non-zero/non-empty overrides
    if max_iterations > 0:
        session["max_iterations"] = max_iterations
    if cost_cap > 0:
        session["cost_cap"] = cost_cap
    if error_threshold > 0:
        session["error_threshold"] = error_threshold
    if status:
        session["status"] = status
    if auto_consensus:
        session["auto_consensus"] = True
    if require_approval_for is not None:
        session["require_approval_for"] = require_approval_for

    _save_session(session)
    return {
        "session_id": session["session_id"],
        "status": session["status"],
        "max_iterations": session["max_iterations"],
        "iterations": session.get("iterations", 0),
        "cost_cap": session["cost_cap"],
        "cost_incurred": session.get("cost_incurred", 0.0),
        "error_threshold": session["error_threshold"],
        "errors": session.get("errors", 0),
    }


def run_governed_iteration(session_id: str) -> Dict[str, Any]:
    """Execute one governed build iteration."""
    from datetime import datetime, timezone
    from ai.swarm import dispatch_task
    
    # 1. Load Session & Check Safeguards
    path = SESSION_DIR / f"{session_id}.json"
    if not path.exists():
        return {"error": f"Session {session_id} not found"}
    session = json.loads(path.read_text())
    
    if session["status"] != "running":
        return {"status": "stopped", "reason": f"Session status is {session['status']}"}
        
    if session["iterations"] >= session["max_iterations"]:
        session["status"] = "finished"
        _save_session(session)
        return {"status": "finished", "reason": "Max iterations reached"}
        
    if session["cost_incurred"] >= session["cost_cap"]:
        session["status"] = "stopped"
        _save_session(session)
        return {"status": "stopped", "reason": "Cost cap reached"}

    # 2. Select Task
    task = get_next_build_task(session)
    if not task:
        return {"status": "idle", "reason": "No build-safe items in ledger"}
        
    # 3. Resolve Context
    v_name = task.get("venture", "root")
    ctx = resolve_venture_context(v_name)
    
    # 4. Dispatch through Swarm (Control Plane)
    logger.info(f"Dispatching build task {task['id']} for venture {v_name}")
    
    start_time = time.time()
    try:
        # Note: Swarm dispatch is the central point of governance
        dispatch_result = dispatch_task(
            title=task["title"],
            description=task["description"],
            context=f"Executing governed build loop for {v_name}. Ledger ID: {task['id']}",
            project_path=ctx["path"],
            priority=task["priority"]
        )
        
        # 5. Update State & Ledger
        duration = time.time() - start_time
        cost = dispatch_result.get("estimated_cost", 0.05) # Default placeholder if missing
        
        session["iterations"] += 1
        session["cost_incurred"] += cost
        
        from ai.ledger_manager import update_item
        if dispatch_result.get("status") == "completed":
            update_item(
                item_id=task["id"],
                status="done",
                note=f"Completed via governed build loop. Result: {dispatch_result.get('summary', 'OK')}",
                project_path=str(ROOT_LEDGER_PATH)
            )
            session["tasks_completed"].append({
                "id": task["id"],
                "status": "success",
                "duration": duration,
                "cost": cost
            })
        else:
            session["errors"] += 1
            if session["errors"] >= session["error_threshold"]:
                session["status"] = "circuit_broken"
            session["tasks_completed"].append({
                "id": task["id"],
                "status": "failed",
                "error": dispatch_result.get("error", "Dispatch failed")
            })
            
        _save_session(session)
        return {"status": "continued", "task_id": task["id"], "result": dispatch_result}
        
    except Exception as e:
        session["errors"] += 1
        _save_session(session)
        return {"error": str(e)}

if __name__ == "__main__":
    # Test pass if run directly
    pass
