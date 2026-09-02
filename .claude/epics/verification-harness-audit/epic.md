---
name: verification-harness-audit
status: in-progress
created: 2026-09-01T19:55:34Z
updated: 2026-09-02T02:00:51+02:00
progress: 71%
prd: .claude/prds/verification-harness-audit.md
github: (not synced)
---

# Epic: verification-harness-audit

## Overview

Deliver a portable, analysis-only skill that audits selected local verification
harnesses for meaningful, timely, reliable protection. The skill emits one
lead-bound canonical result and renders readable human output from it without
editing files, contacting external services, or treating repository content as
execution authority.

## Architecture Decisions

- Keep the audit harness-centered: selected parts and paths are the finding
  boundary; related implementation and contracts are read-only context.
- Support current-filesystem part, file, directory, and project scopes with
  bounded deterministic inventory and progressive semantic classification.
- Keep the installed skill self-contained. Share REVIEW hierarchy behavior
  through repository conformance fixtures rather than a runtime dependency or
  generated common module.
- Resolve user-global and root-to-nearest repository REVIEW guidance under the
  established trust and precedence rules. Repository guidance can shape
  analysis but cannot authorize execution.
- Bind target, guidance, context inventory, and command authority in a separate
  lead-owned envelope. The semantic draft supplies recommendations, evidence,
  coverage, and limitations only.
- Use strengths `essential`, `strong`, `moderate`, and `optional`; derive
  `INCOMPLETE`, `IMPROVEMENTS`, or `PASS` mechanically. Advisory recommendations
  may remain in a pass.
- Analyze local CI configuration as provider-specific project data through a
  provider-neutral verification rubric. Do not call provider APIs or ship
  provider-specific general policy.
- Perform static analysis by default. Record only exact caller- or bounded
  user-global-authorized command plans; do not add an arbitrary command runner.
- Produce outcome-focused safe directions and decision gates rather than exact
  patches. Keep remediation in `review-and-fix` through generic normalization in
  v1.
- Use repository-local executable behavioral evaluation with opt-in local Codex
  runs. Hosted validation checks fixtures and recorded outputs only.

## Technical Approach

- Initialize `skills/verification-harness-audit/` with concise runtime
  instructions, Codex metadata, an analysis rubric, result-authoring guidance, a
  canonical schema, a current-filesystem resolver, and a result
  finalizer/renderer.
- Have the resolver freeze caller-selected path and optional part focus,
  no-link regular-file inventory, REVIEW chains, bounded contextual metadata,
  limitations, and optional pre-authorized execution-plan provenance.
- Have the semantic agent progressively classify harness resources and inspect
  assertions, fixtures, command wiring, CI placement, timing evidence,
  determinism, isolation, redundancy, platform coverage, and failure visibility.
- Have the finalizer reject scope or authority supplied by the semantic draft,
  derive IDs, fingerprints, counts, and status, validate cross-field invariants,
  and render every human report from canonical JSON.
- Add common REVIEW-resolution conformance fixtures while retaining independent
  resolver implementations and target semantics.
- Extend repository tests and the fixed behavioral-evaluation adapter map with
  simulated and opt-in local cases for this result contract.
- Update the catalog, grouped plugin, architecture, compatibility, public docs,
  changelog, packaging expectations, and release tracking.

## Implementation Strategy

1. Freeze the schema, rubric, authority envelope, and installed skill shape.
2. Implement the resolver and result helper as separate trust boundaries.
3. Author the semantic workflow and public integration surfaces in parallel
   once the contract is stable.
4. Add deterministic boundary tests before model-backed evaluations.
5. Run fresh local behavioral cases, generic consumer normalization, complete
   packaging validation, and independent review before delivery.

## Task Breakdown Preview

- 001: Define the canonical audit contract and skill skeleton.
- 002: Implement bounded target, inventory, and REVIEW guidance resolution.
- 003: Implement canonical finalization, validation, and human rendering.
- 004: Author the audit workflow and repository integration surfaces.
- 005: Add deterministic unit, boundary, and conformance tests.
- 006: Add executable behavioral evaluations and consumer evidence.
- 007: Complete integration, forward validation, review, and delivery.

## Dependencies

- Existing repository catalog, packaging, plugin, documentation, and validation
  conventions.
- Existing `project-review` and `review-guidance-audit` hierarchy semantics as a
  shared behavioral contract, not runtime dependencies.
- Existing local behavioral-evaluation harness and fixed adapter architecture.
- Existing generic `review-and-fix` normalizer as an optional downstream
  consumer.

## Success Criteria (Technical)

- Every PRD success criterion is covered by deterministic validation or explicit
  bounded local behavioral evidence.
- Packaged skill contains every runtime dependency and imports no repository-only
  implementation code.
- Resolver and result helpers fail closed on scope, provenance, link, limit,
  malformed-input, and authority errors across Linux and Windows coverage.
- A fresh agent produces schema-valid, hidden-assertion-compliant results for
  realistic part, file, directory, CI, and project fixtures.
- Canonical and hosted validation never invoke a model or external service.
- Generic `review-and-fix` normalization preserves target ownership and
  consequential-decision gates for audit output.

## Estimated Effort

Seven bounded tasks, approximately 39 hours total. After the contract task,
resolver, result-helper, and workflow/documentation streams can progress in
parallel; deterministic tests, behavioral evidence, and delivery remain gated.

## Tasks Created

- [x] 001.md - Define canonical audit contract and skill skeleton (parallel: false)
- [x] 002.md - Implement target, inventory, and guidance resolver (parallel: true)
- [x] 003.md - Implement canonical result finalizer and renderer (parallel: true)
- [x] 004.md - Author audit workflow and repository integration (parallel: true)
- [x] 005.md - Add deterministic and conformance coverage (parallel: false)
- [ ] 006.md - Add behavioral evaluations and consumer evidence (parallel: false)
- [ ] 007.md - Validate, review, and deliver the skill (parallel: false)

Total tasks: 7
Parallel tasks: 3
Sequential tasks: 4
Estimated total effort: 39 hours
