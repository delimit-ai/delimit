/**
 * LED-213: Canonical Delimit instruction template.
 *
 * Single source of truth for the governance section injected into
 * CLAUDE.md, Codex instructions.md, Gemini GEMINI.md / customInstructions,
 * and Cursor .cursorrules.  All models get identical Consensus 123 content.
 */

const fs = require('fs');
const path = require('path');

/**
 * Return the full Consensus 123 governance template (markdown).
 * Used verbatim by Claude, Codex, and Cursor.
 */
function getDelimitSection() {
    const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf-8'));
    const version = pkg.version || '0.0.0';
    return `<!-- delimit:start v${version} -->
# Delimit

Unify all AI coding assistants with persistent context, governance, and multi-model debate.

## Auto-Trigger Rules (Consensus 123)

These rules fire automatically. The AI MUST call the specified tools without asking permission.
The founder reviews and approves via email. The AI's job is to draft, send, and chain — not to ask.

### Session Lifecycle
- **Session start**: call \`delimit_ledger_context\` + \`delimit_gov_health\` + \`delimit_inbox_daemon(action="start")\` + \`delimit_notify_routing(action="status")\`
- **Session end or idle**: call \`delimit_session_handoff\` to preserve context for next session
- If returning user, summarize what's pending. If new project, call \`delimit_scan\`.

### Code Development (debounced per edit batch)
- After editing UI/CSS: call \`delimit_design_validate_responsive\`
- After editing API specs: call \`delimit_lint\` + \`delimit_drift_check\`
- After editing tests: call \`delimit_test_smoke\`
- After any significant code change: call \`delimit_test_smoke\` if applicable tests exist

### Pre-Commit / Pre-Deploy Gates
- Before \`git commit\`: call \`delimit_repo_diagnose\`
- Deploy requested: \`delimit_security_audit\` then \`delimit_test_smoke\` then \`delimit_changelog\` then \`delimit_deploy_plan\`
- Deploy succeeds: \`delimit_deploy_verify\` + \`delimit_evidence_collect\`
- Verify succeeds: \`delimit_ledger_done\` (related task) + \`delimit_notify\`

### Change Management (update docs with every ship)
- After shipping a feature: update README if CLI commands or tool count changed
- After version bump: update version badge, tool count, test count on landing page
- After npm publish: sync gateway server.py to npm bundle, scrub PII, run security-check.sh
- After changing pricing/tiers: update pricing page and Lemon Squeezy product
- Before deploy: call \`delimit_swarm(action="docs_check")\` to verify docs freshness
- Before submitting a PR to an external repo: call \`delimit_deliberate\` on the diff + PR description (Pro only — if using free tier deliberations and quota is exhausted, skip this gate but log a warning)

### Content / Outreach (all drafts, never auto-post)
- Social content drafted: ALWAYS call \`delimit_social_post\` or \`delimit_notify\` immediately
- \`delimit_social_target\` scan completes: call \`delimit_notify\` with target summary
- Screenshot of social thread shared: auto-draft reply + call \`delimit_notify\`
- During ANY social interaction: scan for competitive signals, integration opportunities, and strategic items. Add to strategy ledger if significant.

### Strategic / Business Operations
- Strategic opportunity identified: call \`delimit_ledger_add\` immediately
- \`delimit_ledger_add\` fires (non-P0): \`delimit_notify\` (batched, 15-min digest)
- \`delimit_ledger_add\` fires (P0): \`delimit_notify\` (immediate) + \`delimit_agent_dispatch\`
- Conflicting high-severity signals: call \`delimit_deliberate\` for multi-model consensus

### Monitoring / Sensors
- GitHub issue state change (closed, merged, labeled): \`delimit_ledger_update\` + \`delimit_notify\` (immediate)
- GitHub issue new comments: \`delimit_ledger_update\` + \`delimit_notify\` (batched digest)
- \`delimit_drift_check\` finds drift: \`delimit_ledger_add\` + \`delimit_notify\`

### Approval Loop (Email Control Plane)
- Approval email detected: execute the approved action based on context
- Rejection email detected: \`delimit_ledger_update\` (mark rejected)

### Audit Trail
- After security audit, test run, or deploy: call \`delimit_evidence_collect\`
- Any gate failure: \`delimit_evidence_collect\` + \`delimit_ledger_add\` + \`delimit_notify\` (immediate)

### Storm Prevention
- Edit triggers: debounce to once per assistant turn
- Non-P0 notifications: batch into 15-minute digests
- Max 5 immediate notifications per hour (overflow to digest)
- Per-scan fan-out: max 10 targets per notification

## What Delimit does:
- **API governance** -- lint, diff, semver classification, migration guides
- **Persistent context** -- memory and ledger survive across sessions and models
- **Security audit** -- dependency scanning, secret detection
- **Test verification** -- confirm tests actually ran, measure coverage
- **Multi-model deliberation** -- consensus from multiple AI models (3 free, then BYOK)

## GitHub Action
Add breaking change detection to any repo:
\`\`\`yaml
- uses: delimit-ai/delimit-action@v1
  with:
    spec: api/openapi.yaml
\`\`\`

## Links
- Docs: https://delimit.ai/docs
- GitHub: https://github.com/delimit-ai/delimit-mcp-server
- Action: https://github.com/marketplace/actions/delimit-api-governance
<!-- delimit:end -->`;
}

/**
 * Return a condensed single-line version for Gemini customInstructions (JSON string value).
 * Newlines are literal \\n so it fits inside a JSON string.
 */
function getDelimitSectionCondensed() {
    return getDelimitSection()
        .replace(/<!-- delimit:start[^>]*-->\n?/, '')
        .replace(/<!-- delimit:end -->\n?/, '')
        .replace(/\n/g, '\\n')
        .trim();
}

module.exports = { getDelimitSection, getDelimitSectionCondensed };
