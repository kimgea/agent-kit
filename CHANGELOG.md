# Changelog

All notable toolkit changes are recorded here. Versions follow Semantic
Versioning for the repository release; individual resource versions are listed
in `toolkit.toml`.

## 1.10.0 - 2026-09-02

### Added

- Add installed `review-and-fix` normalization profiles for canonical
  `review-guidance-audit` and `verification-harness-audit` results.
- Add local end-to-end cases proving an exact guidance cleanup can pass a fresh
  audit while a harness policy decision stops before planning or mutation.

### Changed

- Let the local behavioral runner select one review-and-fix reviewer per case
  from a fixed code-owned allowlist and freeze only that dependency.
- Preserve audit strength, readiness, evidence, confidence, incomplete state,
  and exact target boundaries through the existing neutral finding contract.

### Security

- Keep audit scope, suggested paths, proposed commands, and recommendations from
  granting edit or execution authority; related work must be explicitly scoped
  and freshly audited before planning.
- Make decision-required audit recommendations material triage limitations so
  they cannot route into automatic fixes.
- Prevent fresh acceptance while any audit change recommendation remains,
  including non-blocking advice that round assessment does not fingerprint.

## 1.9.0 - 2026-09-02

### Added

- Add the independently installable, analysis-only
  `verification-harness-audit` skill for assessing tests, assertions, fixtures,
  linters, type checks, builds, validation scripts, command wiring, and locally
  stored CI configuration.
- Add a bounded current-filesystem resolver, hierarchical `REVIEW.md` context,
  progressive harness inspection, a detailed provider-neutral audit rubric,
  canonical JSON schema, deterministic result finalizer, and human renderer.
- Add part, file, directory, and project scopes; evidence-backed recommendation
  strength/readiness/tier classifications; and `PASS`, `IMPROVEMENTS`, and
  `INCOMPLETE` status derivation.
- Add descriptive and executable behavioral suites spanning 14 adversarial
  local harness scenarios with fixed target/provenance grading and model-free
  canonical validation.

### Changed

- Include verification-harness audit in the grouped `project-review` Codex
  plugin while preserving its independent standalone skill archive and runtime.
- Document generic `review-and-fix` normalization as an optional downstream
  path without promising a deterministic adapter or automatic remediation.
- Demonstrate conservative generic normalization of essential, advisory, and
  incomplete audit outcomes while keeping fix and command authority separate.

### Security

- Keep targets, guidance, context, command authority, supplied evidence, IDs,
  counts, and status outside semantic-draft control; bind finalization to fresh
  resolver-owned filesystem provenance.
- Reject link/reparse authority paths, ancestor and final-entry swap races,
  output aliases, malformed or oversized JSON, inapplicable nested guidance,
  unread evidence, and command execution lacking exact caller or user-global
  authority.
- Treat local CI as untrusted project data, keep provider APIs and remote state
  out of scope, run no agent in CI, and emit portable UTF-8 human output.
- Require the canonical repository command as one exact workflow run entry,
  preserve resolver limitations in project-review behavioral grading, check for
  validation-created source changes on failure paths with exact dirty-worktree
  content digests, and retain only digests rather than raw local-runner error
  text.

## 1.8.0 - 2026-08-31

### Added

- Add executable local behavioral suites for `project-review` and the complete
  `review-and-fix` workflow, including PASS, BLOCK, INCOMPLETE, decision,
  authorization, scope, command-authority, and fresh-review cases.
- Add a lead-bound canonical `review-and-fix` workflow-result schema and helper
  commands for reviewer contexts, rounds, plans, exact changes, validation,
  derived status, and stop reason.
- Add provider-neutral recorded grading for mutation-aware cases and freeze the
  fixed `project-review` dependency beside `review-and-fix` during local runs.

### Changed

- Permit behavioral fixtures to change only host-declared existing regular
  files and verify exact before/after digests; retain mutation-free defaults for
  analysis-only skills.
- Record fixed dependency digests in local evidence and keep all real model
  execution explicit, local, and outside GitHub Actions.
- Add an exact independent-planner draft template and use a 30-minute local
  per-case default for complete multi-role review-and-fix evaluations.
