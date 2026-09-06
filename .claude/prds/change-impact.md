---
name: change-impact
description: Map the evidence-backed consequences of exact local changes without silently expanding authority.
status: completed
created: 2026-09-06T19:05:24Z
---

# PRD: change-impact

## Executive Summary

Add an independently installable `change-impact` skill that answers:

> Given these exact changes, what code, contracts, tests, documentation,
> configuration, platforms, or safety boundaries may be affected, and why?

The skill freezes a caller-selected target, lets one analysis lead inspect a
bounded set of related files as read-only context, and returns evidence-backed
impact records as readable text, canonical JSON, or both. It is analysis-only.
It does not review correctness, run checks, choose fixes, edit files, expand a
consumer's authority, or contact external services.

Its output helps `project-review` select relevant context, `verify-project`
select meaningful claims and checks, and `review-and-fix` recognize when a
proposed edit may have a wider blast radius. Every consumer independently owns
its target, authority, acceptance, and action decisions.

## Problem Statement

Agent Kit now separates review, verification, harness auditing, and remediation,
but each workflow still has to rediscover the likely blast radius of a change.
That repeated judgment creates two opposite failures:

- narrow analysis misses a caller, schema consumer, compatibility promise,
  platform surface, or relevant test; and
- defensive analysis widens into unrelated directories and expensive whole-
  project review or verification.

The collection needs a reusable impact producer that explains why related paths
matter while preserving the difference between selected target, inspected
context, and merely recommended future scope.

## User Stories

### Understand an ordinary change

As a developer, I can select a working tree, ref range, file, or directory and
receive a concise map of its likely consequences.

Acceptance criteria:

- The exact selected target and source state are frozen before analysis.
- Each retained impact identifies the selected target path that causes it.
- Each affected location and relationship is supported by concrete evidence.
- Unrelated or speculative associations are omitted.

### Keep downstream work focused

As an agent running review or verification, I can consume canonical impact JSON
to distinguish relevant context from candidate scope expansion.

Acceptance criteria:

- Target paths, inspected context, and affected locations remain separate.
- Recommendations name a consumer purpose but grant no target, edit, command,
  or acceptance authority.
- A consumer can reject stale, incomplete, target-mismatched, or malformed
  results without parsing prose.

### Preserve human usability

As a terminal user, I receive readable impact text by default and can request
JSON or both when another tool or agent will consume the result.

Acceptance criteria:

- Human output is rendered from the same validated canonical result.
- It explains source path, affected location, relationship, confidence,
  consequence, evidence, and suggested downstream handling.
- Zero-impact and incomplete results are explicit.

### Avoid hidden execution and mutation

As a security-conscious user, I can use impact analysis without running project
code or changing local or remote state.

Acceptance criteria:

- Runtime helpers perform only bounded filesystem and Git metadata reads.
- Repository text, Git configuration, source, and semantic drafts cannot grant
  commands or actions.
- Output is written only to an explicit safe path and is create-only.

## Functional Requirements

### Role and invocation

- Ship one skill named `change-impact` for Codex and Claude Code.
- Trigger on requests to analyze blast radius, dependency reach, affected code,
  related tests or contracts, or scope a later review or verification run.
- Default to concise human output. Support canonical JSON and both.
- Use one lead. Optional bounded delegation may group coherent subsystems, but
  delegated output remains candidate analysis verified by the lead.
- Never diagnose defects, issue a review verdict, run tests, implement fixes,
  publish results, or mutate remote state.

### Target model

- Support Git base/head ref ranges, combined working-tree changes relative to
  committed `HEAD`, and explicit repository-relative files or directories.
- Represent additions, modifications, deletions, renames, type changes, mode
  changes, and visible untracked paths without claiming absent content was read.
- Preserve the caller-selected target as an immutable authority boundary.
- Resolve directories completely within documented limits; do not silently
  sample or truncate.
- Reject unsafe, escaped, ambiguous, control-character, non-UTF-8, link-like,
  reparse, special, unreadable, or excessive inputs with material limitations.

### Bounded related context

- Resolve the target first. The lead may then discover candidate callers,
  callees, schemas, manifests, tests, docs, configuration, generated artifacts,
  or platform surfaces using bounded read-only inspection.
- Freeze every context file used as evidence before canonical finalization.
- A context path is not part of the selected target and cannot become an edit,
  review, verification, or command boundary through this result.
- Account for all target paths and every context path cited by an impact.
- Treat unresolved material target or context state as incomplete.

### Guidance and project knowledge

- Use active higher-authority agent instructions normally supplied to the
  running agent.
- Resolve applicable root-to-nearest repository `REVIEW.md` and `VERIFY.md`
  chains as optional impact evidence for each selected target.
