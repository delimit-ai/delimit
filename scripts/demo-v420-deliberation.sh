#!/bin/bash
# v4.20 Demo — Ledger + Multi-Model Deliberation
# Shows the "think and build" loop that no competitor has

set -e

export HOME=/tmp/delimit-demo-home
export DELIMIT_MODEL=cli
rm -rf "$HOME" 2>/dev/null
mkdir -p "$HOME/.delimit/memory" "$HOME/.delimit/evidence" "$HOME/.delimit/ledger" "$HOME/.delimit/sessions" "$HOME/.delimit/server/ai"

CLI="node /home/delimit/npm-delimit/bin/delimit-cli.js"

# ── Seed a rich ledger ───────────────────────────────────────────────
cat > "$HOME/.delimit/ledger/ops.jsonl" << 'LEDGER'
{"id":"LED-001","title":"Add rate limiting to /users endpoint","type":"feat","priority":"P0","status":"in_progress","created_at":"2026-04-01T10:00:00Z","description":"Free tier: 100 req/min. Pro tier: 1000 req/min. Use Redis sliding window."}
{"id":"LED-002","title":"Fix pagination cursor bug in /orders","type":"fix","priority":"P0","status":"open","created_at":"2026-04-02T14:00:00Z","description":"Cursor-based pagination returns duplicate rows when items are deleted mid-page."}
{"id":"LED-003","title":"Migrate auth from sessions to JWT","type":"feat","priority":"P1","status":"open","created_at":"2026-04-03T09:00:00Z","description":"15-min access tokens, 7-day refresh. Must not break mobile clients."}
{"id":"LED-004","title":"Add OpenTelemetry tracing to all endpoints","type":"feat","priority":"P2","status":"open","created_at":"2026-04-03T11:00:00Z"}
{"id":"LED-005","title":"Deprecate v1 webhook format","type":"task","priority":"P1","status":"open","created_at":"2026-04-04T08:00:00Z","description":"Send sunset header for 30 days, then remove."}
{"id":"LED-006","title":"Security audit: dependency CVE scan","type":"task","priority":"P0","status":"open","created_at":"2026-04-04T16:00:00Z"}
LEDGER

cat > "$HOME/.delimit/ledger/strategy.jsonl" << 'STRATEGY'
{"id":"STR-001","title":"Evaluate GraphQL federation vs REST gateway","type":"strategy","priority":"P1","status":"open","created_at":"2026-04-01T10:00:00Z","description":"Mobile team wants GraphQL. Backend team prefers REST. Need consensus."}
{"id":"STR-002","title":"Competitor launched rate limiting as a service","type":"strategy","priority":"P1","status":"open","created_at":"2026-04-03T15:00:00Z","description":"Competitor X launched managed rate limiting. Do we build or buy?"}
STRATEGY

# ── Seed memories ────────────────────────────────────────────────────
$CLI remember "PostgreSQL is primary DB, Redis for rate limiting and sessions" --tag postgres --tag redis 2>/dev/null || true
$CLI remember "Mobile clients still on v1 webhooks — 30-day sunset required" --tag webhooks --tag mobile 2>/dev/null || true
$CLI remember "Last security audit was 6 weeks ago — overdue" --tag security 2>/dev/null || true
$CLI remember "Architecture decision: event sourcing for audit trail" --tag architecture 2>/dev/null || true
$CLI remember "JWT migration must not break iOS app — coordinate with mobile team" --tag jwt --tag mobile 2>/dev/null || true

# ── Seed models config ───────────────────────────────────────────────
cat > "$HOME/.delimit/models.json" << 'MODELS'
{
  "claude": { "api_key": "sk-ant-demo", "enabled": true },
  "gemini": { "api_key": "AIza-demo", "enabled": true },
  "codex": { "api_key": "sk-demo", "enabled": true },
  "grok": { "api_key": "xai-demo", "enabled": true }
}
MODELS

# ── Seed MCP + license ───────────────────────────────────────────────
cat > "$HOME/.mcp.json" << 'MCP'
{"mcpServers":{"delimit":{"command":"python3","args":["server.py"]}}}
MCP
cat > "$HOME/.delimit/server/ai/server.py" << 'SRV'
@mcp.tool
def delimit_lint(): pass
@mcp.tool
def delimit_deliberate(): pass
@mcp.tool
def delimit_ledger(): pass
SRV
cat > "$HOME/.delimit/license.json" << 'LIC'
{"tier": "Pro", "status": "active", "email": "team@acme.dev"}
LIC

# ── Seed evidence ────────────────────────────────────────────────────
for i in 1 2 3 4 5 6 7 8; do
  echo "{\"type\":\"evidence_collected\",\"timestamp\":\"2026-04-0${i}T12:00:00Z\",\"project\":\"/projects/acme-api\",\"checks_passed\":true}" >> "$HOME/.delimit/evidence/events.jsonl"
