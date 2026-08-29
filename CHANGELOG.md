# Changelog

All notable toolkit changes are recorded here. Versions follow Semantic
Versioning for the repository release; individual resource versions are listed
in `toolkit.toml`.

## 1.4.0 - 2026-08-29

### Added

- Add the independently installable `project-review` skill and focused plugin
  for bounded, analysis-only reviews under root and nested `REVIEW.md` guidance.
- Add canonical schema-versioned JSON findings with deterministic human
  rendering, trusted-base rule provenance, coverage, limitations, and stable
  finding fingerprints for future publisher or fix-loop consumers.
- Dogfood the review hierarchy with repository-wide and project-review-specific
  policies, and make `project-review` the default method for agent reviews of
  this repository unless the caller explicitly chooses another method.

### Security

- Keep reviewed changes from supplying their own reviewer, keep repository
  guidance from authorizing commands or weakening its own review, reject escaped
  or link-like targets and guidance, and make static inspection the default
  unless the caller or bounded user-global policy grants verification authority.
- Escape untrusted controls and HTML in human reports, preserve old and new rule
  chains across renames, and fail closed when scope or guidance is incomplete.

## 1.3.1 - 2026-08-17

### Fixed

- Exclude generated cache directories and transient file suffixes consistently
  from skill hashing, direct installation, and release packaging so ignored local
  artifacts cannot enter deployments or archives.
- Preserve ownership checks for v1.3.0 installations and rollback records that
  contain standalone generated files.

### Changed

- Retire the redundant owner-only update ruleset and rely on repository write
  access for merge authority, while preserving the no-bypass pull-request,
  required-CI, linear-history, and review-thread protections on `main`.
- Treat an implementation or delivery request as authorization for its ordinary
  branch, pull-request, independent-review, and clean-merge lifecycle without
  repeated merge confirmations.

### Security

- Keep repository write access limited to `kimgea` and explicitly owner-controlled
  agent identities; external contributors may open pull requests but cannot merge.

## 1.3.0 - 2026-08-16

### Added

- Add the `serve-artifacts` skill: a dependency-free loopback host for expiring,
  revocable static web bundles and explicitly selected local HTTP applications.
- Add the `build-interactive-diagram` skill with a responsive, accessible,
  framework-free starter and behavioral quality contract.
- Add provider-neutral remote access through SSH forwarding, an exact private
  interface, or an existing reverse proxy; keep Tailscale Serve as an optional
  preview-first adapter and support reserve-before-build framework base paths.

### Security

- Default the host to loopback, require explicit confirmation and one exact IPv4
  interface for direct remote access, reject wildcard listeners, validate and
  privately copy bundles, bound files, responses, and TTLs, and expose no
  unauthenticated HTTP management surface.
- Restrict proxy targets to explicit loopback HTTP services and preserve unrelated
  Tailscale routes through exact, owned, preview-first setup and removal.
- Refuse cleanup through symlinked or reparse-point content paths, retain registry
  state when owned copies cannot be removed, revalidate live Tailscale route
  ownership before removal, and ignore ambient HTTP proxies for loopback targets.

### Changed

- Add the first reviewed grouped plugin, `artifacts`, while keeping both contained
  skills available as independent standalone archives.
- Require a separate agent to review materially updated pull requests before the
  owner merge decision, with a new exact-head review after every corrective push.

## 1.2.0 - 2026-08-14

### Added

- Add deterministic per-skill Codex plugin bundles and a generated Agent Kit
  marketplace while preserving standalone skill archives.
- Add the `agent-context` skill, a read-only resolver, schemas, private context
  repository templates, and exact project path or Git remote mappings.
- Add layered public, user, profile, domain, repository, and explicit session
  context with per-value provenance and deterministic precedence.

### Security

- Require context sources to be explicitly registered, reject symlinked sources
  and literal values in `secret_refs`, and keep repository instructions and
  skill safety invariants outside the context override boundary.
- Keep private context outside this public repository and avoid automatic global
  configuration, permission grants, discovery, caching, or mutation.

### Changed

- Extend the catalog to schema 2 with explicit plugin membership and marketplace
  metadata, and make the release workflow package every supported format.
- Place the generated marketplace catalog at the Codex repo-marketplace path
  `.agents/plugins/marketplace.json` so an extracted archive can be registered
  directly with the Codex CLI.

## 1.1.1 - 2026-08-10

### Fixed

- Import the shared repository contract through Claude Code's native
  `@AGENTS.md` form and validate that the import remains present.
- Make the fixed-store `todo_safe.py --help` output describe the safe dispatcher
  instead of incorrectly claiming support for custom `--dir` paths.
- Replace stale conditional wording with the Windows CI evidence already
  available for `tool-audit`.

### Documentation

- Add a copy-paste tagged-checkout path for installing selected skills and point
  users to the per-skill release archives and checksums.

## 1.1.0 - 2026-08-08

### Security

- Restart the public Git history from the reviewed current tree so removed
  third-party imports with incomplete immutable provenance are not reachable
  from the published repository.
- Preserve the predecessor history only in a private recovery archive and
  replace its historical notice with a present-tree provenance contract.

### Changed

- Establish 1.1.0 as the first release in the clean public history. Skill runtime
  behavior and individual resource versions are unchanged from 1.0.4.

## 1.0.4 - 2026-08-07

### Changed

- Keep `todo-capture` and `tool-audit` skill bodies focused on everyday runtime
  decisions and safety invariants.
- Route profile-specific tool-audit interpretation through a direct progressive-
  disclosure reference.
- Consolidate skill extension, compatibility, and content-placement guidance in
  maintainer documentation.

## 1.0.3 - 2026-08-07

### Security

- Restrict default-branch updates to pull-request merges performed by the exact
  `kimgea` user while preserving the separate no-bypass PR and CI protections.
- Refuse repository-configuration writes unless `gh-api-get` confirms that the
  active GitHub identity is the pinned repository owner.

## 1.0.2 - 2026-08-07

### Fixed

- Archive the completed hardening epic and enforce active-versus-archived epic
  state in the canonical validator.

## 1.0.1 - 2026-08-06

### Fixed

- Enable Dependabot vulnerability alerts before requesting security updates in
  the fixed GitHub repository hardening sequence.
- Validate committed CCPM status values and task-derived epic progress.

## 1.0.0 - 2026-08-04

### Added

- Repository-wide Codex and Claude Code operating contracts.
- A reviewed machine-readable resource catalog.
- Cross-platform validation, diagnostics, installation, removal, and release
  packaging through `scripts/agent_kit.py`.
- Security policy, license, provenance notices, ownership rules, evaluations,
  reusable instruction/template/policy resources, and harness adapters.
- Unified Linux and Windows CI plus immutable release artifacts.

### Changed

- `grill-me` now uses progressive disclosure and includes Codex metadata,
  maintainer documentation, and evaluation cases.
- Toolkit installation is separate from permission setup; both are dry-run by
  default where they can mutate user state.
