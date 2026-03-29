"""Distributed tracing for agent tool calls.

STR-053: Every tool call is part of a trace -- from prompt to tool to artifact to outcome.
Traces are stored as JSONL files in ~/.delimit/traces/ for local-first observability.
"""
import json
import time
from pathlib import Path
from datetime import datetime, timezone

TRACES_DIR = Path.home() / ".delimit" / "traces"

_span_seq = 0


def start_span(trace_id: str, tool: str, args: dict = None) -> dict:
    """Start a trace span."""
    global _span_seq
    _span_seq += 1
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    span = {
        "trace_id": trace_id,
        "span_id": f"{trace_id}-{int(time.time()*1000) % 10000:04d}-{_span_seq}",
        "tool": tool,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "args_summary": str(args)[:200] if args else "",
    }
    trace_file = TRACES_DIR / f"trace-{trace_id}.jsonl"
    with open(trace_file, "a") as f:
        f.write(json.dumps(span) + "\n")
    return span


def end_span(trace_id: str, span_id: str, status: str = "ok", result_summary: str = ""):
    """End a trace span."""
    span = {
        "trace_id": trace_id,
        "span_id": span_id,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "result_summary": result_summary[:200],
    }
    trace_file = TRACES_DIR / f"trace-{trace_id}.jsonl"
    with open(trace_file, "a") as f:
        f.write(json.dumps(span) + "\n")


def get_trace(trace_id: str) -> list:
    """Get all spans for a trace, merging start/end records by span_id."""
    trace_file = TRACES_DIR / f"trace-{trace_id}.jsonl"
    if not trace_file.exists():
        return []
    spans = {}
    for line in trace_file.read_text().splitlines():
        try:
            s = json.loads(line)
            sid = s.get("span_id", "")
            if sid in spans:
                spans[sid].update(s)
            else:
                spans[sid] = s
        except Exception:
            pass
    return sorted(spans.values(), key=lambda s: s.get("started_at", ""))


def list_traces(limit: int = 20) -> list:
    """List recent traces."""
    if not TRACES_DIR.exists():
        return []
    traces = []
    for f in sorted(TRACES_DIR.glob("trace-*.jsonl"), reverse=True)[:limit]:
        try:
            lines = f.read_text().splitlines()
            first = json.loads(lines[0]) if lines else {}
            span_count = len(set(
                json.loads(l).get("span_id", "") for l in lines if l.strip()
            ))
            traces.append({
                "trace_id": first.get("trace_id", f.stem.replace("trace-", "")),
                "started_at": first.get("started_at", ""),
                "span_count": span_count,
                "first_tool": first.get("tool", ""),
            })
        except Exception:
            pass
    return traces


