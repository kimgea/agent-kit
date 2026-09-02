---
name: review-audit-fix-integration
status: completed
created: 2026-09-02T09:12:50Z
updated: 2026-09-02T13:04:17+02:00
progress: 100%
prd: .claude/prds/review-audit-fix-integration.md
github: null
---

# Epic: review-audit-fix-integration

## Overview

Make `review-and-fix` a proven local consumer of the two canonical audit skills
without weakening independent normalization, target ownership, or decision
gates.

## Architecture Decisions

- Keep canonical JSON plus the neutral finding batch as the inter-skill seam.
- Keep producer-specific interpretation in a progressively disclosed runtime
  reference, not in the always-loaded core workflow.
- Use a fresh non-editing normalizer for both audit producers in v1.
- Extend behavioral evaluation only through fixed code-owned reviewer mappings;
  manifests cannot select executable paths.
- Keep fixer target authority separate from an audit's broader inspected scope.

## Technical Approach

### Runtime guidance

Add one reviewer-integration reference with common validation, target, outcome,
and rerun rules plus compact mapping tables for each audit producer. Link it from
the reviewer-selection and normalization sections of `SKILL.md`.

### Local behavioral harness

Allow review-and-fix cases to select one reviewer from a fixed internal allowlist.
Resolve and freeze that reviewer's canonical context while deriving the exact
neutral fix target independently. Materialize only reviewed skill dependencies
and bind their digests in retained evidence.

### Tests and evaluations

Add deterministic mapping tests and two realistic review-and-fix behavioral
cases: an intent-preserving guidance cleanup that may route automatically, and a
verification recommendation that must stop at a consequential decision. Keep
expectations hidden in suite assertions.

### Documentation and distribution

Align the skill guide, behavioral-eval guide, architecture, catalog versions,
changelog, packaging expectations, and tracking artifacts.

## Implementation Strategy

1. Lock runtime mappings and scope rules.
2. Add fixed reviewer-aware behavioral context resolution and tests.
3. Add synthetic fixtures, cases, graders, and local evidence.
4. Align distribution surfaces and complete independent review.

## Task Breakdown Preview

- Task 001: Runtime integration contract and documentation.
- Task 002: Fixed reviewer-aware behavioral runner support.
- Task 003: Mapping tests and behavioral cases.
- Task 004: Versioning, validation, independent review, and delivery.

## Dependencies

- Existing review-family canonical result helpers.
- Existing local behavioral evaluation runner.

## Success Criteria (Technical)

- Both producer outputs normalize conservatively and remain target-bound.
- `INCOMPLETE`, decision-required, and out-of-target cases fail closed.
- Ready routine guidance cleanup can complete only after a fresh audit pass.
- Suite manifests cannot select arbitrary helper paths or reviewer identities.
- Canonical local validation and all deterministic platform checks pass.

## Estimated Effort

- Size: M
- Hours: 8-12

## Tasks Created

- [x] 001.md - Define runtime reviewer integration guidance
- [x] 002.md - Extend fixed local behavioral reviewer resolution
- [x] 003.md - Add mapping tests and cross-skill behavioral cases
- [x] 004.md - Align releases surfaces and deliver through review

Total tasks: 4
Parallel tasks: 0
Sequential tasks: 4
Estimated total effort: 8-12 hours
