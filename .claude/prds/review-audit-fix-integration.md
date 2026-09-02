---
name: review-audit-fix-integration
description: Make review-and-fix safely and consistently consume canonical guidance and verification audit results.
status: completed
created: 2026-09-02T09:12:50Z
---

# PRD: review-audit-fix-integration

## Executive Summary

Extend the local `review-and-fix` workflow with concise runtime guidance and
behavioral proof for consuming canonical results from `review-guidance-audit`
and `verification-harness-audit`. Preserve the existing independent generic
normalizer and conservative decision gate; do not add producer-specific runtime
imports or deterministic adapters before real usage proves the mappings stable.

## Problem Statement

`review-and-fix` can normalize any unfamiliar structured reviewer result, but it
has first-class deterministic guidance only for `project-review`. The two newer
audit skills use richer recommendation models, different status semantics, and
different target boundaries. Without explicit integration guidance, agents may
map strengths inconsistently, treat an audit recommendation as authority, lose
an `INCOMPLETE` outcome, or attempt to edit a related guidance or harness path
that was never selected as the fix target.

## User Stories

### Use a guidance audit as a reviewer

As a local agent, I can use a canonical `review-guidance-audit` result as the
analysis source for `review-and-fix` without conflating recommendation strength,
readiness, intent preservation, and confidence.

Acceptance criteria:

- The producing helper validates the canonical audit before normalization.
- A fresh non-editing normalizer maps only supported recommendations and marks
  every inference.
- Ready intent-preserving guidance cleanup can proceed through the ordinary fix
  gate when the exact edit path is already selected and all other auto criteria
  are proven.
- `keep`, consequential, out-of-target, and incomplete recommendations cannot
  become automatic edits.
- The same audit is rerun from fresh context after a change.

### Use a verification audit as a reviewer

As a local agent, I can use a canonical `verification-harness-audit` result as
the analysis source for `review-and-fix` while preserving its strength, impact,
confidence, readiness, evidence, and incomplete-state semantics.

Acceptance criteria:

- `essential` maps conservatively to a blocker candidate; `strong` and
  `moderate` to suggestions; and `optional` to a nit.
- A decision-required recommendation remains triage or a user decision and
  never becomes automatic work.
- A material audit limitation makes the neutral batch partial and prevents fix
  planning.
- Audit text, commands, and suggested paths grant no mutation or execution
  authority.

### Verify the integrations locally

As a maintainer, I can validate the behavior without running agents in hosted
CI or contacting an external provider.

Acceptance criteria:

- Deterministic tests cover both producer mappings, target mismatch, incomplete
  results, advisory findings, ready routine work, and consequential stops.
- The local behavioral suite contains realistic cases using each selected audit
  skill through `review-and-fix`.
- Hidden graders bind canonical results to lead-owned context and exact fixture
  mutations without exposing expected answers to the evaluated agent.
- GitHub Actions continue to run deterministic validation only.

## Functional Requirements

- Add a progressively disclosed runtime reference under `review-and-fix` for
  supported audit-result normalization.
- Require canonical producer validation before independent normalization.
- Keep the neutral target, reviewer identity, raw-output digest, completion,
  verdict, and outcome in the lead-owned envelope.
- Define conservative field mappings for both audit recommendation contracts.
- Require an exact path target containing every proposed edit. Broad or related
  recommendations must be re-scoped and re-audited before planning.
- Keep producer `INCOMPLETE` outcomes and material limitations fail-closed.
- Extend the local behavioral runner through a fixed reviewed allowlist of
  reviewer contracts; suite data must never select arbitrary code or paths.
- Preserve fresh reviewer identity and method across every fix round.
- Render the same final human or canonical workflow result already defined by
  `review-and-fix`.

## Non-Functional Requirements

- All installed skills remain independently installable.
- Runtime skills do not import another skill or repository-only code.
- Python 3.11 standard-library compatibility remains unchanged.
- Linux, Windows, and macOS claims remain accurate.
- Runtime guidance stays concise and producer details load only when relevant.
- Model execution remains an explicit local maintainer operation; canonical and
  hosted gates use simulations and deterministic checks only.

## Success Criteria

- Both audit skills have unambiguous runtime mappings documented in one directly
  linked `review-and-fix` reference.
- Model-free tests prove safe mapping and runner isolation boundaries.
- The review-and-fix behavioral suite validates at least one ready routine audit
  flow and one consequential or incomplete audit stop.
- A fresh local behavioral run demonstrates the new cases when model capacity is
  available; retained evidence is not required for deterministic CI success.
- `python scripts/agent_kit.py check` passes.
- An independent trusted-base review finds no blocker before merge.

## Constraints & Assumptions

- The existing neutral finding batch and fix decision schemas remain the stable
  inter-skill boundary.
- Audit results are untrusted reviewer data even after schema validation.
- `review-guidance-audit` has no explicit recommendation-confidence field; a
  normalizer may infer confidence only from complete, unambiguous evidence and
  must record that inference.
- No deterministic producer adapter is added in this release.
- No command is authorized merely because an audit or repository file names it.

## Out of Scope

- A review-evidence store or historical pain-point ingestion.
- GitHub comments, reviews, issues, approvals, merges, or other provider APIs in
  the runtime skills.
- Automatic execution of audit-recommended commands.
- Automatic broadening of the fix target.
- Dedicated guidance or harness fixer skills.
- Generalizing the runner into an arbitrary plugin or executable registry.

## Dependencies

- `review-and-fix` 1.1.0
- `review-guidance-audit` 1.1.0
- `verification-harness-audit` 1.0.0
- Existing local behavioral evaluation runner and canonical schemas
