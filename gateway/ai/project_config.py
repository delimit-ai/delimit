"""delimit.yml — committable project configuration (STR-049).

A single YAML file that teams commit to their repo. Defines:
- Context directories (what the AI should know about)
- Preferred models per task type
- Policy preset
- Playbook references
- Governance mode (advisory/guarded/enforce)

Focus group: "My AI setup on my laptop should match my teammate's."
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml as _yaml
except ImportError:
    _yaml = None


DEFAULT_CONFIG = {
    "version": 1,
    "governance": {
        "mode": "advisory",
        "preset": "default",
    },
    "context": {
        "include": ["src/", "lib/", "app/"],
        "exclude": ["node_modules/", ".git/", "dist/", "__pycache__/"],
    },
    "models": {
        "default": "auto",
        "tasks": {
            "refactoring": "claude-opus",
            "testing": "claude-sonnet",
            "documentation": "gemini-flash",
            "debugging": "auto",
        },
    },
    "playbooks": [],
    "team": {
        "shared_memory": True,
        "shared_ledger": True,
        "require_approval_for": ["deploy", "publish"],
    },
}

CONFIG_FILENAMES = ["delimit.yml", "delimit.yaml", ".delimit.yml", ".delimit.yaml"]


def find_project_config(project_path: str = ".") -> Optional[Path]:
    """Find delimit.yml in the project directory or parents."""
    p = Path(project_path).resolve()
    for _ in range(10):  # Max 10 parent dirs
        for name in CONFIG_FILENAMES:
            candidate = p / name
            if candidate.exists():
                return candidate
        parent = p.parent
        if parent == p:
            break
        p = parent
    return None


def load_project_config(project_path: str = ".") -> Dict[str, Any]:
    """Load project config from delimit.yml or return defaults."""
    config_file = find_project_config(project_path)

    if not config_file:
        return {
            "status": "no_config",
            "config": DEFAULT_CONFIG,
            "source": "defaults",
            "message": "No delimit.yml found. Using defaults. Run delimit_project_init to create one.",
        }

    try:
        content = config_file.read_text()
        if _yaml:
            config = _yaml.safe_load(content)
        else:
            config = json.loads(content)

        # Merge with defaults for missing keys
        merged = {**DEFAULT_CONFIG}
        if isinstance(config, dict):
            for key in config:
                if key in merged and isinstance(merged[key], dict) and isinstance(config[key], dict):
                    merged[key] = {**merged[key], **config[key]}
                else:
                    merged[key] = config[key]

        return {
            "status": "loaded",
            "config": merged,
            "source": str(config_file),
            "message": f"Loaded from {config_file.name}",
        }
    except Exception as e:
        return {
            "status": "error",
            "config": DEFAULT_CONFIG,
            "source": str(config_file),
            "error": str(e),
            "message": f"Error loading {config_file.name}: {e}. Using defaults.",
        }


def init_project_config(
    project_path: str = ".",
    mode: str = "advisory",
    preset: str = "default",
) -> Dict[str, Any]:
    """Create a delimit.yml in the project root."""
    p = Path(project_path).resolve()

    # Check if already exists
    existing = find_project_config(project_path)
    if existing:
        return {
            "status": "exists",
            "path": str(existing),
            "message": f"Config already exists at {existing}",
        }

    config = dict(DEFAULT_CONFIG)
    config["governance"]["mode"] = mode
    config["governance"]["preset"] = preset

    # Auto-detect context dirs
    detected_dirs = []
    for d in ["src", "lib", "app", "api", "server", "client", "packages"]:
        if (p / d).exists():
            detected_dirs.append(f"{d}/")
    if detected_dirs:
        config["context"]["include"] = detected_dirs

    config_path = p / "delimit.yml"

    if _yaml:
        content = _yaml.dump(config, default_flow_style=False, sort_keys=False)
    else:
        content = json.dumps(config, indent=2)

    config_path.write_text(content)

    return {
        "status": "created",
        "path": str(config_path),
        "config": config,
        "message": f"Created delimit.yml with {mode} mode, {preset} preset",
    }


def get_model_for_task(task_type: str, project_path: str = ".") -> Dict[str, Any]:
    """Get the recommended model for a specific task type."""
    result = load_project_config(project_path)
    config = result.get("config", DEFAULT_CONFIG)

    models = config.get("models", {})
    tasks = models.get("tasks", {})

    model = tasks.get(task_type, models.get("default", "auto"))

    return {
        "task": task_type,
        "model": model,
        "source": result.get("source", "defaults"),
    }
