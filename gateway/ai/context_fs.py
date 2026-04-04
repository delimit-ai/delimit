"""Context Filesystem -- versioned namespace for agent state (STR-048).

All agent state lives here: memory, plans, artifacts, embeddings.
Supports branching (per-session forks) and merging (sync back to main).
This is what makes switching models seamless.
"""
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone

CONTEXT_ROOT = Path.home() / ".delimit" / "context"


def init_context(venture: str = "default") -> dict:
    """Initialize a context namespace for a venture."""
    ctx_dir = CONTEXT_ROOT / venture
    ctx_dir.mkdir(parents=True, exist_ok=True)
    for sub in ["memory", "plans", "artifacts", "snapshots", "branches"]:
        (ctx_dir / sub).mkdir(exist_ok=True)

    manifest = ctx_dir / "manifest.json"
    if not manifest.exists():
        manifest.write_text(json.dumps({
            "venture": venture,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "current_branch": "main",
            "version": 1,
        }))
    return {"initialized": venture, "path": str(ctx_dir)}


def _bump_version(venture: str):
    """Increment the version counter in the venture manifest."""
    manifest_path = CONTEXT_ROOT / venture / "manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        m["version"] = m.get("version", 0) + 1
        m["updated_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(m))


def write_artifact(venture: str, name: str, content: str, artifact_type: str = "text") -> dict:
    """Write an artifact to the context filesystem."""
    ctx_dir = CONTEXT_ROOT / venture / "artifacts"
    ctx_dir.mkdir(parents=True, exist_ok=True)

    artifact = {
        "name": name,
        "type": artifact_type,
        "content": content,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "size": len(content),
    }
    (ctx_dir / f"{name}.json").write_text(json.dumps(artifact))

    # Version tracking
    _bump_version(venture)
    return {"written": name, "venture": venture, "size": len(content)}


def read_artifact(venture: str, name: str) -> dict:
    """Read an artifact from the context filesystem."""
    path = CONTEXT_ROOT / venture / "artifacts" / f"{name}.json"
    if not path.exists():
        return {"error": f"Artifact '{name}' not found in {venture}"}
    return json.loads(path.read_text())


def list_artifacts(venture: str) -> list:
    """List all artifacts in a venture's context."""
    ctx_dir = CONTEXT_ROOT / venture / "artifacts"
    if not ctx_dir.exists():
        return []
    artifacts = []
    for f in sorted(ctx_dir.glob("*.json")):
        try:
            a = json.loads(f.read_text())
            artifacts.append({
                "name": a["name"],
                "type": a.get("type"),
                "size": a.get("size", 0),
                "created_at": a.get("created_at"),
            })
        except (json.JSONDecodeError, KeyError):
            pass
    return artifacts


def create_snapshot(venture: str, label: str = "") -> dict:
    """Create a point-in-time snapshot of the entire context."""
    ctx_dir = CONTEXT_ROOT / venture
    snapshots_dir = ctx_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    snap_name = f"{ts}_{label}" if label else ts
    snap_dir = snapshots_dir / snap_name

    # Copy artifacts and memory
    for sub in ["artifacts", "memory"]:
        src = ctx_dir / sub
        if src.exists():
            shutil.copytree(src, snap_dir / sub, dirs_exist_ok=True)

    # Save manifest
    manifest = {
        "snapshot": snap_name,
        "venture": venture,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label": label,
    }
    (snap_dir / "snapshot.json").write_text(json.dumps(manifest))

    return {"snapshot": snap_name, "venture": venture}


def list_snapshots(venture: str) -> list:
    """List all snapshots for a venture."""
    snapshots_dir = CONTEXT_ROOT / venture / "snapshots"
    if not snapshots_dir.exists():
        return []
    snaps = []
    for d in sorted(snapshots_dir.iterdir(), reverse=True):
        if d.is_dir():
            meta_file = d / "snapshot.json"
            if meta_file.exists():
                snaps.append(json.loads(meta_file.read_text()))
            else:
                snaps.append({"snapshot": d.name, "venture": venture})
    return snaps


def create_branch(venture: str, branch_name: str) -> dict:
    """Create a branch (fork) of the current context."""
    ctx_dir = CONTEXT_ROOT / venture
    branch_dir = ctx_dir / "branches" / branch_name
    if branch_dir.exists():
        return {"error": f"Branch '{branch_name}' already exists"}

    branch_dir.mkdir(parents=True)
    for sub in ["artifacts", "memory"]:
        src = ctx_dir / sub
        if src.exists():
            shutil.copytree(src, branch_dir / sub, dirs_exist_ok=True)

    manifest = {
        "branch": branch_name,
        "venture": venture,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parent": "main",
    }
    (branch_dir / "branch.json").write_text(json.dumps(manifest))

    return {"branch": branch_name, "venture": venture}


def list_branches(venture: str) -> list:
    """List all branches for a venture."""
    branches_dir = CONTEXT_ROOT / venture / "branches"
    if not branches_dir.exists():
        return []
    branches = []
    for d in sorted(branches_dir.iterdir()):
        if d.is_dir():
            meta_file = d / "branch.json"
            if meta_file.exists():
                branches.append(json.loads(meta_file.read_text()))
            else:
                branches.append({"branch": d.name, "venture": venture})
    return branches


def merge_branch(venture: str, branch_name: str) -> dict:
    """Merge a branch back into main context."""
    branch_dir = CONTEXT_ROOT / venture / "branches" / branch_name
    if not branch_dir.exists():
        return {"error": f"Branch '{branch_name}' not found"}

    ctx_dir = CONTEXT_ROOT / venture
    merged_files = 0
    for sub in ["artifacts", "memory"]:
        src = branch_dir / sub
        if src.exists():
            dest = ctx_dir / sub
            dest.mkdir(parents=True, exist_ok=True)
            for f in src.glob("*"):
                shutil.copy2(f, dest / f.name)
                merged_files += 1

    shutil.rmtree(branch_dir)
    _bump_version(venture)
    return {"merged": branch_name, "files": merged_files}
