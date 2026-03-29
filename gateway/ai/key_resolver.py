"""Auto-resolve API keys from multiple sources.

Priority: env var -> secrets broker -> return None (free fallback).

Every MCP tool that depends on an external service should use this module
so it works out of the box without API keys, with enhanced functionality
unlocked when keys are available.
"""

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("delimit.ai.key_resolver")

SECRETS_DIR = Path.home() / ".delimit" / "secrets"


def get_key(name: str, env_var: str = "", _secrets_dir: Optional[Path] = None) -> Tuple[Optional[str], str]:
    """Get an API key.  Returns (key, source) or (None, "not_found").

    Sources checked in order:
    1. Environment variable (explicit *env_var*, then common conventions)
    2. ~/.delimit/secrets/{name}.json
    3. None (free fallback)
    """
    # 1. Env var — explicit, then common patterns
    candidates = [env_var] if env_var else []
    candidates += [
        f"{name.upper()}_TOKEN",
        f"{name.upper()}_API_KEY",
        f"{name.upper()}_KEY",
    ]
    for var in candidates:
        if not var:
            continue
        val = os.environ.get(var)
        if val:
            return val, "env"

    # 2. Secrets broker
    secrets_dir = _secrets_dir if _secrets_dir is not None else SECRETS_DIR
    secrets_file = secrets_dir / f"{name.lower()}.json"
    if secrets_file.exists():
        try:
            data = json.loads(secrets_file.read_text())
            for field in ("value", "api_key", "token", "key"):
                if data.get(field):
                    return data[field], "secrets_broker"
        except Exception:
            logger.debug("Failed to read secrets file %s", secrets_file)

    # 3. Not found
    return None, "not_found"


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------

def get_figma_token() -> Tuple[Optional[str], str]:
    """Resolve Figma API token."""
    return get_key("figma", "FIGMA_TOKEN")


def get_trivy_path() -> Tuple[Optional[str], str]:
    """Check if Trivy binary is available on PATH."""
    path = shutil.which("trivy")
    return (path, "installed") if path else (None, "not_found")


def get_playwright() -> Tuple[bool, str]:
    """Check whether Playwright is usable (Python package installed)."""
    try:
        import playwright  # noqa: F401
        return True, "installed"
    except ImportError:
        return False, "not_found"


def get_puppeteer() -> Tuple[bool, str]:
    """Check whether puppeteer (npx) is available for screenshot fallback."""
    try:
        result = subprocess.run(
            ["npx", "puppeteer", "--version"],
            capture_output=True,
            timeout=15,
        )
        return (True, "installed") if result.returncode == 0 else (False, "not_found")
    except Exception:
        return False, "not_found"
