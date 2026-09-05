---
name: verify-project
status: backlog
created: 2026-09-05T19:50:10Z
progress: 0%
prd: .claude/prds/verify-project.md
github: (will be set on sync)
---

# Epic: verify-project

## Overview

Deliver a self-contained local verifier that binds exact current project state,
resolves optional hierarchical `VERIFY.md` policy, freezes a bounded authorized
command plan, records mutation-safe execution evidence, and returns canonical
completion, outcome, and next-action state. Stabilize the standalone contract
before adding an optional target-bound `review-and-fix` adapter.

## Architecture Decisions

- Verify only current-filesystem combined working-tree or explicit path targets
  in v1; represent project scope as explicit `.`.
- Use repository-only plain-Markdown `VERIFY.md` guidance with root-to-nearest
  applicability, additive defaults, explicit scoped replacement, and committed
  `HEAD` trust for Git working-tree verification.
- Layer caller intent, active agent policy, trusted verification guidance,
  project entry points, and related contract discovery without treating any
  repository content as execution authority.
- Separate canonical verification plans from canonical results. Bind both to a
  lead-owned target and authority context and derive identifiers, status, and
  executability mechanically.
- Run exact argv sequentially through normal agent tools. Do not ship a generic
  command executor or permission-obscuring wrapper.
- Protect complete visible source state while allowing only predeclared bounded
  disposable artifacts. Detect and report unexpected effects without cleanup.
- Require evidence coverage, not merely zero exit codes, for `pass`.
- Retain bounded redacted diagnostic evidence and full-output digests, never raw
  logs by default.
- Make fresh-context requirements consumer-owned. Direct use needs one lead;
  post-fix `review-and-fix` verification requires a fresh verifier.
- Keep `verify-project` and `review-and-fix` independently installable. Add the
  deterministic adapter only after the standalone schema and behavior stabilize.
- Run model-backed behavioral evaluations locally and explicitly; hosted CI
  checks only deterministic artifacts and stored evidence.

## Technical Approach

- Initialize `skills/verify-project/` with concise runtime instructions, Codex
  metadata, progressive-verification guidance, `VERIFY.md` semantics, plan and
  result authoring references, two canonical schemas, and standard-library
  resolver/finalizer helpers.
- Build a resolver that freezes combined working-tree or explicit current paths,
  related bounded context, trusted guidance chains, caller intent, freshness,
  run caps, and command-authority provenance.
- Build a plan helper that accepts only semantic relevance and claim mappings,
  then injects lead-owned authority, normalizes exact argv and effects, derives
  stable IDs/fingerprints, and rejects scope or authority forgery.
- Build a result helper that binds the frozen plan, validates per-command
  evidence and before/after snapshots, derives claim coverage and state axes,
  and renders human output only from canonical JSON.
- Execute planned commands through visible agent tool calls and record bounded
  evidence into the lead-owned run context; keep command output inert.
- Extend hierarchy conformance tests without introducing a shared runtime
  dependency between installed skills.
- Add a behavioral suite with fixed adapters and hidden deterministic graders,
  then obtain fresh local evidence for representative success and failure cases.
- Add a `review-and-fix` profile and deterministic adapter only after standalone
  behavior is frozen and proven.
- Update catalog, grouped plugin, docs, compatibility, packaging, changelog, and
  release tracking as implementation lands.

## Implementation Strategy

1. Freeze target, guidance, authority, plan, result, status, and effect contracts.
2. Implement target and guidance resolution independently from semantic planning.
3. Implement deterministic plan/result finalization and mutation binding.
4. Author the agent workflow and public integration surfaces against the frozen
   contracts.
5. Prove boundaries with deterministic tests before model-backed evaluations.
6. Stabilize standalone behavioral evidence before adding the downstream adapter.
7. Run full packaging, cross-platform validation, fresh exact-head review, and
   gated delivery.

## Task Breakdown Preview

- 001: Define the standalone skill skeleton and canonical contracts.
- 002: Implement current-state target and `VERIFY.md` resolution.
- 003: Implement plan, snapshot, result, and rendering helpers.
- 004: Author the progressive verifier workflow and repository integration.
- 005: Add deterministic boundary and hierarchy-conformance tests.
- 006: Add executable behavioral evaluations and fresh local evidence.
- 007: Integrate canonical verification with `review-and-fix`.
- 008: Complete compatibility, packaging, review, and delivery.

## Dependencies

- Accepted `.claude/prds/verify-project.md`.
- Existing review hierarchy behavior and deterministic conformance fixtures.
- Existing behavioral-evaluation harness and local fresh-agent runner.
- Existing `review-and-fix` canonical run and validation surfaces.
- Repository catalog, grouped plugin, packaging, documentation, and release
  conventions.

## Success Criteria (Technical)

- Every PRD criterion maps to deterministic tests or retained, target-bound
  local behavioral evidence.
- Resolver and helpers fail closed across Linux and Windows path, alias,
  snapshot, mutation, malformed-input, limit, authority, and output boundaries.
- Fresh agents produce canonical evidence that passes hidden graders for
  relevant success, irrelevant green checks, failure, unavailable checks,
  hierarchical guidance, command injection, and mutation cases.
- Standalone packages contain all runtime resources and import no repository-only
  code or other skill.
- `review-and-fix` accepts only a fresh, independently validated, target-matched
  canonical pass and retains an accurate standalone fallback.
- Canonical and hosted validation never invokes an agent, paid model, provider
  API, or external service.

## Estimated Effort

Eight bounded tasks, approximately 48 hours total. Resolver, result-helper, and
workflow surfaces can proceed in parallel after the contract task. Boundary
tests, behavioral evidence, consumer integration, and delivery remain gated.

## Tasks Created

- [ ] 001.md - Define skill skeleton and canonical contracts (parallel: false)
- [ ] 002.md - Implement current-state target and VERIFY guidance resolver (parallel: true)
- [ ] 003.md - Implement plan, snapshot, result, and rendering helpers (parallel: true)
- [ ] 004.md - Author verifier workflow and repository integration (parallel: true)
- [ ] 005.md - Add deterministic and hierarchy-conformance coverage (parallel: false)
- [ ] 006.md - Add behavioral evaluations and fresh local evidence (parallel: false)
- [ ] 007.md - Integrate verify-project with review-and-fix (parallel: false)
- [ ] 008.md - Validate, review, and deliver the capability (parallel: false)

Total tasks: 8
Parallel tasks: 3
Sequential tasks: 5
Estimated total effort: 48 hours
