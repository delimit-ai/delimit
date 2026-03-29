"""
Bridge to delimit-generator MCP server.
Tier 3 Extended — code generation and project scaffolding.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("delimit.ai.generate_bridge")

GEN_PACKAGE = Path(os.environ.get("DELIMIT_HOME", str(Path.home() / ".delimit"))) / "server" / "packages" / "delimit-generator"


def _ensure_gen_path():
    if str(GEN_PACKAGE) not in sys.path:
        sys.path.insert(0, str(GEN_PACKAGE))


_TEMPLATES = {
    "component": {
        "nextjs": 'import React from "react";\n\nexport default function {name}() {{\n  return <div>{name}</div>;\n}}\n',
        "react": 'import React from "react";\n\nexport function {name}() {{\n  return <div>{name}</div>;\n}}\n',
    },
    "api-route": {
        "nextjs": 'import {{ NextRequest, NextResponse }} from "next/server";\n\nexport async function GET(request: NextRequest) {{\n  return NextResponse.json({{ message: "{name}" }});\n}}\n',
        "express": 'const express = require("express");\nconst router = express.Router();\n\nrouter.get("/{name}", (req, res) => {{\n  res.json({{ message: "{name}" }});\n}});\n\nmodule.exports = router;\n',
    },
    "test": {
        "jest": 'describe("{name}", () => {{\n  it("should work", () => {{\n    expect(true).toBe(true);\n  }});\n}});\n',
        "pytest": 'def test_{name}():\n    assert True\n',
    },
}


def template(template_type: str, name: str, framework: str = "nextjs", features: Optional[List[str]] = None, target: Optional[str] = None) -> Dict[str, Any]:
    """Generate a code file from built-in templates.

    Args:
        target: Directory to write the generated file into. Defaults to cwd if not specified.
    """
    tpl_group = _TEMPLATES.get(template_type)
    if not tpl_group:
        return {"tool": "gen.template", "status": "error",
                "error": f"Unknown template_type '{template_type}'. Available: {list(_TEMPLATES.keys())}"}
    tpl = tpl_group.get(framework, list(tpl_group.values())[0])
    content = tpl.format(name=name)
    ext_map = {"component": ".tsx", "api-route": ".ts", "test": ".test.ts"}
    ext = ext_map.get(template_type, ".ts")
    target_dir = Path(target).resolve() if target else Path.cwd()
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{name}{ext}"
    try:
        out_path.write_text(content)
    except Exception as e:
        return {"tool": "gen.template", "status": "error", "error": str(e)}
    return {"tool": "gen.template", "status": "ok", "file": str(out_path), "template_type": template_type, "framework": framework}


_SCAFFOLD = {
    "node": {"dirs": ["src", "tests", "src/routes"], "files": {
        "package.json": '{{"name": "{name}", "version": "0.1.0", "main": "src/index.js"}}\n',
        "src/index.js": 'console.log("Hello from {name}");\n',
        "tests/.gitkeep": "",
        ".gitignore": "node_modules/\ndist/\n.env\n",
    }},
    "python": {"dirs": ["src", "tests"], "files": {
        "pyproject.toml": '[project]\nname = "{name}"\nversion = "0.1.0"\n',
        "src/__init__.py": "",
        "tests/__init__.py": "",
        "tests/test_placeholder.py": "def test_placeholder():\n    assert True\n",
        ".gitignore": "__pycache__/\n*.pyc\n.venv/\ndist/\n.env\n",
    }},
    "nextjs": {"dirs": ["app", "components", "public", "tests"], "files": {
        "package.json": '{{"name": "{name}", "version": "0.1.0", "scripts": {{"dev": "next dev"}}}}\n',
        "app/page.tsx": 'export default function Home() {{ return <main>{name}</main>; }}\n',
        ".gitignore": "node_modules/\n.next/\n.env\n",
    }},
}

_SCAFFOLD_ALIASES = {
    "api": "node",
    "library": "node",
}


def scaffold(project_type: str, name: str, packages: Optional[List[str]] = None) -> Dict[str, Any]:
    """Create a project directory structure."""
    resolved_type = _SCAFFOLD_ALIASES.get(project_type, project_type)
    spec = _SCAFFOLD.get(resolved_type)
    if not spec:
        return {"tool": "gen.scaffold", "status": "error",
                "error": f"Unknown project_type '{project_type}'. Available: {list(_SCAFFOLD.keys()) + list(_SCAFFOLD_ALIASES.keys())}"}
    root = Path.cwd() / name
    try:
        root.mkdir(parents=True, exist_ok=True)
        for d in spec["dirs"]:
            (root / d).mkdir(parents=True, exist_ok=True)
        created = []
        for fp, content in spec["files"].items():
            full = root / fp
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content.format(name=name))
            created.append(fp)
        return {"tool": "gen.scaffold", "status": "ok", "project_path": str(root),
                "project_type": resolved_type, "requested_project_type": project_type, "files_created": created}
    except Exception as e:
        return {"tool": "gen.scaffold", "status": "error", "error": str(e)}
