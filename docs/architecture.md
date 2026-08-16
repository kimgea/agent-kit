# Repository architecture

## Layers

`toolkit.toml` is the reviewed resource registry. `scripts/agent_kit.py` is the
repository lifecycle interface. Installable resources remain self-contained under
`skills/`; repository tooling never becomes a runtime import for a deployed skill.

Each installable skill belongs to exactly one cataloged plugin. Release packaging
derives plugin manifests, plugin trees, and the marketplace from the catalog and
skill UI metadata. These are distributions of canonical skill sources, not a
second development layer. A plugin may group related skills later, but a single
skill is the default ownership and versioning boundary. The `artifacts` plugin is
an explicit coherent group: its producer and host remain independently installable,
but together form the normal create-and-deliver workflow.

Non-skill resources stay organized by asset type:

- instructions, templates, and policies are reviewed text assets;
- hooks are deterministic defense-in-depth components;
- adapters describe harness-specific integration;
- tools are reusable executables or wrappers;
- evaluations are behavioral fixtures outside installed skills.

## Context layering

`agent-context` provides an optional read-only bridge between public defaults and
separate private context repositories. It loads only sources registered in the
user's OS-native registry and selects project context by an exact resolved path
or exact Git remote. There is no directory crawling, fuzzy matching, network
lookup, or automatic project enrollment.

Layers merge from public to user, profile, domain, repository, and explicit
session context. Later values override earlier values within mergeable knowledge
categories, while provenance remains visible. Public invariants are locked;
private context cannot replace repository instructions, permission boundaries,
or skill safety rules. Skills remain complete without any private source.

## Transient artifact delivery

`build-interactive-diagram` is a producer and `serve-artifacts` is the shared
delivery layer. They communicate through a directory plus the host's JSON CLI,
never cross-skill Python imports. This keeps future producers independent from
server implementation details and leaves a stable seam for a later MCP adapter.

The host is a local-first, standard-library background service backed by private
OS-native state. It defaults to loopback and can bind to one explicitly reviewed
private IPv4 interface; wildcard listeners remain forbidden. Static bundles are
validated and copied atomically under random TTL-bound IDs. An optional proxy accepts
only already-running loopback HTTP targets; the host never runs builds or applications.

Remote access is a replaceable adapter boundary: SSH forwarding, direct private
LAN or VPN binding, and an existing reverse proxy all use the same host contract.
Tailscale Serve is one optional adapter whose preview-first setup owns one path,
preserves unrelated handlers, and never enables public Funnel access. Durable
documentation and cloud publication remain separate owning-repository workflows.

## Installation ownership

The installer resolves the selected harness home at runtime and stores ownership
under `<agent-home>/.agent-kit/state.json`. State records the exact content digest,
version, destination, and recoverable trash deployments. POSIX state directories
and files use `0700` and `0600`.

Install and update refuse symlinked resources, unowned destinations, and content
drift. Update stages and verifies a complete copy before moving the previous owned
deployment into trash. Uninstall also moves rather than deletes. Rollback selects
only an owned recorded deployment and accepts no caller-controlled source path.

Installation never invokes a skill permission bootstrap. This separation keeps a
general repository installer out of automatic permission lists and makes each
permission grant independently reviewable and removable.

## Validation

The canonical check validates catalog/resource parity, skill frontmatter, Codex
metadata, evaluation JSON, local Markdown links, generated-file hygiene, Python
compilation, and unit tests. It snapshots Git status before and after execution to
detect validation side effects.

Release packaging uses fixed timestamps, sorted paths, stable permissions, and a
single Linux release job. It emits standalone skill archives, per-skill plugin
archives, and one marketplace archive. Bundles include the repository license and
third-party notices, and one `SHA256SUMS` covers every archive.

## Trust boundaries

Automatic permission eligibility is defined in `policies/permission-boundary.md`.
The catalog documents sensitivity and setup requirements but does not itself
grant trust. Agent instructions, GitHub branch controls, pinned Actions, code
ownership, tests, and human review provide independent layers.
