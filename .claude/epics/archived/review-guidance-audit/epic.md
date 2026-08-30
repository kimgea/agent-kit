---
name: review-guidance-audit
status: completed
created: 2026-08-30T11:28:49Z
updated: 2026-08-30T12:07:24Z
progress: 100%
prd: .claude/prds/review-guidance-audit.md
github: (not synced)
---

# Epic: review-guidance-audit

## Overview

Deliver a portable analysis-only skill that audits hierarchical `REVIEW.md`
guidance and emits deterministic human and JSON recommendations.

## Architecture Decisions

- Keep the skill independently installable with a bounded current-filesystem
  resolver and a separate result finalizer/renderer.
- Bind agent-authored analysis to resolver-owned scope and provenance.
- Nest harness proposals inside guidance recommendations so general harness
  auditing cannot leak into scope.
- Use agent judgment for context quality in v1 while reporting deterministic
  word, byte, and inheritance metrics.

## Technical Approach

- Add `skills/review-guidance-audit/` with runtime instructions, a rubric,
  canonical schema, context resolver, result helper, and Codex metadata.
- Add unit and boundary tests plus behavioral evaluation cases.
- Update the catalog, plugin grouping, public documentation, architecture, and
  release notes.

## Implementation Strategy

1. Establish the contracts and deterministic helpers.
2. Implement the agent workflow and output model.
3. Integrate documentation, catalog, tests, and evals.
4. Run focused, canonical, and fresh-agent validation.

## Task Breakdown Preview

- 001: Implement scope and guidance resolution.
- 002: Implement canonical result validation and rendering.
- 003: Author the skill workflow, documentation, catalog, and dogfood policy.
- 004: Add unit tests, evals, forward tests, and complete delivery validation.

## Dependencies

- Existing repository catalog, packaging, and validation conventions.
- Existing `project-review` hierarchy semantics as behavioral precedent, not a
  runtime dependency.

## Success Criteria (Technical)

- All PRD success criteria pass locally and in the repository validation matrix.
- Packaged skill contains every runtime dependency and no repository-only code.
- A fresh agent produces schema-valid analysis for realistic fixtures.

## Estimated Effort

One focused feature branch with four tightly coupled implementation slices.
