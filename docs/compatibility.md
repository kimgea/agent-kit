# Compatibility

## Repository tooling

| Environment | Support | Verification |
|---|---|---|
| Linux, Python 3.11/3.13 | Supported | GitHub Actions plus local lifecycle tests |
| Windows, Python 3.11/3.13 | Supported | GitHub Actions, path, rule, locking, and lifecycle tests |
| macOS, Python 3.11+ | Supported | Standard-library/path design; no native macOS CI runner yet |

Repository tooling requires Python 3.11 or newer because it uses the standard
library `tomllib`. Git and GitHub CLI are optional for local discovery; publishing
and GitHub reads require them.

## Harnesses

| Resource | Codex | Claude Code | Notes |
|---|---|---|---|
| `agent-context` | Supported | Supported | Plain Markdown plus standard-library resolver; private registry paths are OS-native |
| `build-interactive-diagram` | Supported | Supported | Plain HTML/CSS/JS starter; host is optional |
| `grill-me` | Supported | Supported | Plain Markdown; no runtime code |
| `serve-artifacts` | Supported | Supported | Standard-library local-first host; network adapters are optional |
| `todo-capture` | Supported | Supported | Native Windows and POSIX storage/permission fixtures |
| `tool-audit` | Supported | Supported | Codex and Claude transcript parsers; wrapped Codex calls are conservative |
| `gh-api-get` | Supported | Supported | Python module plus POSIX and Windows launchers |
| GitHub API guard | Policy/wrapper preferred | Supported hook shape | Defense in depth only |

Standalone skill archives are the cross-harness distribution. Codex plugin and
marketplace archives target Codex plugin surfaces; they package the same
canonical skill directories and do not make the skills depend on Codex at
runtime. Plugin manifest and marketplace structure are validated locally, but an
interactive Codex marketplace install is still a release smoke-test rather than
part of network-free CI. Before the 1.2.0 release, Codex CLI 0.147.0 successfully
registered the extracted marketplace and installed all four plugins into an
isolated Codex home.

Codex on Linux has been exercised with real local transcripts and policy files.
Claude Code compatibility is covered by synthetic transcript/configuration
fixtures; a live Claude CLI was not available on the maintainer machine during
the 1.0.0 hardening. Windows CI validates native path and configuration behavior,
not an interactive Codex or Claude desktop session.

The artifact host's store, locking, lifecycle, static serving, direct-bind boundary,
advertised URLs, and Tailscale command construction are covered on Linux and Windows
CI. Linux additionally has live loopback HTTP integration tests. CI changes no real
network configuration; provider ownership behavior uses synthetic CLI responses,
and a maintainer performs any private-network smoke test explicitly.

## Installation paths

| Harness/platform | Default skill root |
|---|---|
| Codex | `${CODEX_HOME:-~/.codex}/skills` |
| Claude Code | `${CLAUDE_CONFIG_DIR:-~/.claude}/skills` |

Environment overrides are resolved at execution time. Rerun a skill's permission
setup after relocating it because generated rules pin resolved interpreter and
script paths.

The context registry defaults to the platform's OS-native user configuration
directory and may be overridden only with an absolute
`AGENT_KIT_CONTEXT_CONFIG` path. Private source directories can live in separate
Git repositories, ordinary directories, or encrypted storage that is already
mounted; the resolver does not clone, decrypt, synchronize, or discover them.
