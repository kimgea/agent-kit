---
name: change-impact
status: completed
created: 2026-09-06T19:05:24Z
updated: 2026-09-06T23:15:20+02:00
progress: 100%
prd: .claude/prds/change-impact.md
github: (will be set on sync)
---

# Epic: change-impact

## Overview

Deliver an independently installable, analysis-only `change-impact` skill that
maps evidence-backed consequences of exact changes while preserving the target,
context, and downstream-authority boundaries.

## Architecture Decisions

- Use a two-stage workflow: a deterministic resolver freezes selected targets
  and lead-selected context; a deterministic finalizer binds semantic impact
  judgments into one canonical result.
- Support ref-range, combined working-tree, and explicit path targets.
- Resolve trusted-base `REVIEW.md` and `VERIFY.md` as optional impact evidence,
  not execution or scope authority.
- Represent impacts rather than findings. Use `COMPLETE`/`INCOMPLETE`, not a
  correctness verdict.
- Keep consumer suggestions advisory and typed; consumers retain target,
  execution, edit, and acceptance authority.
- Duplicate the small runtime-safe resolver logic needed by this skill rather
  than importing another installed skill or repository helper.

## Technical Approach

### Skill runtime

- `SKILL.md` defines the locked workflow and authority boundary.
- `impact_context.py` resolves and freezes target, context, guidance, content,
  and source provenance with bounded safe reads.
- `impact_result.py` validates semantic drafts, derives canonical identifiers,
  coverage and completion, binds the context digest, and renders text.
- Direct references hold context/result authoring rules and JSON Schemas.

### Evaluation and integration

- Standard-library unit tests exercise resolver and finalizer boundaries.
- Shared hierarchy conformance verifies compatible trusted-base behavior.
- Behavioral fixtures test true impact, indirect impact, safe omission, and
  incomplete evidence without invoking models in hosted CI.
- Catalog, plugin, docs, package manifests, and changelog are updated together.

## Implementation Strategy

Build the trust boundary first, then semantic result construction, then public
documentation and evaluations. Use focused tests while iterating. Run the
canonical range-selected gate only on the frozen final commit before review.

## Task Breakdown Preview

1. Define canonical contracts and scaffold the skill.
2. Implement safe target, context, and guidance resolution.
3. Implement result finalization, validation, and human rendering.
4. Integrate catalog, plugin, version, docs, and packaging surfaces.
5. Add deterministic and behavioral coverage.
6. Dogfood, verify, independently review, and deliver.

## Dependencies

- Approved `.claude/prds/change-impact.md`.
- Tasks 2 and 3 depend on the canonical contract in Task 1.
- Public integration and behavioral evidence depend on stable runtime shape.

## Success Criteria (Technical)

- The skill is self-contained and packages independently.
- Canonical results are target/context bound and reject unauthorized scope.
- Human output is rendered from validated JSON.
- Realistic positive, negative, stale, malformed, and cross-platform cases pass.
- The grouped review plugin includes the skill without making it mandatory for
  existing workflows.

## Estimated Effort

- Size: L
- Hours: 14-20

## Tasks Created

- [x] 001.md - Define contract and scaffold (parallel: false)
- [x] 002.md - Implement context resolver (parallel: false)
- [x] 003.md - Implement canonical result helper (parallel: false)
- [x] 004.md - Integrate public and package surfaces (parallel: false)
- [x] 005.md - Add unit and behavioral evidence (parallel: false)
- [x] 006.md - Dogfood, review, and deliver (parallel: false)

Total tasks: 6
Parallel tasks: 0
Sequential tasks: 6
Estimated total effort: 14-20 hours
