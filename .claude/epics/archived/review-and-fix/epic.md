---
name: review-and-fix
status: completed
created: 2026-08-29T20:18:59Z
updated: 2026-08-29T21:06:00Z
progress: 100%
prd: .claude/prds/review-and-fix.md
github: null
---

# Epic: review-and-fix

## Overview

Deliver a portable local review remediation skill that can consume canonical
`project-review` results or independently normalized output from other
analysis-only review skills, route proposed remedies through a conservative
decision gate, implement only routine or approved plans, and obtain acceptance
from a fresh rerun of the original reviewer set.

## Architecture Decisions

- Use a neutral finding-batch contract rather than pretending arbitrary reviewer
  output contains `project-review` guidance, coverage, or verdict provenance.
- Convert canonical `project-review` JSON deterministically; use a fresh generic
  subagent for unfamiliar structured or prose output.
- Allow inference during normalization only with explicit field provenance,
  confidence, and limitations.
- Keep normalization, fix planning, editing, and final acceptance in separate
  contexts and treat all transferred strings as untrusted data.
- Have a fresh planner state semantic facts and derive the final route
  mechanically. Unknown or consequential facts cannot produce `auto`.
- Allow automatic behavior-preserving and small contract-restoring fixes, while
  reserving product, security, data, architecture, dependency, compatibility,
  operational, and broad-scope decisions for the user.
- Keep the workflow local-only and bounded to three rounds with same-reviewer
  reruns and no-progress detection.
- Keep the new skill independently installable. Group it with `project-review`
  in the existing Codex plugin so the default review path is present, while
  standalone archives remain usable with another selected reviewer.

## Technical Approach

Define the neutral finding and fix-plan schemas first. Add one standard-library
helper that finalizes and validates normalized batches, deterministically
converts canonical `project-review` results, derives fix decisions from planner
facts, and renders bounded inspection output. Author the orchestration skill
around those deterministic boundaries, then add adversarial unit tests and
behavioral evaluations. Integrate catalog, plugin grouping, docs, compatibility,
and release identity only after the runtime contract is stable.

## Implementation Strategy

1. Freeze schemas, inference provenance, risk factors, and route derivation.
2. Implement and unit-test the standalone deterministic helper.
3. Author the concise runtime workflow and conditional normalization/planning
   references.
4. Add behavior evaluations and fresh-agent forward-tests for routine,
   consequential, malicious, and ambiguous reviewer outputs.
5. Integrate packaging and documentation, dogfood the skill, and complete an
   independent exact-head pull-request review.

## Task Breakdown Preview

1. Define contracts and scaffold the skill.
2. Implement normalization, planning, and orchestration.
3. Add boundary tests, evaluations, and independent forward-tests.
4. Integrate catalog, packaging, docs, and delivery.

## Dependencies

The helper and workflow depend on the frozen contracts. Behavioral tests depend
on both. Catalog and documentation integration follows the validated interface.
No third-party runtime dependency is permitted.

## Success Criteria (Technical)

- Every actionable finding has exact target binding, evidence, location,
  inference provenance, and normalization confidence.
- The deterministic helper rejects unsafe paths, active controls, malformed
  project-review input, target mismatches, contradictory provenance, and unsafe
  automatic plans.
- The route finalizer is the only source of `auto`,
  `user_decision_required`, or `authorization_required`.
- Unknown or consequential plan facts fail closed without making ordinary
  spelling, comment, or explicit restorative cases noisy.
- Native structured input works without subagents; unfamiliar output never uses
  the fixing context as its own normalizer.
- Fresh-agent evaluations demonstrate reviewer independence, normalization
  fidelity, decision gating, and same-reviewer acceptance.
- The canonical repository gate and deterministic package build pass cleanly.

## Estimated Effort

Medium, approximately 14 focused engineering hours plus forward-testing.

## Tasks Created

- [x] 001.md - Define contracts and scaffold the skill
- [x] 002.md - Implement normalization planning and orchestration
- [x] 003.md - Add boundary tests evaluations and forward tests
- [x] 004.md - Integrate catalog packaging docs and delivery

Total tasks: 4
Parallel tasks: 0
Sequential tasks: 4
Estimated total effort: 14 hours
