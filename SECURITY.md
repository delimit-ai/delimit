# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 4.x     | Yes |
| 3.x     | Security fixes only |
| 2.x     | No |
| 1.x     | No |

## Reporting a Vulnerability

We take security seriously at Delimit. If you discover a security vulnerability:

1. **Do NOT** open a public GitHub issue.
2. Email security@delimit.ai with:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Your suggested fix (if any)

## Response timeline

- **Acknowledgment:** within 24 hours
- **Initial assessment:** within 72 hours
- **Fix timeline:** by severity
  - Critical: within 7 days
  - High: within 14 days
  - Medium: within 30 days
  - Low: next release

## Threat model

We document install-time and runtime surfaces separately because developers
evaluate them separately. The short version: **your data never leaves your
machine unless you explicitly configure cloud sync, and even then only to
*your own* Supabase project.**

### Install-time surface

*What happens when you run `npm install -g delimit-cli` or `npx delimit-cli`:*

- **Minimal postinstall.** The `postinstall` hook prints a setup reminder — no network calls, no file writes outside the normal npm install path.
- **npm provenance.** Every release is published with [npm provenance attestation](https://docs.npmjs.com/generating-provenance-statements), cryptographically linking the published tarball to the exact GitHub commit and CI workflow that produced it. Verify with `npm audit signatures delimit-cli` or inspect at `https://www.npmjs.com/package/delimit-cli`.
- **Pinned dependency tree.** Locked versions in `package-lock.json`; transitive graph audited pre-release.
- **SBOM available on request.** CycloneDX SBOM is generated per release; attach-to-release in progress.
- **Package contents allowlist.** Only `bin/`, `lib/`, `adapters/`, `gateway/`, `scripts/`, and documentation files ship. Secrets, tests, and development files are excluded via the `files:` field in `package.json`.
- **Publish workflow.** Releases pass CI validation, dependency audit, and a secrets scan before publish. See `.github/workflows/publish.yml`.

### Runtime surface — CLI

*What `delimit` does when you run it locally:*

- **File reads:**
  - OpenAPI / JSON-schema files at paths you pass to `delimit lint` / `delimit diff` / `delimit wrap`.
  - `.delimit/policies.yml` in the current repo (if present).
  - `.delimit/baselines/*` snapshots.
  - `~/.delimit/` for local state (memories, ledger, attestations, secrets).
- **File writes:**
  - `~/.delimit/attestations/att_*.json` — HMAC-signed `delimit.attestation.v1` bundles. Never sent anywhere.
  - `~/.delimit/memories.jsonl` — cross-session memory. Never sent anywhere unless you opt into cloud sync.
  - `~/.delimit/ledger/*.jsonl` — dated ledger items. Never sent anywhere unless you opt into cloud sync.
  - `/tmp/delimit_report.json` — governance report, consumed by the GitHub Action.
- **Outbound network calls:** the base CLI makes **no outbound network calls**. Every optional network behavior is explicitly opt-in:
  - Multi-model deliberation (`delimit think`) calls the LLM endpoint for whichever model you enabled in `~/.delimit/models.json`.
  - Supabase cloud sync (`delimit_*` tools that mirror events to your dashboard) activates only when `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` are set, AND can be globally disabled with `DELIMIT_DISABLE_CLOUD_SYNC=1`.
  - Social drafting tools (`delimit social*`) call the configured LLM API; drafts are written locally and never auto-posted.

### Runtime surface — MCP server

*What the bundled MCP server does when an AI coding agent loads it:*

- Runs as a local subprocess inside the agent's client (Claude Desktop, Cursor, Cline, etc.).
- Reads: your repo's files (only the ones the agent requests), your `~/.delimit/` state, your `~/.delimit/models.json`.
- Writes: the same local-state files as the CLI.
- **Explicit tool surface**: see the "Tools" section of the MCP manifest — each tool declares which paths it reads/writes.
- **No phone-home.** The MCP server itself makes no calls to any delimit.ai endpoint. The cloud-sync path (Supabase) remains opt-in and user-controlled.

### Explicitly out of scope

- Delimit is **not** a runtime secret scanner, SAST tool, dependency vulnerability scanner, or license scanner. Use dedicated tools for those.
- Delimit is **not** a code executor. `delimit wrap` shells out to whatever command you pass; it does not evaluate code itself.
- Delimit does **not** send your API specs, code, prompts, or agent conversations to Delimit-operated servers. The only network calls that leave your machine are to LLM providers you configured, to `api.github.com` for PR comments from the Action, or to your own Supabase project if you opted in.

## Supply chain verification

For compliance regimes that require explicit supply-chain verification:

- **npm provenance:** every release ties tarball → commit → CI workflow. Verify with `npm audit signatures delimit-cli`.
- **Sigstore signing:** release artifacts for v4.4.0 onward will include Sigstore/Cosign signatures in the public Rekor transparency log.
- **Reproducible builds:** the build is a straight `npm publish` with `sync-gateway.sh` run first to bundle the Python gateway. Reproducibility instructions in `scripts/README.md`.

## Best practices

1. Never commit API keys or tokens to your repository.
2. Store credentials in `~/.delimit/secrets/` (mode 0600) or environment variables — never in `models.json` on a shared machine.
3. Pin the CLI version in CI (`npm install delimit-cli@4.x.x`, not `@latest`).
4. If you do enable Supabase cloud sync, use a service-role key **scoped to your project** and respect the `DELIMIT_DISABLE_CLOUD_SYNC=1` kill switch during development.
5. Review PR annotations from the GitHub Action before merging, especially in `mode: advisory`.
6. `delimit wrap --max-time <s>` caps wall-clock on any wrapped AI-assisted command; recommend using it when the wrapped command is an LLM CLI.

## Data privacy

- Delimit processes your data **locally by default**. CLI and GitHub Action do not send your specs, code, or memory to Delimit-operated servers.
- Cloud sync to Supabase is **opt-in** (requires your own `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`).
- LLM API calls are directed at the provider you configured (Anthropic / OpenAI / xAI / Vertex AI). Delimit does not proxy or intercept these.
- Attestations (`att_*.json`) and ledger entries are local files. Only the public replay URL (`https://delimit.ai/att/<id>`) is shared if **you** choose to publish it.
