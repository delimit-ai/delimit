"""
Backend bridge to delimit-gateway core engine.

Adapter Boundary Contract v1.0:
- Pure translation layer: no governance logic here
- Deterministic error on failure (never swallow)
- Zero state (stateless between calls)
- No schema forking (gateway types are canonical)
"""

import sys
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("delimit.ai.gateway_core")

# Add gateway root to path so we can import core modules
GATEWAY_ROOT = Path(__file__).resolve().parent.parent.parent
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))


def _load_specs(spec_path: str) -> Dict[str, Any]:
    """Load an OpenAPI spec from a file path."""
    import yaml

    p = Path(spec_path)
    if not p.exists():
        raise FileNotFoundError(f"Spec file not found: {spec_path}")

    content = p.read_text(encoding="utf-8")
    if p.suffix in (".yaml", ".yml"):
        return yaml.safe_load(content)
    return json.loads(content)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Read JSONL entries from a file, skipping malformed lines."""
    items: List[Dict[str, Any]] = []
    if not path.exists():
        return items
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    items.append(payload)
    except OSError:
        return []
    return items


def _query_project_ledger_fallback(ledger_path: Path) -> Optional[Dict[str, Any]]:
    """Fallback for project-local ledgers that use operations/strategy jsonl files."""
    if ledger_path.name != "events.jsonl":
        return None

    ledger_dir = ledger_path.parent
    operations = _read_jsonl(ledger_dir / "operations.jsonl")
    strategy = _read_jsonl(ledger_dir / "strategy.jsonl")
    combined = operations + strategy
    if not combined:
        return None

    latest = combined[-1]
    return {
        "path": str(ledger_path),
        "event_count": len(combined),
        "latest_event": latest,
        "storage_mode": "project_local_ledger",
        "ledger_files": [
            str(p)
            for p in (ledger_dir / "operations.jsonl", ledger_dir / "strategy.jsonl")
            if p.exists()
        ],
        "chain_valid": True,
    }


def run_lint(old_spec: str, new_spec: str, policy_file: Optional[str] = None) -> Dict[str, Any]:
    """Run the full lint pipeline: diff + policy evaluation.

    This is the Tier 1 primary tool — combines diff detection with
    policy enforcement into a single pass/fail decision.
    """
    from core.policy_engine import evaluate_with_policy

    old = _load_specs(old_spec)
    new = _load_specs(new_spec)

    return evaluate_with_policy(old, new, policy_file)


def run_diff(old_spec: str, new_spec: str) -> Dict[str, Any]:
    """Run diff engine only — no policy evaluation."""
    from core.diff_engine_v2 import OpenAPIDiffEngine

    old = _load_specs(old_spec)
    new = _load_specs(new_spec)

    engine = OpenAPIDiffEngine()
    changes = engine.compare(old, new)

    breaking = [c for c in changes if c.is_breaking]

    return {
        "total_changes": len(changes),
        "breaking_changes": len(breaking),
        "changes": [
            {
                "type": c.type.value,
                "path": c.path,
                "message": c.message,
                "is_breaking": c.is_breaking,
                "details": c.details,
            }
            for c in changes
        ],
    }


def run_changelog(
    old_spec: str,
    new_spec: str,
    fmt: str = "markdown",
    version: str = "",
) -> Dict[str, Any]:
    """Generate a changelog from API spec changes.

    Uses the diff engine to detect changes, then formats them into
    a human-readable changelog grouped by category.
    """
    from core.diff_engine_v2 import OpenAPIDiffEngine
    from datetime import datetime, timezone

    old = _load_specs(old_spec)
    new = _load_specs(new_spec)

    engine = OpenAPIDiffEngine()
    changes = engine.compare(old, new)

    # Categorize changes
    breaking = []
    features = []
    deprecations = []
    fixes = []

    for c in changes:
        entry = {
            "type": c.type.value,
            "path": c.path,
            "message": c.message,
            "is_breaking": c.is_breaking,
        }
        if c.type.value == "deprecated_added":
            deprecations.append(entry)
        elif c.is_breaking:
            breaking.append(entry)
        elif c.type.value in (
            "endpoint_added", "method_added", "optional_param_added",
            "response_added", "optional_field_added", "enum_value_added",
            "security_added",
        ):
            features.append(entry)
        else:
            fixes.append(entry)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    version_label = version or "Unreleased"

    if fmt == "json":
        return {
            "format": "json",
            "version": version_label,
            "date": date_str,
            "total_changes": len(changes),
            "sections": {
                "breaking_changes": breaking,
                "new_features": features,
                "deprecations": deprecations,
                "other_changes": fixes,
            },
        }

    if fmt == "keepachangelog":
        lines = [f"## [{version_label}] - {date_str}", ""]
        if breaking:
            lines.append("### Removed / Breaking")
            for e in breaking:
                lines.append(f"- {e['message']} (`{e['path']}`)")
            lines.append("")
        if features:
            lines.append("### Added")
            for e in features:
                lines.append(f"- {e['message']} (`{e['path']}`)")
            lines.append("")
        if deprecations:
            lines.append("### Deprecated")
            for e in deprecations:
                lines.append(f"- {e['message']} (`{e['path']}`)")
            lines.append("")
        if fixes:
            lines.append("### Changed")
            for e in fixes:
                lines.append(f"- {e['message']} (`{e['path']}`)")
            lines.append("")
        return {
            "format": "keepachangelog",
            "version": version_label,
            "date": date_str,
            "total_changes": len(changes),
            "changelog": "\n".join(lines),
        }

    if fmt == "github-release":
        lines = []
        if breaking:
            lines.append("## :warning: Breaking Changes")
            for e in breaking:
                lines.append(f"- {e['message']} (`{e['path']}`)")
            lines.append("")
        if features:
            lines.append("## :rocket: New Features")
            for e in features:
                lines.append(f"- {e['message']} (`{e['path']}`)")
            lines.append("")
        if deprecations:
            lines.append("## :no_entry_sign: Deprecations")
            for e in deprecations:
                lines.append(f"- {e['message']} (`{e['path']}`)")
            lines.append("")
        if fixes:
            lines.append("## :wrench: Other Changes")
            for e in fixes:
                lines.append(f"- {e['message']} (`{e['path']}`)")
            lines.append("")
        return {
            "format": "github-release",
            "version": version_label,
            "date": date_str,
            "total_changes": len(changes),
            "changelog": "\n".join(lines),
        }

    # Default: markdown
    lines = [f"# Changelog — {version_label} ({date_str})", ""]
    if breaking:
        lines.append("## Breaking Changes")
        for e in breaking:
            lines.append(f"- **{e['type']}**: {e['message']} (`{e['path']}`)")
        lines.append("")
    if features:
        lines.append("## New Features")
        for e in features:
            lines.append(f"- **{e['type']}**: {e['message']} (`{e['path']}`)")
        lines.append("")
    if deprecations:
        lines.append("## Deprecations")
        for e in deprecations:
            lines.append(f"- **{e['type']}**: {e['message']} (`{e['path']}`)")
        lines.append("")
    if fixes:
        lines.append("## Other Changes")
        for e in fixes:
            lines.append(f"- **{e['type']}**: {e['message']} (`{e['path']}`)")
        lines.append("")
    return {
        "format": "markdown",
        "version": version_label,
        "date": date_str,
        "total_changes": len(changes),
        "changelog": "\n".join(lines),
    }


def run_policy(spec_files: List[str], policy_file: Optional[str] = None) -> Dict[str, Any]:
    """Evaluate specs against governance policy without diffing."""
    from core.policy_engine import PolicyEngine

    engine = PolicyEngine(policy_file)

    return {
        "rules_loaded": len(engine.rules),
        "custom_rules": len(engine.custom_rules),
        "policy_file": policy_file,
        "template": engine.create_policy_template() if not policy_file else None,
    }


def query_ledger(
    ledger_path: str,
    api_name: Optional[str] = None,
    repository: Optional[str] = None,
    validate_chain: bool = False,
) -> Dict[str, Any]:
    """Query the contract ledger."""
    from core.contract_ledger import ContractLedger

    ledger = ContractLedger(ledger_path)

    if not ledger.exists():
        return {"error": "Ledger not found", "path": ledger_path}

    result: Dict[str, Any] = {"path": ledger_path, "event_count": ledger.get_event_count()}
    if result["event_count"] == 0:
        fallback = _query_project_ledger_fallback(Path(ledger_path))
        if fallback:
            if api_name:
                fallback["events"] = [e for e in _read_jsonl(Path(ledger_path).parent / "operations.jsonl") + _read_jsonl(Path(ledger_path).parent / "strategy.jsonl") if e.get("api_name") == api_name]
            elif repository:
                fallback["events"] = [e for e in _read_jsonl(Path(ledger_path).parent / "operations.jsonl") + _read_jsonl(Path(ledger_path).parent / "strategy.jsonl") if e.get("repository") == repository]
            return fallback

    if validate_chain:
        try:
            ledger.validate_chain()
            result["chain_valid"] = True
        except Exception as e:
            result["chain_valid"] = False
            result["chain_error"] = str(e)

    if api_name:
        result["events"] = ledger.get_api_timeline(api_name)
    elif repository:
        result["events"] = ledger.get_events_by_repository(repository)
    else:
        latest = ledger.get_latest_event()
        result["latest_event"] = latest

    return result


def run_impact(api_name: str, dependency_file: Optional[str] = None) -> Dict[str, Any]:
    """Analyze downstream impact of an API change."""
    from core.dependency_graph import DependencyGraph
    from core.impact_analyzer import ImpactAnalyzer

    graph = DependencyGraph()
    if dependency_file:
        graph.load_from_file(dependency_file)

    analyzer = ImpactAnalyzer(graph)
    return analyzer.analyze(api_name)


def run_semver(
    old_spec: str,
    new_spec: str,
    current_version: Optional[str] = None,
) -> Dict[str, Any]:
    """Classify the semver bump for a spec change.

    Returns detailed breakdown: bump level, per-category counts,
    and optionally the bumped version string.
    """
    from core.diff_engine_v2 import OpenAPIDiffEngine
    from core.semver_classifier import classify_detailed, bump_version, classify

    old = _load_specs(old_spec)
    new = _load_specs(new_spec)

    engine = OpenAPIDiffEngine()
    changes = engine.compare(old, new)
    result = classify_detailed(changes)

    if current_version:
        bump = classify(changes)
        result["current_version"] = current_version
        result["next_version"] = bump_version(current_version, bump)

    return result


def run_explain(
    old_spec: str,
    new_spec: str,
    template: str = "developer",
    old_version: Optional[str] = None,
    new_version: Optional[str] = None,
    api_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a human-readable explanation of API changes.

    Supports 7 templates: developer, team_lead, product, migration,
    changelog, pr_comment, slack.
    """
    from core.diff_engine_v2 import OpenAPIDiffEngine
    from core.explainer import explain, TEMPLATES

    old = _load_specs(old_spec)
    new = _load_specs(new_spec)

    engine = OpenAPIDiffEngine()
    changes = engine.compare(old, new)

    output = explain(
        changes,
        template=template,
        old_version=old_version,
        new_version=new_version,
        api_name=api_name,
    )

    return {
        "template": template,
        "available_templates": TEMPLATES,
        "output": output,
    }