def write_demo_traces() -> list:
    """Generate demo trace data for UI development. Returns trace IDs created."""
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    demo_traces = []

    # Trace 1: Successful lint + diff + ledger workflow
    t1 = "demo-a1b2"
    spans_1 = [
        {"tool": "delimit_lint", "duration_ms": 120, "status": "ok", "args": "old=api_v1.yaml new=api_v2.yaml", "result": "2 breaking changes found"},
        {"tool": "delimit_diff", "duration_ms": 85, "status": "ok", "args": "old=api_v1.yaml new=api_v2.yaml", "result": "5 changes: 2 breaking, 1 deprecation, 2 additions"},
        {"tool": "delimit_ledger_add", "duration_ms": 45, "status": "ok", "args": "title=Fix breaking changes priority=high", "result": "Created DLM-105"},
        {"tool": "delimit_deliberate", "duration_ms": 3200, "status": "ok", "args": "question=Should we ship v2 with breaks?", "result": "Consensus: delay release, add migration guide"},
        {"tool": "delimit_explain", "duration_ms": 210, "status": "ok", "args": "template=migration", "result": "Migration guide generated for 2 endpoints"},
    ]
    trace_file = TRACES_DIR / f"trace-{t1}.jsonl"
    with open(trace_file, "w") as f:
        for i, s in enumerate(spans_1):
            offset = sum(sp["duration_ms"] for sp in spans_1[:i]) / 1000
            started = now - 300 + offset
            span_id = f"{t1}-{i:04d}"
            start_record = {
                "trace_id": t1,
                "span_id": span_id,
                "tool": s["tool"],
                "started_at": datetime.fromtimestamp(started, tz=timezone.utc).isoformat(),
                "status": "running",
                "args_summary": s["args"],
            }
            end_record = {
                "trace_id": t1,
                "span_id": span_id,
                "ended_at": datetime.fromtimestamp(started + s["duration_ms"] / 1000, tz=timezone.utc).isoformat(),
                "status": s["status"],
                "result_summary": s["result"],
            }
            f.write(json.dumps(start_record) + "\n")
            f.write(json.dumps(end_record) + "\n")
    demo_traces.append(t1)

    # Trace 2: Deploy workflow with a blocked step
    t2 = "demo-c3d4"
    spans_2 = [
        {"tool": "delimit_deploy_plan", "duration_ms": 150, "status": "ok", "args": "service=gateway version=3.3.0", "result": "Plan: build, test, publish"},
        {"tool": "delimit_deploy_build", "duration_ms": 890, "status": "warn", "args": "service=gateway", "result": "Built with 2 warnings (deprecated deps)"},
        {"tool": "delimit_deploy_publish", "duration_ms": 12, "status": "blocked", "args": "service=gateway target=prod", "result": "Blocked: requires approval (high risk)"},
    ]
    trace_file = TRACES_DIR / f"trace-{t2}.jsonl"
    with open(trace_file, "w") as f:
        for i, s in enumerate(spans_2):
            offset = sum(sp["duration_ms"] for sp in spans_2[:i]) / 1000
            started = now - 600 + offset
            span_id = f"{t2}-{i:04d}"
            start_record = {
                "trace_id": t2,
                "span_id": span_id,
                "tool": s["tool"],
                "started_at": datetime.fromtimestamp(started, tz=timezone.utc).isoformat(),
                "status": "running",
                "args_summary": s["args"],
            }
            end_record = {
                "trace_id": t2,
                "span_id": span_id,
                "ended_at": datetime.fromtimestamp(started + s["duration_ms"] / 1000, tz=timezone.utc).isoformat(),
                "status": s["status"],
                "result_summary": s["result"],
            }
            f.write(json.dumps(start_record) + "\n")
            f.write(json.dumps(end_record) + "\n")
    demo_traces.append(t2)

    # Trace 3: Security scan workflow
    t3 = "demo-e5f6"
    spans_3 = [
        {"tool": "delimit_scan", "duration_ms": 340, "status": "ok", "args": "path=./project", "result": "Project scanned: FastAPI, 76 tools, OpenAPI spec found"},
        {"tool": "delimit_security_scan", "duration_ms": 1200, "status": "warn", "args": "path=./project", "result": "1 high severity: outdated cryptography package"},
        {"tool": "delimit_ledger_add", "duration_ms": 38, "status": "ok", "args": "title=Upgrade cryptography package priority=high", "result": "Created SEC-001"},
    ]
    trace_file = TRACES_DIR / f"trace-{t3}.jsonl"
    with open(trace_file, "w") as f:
        for i, s in enumerate(spans_3):
            offset = sum(sp["duration_ms"] for sp in spans_3[:i]) / 1000
            started = now - 900 + offset
            span_id = f"{t3}-{i:04d}"
            start_record = {
                "trace_id": t3,
                "span_id": span_id,
                "tool": s["tool"],
                "started_at": datetime.fromtimestamp(started, tz=timezone.utc).isoformat(),
                "status": "running",
                "args_summary": s["args"],
            }
            end_record = {
                "trace_id": t3,
                "span_id": span_id,
                "ended_at": datetime.fromtimestamp(started + s["duration_ms"] / 1000, tz=timezone.utc).isoformat(),
                "status": s["status"],
                "result_summary": s["result"],
            }
            f.write(json.dumps(start_record) + "\n")
            f.write(json.dumps(end_record) + "\n")
    demo_traces.append(t3)

    return demo_traces
