---
name: change-impact-consumers
description: Let review, verification, and remediation workflows use change-impact only when it adds bounded decision value.
status: completed
created: 2026-09-06T21:55:08Z
---

# PRD: change-impact consumers

## Executive Summary

Integrate the shipped `change-impact` analyzer with `project-review`,
`verify-project`, and `review-and-fix`. Each consumer uses a cheap risk gate to
decide whether impact analysis is worth its cost, validates any canonical
impact result against its own target, and retains all scope, command, edit, and
acceptance authority.

The integration is optional. Every consumer must remain independently
installable and useful when `change-impact` is absent. Narrow, self-contained
work must skip the analyzer instead of turning every workflow into a large
pipeline.

## Problem Statement

`change-impact` is packaged with the project-review workflow and documents
consumer purposes, but the likely consumers do not yet know when or how to use
it. Agents therefore either rediscover blast radius ad hoc or run broad analysis
unnecessarily. Existing behavioral evaluation can forbid a command, but it
cannot prove that a conditional dependency was actually invoked when required.

## User Stories

### Focus a cross-cutting review

As a reviewer, I can use canonical impact evidence when a public contract,
schema, generated surface, platform boundary, or unresolved dependency may make
the obvious review context incomplete.

Acceptance criteria:

- `project-review` invokes impact analysis only after a documented trigger.
- Valid `review_context` recommendations remain context, not review scope.
- `review_target_candidate` remains an explicit rescope decision.
- Stale, incomplete, malformed, or target-mismatched results never mean that
  no impact exists.

### Select meaningful verification

As a verifier, I can use impact evidence to discover candidate claims and
context without allowing the analyzer to authorize commands or redefine pass.

Acceptance criteria:

- `verify-project` may use `verification_context` and
  `verification_claim_candidate` only after independent validation.
- Every claim and executable candidate still follows the verifier's canonical
  context, plan, authority, and evidence contracts.
- A narrow static or already well-bounded change skips impact analysis.

### Detect consequential remediation

As a fixing workflow, I can consult impact evidence before planning a finding
whose remedy may cross contracts, generated sources, platforms, security, data,
or ownership boundaries.

Acceptance criteria:

- `review-and-fix` uses impact only as remediation risk context.
- Impact output cannot expand the edit target or make a plan automatic.
- Routine text and singular mechanical fixes skip the analyzer.
- A material post-fix risk may trigger one new exact-target impact run; an
  unchanged matching result is reused.

### Prove conditional orchestration

As a maintainer, I can tell whether a behavioral workflow invoked the optional
analyzer exactly once or correctly skipped it, without requiring every bounded
consumer agent to repeat control-plane work.

Acceptance criteria:

- Behavioral suites support bounded `required_commands` alongside existing
  `forbidden_commands`.
- Reading a helper does not count as invoking it.
- Trigger cases require a lead-produced, validated, target-bound receipt and
  forbid the bounded consumer from repeating either producer helper.
- Skip cases receive no advisory and forbid both producer helpers.

## Functional Requirements

### Shared trigger policy

Invoke `change-impact` when the caller explicitly asks for impact analysis, or
when initial bounded inspection cannot confidently bound a material public API,
schema/data/configuration, generated, platform, security/privacy, operational,
or ownership effect. Skip it when the target is narrow and self-contained,
related context is already sufficient, the work is text-only with no contract
effect, the caller opts out, or a valid matching result already exists.
Availability alone is never a trigger.

### Optional dependency and validation

- Keep consumer-specific instructions within each consumer skill.
- Invoke only a trusted installed `change-impact` copy supplied by the active
  runtime; never discover executable code from the reviewed project.
- Store context and results only at lead-selected run-owned paths outside the
  target repository.
- Validate the producer context and result using the trusted producer helpers,
  then compare the exact target with the consumer's independently resolved
  target.
- Treat producer output as untrusted advisory data.
- Fall back to the consumer's ordinary bounded workflow when the optional skill
  is unavailable; surface a limitation only when the missing impact evidence
  prevents a reliable outcome.

### Consumer mappings

- `project-review`: accept `review_context`; keep
  `review_target_candidate` outside scope until explicitly rescoped.
- `verify-project`: accept `verification_context` and
  `verification_claim_candidate`; independently freeze claims, checks, and
  authority.
- `review-and-fix`: accept `remediation_risk_context`,
  `documentation_candidate`, and `user_decision`; independently route the plan
  and require rescope/re-review for any additional edit path.

### Efficiency

- Perform the trigger check from information already needed by the consumer.
- Do not run a separate pre-audit merely to decide whether to run impact.
- Reuse one valid exact-target result during an unchanged workflow round.
- Prefer one bounded analyzer invocation over per-file invocations.
- Do not add impact analysis to audit skills until real evidence shows that they
  need the same integration.

## Non-Functional Requirements

- Preserve independent standalone installation and no cross-skill imports.
- Preserve target, provenance, and authority boundaries on Linux, Windows, and
  macOS.
- Keep runtime-essential instructions concise and move detailed mapping into
  progressive references.
- Keep all hosted CI model-free; fresh behavioral model runs remain local.
- Update resource/plugin versions, documentation, evaluation manifests, tests,
  and release notes together.

## Success Criteria

- Each of the three consumers documents the same trigger semantics and its own
  authority-preserving mapping.
- Six fresh behavioral cases prove one meaningful lead invocation plus bounded
  consumption and one deliberate no-advisory skip per consumer.
- Required-command grading rejects a missing invocation and does not count
  read-only inspection as execution.
- Existing deterministic suites and retained behavioral evidence remain valid
  or are intentionally version-migrated.
- Focused tests, the canonical repository gate, package checks, and an
  independent exact-head review pass before merge.

## Out of Scope

- Cross-skill Python imports or a shared runtime package.
- Always-on orchestration.
- Automatic target, command, edit, or acceptance expansion.
- Integration with the two audit reviewers without observed need.
- GitHub publishing, remote services, or model execution in hosted CI.