def run_zero_spec(
    project_dir: str = ".",
    python_bin: Optional[str] = None,
) -> Dict[str, Any]:
    """Detect framework and extract OpenAPI spec from source code.

    Currently supports FastAPI. Returns the extracted spec or an error
    with guidance on how to fix it.
    """
    from core.zero_spec.detector import detect_framework, Framework
    from core.zero_spec.express_extractor import extract_express_spec
    from core.zero_spec.fastapi_extractor import extract_fastapi_spec
    from core.zero_spec.nestjs_extractor import extract_nestjs_spec

    info = detect_framework(project_dir)

    result: Dict[str, Any] = {
        "framework": info.framework.value,
        "confidence": info.confidence,
        "message": info.message,
    }

    if info.framework == Framework.FASTAPI:
        extraction = extract_fastapi_spec(
            info, project_dir, python_bin=python_bin
        )
        result.update(extraction)
        if extraction["success"] and info.app_locations:
            loc = info.app_locations[0]
            result["app_file"] = loc.file
            result["app_variable"] = loc.variable
            result["app_line"] = loc.line
    elif info.framework == Framework.NESTJS:
        extraction = extract_nestjs_spec(info, project_dir)
        result.update(extraction)
        if extraction["success"] and info.app_locations:
            loc = info.app_locations[0]
            result["app_file"] = loc.file
            result["app_variable"] = loc.variable
            result["app_line"] = loc.line
    elif info.framework == Framework.EXPRESS:
        extraction = extract_express_spec(info, project_dir)
        result.update(extraction)
        if extraction["success"] and info.app_locations:
            loc = info.app_locations[0]
            result["app_file"] = loc.file
            result["app_variable"] = loc.variable
            result["app_line"] = loc.line
    else:
        result["success"] = False
        result["error"] = "No supported API framework found. Provide an OpenAPI spec file."
        result["error_type"] = "no_framework"

    return result