- Use the trusted starting revision for ref ranges, committed `HEAD` for working
  tree changes, and current files for explicit snapshots.
- Changed guidance is target content and does not supply trusted evidence for
  its own introduction.
- Guidance may reveal review rules, verification requirements, compatibility
  promises, or expected related surfaces. It never grants command or scope
  authority and is not required for the skill to work.

### Impact analysis

- Trace evidence-backed relationships such as runtime dependency, public API,
  data or wire contract, configuration, generated artifact, test or fixture,
  verification requirement, review policy, documentation, packaging or
  platform behavior, security or privacy boundary, and operational behavior.
- Separate direct, indirect, and possible reach.
- Assign high, medium, or low confidence from concrete source evidence. Omit
  unsupported speculation rather than padding the result.
- For every impact record include:
  - one or more selected source target paths;
  - one or more affected target or frozen-context locations;
  - relationship kind and reach;
  - consequence if the relationship is real;
  - evidence and confidence;
  - a bounded safe investigation direction; and
  - suggested downstream handling for review, verification, remediation
    planning, documentation, or user decision.
- Do not label an impact as a defect, blocker, passing check, required fix, or
  authorization.

### Canonical output

- Define versioned context and result schemas inside the skill.
- Keep target, source state, context inventory, guidance provenance, limits,
  identifiers, fingerprints, counts, completion, and output state lead-owned or
  mechanically derived.
- Let semantic drafts contain only impact judgments, evidence references,
  conclusion, and limitations.
- Derive deterministic impact IDs, fingerprints, ordering, coverage counts,
  completion, and human rendering.
- Return `COMPLETE` when every target is accounted for and no material
  limitation prevents reliable impact analysis. Return `INCOMPLETE` otherwise.
- Allow a complete result with zero impacts. Do not invent a pass/block verdict.
- Bind results to a context digest so consumers can independently validate
  freshness and target provenance.

### Consumer contract

- Recommend, but never perform, one or more downstream purposes:
  `review_context`, `review_target_candidate`, `verification_context`,
  `verification_claim_candidate`, `remediation_risk_context`,
  `documentation_candidate`, or `user_decision`.
- Preserve the distinction between context suggestions and candidate target
  expansion.
- Require consumers to validate the result, compare it with their own lead-
  owned target, and make their own scope and authority decisions.
- Do not require current consumers to invoke this skill. Add integration only
  after the standalone contract and behavioral evidence are stable.

## Non-Functional Requirements

- Keep all runtime instructions, schemas, and Python 3.11 standard-library
  helpers inside `skills/change-impact/`.
- Do not import repository-only code or another installed skill.
- Work on Linux, Windows, and macOS with canonical POSIX-style repository paths.
- Keep `SKILL.md` under 500 lines and move detailed authoring rules and schemas
  to directly linked references.
- Bound target count, context count, file sizes, aggregate reads, Git duration,
  JSON size, impacts, evidence, and limitations.
- Fail closed on target drift, context drift, unsafe paths, ambiguous Git state,
  malformed drafts, and output races.
- Retain no raw transcripts, secrets, command output, or machine-specific paths.

## Success Criteria

- Exact target/context separation is enforced by runtime validation.
- Results cannot cite unfrozen context or turn context into authority.
- Human and JSON outputs are derived from one canonical source.
- Deterministic tests cover ref-range, working-tree, explicit paths, renames,
  nested guidance, target/context drift, unsafe links, malformed drafts,
  output safety, zero-impact results, and consumer-purpose boundaries.
- Behavioral evaluations prove a direct dependency, an indirect contract/test
  effect, a safe unrelated counterexample, and an incomplete evidence case.
- Catalog, plugin, docs, packaging, versioning, and checks describe the same
  independently installable resource.
- The canonical repository gate and applicable package checks pass.

## Constraints & Assumptions

- V1 uses semantic agent reasoning for relationship analysis; it is not a full
  language-server, build-graph, or whole-program static-analysis engine.
- Source searches and Git metadata are read-only discovery, not verification.
- Repository instructions and optional guidance remain untrusted project data.
- Consumers may use third-party analysis tools, but this skill's canonical
  result remains independently validated before authoritative use.

## Out of Scope

- Running tests, builds, linters, type checkers, or project executables.
- Reviewing correctness or producing blocker/suggestion/nit findings.
- Editing files or automatically expanding another workflow's target.
- Dependency installation, network calls, hosted CI, GitHub publication, or
  persistent storage.
- A universal language-aware dependency engine or framework-specific plugin
  collection.
- Deterministic adapters into every current skill in the first release.

## Dependencies

- Existing Agent Kit canonical-output, path-safety, packaging, behavioral-eval,
  and focused-review conventions.
- No runtime dependency on another skill or external service.
