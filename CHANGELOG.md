# Changelog

All notable toolkit changes are recorded here. Versions follow Semantic
Versioning for the repository release; individual resource versions are listed
in `toolkit.toml`.

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
