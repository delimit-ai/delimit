"""Data/Action Plane — external systems as typed mounted resources.

Instead of ad hoc API calls, external systems appear as structured resources
with schemas, permissions, and transactional operations. Like device drivers.

STR-050: First driver is GitHub (repos, PRs, issues, workflows).
"""
import json
import os
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any


class GitHubDriver:
    """GitHub as a typed mounted resource."""

    def __init__(self):
        self.gh_available = bool(
            subprocess.run(["which", "gh"], capture_output=True).returncode == 0
        )

    def _gh(self, args: list, parse_json: bool = True) -> dict:
        """Run a gh CLI command."""
        if not self.gh_available:
            return {"error": "GitHub CLI (gh) not available"}
        try:
            result = subprocess.run(
                ["gh"] + args,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return {"error": result.stderr.strip()}
            if parse_json and result.stdout.strip():
                return json.loads(result.stdout)
            return {"output": result.stdout.strip()}
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out after 30s"}
        except json.JSONDecodeError as e:
            return {"error": f"Failed to parse JSON: {e}"}
        except Exception as e:
            return {"error": str(e)}

    # --- Repos ---

    def list_repos(self, org: str = "", limit: int = 20) -> list:
        """List repositories."""
        args = [
            "repo",
            "list",
            "--json",
            "name,description,url,isPrivate,stargazerCount,updatedAt",
            "--limit",
            str(limit),
        ]
        if org:
            args.insert(2, org)
        result = self._gh(args)
        return result if isinstance(result, list) else [result]

    def get_repo(self, repo: str) -> dict:
        """Get repository details."""
        return self._gh(
            [
                "repo",
                "view",
                repo,
                "--json",
                "name,description,url,defaultBranchRef,isPrivate,stargazerCount,issues,pullRequests",
            ]
        )

    # --- Pull Requests ---

    def list_prs(self, repo: str = "", state: str = "open", limit: int = 10) -> list:
        """List pull requests."""
        args = [
            "pr",
            "list",
            "--json",
            "number,title,state,author,createdAt,url,labels",
            "--state",
            state,
            "--limit",
            str(limit),
        ]
        if repo:
            args.extend(["--repo", repo])
        result = self._gh(args)
        return result if isinstance(result, list) else [result]

    def get_pr(self, repo: str, number: int) -> dict:
        """Get PR details with comments and checks."""
        return self._gh(
            [
                "pr",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "number,title,body,state,author,comments,statusCheckRollup,files,additions,deletions",
            ]
        )

    def create_pr(
        self, repo: str, title: str, body: str, head: str, base: str = "main"
    ) -> dict:
        """Create a pull request."""
        return self._gh(
            [
                "pr",
                "create",
                "--repo",
                repo,
                "--title",
                title,
                "--body",
                body,
                "--head",
                head,
                "--base",
                base,
                "--json",
                "number,url",
            ]
        )

    # --- Issues ---

    def list_issues(
        self, repo: str = "", state: str = "open", limit: int = 10
    ) -> list:
        """List issues."""
        args = [
            "issue",
            "list",
            "--json",
            "number,title,state,author,createdAt,url,labels",
            "--state",
            state,
            "--limit",
            str(limit),
        ]
        if repo:
            args.extend(["--repo", repo])
        result = self._gh(args)
        return result if isinstance(result, list) else [result]

    def create_issue(self, repo: str, title: str, body: str) -> dict:
        """Create an issue."""
        return self._gh(
            [
                "issue",
                "create",
                "--repo",
                repo,
                "--title",
                title,
                "--body",
                body,
                "--json",
                "number,url",
            ]
        )

    def get_issue(self, repo: str, number: int) -> dict:
        """Get issue details with comments."""
        return self._gh(
            [
                "issue",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "number,title,body,state,author,comments,labels",
            ]
        )

    # --- Workflows ---

    def list_runs(self, repo: str = "", limit: int = 5) -> list:
        """List recent workflow runs."""
        if not repo:
            return [{"error": "repo is required for workflow runs"}]
        result = self._gh(
            [
                "run",
                "list",
                "--repo",
                repo,
                "--json",
                "databaseId,displayTitle,status,conclusion,createdAt,url",
                "--limit",
                str(limit),
            ]
        )
        return result if isinstance(result, list) else [result]

    def get_run(self, repo: str, run_id: int) -> dict:
        """Get workflow run details."""
        return self._gh(
            [
                "run",
                "view",
                str(run_id),
                "--repo",
                repo,
                "--json",
                "databaseId,displayTitle,status,conclusion,jobs",
            ]
        )

    # --- Resource Schema ---

    @staticmethod
    def schema() -> dict:
        """Return the typed resource schema for GitHub."""
        return {
            "driver": "github",
            "resources": {
                "repos": {
                    "operations": ["list", "get"],
                    "fields": [
                        "name",
                        "description",
                        "url",
                        "isPrivate",
                        "stars",
                    ],
                },
                "pull_requests": {
                    "operations": ["list", "get", "create"],
                    "fields": [
                        "number",
                        "title",
                        "state",
                        "author",
                        "files",
                    ],
                },
                "issues": {
                    "operations": ["list", "get", "create"],
                    "fields": [
                        "number",
                        "title",
                        "state",
                        "author",
                        "labels",
                    ],
                },
                "workflows": {
                    "operations": ["list_runs", "get_run"],
                    "fields": [
                        "id",
                        "title",
                        "status",
                        "conclusion",
                    ],
                },
            },
        }


# Registry of available drivers
DRIVERS: Dict[str, type] = {
    "github": GitHubDriver,
}


def get_driver(name: str) -> Optional[Any]:
    """Get a data plane driver by name."""
    cls = DRIVERS.get(name)
    if not cls:
        return None
    return cls()


def list_drivers() -> list:
    """List all available data plane drivers."""
    return [
        {
            "name": name,
            "schema": cls.schema() if hasattr(cls, "schema") else {},
        }
        for name, cls in DRIVERS.items()
    ]
