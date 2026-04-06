#!/bin/bash
# v4.20 Clean Demo — realistic mock data, no personal info
# Uses a temp HOME so nothing leaks

set -e

export HOME=/tmp/delimit-demo-home
export DELIMIT_MODEL=cli
rm -rf "$HOME" 2>/dev/null
mkdir -p "$HOME/.delimit/memory" "$HOME/.delimit/evidence" "$HOME/.delimit/ledger" "$HOME/.delimit/sessions" "$HOME/.delimit/server/ai"

CLI="node /home/delimit/npm-delimit/bin/delimit-cli.js"

# ── Seed memories (12 realistic entries) ─────────────────────────────
$CLI remember "API uses JWT with 15-minute expiry, refresh tokens last 7 days" --tag jwt 2>/dev/null || true
$CLI remember "PostgreSQL is primary DB, Redis for sessions only" --tag postgres --tag redis 2>/dev/null || true
$CLI remember "Never modify the payments service on Fridays — incident 2024-11" --tag payments 2>/dev/null || true
$CLI remember "GraphQL gateway handles auth, REST endpoints are internal only" --tag graphql --tag auth 2>/dev/null || true
$CLI remember "Docker images must be under 500MB, scanned by Trivy before push" --tag docker --tag security 2>/dev/null || true
$CLI remember "Staging deploys to us-east-1, production is multi-region" --tag aws --tag deploy 2>/dev/null || true
$CLI remember "OpenAPI spec is source of truth — SDK types generated from it weekly" --tag openapi 2>/dev/null || true
$CLI remember "Rate limiting: 100 req/min for free tier, 1000 for pro" --tag api 2>/dev/null || true
$CLI remember "Migrated from REST to GraphQL for mobile clients in Q3" --tag graphql 2>/dev/null || true
$CLI remember "Sentry alerting threshold: P50 > 200ms triggers page" --tag sentry --tag monitoring 2>/dev/null || true
$CLI remember "E2E tests run against staging before every prod deploy" --tag testing --tag ci 2>/dev/null || true
$CLI remember "Architecture decision: chose event sourcing for audit trail" --tag architecture 2>/dev/null || true

# ── Seed models config ───────────────────────────────────────────────
cat > "$HOME/.delimit/models.json" << 'MODELS'
{
  "claude": { "api_key": "sk-ant-demo", "enabled": true },
  "gemini": { "api_key": "AIza-demo", "enabled": true },
  "codex": { "api_key": "sk-demo", "enabled": true }
}
MODELS

# ── Seed MCP config ──────────────────────────────────────────────────
cat > "$HOME/.mcp.json" << 'MCP'
{
  "mcpServers": {
    "delimit": {
      "command": "python3",
      "args": ["server.py"]
    }
  }
}
MCP

# ── Seed server.py stub (for doctor check) ───────────────────────────
cat > "$HOME/.delimit/server/ai/server.py" << 'SRV'
# Delimit MCP Server stub
@mcp.tool
def delimit_lint(): pass
@mcp.tool
def delimit_diff(): pass
@mcp.tool
def delimit_scan(): pass
SRV

# ── Seed license ─────────────────────────────────────────────────────
cat > "$HOME/.delimit/license.json" << 'LIC'
{"tier": "Pro", "status": "active", "email": "team@acme.dev"}
LIC

# ── Seed ledger items ────────────────────────────────────────────────
cat > "$HOME/.delimit/ledger/ops.jsonl" << 'LEDGER'
{"id":"LED-001","title":"Add rate limiting to /users endpoint","type":"feat","priority":"P1","status":"open","created_at":"2026-04-01T10:00:00Z"}
{"id":"LED-002","title":"Fix pagination bug in /orders","type":"fix","priority":"P0","status":"in_progress","created_at":"2026-04-02T14:00:00Z"}
{"id":"LED-003","title":"Migrate auth to OAuth 2.1","type":"feat","priority":"P1","status":"open","created_at":"2026-04-03T09:00:00Z"}
{"id":"LED-004","title":"Add OpenTelemetry tracing","type":"feat","priority":"P2","status":"open","created_at":"2026-04-03T11:00:00Z"}
{"id":"LED-005","title":"Update SDK types from spec","type":"task","priority":"P1","status":"done","created_at":"2026-04-04T08:00:00Z"}
{"id":"LED-006","title":"Security audit: dependency scan","type":"task","priority":"P0","status":"open","created_at":"2026-04-04T16:00:00Z"}
{"id":"LED-007","title":"Deprecate v1 webhook format","type":"task","priority":"P2","status":"open","created_at":"2026-04-05T10:00:00Z"}
LEDGER

