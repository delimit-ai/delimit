"""
Delimit license — thin shim.
The enforcement logic is in license_core (shipped as compiled binary).
This shim handles imports and provides fallback error messages.
"""
from pathlib import Path

# Always export LICENSE_FILE for tests and external access
LICENSE_FILE = Path.home() / ".delimit" / "license.json"

try:
    from ai.license_core import (
        load_license as get_license,
        check_premium as is_premium,
        gate_tool as require_premium,
        activate as activate_license,
        PRO_TOOLS as _CORE_PRO_TOOLS,
        FREE_TRIAL_LIMITS,
    )
    # Extend compiled PRO_TOOLS with tools added after last binary build
    PRO_TOOLS = _CORE_PRO_TOOLS | frozenset({
        "delimit_social_approve",
        # Autonomous build loop
        "delimit_next_task", "delimit_task_complete",
        "delimit_loop_status", "delimit_loop_config",
    })
except ImportError:
    # license_core not available (development mode or missing binary)
    import json
    import time
    from pathlib import Path

    LICENSE_FILE = Path.home() / ".delimit" / "license.json"

    PRO_TOOLS = frozenset({
        # Governance deep
        "delimit_gov_evaluate", "delimit_gov_policy", "delimit_gov_run", "delimit_gov_verify",
        "delimit_gov_new_task",
        # OS layer
        "delimit_os_plan", "delimit_os_status", "delimit_os_gates",
        # Deploy pipeline
        "delimit_deploy_plan", "delimit_deploy_build", "delimit_deploy_publish",
        "delimit_deploy_verify", "delimit_deploy_rollback", "delimit_deploy_status",
        "delimit_deploy_site", "delimit_deploy_npm",
        # Memory (search is Pro; store + recent are free)
        "delimit_memory_search",
        "delimit_vault_search", "delimit_vault_snapshot", "delimit_vault_health",
        # Evidence
        "delimit_evidence_collect", "delimit_evidence_verify",
        # Deliberation + Models
        "delimit_deliberate", "delimit_models",
        # Security orchestrator
        "delimit_security_ingest", "delimit_security_deliberate",
        # Observability
        "delimit_obs_metrics", "delimit_obs_logs", "delimit_obs_status",
        # Release
        "delimit_release_plan", "delimit_release_status", "delimit_release_sync",
        # Cost
        "delimit_cost_analyze", "delimit_cost_optimize", "delimit_cost_alert",
        # Social
        "delimit_social_post", "delimit_social_generate", "delimit_social_history",
        "delimit_social_approve",
        # Repo deep
        "delimit_repo_analyze", "delimit_repo_config_audit", "delimit_repo_config_validate",
        "delimit_repo_diagnose",
        # Test
        "delimit_test_coverage",
        # Screen recording
        "delimit_screen_record", "delimit_screenshot",
        # Notifications
        "delimit_notify",
        # Agent orchestration
        "delimit_agent_dispatch", "delimit_agent_status",
        "delimit_agent_complete", "delimit_agent_handoff",
        # Autonomous build loop
        "delimit_next_task", "delimit_task_complete",
        "delimit_loop_status", "delimit_loop_config",
    })
    FREE_TRIAL_LIMITS = {"delimit_deliberate": 3}

    def get_license() -> dict:
        if not LICENSE_FILE.exists():
            return {"tier": "free", "valid": True}
        try:
            return json.loads(LICENSE_FILE.read_text())
        except Exception:
            return {"tier": "free", "valid": True}

    def is_premium() -> bool:
        lic = get_license()
        return lic.get("tier") in ("pro", "enterprise") and lic.get("valid", False)

    def require_premium(tool_name: str) -> dict | None:
        full_name = tool_name if tool_name.startswith("delimit_") else f"delimit_{tool_name}"
        if full_name not in PRO_TOOLS:
            return None
        if is_premium():
            return None
        return {
            "error": f"'{tool_name}' requires Delimit Pro.",
            "status": "premium_required",
            "tool": tool_name,
            "current_tier": get_license().get("tier", "free"),
            "upgrade": "https://delimit.ai/pricing",
            "activate": "npx delimit-cli activate YOUR_KEY",
            "free_alternatives": [
                "delimit_lint — check API specs for free",
                "delimit_diff — compare two specs",
                "delimit_scan — discover what Delimit can do",
                "delimit_ledger_add — track tasks across sessions",
                "delimit_quickstart — guided first-run",
            ],
        }

    def activate_license(key: str) -> dict:
        import re
        if not key or len(key) < 10:
            return {"error": "Invalid license key format"}
        if key.startswith("DELIMIT-") and not re.match(r"^DELIMIT-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$", key):
            return {"error": "Invalid key format. Expected: DELIMIT-XXXX-XXXX-XXXX"}
        # Store key for offline validation
        license_data = {
            "key": key, "tier": "pro", "valid": True,
            "activated_at": time.time(), "validated_via": "offline_fallback",
        }
        LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LICENSE_FILE.write_text(json.dumps(license_data, indent=2))
        return {"status": "activated", "tier": "pro", "message": "Activated (offline fallback). Will validate on next network access."}
