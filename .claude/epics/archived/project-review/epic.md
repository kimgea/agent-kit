---
name: project-review
status: completed
created: 2026-08-29T09:45:52Z
updated: 2026-08-29T16:04:07Z
progress: 100%
prd: .claude/prds/project-review.md
github: null
---

# Epic: project-review

## Overview

Deliver an independently installable, cross-agent review skill that applies
trusted hierarchical `REVIEW.md` guidance to bounded project scopes and emits a
canonical schema-versioned result with deterministic human rendering.

## Architecture Decisions

- Keep the skill analysis-only; future publisher and fixer skills consume its
  structured result.
- Make JSON canonical and derive prose from it.
- Resolve repository guidance per reviewed path and from the trusted starting
  revision for change reviews.
- Keep locked review, safety, evidence, and verdict invariants in the skill;
  keep project and domain checks in `REVIEW.md`.
- Use one lead reviewer, with adaptive bounded delegation for coherent groups.
- Perform static inspection by default and gate command execution on explicit
  caller or bounded user-global authorization.
- Package deterministic resolution, validation, and rendering helpers inside the
  skill using Python 3.11 standard-library code.

## Technical Approach

Freeze the JSON and guidance-resolution contracts first. Implement the trusted
scope resolver and result validator/renderer as separate helpers, then author the
agent workflow around those deterministic seams. Add adversarial boundary tests
and behavioral evaluations before integrating the resource into the catalog,
docs, compatibility matrix, and generated packages.

## Task Breakdown Preview

1. Define the schema, calibration, and executable contracts.
2. Implement trusted scope and `REVIEW.md` resolution.
3. Implement result validation and deterministic rendering.
4. Author the lead-review workflow and adaptive orchestration.
5. Add boundary tests, integration fixtures, and behavior evaluations.
6. Integrate catalog metadata, docs, packaging, and forward-testing.

## Dependencies

Tasks 002, 003, and 004 depend on the frozen contract in task 001 and may proceed
in parallel because they own separate files. Cross-component tests depend on all
three. Catalog and packaging integration is last so generated metadata reflects
the validated interface.

## Success Criteria (Technical)

- Trusted-base resolution and per-path precedence are deterministic and tested.
- The canonical schema captures target, guidance, coverage, verification,
  findings, limitations, and verdict without provider-specific fields.
- Human output is generated only from validated canonical JSON.
- Verification never runs without a valid authorization source.
- Single-agent and delegated paths produce the same calibrated contract.
- The canonical repository gate and package checks pass on a clean worktree.

## Estimated Effort

Large, approximately 22 focused engineering hours plus forward-testing.

## Tasks Created

- [x] 001.md - Define contracts schema and calibration
- [x] 002.md - Implement trusted review context resolution
- [x] 003.md - Implement result validation and rendering
- [x] 004.md - Author review workflow and orchestration
- [x] 005.md - Add boundary tests and behavior evaluations
- [x] 006.md - Integrate catalog packaging docs and forward tests
- [x] 007.md - Dogfood hierarchical review policy in Agent Kit

Total tasks: 7
Parallel tasks: 3
Sequential stages: 4
Estimated total effort: 22 hours
