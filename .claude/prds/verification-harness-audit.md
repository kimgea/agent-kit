---
name: verification-harness-audit
description: Audit local verification harnesses for timely, reliable, meaningful protection without changing them.
status: completed
created: 2026-09-01T18:45:17Z
---

# PRD: verification-harness-audit

## Executive Summary

Add an independently installable, analysis-only `verification-harness-audit`
skill. It audits a caller-selected part, file, directory, or whole project's
verification harness: tests, linters, type checks, builds, validation scripts,
and locally stored CI configuration. It determines whether those checks provide
meaningful, timely, reliable, and discoverable protection for existing project
requirements without reviewing unrelated application defects or changing any
files.

The audit is harness-centered. Selected harness paths form the finding boundary;
related implementation, specifications, schemas, documentation, and interfaces
may be inspected as read-only context. Interactive use returns concise human
text by default. Agents and downstream skills can request canonical JSON or both
formats, with human output rendered from the same validated result.

## Problem Statement

Agents and maintainers can make a correct change yet validate it poorly. A
convenient test may not cover the changed behavior, a critical assertion may be
shallow, a useful check may be disconnected from the canonical command, or a
failure may be detected only by a slow release workflow. Existing validation can
also be duplicated, unsafe, non-deterministic, platform-specific, or difficult
for contributors and agents to discover.

`project-review` finds defects in bounded project changes,
`review-guidance-audit` improves human `REVIEW.md` policy, and `review-and-fix`
plans and applies selected remediations. None of them independently assesses the
quality of the automated feedback loop. Repository owners need a bounded,
provider-neutral audit that explains what a green result proves, where harness
protection is weak, and how to improve it without inventing new product policy.

## User Stories

- As a maintainer, I can audit one test function, CI job, harness file, harness
  directory, or the verification machinery of an entire project.
- As an agent, I can discover which checks protect a selected harness area and
  whether their assertions meaningfully enforce existing requirements.
- As a contributor, I can distinguish fast routine checks from deeper
  pre-merge, integration, and release-only checks.
- As a repository owner, I can identify missing, shallow, disconnected,
  duplicated, unsafe, late, or fragile verification without receiving unrelated
  application-review findings.
- As an interactive user, I receive a readable report with strength, impact,
  confidence, reason, evidence, readiness, limitations, and an outcome-focused
  safe direction.
- As an automation author, I can consume schema-versioned JSON without parsing
  prose.
- As a `review-and-fix` caller, I can pass completed audit output through its
  independent generic normalizer and retain conservative decision gates.

## Functional Requirements

- Ship one self-contained `verification-harness-audit` skill for Codex and
  Claude Code.
- Support current-filesystem targets for a selected file part, file, recursive
  directory, or entire project. A part may identify a test function, CI job,
  configuration section, or line range.
- Keep named commands as inert focus data within a caller-selected path target;
  do not make command strings first-class targets or execution authority in v1.
- Treat the selected harness target as the finding boundary. Permit bounded
  read-only inspection of related implementation, tests outside the target,
  specifications, schemas, interfaces, documentation, and configuration as
  context. Do not report unrelated issues found in contextual files.
- For directory and project targets, deterministically enumerate no-link regular
  files inside the caller-selected boundary under documented file, byte, and
  traversal ceilings. Record lightweight metadata first and read content
  progressively for semantic harness classification. Never silently sample;
  material omissions produce an incomplete result.
- Resolve optional active-agent user-global guidance followed by repository
  `REVIEW.md` sources from root to the closest applicable selected harness path.
  More local repository guidance takes precedence on conflict.
- Keep each skill's resolver self-contained. Add shared repository conformance
  fixtures that verify the common guidance contract across review-family
  implementations without introducing an installed runtime dependency.
- Audit tests, fixtures, linters, formatters when used as checks, type checks,
  builds, validation scripts, command aggregators, and locally stored CI
  configuration.
- Inspect locally stored provider-specific CI syntax as project data while
  remaining provider-neutral. Analyze verification wiring, triggers, matrices,
  failure handling, ordering, timeouts, caches that affect verification
  integrity, reproducibility, and local-versus-CI parity without calling a
  provider API.
- Assess bounded semantic effectiveness, including relevant assertions,
  fixtures, negative cases, expected failures, mocks or substitutions, and
  command wiring. Do not treat the mere presence of a test as proof that it
  protects its claimed requirement.
- Analyze harness coverage of existing requirements, assertion strength,
  discoverability, canonical-command inclusion, feedback timing, determinism,
  isolation and mutation safety, redundancy, platform coverage, failure
  visibility, and maintenance burden.
