"""
Delimit license — thin shim.
The enforcement logic is in license_core (shipped as compiled binary).
This shim handles imports and provides fallback error messages.
"""
try:
    from ai.license_core import (
        load_license as get_license,
        check_premium as is_premium,
        gate_tool as require_premium,
        activate as activate_license,
        PRO_TOOLS,
        FREE_TRIAL_LIMITS,
    )
except ImportError:
    # license_core not available (development mode or missing binary)
    import json
    import time
    from pathlib import Path

    LICENSE_FILE = Path.home() / ".delimit" / "license.json"

    PRO_TOOLS = set()
    FREE_TRIAL_LIMITS = {}

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
        if is_premium():
            return None
        return {
            "error": f"'{tool_name}' requires Delimit Pro. Upgrade at https://delimit.ai/pricing",
            "status": "premium_required",
            "tool": tool_name,
        }

    def activate_license(key: str) -> dict:
        return {"error": "License core not available. Reinstall: npx delimit-cli setup"}
