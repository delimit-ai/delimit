"""
Delimit Governance Layer — the loop that keeps AI agents on track.

Every tool flows through governance. Governance:
1. Logs what happened (evidence)
2. Checks result against rules (thresholds, policies)
3. Auto-creates ledger items for failures/warnings
4. Suggests next steps (loops back to keep building)

This replaces _with_next_steps — governance IS the next step system.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("delimit.governance")


# Governance rules — what triggers auto-ledger-creation
RULES = {
    "test_coverage": {
        "threshold_key": "line_coverage",
        "threshold": 80,
        "comparison": "below",
        "ledger_title": "Test coverage below {threshold}% — currently {value}%",
        "ledger_type": "fix",
        "ledger_priority": "P1",
    },
    "security_audit": {
        "trigger_key": "vulnerabilities",
        "trigger_if_nonempty": True,
        "ledger_title": "Security: {count} vulnerabilities found",
        "ledger_type": "fix",
        "ledger_priority": "P0",
    },
    "security_scan": {
        "trigger_key": "vulnerabilities",
        "trigger_if_nonempty": True,
        "ledger_title": "Security scan: {count} issues detected",
        "ledger_type": "fix",
        "ledger_priority": "P0",
    },
    "lint": {
        "trigger_key": "violations",
        "trigger_if_nonempty": True,
        "ledger_title": "API lint: {count} violations found",
        "ledger_type": "fix",
        "ledger_priority": "P1",
    },
    "deliberate": {
        "trigger_key": "unanimous",
        "trigger_if_true": True,
        "extract_actions": True,
        "ledger_title": "Deliberation consensus reached — action items pending",
        "ledger_type": "strategy",
        "ledger_priority": "P1",
    },
    "gov_health": {
        "trigger_key": "status",
        "trigger_values": ["not_initialized", "degraded"],
        "ledger_title": "Governance health: {value} — needs attention",
        "ledger_type": "fix",
        "ledger_priority": "P1",
    },
    "docs_validate": {
        "threshold_key": "coverage_percent",
        "threshold": 50,
        "comparison": "below",
        "ledger_title": "Documentation coverage below {threshold}% — currently {value}%",
        "ledger_type": "task",
        "ledger_priority": "P2",
    },
}

# Milestone rules — auto-create DONE ledger items for significant completions.
# Unlike threshold RULES (which create open items for problems), milestones
# record achievements so the ledger reflects what was shipped.
MILESTONES = {
    "deploy_site": {
        "trigger_key": "status",
        "trigger_values": ["deployed"],
        "ledger_title": "Deployed: {project}",
        "ledger_type": "feat",
        "ledger_priority": "P1",
        "auto_done": True,
    },
    "deploy_npm": {
        "trigger_key": "status",
        "trigger_values": ["published"],
        "ledger_title": "Published: {package}@{new_version}",
        "ledger_type": "feat",
        "ledger_priority": "P1",
        "auto_done": True,
    },
    "deliberate": {
        "trigger_key": "status",
        "trigger_values": ["unanimous"],
        "ledger_title": "Consensus reached: {question_short}",
        "ledger_type": "strategy",
        "ledger_priority": "P1",
        "auto_done": True,
    },
    "test_generate": {
        "threshold_key": "tests_generated",
        "threshold": 10,
        "comparison": "above",
        "ledger_title": "Generated {value} tests",
        "ledger_type": "feat",
        "ledger_priority": "P2",
        "auto_done": True,
    },
    "sensor_github_issue": {
        "trigger_key": "has_new_activity",
        "trigger_if_true": True,
        "ledger_title": "Outreach response: new activity detected",
        "ledger_type": "task",
        "ledger_priority": "P1",
        "auto_done": False,  # needs follow-up
    },
    "zero_spec": {
        "trigger_key": "success",
        "trigger_if_true": True,
        "ledger_title": "Zero-spec extracted: {framework} ({paths_count} paths)",
        "ledger_type": "feat",
        "ledger_priority": "P2",
        "auto_done": True,
    },
}

# Next steps registry — what to do after each tool
NEXT_STEPS = {
    "lint": [
        {"tool": "delimit_explain", "reason": "Get migration guide for violations", "premium": False},
        {"tool": "delimit_semver", "reason": "Classify the version bump", "premium": False},
    ],
    "diff": [
        {"tool": "delimit_semver", "reason": "Classify changes as MAJOR/MINOR/PATCH", "premium": False},
        {"tool": "delimit_policy", "reason": "Check against governance policies", "premium": False},
    ],
    "semver": [
        {"tool": "delimit_explain", "reason": "Generate human-readable changelog", "premium": False},
        {"tool": "delimit_deploy_npm", "reason": "Publish the new version to npm", "premium": False},
    ],
    "init": [
        {"tool": "delimit_gov_health", "reason": "Verify governance is set up correctly", "premium": True},
        {"tool": "delimit_diagnose", "reason": "Check for any issues", "premium": False},
    ],
    "deploy_site": [
        {"tool": "delimit_deploy_npm", "reason": "Publish npm package if applicable", "premium": False},
        {"tool": "delimit_ledger_context", "reason": "Check what else needs deploying", "premium": False},
    ],
    "test_coverage": [
        {"tool": "delimit_test_generate", "reason": "Generate tests for uncovered files", "premium": False},
    ],
    "security_audit": [
        {"tool": "delimit_evidence_collect", "reason": "Collect evidence of findings", "premium": True},
    ],
    "gov_health": [
        {"tool": "delimit_gov_status", "reason": "See detailed governance status", "premium": True},
        {"tool": "delimit_repo_analyze", "reason": "Full repo health report", "premium": True},
    ],
    "deploy_npm": [
        {"tool": "delimit_deploy_verify", "reason": "Verify the published package", "premium": True},
    ],
    "deploy_plan": [
        {"tool": "delimit_deploy_build", "reason": "Build the deployment", "premium": True},
    ],
    "deploy_build": [
        {"tool": "delimit_deploy_publish", "reason": "Publish the build", "premium": True},
    ],
    "deploy_publish": [
        {"tool": "delimit_deploy_verify", "reason": "Verify the deployment", "premium": True},
    ],
    "deploy_verify": [
        {"tool": "delimit_deploy_rollback", "reason": "Rollback if unhealthy", "premium": True},
    ],
    "repo_analyze": [
        {"tool": "delimit_security_audit", "reason": "Scan for security issues", "premium": False},
        {"tool": "delimit_gov_health", "reason": "Check governance status", "premium": True},
    ],
    "deliberate": [
        {"tool": "delimit_ledger_context", "reason": "Review what's on the ledger after consensus", "premium": False},
    ],
    "ledger_add": [
        {"tool": "delimit_ledger_context", "reason": "See updated ledger state", "premium": False},
    ],
    "diagnose": [
        {"tool": "delimit_init", "reason": "Initialize governance if not set up", "premium": False},
    ],
}


def govern(tool_name: str, result: Dict[str, Any], project_path: str = ".") -> Dict[str, Any]:
    """
    Run governance on a tool's result. This is the central loop.

    1. Check result against rules
    2. Auto-create ledger items if thresholds breached
    3. Add next_steps for the AI to continue
    4. Return enriched result

    Every tool should call this before returning.
    """
    # Strip "delimit_" prefix for rule matching
    clean_name = tool_name.replace("delimit_", "")

    governed_result = dict(result)

    # 1. Check governance rules
    rule = RULES.get(clean_name)
    auto_items = []

    if rule:
        triggered = False
        context = {}

        # Threshold check (e.g., coverage < 80%)
        if "threshold_key" in rule:
            value = _deep_get(result, rule["threshold_key"])
            if value is not None:
                threshold = rule["threshold"]
                if rule.get("comparison") == "below" and value < threshold:
                    triggered = True
                    context = {"value": f"{value:.1f}" if isinstance(value, float) else str(value), "threshold": str(threshold)}

        # Non-empty list check (e.g., vulnerabilities found)
        if "trigger_key" in rule and "trigger_if_nonempty" in rule:
            items = _deep_get(result, rule["trigger_key"])
            if items and isinstance(items, list) and len(items) > 0:
                triggered = True
                context = {"count": str(len(items))}

        # Value match check (e.g., status == "degraded")
        if "trigger_key" in rule and "trigger_values" in rule:
            value = _deep_get(result, rule["trigger_key"])
            if value in rule["trigger_values"]:
                triggered = True
                context = {"value": str(value)}

        # Boolean check (e.g., unanimous == True)
        if "trigger_key" in rule and "trigger_if_true" in rule:
            value = _deep_get(result, rule["trigger_key"])
            if value:
                triggered = True

        if triggered:
            title = rule["ledger_title"].format(**context) if context else rule["ledger_title"]
            auto_items.append({
                "title": title,
                "type": rule.get("ledger_type", "task"),
                "priority": rule.get("ledger_priority", "P1"),
                "source": f"governance:{clean_name}",
            })

    # 1b. Check milestone rules (auto-create DONE items for achievements)
    milestone = MILESTONES.get(clean_name)
    if milestone:
        m_triggered = False
        m_context = {}

        # Value match (e.g., status == "deployed")
        if "trigger_key" in milestone and "trigger_values" in milestone:
            value = _deep_get(result, milestone["trigger_key"])
            if value in milestone["trigger_values"]:
                m_triggered = True
                m_context = {"value": str(value)}

        # Boolean check (e.g., success == True)
        if "trigger_key" in milestone and milestone.get("trigger_if_true"):
            value = _deep_get(result, milestone["trigger_key"])
            if value:
                m_triggered = True

        # Threshold above (e.g., tests_generated > 10)
        if "threshold_key" in milestone:
            value = _deep_get(result, milestone["threshold_key"])
            if value is not None:
                threshold = milestone["threshold"]
                if milestone.get("comparison") == "above" and value > threshold:
                    m_triggered = True
                    m_context = {"value": str(value), "threshold": str(threshold)}

        if m_triggered:
            # Build context from result fields for title interpolation
            for key in ("project", "package", "new_version", "framework", "paths_count", "repo"):
                if key not in m_context:
                    v = _deep_get(result, key)
                    if v is not None:
                        m_context[key] = str(v)
            # Special: short question for deliberations
            if "question_short" not in m_context:
                q = _deep_get(result, "question") or _deep_get(result, "note") or ""
                m_context["question_short"] = str(q)[:80]

            try:
                title = milestone["ledger_title"].format(**m_context)
            except (KeyError, IndexError):
                title = milestone["ledger_title"]

            auto_items.append({
                "title": title,
                "type": milestone.get("ledger_type", "feat"),
                "priority": milestone.get("ledger_priority", "P1"),
                "source": f"milestone:{clean_name}",
                "auto_done": milestone.get("auto_done", True),
            })

    # 2. Auto-create ledger items (with dedup — skip if open item with same title exists)
    if auto_items:
        try:
            from ai.ledger_manager import add_item, update_item, list_items
            # Load existing open titles for dedup
            existing = list_items(project_path=project_path)
            # items can be a list or dict of lists (by ledger type)
            all_items = []
            raw_items = existing.get("items", [])
            if isinstance(raw_items, dict):
                for ledger_items in raw_items.values():
                    if isinstance(ledger_items, list):
                        all_items.extend(ledger_items)
            elif isinstance(raw_items, list):
                all_items = raw_items
            open_titles = {
                i.get("title", "")
                for i in all_items
                if isinstance(i, dict) and i.get("status") == "open"
            }
            created = []
            for item in auto_items:
                if item["title"] in open_titles:
                    logger.debug("Skipping duplicate ledger item: %s", item["title"])
                    continue
                entry = add_item(
                    title=item["title"],
                    type=item["type"],
                    priority=item["priority"],
                    source=item["source"],
                    project_path=project_path,
                )
                item_id = entry.get("added", {}).get("id", "")
                created.append(item_id)
                # Auto-close milestone items
                if item.get("auto_done") and item_id:
                    try:
                        update_item(item_id, status="done", project_path=project_path)
                    except Exception:
                        pass
            governed_result["governance"] = {
                "action": "ledger_items_created",
                "items": created,
                "reason": "Governance rule triggered by tool result",
            }
        except Exception as e:
            logger.warning("Governance auto-ledger failed: %s", e)

    # 3. Add governance-directed next steps
    steps = NEXT_STEPS.get(clean_name, [])
    if steps:
        governed_result["next_steps"] = steps

    # 4. GOVERNANCE LOOP: always route back to ledger_context
    # This is not a suggestion — it's how the loop works.
    # The AI should call ledger_context after every tool to check what's next.
    if clean_name not in ("ledger_add", "ledger_done", "ledger_list", "ledger_context", "ventures", "version", "help", "diagnose", "activate", "license_status", "models", "scan"):
        if "next_steps" not in governed_result:
            governed_result["next_steps"] = []
        # Don't duplicate
        existing = {s.get("tool") for s in governed_result.get("next_steps", [])}
        if "delimit_ledger_context" not in existing:
            governed_result["next_steps"].insert(0, {
                "tool": "delimit_ledger_context",
                "reason": "GOVERNANCE LOOP: check ledger for next action",
                "premium": False,
                "required": True,
            })
    else:
        # Excluded tools still get the next_steps field (empty) for schema consistency
        if "next_steps" not in governed_result:
            governed_result["next_steps"] = []

    return governed_result


def _deep_get(d: Dict, key: str) -> Any:
    """Get a value from a dict, supporting nested keys with dots."""
    if "." in key:
        parts = key.split(".", 1)
        sub = d.get(parts[0])
        if isinstance(sub, dict):
            return _deep_get(sub, parts[1])
        return None

    # Check top-level and common nested locations
    if key in d:
        return d[key]
    # Check inside 'data', 'result', 'overall_coverage'
    for wrapper in ["data", "result", "overall_coverage", "summary"]:
        if isinstance(d.get(wrapper), dict) and key in d[wrapper]:
            return d[wrapper][key]
    return None