done

# ── Seed session ─────────────────────────────────────────────────────
cat > "$HOME/.delimit/sessions/session_20260405_100000.json" << 'SESS'
{"summary":"Rate limiting implementation + security audit prep","created_at":"2026-04-05T10:00:00Z"}
SESS

# ── Create demo project ──────────────────────────────────────────────
DEMO_DIR=/tmp/delimit-demo-project
rm -rf "$DEMO_DIR"
mkdir -p "$DEMO_DIR/.delimit" "$DEMO_DIR/.git/hooks" "$DEMO_DIR/.github/workflows"
cd "$DEMO_DIR"
git init -q .
git config user.email "dev@acme.dev"
git config user.name "Acme Dev"

cat > openapi.yaml << 'SPEC'
openapi: "3.0.0"
info:
  title: Acme API
  version: 2.1.0
paths:
  /users:
    get:
      operationId: listUsers
      summary: List users
      responses:
        "200":
          description: OK
  /orders:
    get:
      operationId: listOrders
      summary: List orders
      responses:
        "200":
          description: OK
SPEC

cat > .delimit/policies.yml << 'POL'
name: acme-governance
preset: default
enforcement_mode: enforce
rules:
  no-breaking-changes:
    severity: error
  require-descriptions:
    severity: warn
POL

echo "# delimit-governance-hook" > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
echo "uses: delimit-ai/delimit-action@v1" > .github/workflows/api-governance.yml
git add -A && git commit -q -m "initial"

# ── Typing effect ────────────────────────────────────────────────────
type_cmd() {
    echo ""
    echo -n "$ "
    for ((i=0; i<${#1}; i++)); do
        echo -n "${1:$i:1}"
        sleep 0.04
    done
    echo ""
    sleep 0.3
}

# ── Mock deliberation output ─────────────────────────────────────────
mock_deliberation() {
    echo ""
    echo "  Delimit Deliberate"
    echo ""
    echo "  Question: Should we build rate limiting in-house or use a managed service?"
    echo "  Models: Claude + Gemini + Codex + Grok"
    echo ""
    sleep 1
    echo "  Round 1 (independent):"
    sleep 0.5
    echo "    Claude:  Build in-house. Redis sliding window is 50 lines."
    echo "             Managed service adds latency + vendor lock-in."
    sleep 1
    echo "    Gemini:  Build. You already have Redis. The complexity is"
    echo "             in the policy, not the counter."
    sleep 1
    echo "    Codex:   Agree — build. But add circuit breaker for Redis"
    echo "             failures so rate limiting degrades gracefully."
    sleep 1
    echo "    Grok:    Build. Managed services charge per request."
    echo "             At your scale that's \$200/mo for a 50-line feature."
    sleep 1.5
    echo ""
    echo "  Round 2 (deliberation):"
    sleep 0.5
    echo "    All models: AGREE — build in-house with Redis sliding window."
    echo "    Key addition: circuit breaker for Redis failures (Codex)."
    sleep 1.5
    echo ""
    echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  UNANIMOUS CONSENSUS (2 rounds)"
    echo "  Confidence: 94/100"
    echo ""
    echo "  Verdict: Build rate limiting in-house using Redis"
    echo "  sliding window. Add circuit breaker for Redis failures."
    echo "  Estimated complexity: small (50 LOC + tests)."
    echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# ══════════════════════════════════════════════════════════════════════
# DEMO START
# ══════════════════════════════════════════════════════════════════════

clear
echo ""
echo "  Delimit v4.20 — Think and Build"
echo "  Multi-model deliberation + persistent ledger"
echo ""
sleep 2

# 1. Show the status dashboard
type_cmd "delimit status"
$CLI status 2>/dev/null
sleep 4

# 2. Show the report with ledger items
type_cmd "delimit report --since 7d"
$CLI report --since 7d 2>/dev/null
sleep 5

# 3. Run a deliberation
type_cmd "delimit deliberate 'Should we build rate limiting in-house or use a managed service?'"
mock_deliberation
sleep 4

# 4. Remember the decision
type_cmd "delimit remember 'Consensus: build rate limiting in-house with Redis sliding window + circuit breaker'"
$CLI remember 'Consensus: build rate limiting in-house with Redis sliding window + circuit breaker' --tag redis --tag architecture 2>/dev/null
sleep 2

# 5. Recall to show it persists
type_cmd "delimit recall rate limiting"
$CLI recall "rate limiting" 2>/dev/null
sleep 3

echo ""
echo "  4 models. 1 consensus. 0 meetings."
echo ""
echo "  npm i -g delimit-cli"
echo "  github.com/delimit-ai/delimit-mcp-server"
echo ""
sleep 4

# Cleanup
rm -rf "$DEMO_DIR" /tmp/delimit-demo-home
