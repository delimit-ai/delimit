# delimit-cli

**ESLint for API contracts** — detect breaking changes, enforce semver, and generate migration guides for OpenAPI specs.

[![npm](https://img.shields.io/npm/v/delimit-cli)](https://www.npmjs.com/package/delimit-cli)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

## Install

```bash
npm install -g delimit-cli
```

This installs the `delimit` command globally.

## Quick Start

```bash
# Initialize a policy file in your repo
delimit init

# Detect breaking changes between two specs
delimit lint api/openapi-old.yaml api/openapi-new.yaml

# See raw diff output
delimit diff api/openapi-old.yaml api/openapi-new.yaml

# Generate a human-readable explanation
delimit explain api/openapi-old.yaml api/openapi-new.yaml
```

## Commands

| Command | Description |
|---------|-------------|
| `delimit init` | Create `.delimit/policies.yml` with default rules |
| `delimit lint <old> <new>` | Diff + policy check with semver badge and violations |
| `delimit diff <old> <new>` | Raw diff with `[BREAKING]`/`[safe]` tags |
| `delimit explain <old> <new>` | Human-readable change explanation |

### Options

```bash
# Specify explainer template (default: developer)
delimit explain old.yaml new.yaml -t migration
delimit explain old.yaml new.yaml -t pr_comment
delimit explain old.yaml new.yaml -t changelog

# Include semver classification
delimit lint old.yaml new.yaml --current-version 1.0.0

# Use custom policy file
delimit lint old.yaml new.yaml -p .delimit/policies.yml
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

For automated PR checks, use the GitHub Action:

```yaml
- uses: delimit-ai/delimit-action@v1
  with:
    old_spec: base/api/openapi.yaml
    new_spec: api/openapi.yaml
```

See [Delimit API Governance](https://github.com/marketplace/actions/delimit-api-governance) on the GitHub Marketplace.

## Custom Policies

Create `.delimit/policies.yml`:

```yaml
rules:
  - id: no_endpoint_removal
    change_types: [endpoint_removed]
    severity: error
    action: forbid
    message: "Endpoints cannot be removed without deprecation"

  - id: warn_type_change
    change_types: [type_changed]
    severity: warning
    action: warn
    message: "Type change may break clients"
```

## Supported Specs

- OpenAPI 3.0.x and 3.1.x
- Swagger 2.0
- YAML and JSON formats

## Links

- [GitHub Action](https://github.com/marketplace/actions/delimit-api-governance) — CI/CD integration
- [GitHub](https://github.com/delimit-ai/delimit) — Source code
- [Issues](https://github.com/delimit-ai/delimit/issues) — Bug reports and feature requests

## License

MIT