# ── Seed evidence records ────────────────────────────────────────────
for i in $(seq 1 8); do
  cat >> "$HOME/.delimit/evidence/events.jsonl" << EVIDENCE
{"type":"evidence_collected","timestamp":"2026-04-0${i}T12:00:00Z","project":"/projects/acme-api","checks_passed":true}
EVIDENCE
done

# ── Seed session ─────────────────────────────────────────────────────
cat > "$HOME/.delimit/sessions/session_20260405_100000.json" << 'SESS'
{"summary":"Rate limiting implementation + SDK type regeneration","description":"Shipped rate limiting for free tier, regenerated SDK types from latest spec","created_at":"2026-04-05T10:00:00Z"}
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
  description: The Acme platform API — users, orders, payments, webhooks
paths:
  /users:
    get:
      operationId: listUsers
      summary: List all users with pagination
      parameters:
        - name: limit
          in: query
          schema:
            type: integer
            default: 20
        - name: offset
          in: query
          schema:
            type: integer
            default: 0
      responses:
        "200":
          description: Paginated user list
    post:
      operationId: createUser
      summary: Create a new user
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [email, name]
              properties:
                email:
                  type: string
                  format: email
                name:
                  type: string
      responses:
        "201":
          description: User created
  /users/{id}:
    get:
      operationId: getUser
      summary: Get user by ID
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        "200":
          description: User details
        "404":
          description: Not found
  /orders:
    get:
      operationId: listOrders
      summary: List orders
      responses:
        "200":
          description: Order list
  /payments/webhook:
    post:
      operationId: handlePaymentWebhook
      summary: Stripe webhook endpoint
      responses:
        "200":
          description: Webhook processed
SPEC

cat > .delimit/policies.yml << 'POL'
name: acme-governance
preset: default
enforcement_mode: enforce
rules:
  no-breaking-changes:
    severity: error
    description: Block removal of endpoints or required fields
  no-unversioned-changes:
    severity: error
    description: Require version bump for breaking changes
  require-descriptions:
    severity: warn
    description: All endpoints must have descriptions
  require-operation-ids:
    severity: warn
    description: All operations need unique IDs
  max-response-time:
    severity: warn
    threshold: 500ms
  require-auth:
    severity: error
    description: All non-public endpoints require authentication
POL

echo "# delimit-governance-hook" > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

cat > .github/workflows/api-governance.yml << 'WF'
name: API Governance
on: [pull_request]
jobs:
  governance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: delimit-ai/delimit-action@v1
        with:
          spec: openapi.yaml
WF

git add -A
git commit -q -m "initial: Acme API v2.1.0 with governance"

# ── Simulated typing ─────────────────────────────────────────────────
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

clear
echo ""
echo "  Delimit v4.20 — The Highest State of AI Governance"
echo ""
sleep 2

# 1. Doctor — full health check
type_cmd "delimit doctor"
$CLI doctor 2>/dev/null
sleep 4

# 2. Status — the visual dashboard
type_cmd "delimit status"
$CLI status 2>/dev/null
sleep 5

# 3. Simulate — dry run before commit
type_cmd "delimit simulate"
$CLI simulate 2>/dev/null
sleep 4

# 4. Remember — cross-model memory
type_cmd "delimit remember 'webhook v1 deprecated, migrate by Q3'"
$CLI remember 'webhook v1 deprecated, migrate by Q3' 2>/dev/null
sleep 2

# 5. Recall — verify it persists
type_cmd "delimit recall webhook"
$CLI recall webhook 2>/dev/null
sleep 3

echo ""
echo "  npm i -g delimit-cli"
echo "  github.com/delimit-ai/delimit-mcp-server"
echo ""
sleep 3

# Cleanup
rm -rf "$DEMO_DIR" /tmp/delimit-demo-home