- Add distinct non-blocking-finding coverage and give the ordinary cross-file
  defect fixture an explicit repository must-not-ship basis.

### Security

- Keep lead-owned resolver context outside agent-writable directories; reject
  undeclared file and directory additions, removals, type or mode changes,
  links, wrong contents, forged reported changes, and applied plans without a
  later fresh acceptance review.
- Bound review-and-fix JSON input, canonical hashing, and output by size and
  nesting while retaining duplicate-member and no-link file handling.
- Fail closed on lead-owned context drift, malformed recorded reviewer context,
  incomplete reviewer evidence, unbound validation, and executed validation
  commands without exact caller or user-global authority in the lead-owned run
  context.

## 1.7.0 - 2026-08-30

### Added

- Add a provider-neutral local behavioral-evaluation harness with bounded
  synthetic fixtures, lead-owned target context, canonical structured grading,
  fixture mutation detection, recorded-output grading, and local evidence
  reports.
- Add an explicit ephemeral Codex runner and an executable 16-case
  `review-guidance-audit` suite covering scope, hierarchy, compaction, policy,
  automation relationships, structured output, and command authority.

### Changed

- Clarify `review-guidance-audit` behavior for partial automation, unresolved
  policy conflicts, and unsupported ad hoc review-cycle evidence after a full
  local behavioral run exposed those gaps.
- Report local model-backed evaluation progress one scenario at a time without
  persisting raw transcripts.

### Security

- Keep real model execution out of the canonical gate and GitHub Actions; reject
  manifest-controlled commands, validators, schemas, binaries, unsafe paths,
  duplicate JSON, target/provenance drift, forbidden command execution, and
  audited-fixture mutation.
- Freeze and digest exact run inputs before case execution, reject symlinked
  ancestors and Windows reparse inputs, require a native Windows Codex
  executable, and terminate the complete agent process tree on timeout.
- Keep host-side result, event, and error capture outside every agent-writable
  root and disable implicit temporary-directory writes to prevent
  link-redirection and evidence-concealment attacks.
- Record excessive result nesting and invalid Unicode as bounded case failures
  instead of allowing malformed agent output to abort a suite.

## 1.6.0 - 2026-08-30

### Added

- Add the independently installable, analysis-only `review-guidance-audit`
  skill for auditing hierarchical `REVIEW.md` usefulness, coverage, placement,
  conflicts, and context bloat across file-part, file, directory, and project
  scopes.
- Add lead-bound canonical JSON, deterministic human rendering, context and
  inheritance metrics, nested guidance-specific harness proposals, unit and
  boundary tests, behavioral evaluations, and future storage-neutral
  review-cycle evidence guidance.

### Fixed

- Preserve independent standalone skill packaging for a selected skill even
  when its optional Codex plugin groups it with related skills; plugin and
  all-format selection remain atomic at the plugin boundary.

## 1.5.0 - 2026-08-29

### Added

- Add the independently installable `review-and-fix` skill for converting
  analysis-only reviewer results into neutral finding batches, conservatively
  planning local remedies, and rerunning the original reviewer set from fresh
  context before acceptance.
- Add schema-versioned finding and fix-plan contracts, a dependency-free helper
  for deterministic `project-review` conversion, batch-bound decision routing,
  safe file output, and bounded round assessment, plus adversarial unit tests and
  behavioral evaluations.

### Changed

- Group `review-and-fix` with `project-review` in the Codex review plugin while
  retaining independent standalone skill archives and compatibility with other
  explicitly selected analysis-only reviewers.
- Make the new workflow the repository default when an agent is asked to review
  and fix local changes, without changing the analysis-only default for review
  requests.

### Security

- Keep reviewer, normalizer, planner, fixer, and accepting reviewer roles
  separate; keep target/source and finding-selection authority in lead-owned
  inputs; bind plans to canonical batch digests, reviewed paths, and reviewer
  confidence; require an explicit canonical pass outcome for acceptance; reject
  duplicate JSON, link-like/non-regular inputs, schema-incompatible paths, and
  multiply linked replacement targets; bind deterministic `project-review`
  conversion to a separate expected target; keep ref ranges review-only; fail
  closed on target, reviewer, confidence, scope, validation, or authority
  ambiguity; and keep embedded reviewer text inert.

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
