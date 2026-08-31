---
name: expand-behavioral-evals
status: in-progress
created: 2026-08-31T06:59:14Z
updated: 2026-08-31T16:09:36Z
progress: 75%
prd: .claude/prds/expand-behavioral-evals.md
github: (not synced)
---

# Epic: expand-behavioral-evals

## Overview

Adopt executable local behavioral evaluation for `project-review` and for the
complete bounded `review-and-fix` workflow.

## Architecture Decisions

- Keep suite orchestration under repository `scripts/` and `evals/`.
- Reuse installed skill validators and add fixed adapters in the harness; suite
  manifests cannot choose executable paths or commands.
- Add a canonical reporting contract to `review-and-fix`, while preserving its
  existing batch, plan, and round artifacts as the authority for decisions.
- Let the host own target resolution, dependency selection, expected mutation,
  and final fixture comparison.
- Permit only exact declared mutations inside disposable fixtures and require
  fresh reviewer evidence before a successful fix result.

## Technical Approach

- Generalize fixed result-contract metadata, context resolution, authority
  binding, and skill-dependency snapshots.
- Add `project-review/v1` and `review-and-fix/v1` adapters.
- Define and validate a bounded review-and-fix workflow result.
- Add synthetic suites and structural hidden assertions for both skills.
- Expand deterministic runner tests for mutable cases and dependency isolation.

## Implementation Strategy

1. Establish durable contracts and generic fixed-adapter seams.
2. Add and prove the project-review suite.
3. Add the end-to-end review-and-fix contract, mutation policy, and suite.
4. Validate, forward-test locally, independently review, and deliver.

## Task Breakdown Preview

- 001: Add fixed project-review adapter and executable suite.
- 002: Add canonical review-and-fix workflow result and mutation contract.
- 003: Add end-to-end review-and-fix fixtures and grading.
- 004: Integrate documentation, tests, versions, and delivery evidence.

## Dependencies

- Completed `local-behavioral-evals` epic.
- Stable project-review and review-and-fix canonical helpers.

## Success Criteria (Technical)

- Every PRD success criterion is covered by deterministic tests or explicit
  local behavioral evidence.
- No canonical or hosted validation path invokes a model.
- Installed skill packages remain self-contained.

## Estimated Effort

One focused feature branch with four sequential tasks because the suites share
the fixed-adapter and mutation-policy implementation.

## Tasks Created

- [x] 001.md - Add project-review behavioral adapter and suite (parallel: false)
- [x] 002.md - Add review-and-fix workflow result contract (parallel: false)
- [x] 003.md - Add review-and-fix end-to-end suite (parallel: false)
- [ ] 004.md - Integrate, validate, and deliver (parallel: false)

Total tasks: 4
Parallel tasks: 0
Sequential tasks: 4
Estimated total effort: 18 hours
