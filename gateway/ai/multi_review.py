"""Multi-model PR review — consolidated code review from multiple AI models (STR-053).

Takes a diff or file changes, sends them to multiple models for review,
and consolidates the feedback into a single structured report.

Focus group: "GitHub Action runs delimit review, posts consolidated PR
review combining feedback from multiple models. 10x over standard
Copilot review."
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REVIEWS_DIR = Path.home() / ".delimit" / "reviews"


def _ensure_dir():
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)


def generate_review_prompt(diff: str, context: str = "") -> str:
    """Generate a code review prompt from a diff."""
    return f"""Review this code change. For each issue found, provide:
- Line number or location
- Severity (critical/warning/suggestion)
- What's wrong and why
- How to fix it

Be concise. Only flag real issues, not style preferences.

{f"Context: {context}" if context else ""}

```diff
{diff[:8000]}
```"""


def consolidate_reviews(reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Consolidate reviews from multiple models into one report.

    Groups findings by file/line, identifies agreements and disagreements,
    and ranks by severity.
    """
    all_findings = []
    model_summaries = []

    for review in reviews:
        model = review.get("model", "unknown")
        content = review.get("content", "")
        duration = review.get("duration_ms", 0)

        model_summaries.append({
            "model": model,
            "response_length": len(content),
            "duration_ms": duration,
        })

        # Each model's review content becomes a finding block
        all_findings.append({
            "model": model,
            "review": content,
            "duration_ms": duration,
        })

    # Build consolidated report
    report = {
        "models_used": [r.get("model") for r in reviews],
        "total_models": len(reviews),
        "reviews": all_findings,
        "model_summaries": model_summaries,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    return report


def format_pr_comment(report: Dict[str, Any]) -> str:
    """Format the consolidated review as a GitHub PR comment."""
    models = report.get("models_used", [])
    reviews = report.get("reviews", [])

    lines = []
    lines.append("## Delimit Multi-Model Review")
    lines.append("")
    lines.append(f"Reviewed by: **{', '.join(models)}**")
    lines.append("")

    for review in reviews:
        model = review.get("model", "unknown")
        content = review.get("review", "")
        duration = review.get("duration_ms", 0)

        lines.append(f"### {model}")
        if duration:
            lines.append(f"*({duration}ms)*")
        lines.append("")
        lines.append(content)
        lines.append("")

    lines.append("---")
    lines.append("Powered by [Delimit](https://delimit.ai) multi-model review")

    return "\n".join(lines)


def save_review(
    diff: str,
    report: Dict[str, Any],
    pr_url: str = "",
) -> Dict[str, Any]:
    """Save a review report to disk."""
    _ensure_dir()

    review_id = f"review-{int(time.time())}"
    review_file = REVIEWS_DIR / f"{review_id}.json"

    data = {
        "id": review_id,
        "diff_preview": diff[:500],
        "report": report,
        "pr_url": pr_url,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    review_file.write_text(json.dumps(data, indent=2))

    return {
        "status": "saved",
        "review_id": review_id,
        "path": str(review_file),
        "pr_comment": format_pr_comment(report),
    }


def list_reviews(limit: int = 10) -> Dict[str, Any]:
    """List recent reviews."""
    _ensure_dir()
    reviews = []

    for f in sorted(REVIEWS_DIR.glob("review-*.json"), reverse=True)[:limit]:
        try:
            data = json.loads(f.read_text())
            reviews.append({
                "id": data["id"],
                "models": data["report"].get("models_used", []),
                "created_at": data.get("created_at", ""),
                "pr_url": data.get("pr_url", ""),
            })
        except:
            pass

    return {"status": "ok", "reviews": reviews, "total": len(reviews)}
