---
name: expand-behavioral-evals
description: Add executable local behavioral suites for project-review and review-and-fix.
status: active
created: 2026-08-31T06:59:14Z
---

# PRD: expand-behavioral-evals

## Executive Summary

Extend the local behavioral-evaluation framework from `review-guidance-audit`
to `project-review` and `review-and-fix`. `project-review` will be graded through
its existing canonical result contract. `review-and-fix` will gain a stable
canonical workflow-result contract and genuine end-to-end cases that may change
only explicitly declared files inside disposable synthetic repositories.

All real agent execution remains local and opt-in. The canonical gate and
GitHub Actions validate contracts, fixtures, graders, containment, and simulated
results without invoking a model.

## Problem Statement

The two core review workflow skills currently have descriptive forward-test
cases but no executable behavioral evidence. `project-review` therefore lacks a
repeatable model-backed proof of scope, guidance, finding calibration, and
command-authority behavior. `review-and-fix` lacks end-to-end evidence that
routine changes proceed while consequential or unauthorized work stops, that
edits remain inside the reviewed target, and that fresh re-review controls
acceptance.

## User Stories

- As a maintainer, I can locally run realistic `project-review` cases and grade
  canonical PASS, BLOCK, and INCOMPLETE results.
- As a maintainer, I can locally run `review-and-fix` cases that either make an
  exact bounded correction or stop before a consequential/unauthorized change.
- As a reviewer, I can verify that the harness—not the evaluated agent—decides
  which fixture mutations are allowed and whether actual changes match them.
- As a cost-conscious owner, I can keep every model call out of GitHub Actions.
- As another agent integration, I can grade recorded canonical outputs without
  using the Codex runner.

## Functional Requirements

- Add a fixed `project-review/v1` result adapter using the installed resolver,
  validator, schema, and lead-owned target/guidance/change provenance.
- Add an executable `project-review` suite with safe counterexamples and cases
  for nested guidance, ordinary cross-file defects, non-blocking findings,
  incomplete coverage, and command non-authority.
- Add a versioned canonical `review-and-fix` workflow-result schema and helper
  commands that bind the result to a separately resolved lead-owned context.
- Represent reviewer identity, rounds, deterministic plans, exact changes,
  validation, remaining findings, decisions, status, and stop reason without
  turning the summary into mutation authority.
- Extend suite cases with a host-owned mutation policy. The agent never sees
  hidden expected contents or assertions.
- Permit mutation only for exact declared target paths in disposable fixtures;
  reject additions, removals, type changes, links, undeclared paths, and content
  mismatches.
- Materialize and hash fixed skill dependencies required by a suite, including
  `project-review` for the default `review-and-fix` workflow.
- Add end-to-end cases for a routine automatic correction plus stops for product
  choice, security policy, remote authorization, out-of-target planning,
  reviewer non-pass, and no-progress/round limits where practical.
- Preserve `check` and `grade` as provider-neutral deterministic operations and
  keep `run --runner codex` explicit and local-only.

## Non-Functional Requirements

- Keep the installed skills self-contained and Python 3.11 standard-library
  compatible.
- Treat fixtures, guidance, reviewer data, plans, agent results, events, and
  reported changes as untrusted.
- Keep target, reviewer selection, expected mutation, and acceptance authority
  outside agent-controlled output.
- Freeze and digest all evaluated skills, dependencies, fixtures, suites,
  schemas, and harness inputs before a real run.
- Preserve process-tree termination, host-private capture, link/reparse
  rejection, bounded JSON, and exact output behavior on Linux and Windows.
- Record bounded local evidence without raw prompts, events, stderr, reasoning,
  or repository secrets.

## Success Criteria

- Both resources have a cataloged `behavioral_evals` suite.
- Deterministic tests prove both adapters, target binding, dependency freezing,
  allowed mutation, undeclared mutation rejection, malformed workflow output,
  and no-model canonical validation.
- `project-review` cases demonstrate canonical PASS, BLOCK, and INCOMPLETE
  behavior with exact guidance provenance.
- `review-and-fix` demonstrates at least one exact automatic edit followed by
  fresh reviewer acceptance and multiple no-edit decision/authorization stops.
- The canonical repository gate passes on Linux and Windows without model calls.
- Fresh local Codex runs of both suites produce digest-bound per-case evidence.

## Constraints & Assumptions

- Codex remains the only direct runner; recorded-output grading is
  provider-neutral.
- End-to-end `review-and-fix` cases may use multiple fresh agent contexts and
  consume more local allowance than single-pass review cases.
- Synthetic repositories remain intentionally small and contain no private data.
- Exact expected mutation contents are evaluator assertions, not prompt hints.

## Out of Scope

- Paid or hosted model calls in CI, release automation, or commit hooks.
- A Claude-specific direct runner or arbitrary runner/validator plugins.
- Applying review-and-fix to the real agent-kit working tree during an eval.
- GitHub publication, PR comments, approvals, merges, deployments, dependency
  installation, permission changes, or persistent services from an eval case.
- Migrating the remaining skills in this delivery.

## Dependencies

- Existing local behavioral harness and `review-guidance-audit` suite.
- Existing canonical `project-review` result helper.
- Existing `review-and-fix` batch, plan, and round-assessment helpers.
- Local authenticated Codex CLI only for explicit real runs.