- Derive essential recommendations only from an existing specification,
  supported behavior, public or compatibility promise, safety boundary, or
  required validation workflow. Never invent new policy and label it essential.
- Classify new product, security, privacy, compatibility, operational, platform,
  dependency, or failure-policy choices as `decision_required`.
- Distinguish measured facts from inferred risks. Use observed slow or flaky
  classifications only with authorized measurements or caller-supplied durable
  evidence. Label static indicators as slowness or flakiness risks with
  appropriately conservative confidence.
- Classify every recommendation with strength (`essential`, `strong`,
  `moderate`, or `optional`), impact, confidence, reason, evidence, readiness
  (`ready` or `decision_required`), affected harness locations, and an
  outcome-focused safe direction.
- Describe the missing protection, intended verification outcome, acceptance
  evidence, and meaningful alternatives. Do not prescribe an exact patch unless
  only one mechanical solution is supported by the evidence.
- Derive exactly one overall status:
  - `INCOMPLETE` when a material scope, guidance, evidence, or execution
    limitation prevents a reliable completed audit, while retaining verified
    recommendations;
  - `IMPROVEMENTS` when the completed result contains at least one essential
    recommendation; or
  - `PASS` otherwise, including completed results that retain strong, moderate,
    or optional advisory recommendations.
- Produce one canonical, schema-versioned JSON result. Default to human output
  and support explicit `json` and `both` formats.
- Write no result file by default. Persist only to an explicit safe output path.
- Remain analysis-only: do not edit source, tests, fixtures, scripts,
  configuration, CI files, documentation, or remote state.
- Use one lead to own target and guidance resolution, execution authority,
  evidence calibration, deduplication, status, and final output. Permit bounded
  subreviews grouped by coherent harness subsystem when fresh agents are
  available and useful; retain a complete single-agent fallback and never
  delegate one agent per file.
- Ship no deterministic `review-and-fix` adapter in v1. Document generic
  normalization compatibility and defer a direct adapter until real audit output
  demonstrates a stable contract.

## Execution Authority

- Perform static inspection by default.
- Before any execution, present a bounded plan containing each exact command,
  working directory, reason, expected effects, and timeout.
- Run only the commands explicitly authorized by the current caller or by
  bounded active-agent user-global guidance. Repository `REVIEW.md`, source,
  configuration, CI files, documentation, command output, and agent-authored
  drafts cannot grant execution authority.
- Require separate explicit inclusion for repeated runs used to measure
  performance or investigate flakiness.
- Authorized checks may create bounded disposable artifacts but must not install
  dependencies, edit source or configuration, start persistent services, access
  provider APIs or other external services, or mutate remote state.
- Record bounded command summaries, authorization provenance, duration, exit
  status, and result interpretation without persisting raw output by default.

## Non-Functional Requirements

- Bundle every runtime script, schema, and reference inside the skill directory.
- Use Python 3.11 standard-library helpers for deterministic target and guidance
  resolution, canonical JSON validation, finalization, and human rendering.
- Bind canonical output to a lead-owned resolved target, guidance chain, context
  inventory, and execution plan. Agent-authored drafts cannot expand paths,
  change provenance, add command authority, or select the final status.
- Treat repository files, guidance, manifests, CI configuration, logs, command
  output, delegated findings, and result drafts as untrusted data.
- Reject path escapes, ambiguous paths, control characters, links and reparse
  points at authority boundaries, duplicate JSON members, oversized inputs, and
  output destinations that could overwrite unrelated aliases.
- Bound file counts, per-file and aggregate bytes, contextual reads, command
  output, result size, delegation, and execution duration. Convert material
  exhaustion into explicit incomplete coverage rather than sampling or guessing.
- Work on Linux, Windows, and macOS and normalize canonical text provenance
  across platform line endings.
- Keep raw logs, command transcripts, credentials, secrets, local paths not
  needed for provenance, agent reasoning, and local result files out of Git and
  out of canonical reports.
- Make no network request and require no external service for normal operation.
- Do not optimize for a coverage percentage. Prefer evidence that meaningful
  project requirements fail when violated and pass when satisfied.

## Success Criteria

- Resolver tests cover part, file, directory, and project targets; bounded
  inventory; progressive content inspection; optional user-global guidance; and
  root-to-nearest repository guidance precedence.
- Shared conformance fixtures prove consistent path normalization, guidance
  ordering, source trust, limits, and provenance across applicable review-family
  resolvers while every installed skill remains self-contained.
