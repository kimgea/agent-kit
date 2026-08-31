---
name: local-behavioral-evals
status: completed
created: 2026-08-30T20:24:19Z
updated: 2026-08-30T22:06:10Z
progress: 100%
prd: .claude/prds/local-behavioral-evals.md
github: (not synced)
---

# Epic: local-behavioral-evals

## Overview

Deliver a reusable local behavioral-evaluation harness and prove it first with
the `review-guidance-audit` skill.

## Architecture Decisions

- Keep evaluation infrastructure under repository `scripts/` and `evals/`, not
  inside installed skills.
- Separate deterministic check/grade operations from explicit model-backed
  execution.
- Use fixed runner and validator adapters rather than manifest-supplied command
  execution.
- Grade canonical JSON with deterministic structural assertions and preserve
  exact-run provenance.
- Adopt executable evaluation incrementally, leaving older descriptive suites
  backward compatible.

## Technical Approach

- Define a versioned executable-suite manifest and bounded fixture layout.
- Implement manifest validation, fixture materialization and hashing, canonical
  result validation, assertions, evidence records, and safe persistence.
- Add recorded-output grading and one fixed Codex CLI adapter.
- Convert representative `review-guidance-audit` cases into synthetic fixtures
  and structured expectations, then cover the remaining cases.
- Integrate deterministic suite validation into the existing canonical gate.

## Implementation Strategy

1. Establish contracts and deterministic core behavior.
2. Add the explicit Codex adapter and isolation checks.
3. Adopt the harness for `review-guidance-audit`.
4. Validate locally, forward-test, review, and deliver through a pull request.

## Task Breakdown Preview

- 001: Define and implement the provider-neutral harness core.
- 002: Add the fixed opt-in Codex runner and isolation controls.
- 003: Build the executable `review-guidance-audit` suite.
- 004: Integrate documentation, validation, and delivery evidence.

## Dependencies

- Existing skill catalog and canonical validation framework.
- Existing `review-guidance-audit` canonical result helper and schema.
- Local Codex CLI for the explicit forward-test only.

## Success Criteria (Technical)

- All PRD success criteria pass locally and in deterministic hosted CI.
- No installed skill gains a runtime dependency on the harness.
- A fresh local Codex run produces a bounded, validated evidence report.

## Estimated Effort

One focused feature branch with four sequential, tightly coupled tasks.

## Tasks Created

- [x] 001.md - Implement behavioral evaluation core (parallel: false)
- [x] 002.md - Add opt-in Codex runner (parallel: false)
- [x] 003.md - Add executable review-guidance-audit suite (parallel: false)
- [x] 004.md - Integrate, validate, and deliver (parallel: false)

Total tasks: 4
Parallel tasks: 0
Sequential tasks: 4
Estimated total effort: 16 hours
