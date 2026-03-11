# delimit-cli

**Prevent breaking API changes before they reach production.**

Deterministic diff engine + policy enforcement + semver classification for OpenAPI specs. The independent successor to Optic.

[![npm](https://img.shields.io/npm/v/delimit-cli)](https://www.npmjs.com/package/delimit-cli)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

## Install

```bash
npm install -g delimit-cli
```

## Quick Start (Under 5 Minutes)

```bash
# 1. Initialize with a policy preset
delimit init --preset default

# 2. Detect breaking changes
delimit lint api/openapi-old.yaml api/openapi-new.yaml

# 3. Add the GitHub Action for automated PR checks
#    Copy .github/workflows/api-governance.yml (see CI section below)
```

## What It Catches

Delimit deterministically detects 23 types of API changes, including 10 breaking patterns:

- Endpoint or method removal
- Required parameter addition
- Response field removal
- Type changes
- Enum value removal
- And more

Every change is classified as `MAJOR`, `MINOR`, `PATCH`, or `NONE` per semver.

## Commands

| Command | Description |
|---------|-------------|
| `delimit init` | Create `.delimit/policies.yml` with a policy preset |
| `delimit lint <old> <new>` | Diff + policy check — returns exit code 1 on violations |
| `delimit diff <old> <new>` | Raw diff with `[BREAKING]`/`[safe]` tags |
| `delimit explain <old> <new>` | Human-readable change explanation |

## Policy Presets

Choose a preset that fits your team:

```bash
delimit init --preset strict    # Public APIs, payments — zero tolerance
delimit init --preset default   # Most teams — balanced rules
delimit init --preset relaxed   # Internal APIs, startups — warnings only
```

| Preset | Breaking changes | Type changes | Field removal |
|--------|-----------------|--------------|---------------|
| `strict` | Error (blocks) | Error (blocks) | Error (blocks) |
| `default` | Error (blocks) | Warning | Error (blocks) |
| `relaxed` | Warning | Warning | Info |

Pass a preset directly to lint:

```bash
delimit lint --policy strict old.yaml new.yaml
```

## Options

```bash
# Semver classification with version bump
delimit lint old.yaml new.yaml --current-version 1.0.0

# Explainer templates
delimit explain old.yaml new.yaml -t migration
delimit explain old.yaml new.yaml -t pr_comment
delimit explain old.yaml new.yaml -t changelog

# JSON output for scripting
delimit lint old.yaml new.yaml --json
```

### Explainer Templates

| Template | Audience |
|----------|----------|
| `developer` | Technical details for engineers |
| `team_lead` | Summary for engineering managers |
| `product` | Non-technical overview for PMs |
| `migration` | Step-by-step migration guide |
| `changelog` | Ready-to-paste changelog entry |
| `pr_comment` | GitHub PR comment format |
| `slack` | Slack message format |

## CI/CD Integration

Add this workflow to `.github/workflows/api-governance.yml`:

```yaml
name: API Governance
on:
  pull_request:
    paths:
      - 'path/to/openapi.yaml'  # adjust to your spec path
permissions:
  contents: read
  pull-requests: write
jobs:
  api-governance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.base.sha }}
          path: _base
      - uses: delimit-ai/delimit@v1
        with:
          old_spec: _base/path/to/openapi.yaml
          new_spec: path/to/openapi.yaml
          mode: advisory  # or 'enforce' to block PRs
```

The action posts a PR comment with:
- Semver badge (`MAJOR` / `MINOR` / `PATCH`)
- Violation table with severity
- Expandable migration guide for breaking changes

See [Delimit API Governance](https://github.com/marketplace/actions/delimit-api-governance) on the GitHub Marketplace.

## Custom Policies

Create `.delimit/policies.yml` or start from a preset:

```yaml
override_defaults: false

rules:
  - id: protect_v1
    name: Protect V1 API
    change_types: [endpoint_removed, method_removed, field_removed]
    severity: error
    action: forbid
    conditions:
      path_pattern: "^/v1/.*"
    message: "V1 API is frozen. Make changes in V2."
```

## Supported Specs

- OpenAPI 3.0.x and 3.1.x
- Swagger 2.0
- YAML and JSON formats

## Links

- [GitHub Action](https://github.com/marketplace/actions/delimit-api-governance) — Automated PR checks
- [GitHub](https://github.com/delimit-ai/delimit) — Source code
- [Issues](https://github.com/delimit-ai/delimit/issues) — Bug reports and feature requests

## License

MIT