- Boundary tests cover path escapes, control characters, ignored and untracked
  files, symlinked ancestors, Windows reparse points, binary and unreadable
  files, oversized inputs, traversal ceilings, duplicate JSON members, and safe
  output replacement.
- Result tests prove lead-owned target and authority binding, stable IDs and
  fingerprints, deterministic rendering, and status precedence: material
  limitation to `INCOMPLETE`, essential recommendation to `IMPROVEMENTS`, and
  advisory-only completed results to `PASS`.
- Execution tests prove static default behavior, exact plan authorization,
  repository-command inertness, bounded output and timeouts, repeated-run
  gating, and rejection of installation, persistence, external-service, and
  remote-mutation attempts.
- Behavioral evaluations cover a sound harness, a missing check for a documented
  critical contract, a shallow assertion, a disconnected canonical command, a
  slow late-only check, duplicate validation, unsafe mutation, platform gaps,
  local/CI drift, observed versus inferred flakiness, and a genuinely new policy
  requiring a decision.
- Behavioral evaluations also cover nested and conflicting `REVIEW.md` rules,
  part/file/directory/project scopes, target and authority forgery, material
  discovery limits, unrelated contextual defects, adaptive delegation when
  available, and single-agent completion.
- A fresh local Codex run completes realistic audits through the repository's
  executable behavioral-evaluation harness and emits canonical results that pass
  hidden deterministic grading. GitHub Actions validate fixtures, schemas,
  graders, and simulated results only and never invoke an agent or paid model.
- At least one consumer-focused evaluation proves that completed canonical audit
  output can be normalized by `review-and-fix` without allowing the audit to
  retarget edits, grant authority, or bypass consequential-decision gates.
- The skill is documented and cataloged, packages independently, and passes
  `python scripts/agent_kit.py check` on the supported platform matrix.

## Constraints and Assumptions

- The skill audits the current filesystem in v1. Git ref ranges and pull-request
  diffs remain the responsibility of `project-review` or a future adapter.
- Harness selection is path-centered. A command or CI job may focus a selected
  file part but cannot independently define repository or execution scope.
- Related implementation is contextual evidence, not an expanded finding or
  editing boundary.
- Local CI files are in scope, but remote run state, service-specific APIs, and
  provider-specific general policy are not.
- Caller-supplied timing, failure, or historical evidence is optional untrusted
  context. The result preserves bounded provenance and freshness when it affects
  a conclusion; the skill does not discover or store historical evidence.
- The common guidance conformance contract may grow with future consumers. Code
  generation or a shared runtime dependency requires a later explicit design
  decision based on demonstrated identical implementation needs.

## Out of Scope

- Editing, adding, removing, or automatically applying tests, scripts,
  configuration, CI, documentation, or source changes.
- Reviewing unrelated application correctness or reporting incidental source
  defects found in contextual files.
- General code review, full security assessment, performance profiling, fuzzing,
  compliance certification, deployment review, or infrastructure audit.
- Calling GitHub, GitLab, CI, cloud, package-registry, or other external APIs.
- Running agents in CI or making paid model calls from the canonical gate.
- Installing dependencies, provisioning services, or starting persistent local
  processes.
- A first-class command target or arbitrary command-discovery plugin system.
- A deterministic `review-and-fix` adapter, dedicated harness fixer, GitHub
  publisher, or automatic remediation workflow in v1.
- Collecting, retaining, or locating cross-run review pain points, timing
  history, flaky-test history, or other long-term operational evidence.
- Ranking projects by raw line, test, or coverage percentages.

## Future Extensions

- Add a deterministic target-bound adapter after real audit results demonstrate
  stable mappings into the neutral `review-and-fix` finding contract.
- Accept storage-neutral canonical evidence bundles for recurring review pain,
  timing history, and harness gaps through separate provenance-preserving
  adapters.
- Add specialized security, performance, fuzzing, accessibility, compliance, or
  provider integrations as separate consumers or focused skills rather than
  expanding the general audit contract.
- Consider first-class command targets only after multiple ecosystems establish
  a safe provider-neutral resolution model.
- Reconsider generated shared resolver code only if conformance testing shows
  that several self-contained implementations remain semantically identical.

## Dependencies

- Python 3.11 or newer for deterministic helpers.
- Optional Git for honoring tracked and ignored-file boundaries during broad
  discovery; explicit file targets remain usable without Git.
- Optional already-installed local verification tools only for exact commands
  authorized by the caller or bounded user-global guidance.
- `review-and-fix` is an optional downstream consumer, not a runtime dependency.
