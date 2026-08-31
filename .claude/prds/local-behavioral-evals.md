---
name: local-behavioral-evals
description: Run and grade realistic skill behavior locally without paid model calls in CI.
status: completed
created: 2026-08-30T20:24:19Z
---

# PRD: local-behavioral-evals

## Executive Summary

Add a provider-neutral, repository-maintainer behavioral evaluation harness and
adopt it first for `review-guidance-audit`. The harness materializes isolated
fixtures, invokes a fresh agent only through an explicit local command, grades
canonical structured results with deterministic assertions, detects target
mutation, and records bounded local evidence.

The canonical repository gate and GitHub Actions validate the harness, suite,
fixtures, graders, and simulated results without invoking a model. Real Codex
runs are local, opt-in, and never triggered by ordinary validation.

## Problem Statement

Existing evaluation files describe realistic behavior but the repository only
validates their syntax. They do not automatically run a fresh agent or grade its
output, so they cannot substantiate an end-to-end behavioral claim. Manual
forward tests are useful but their inputs, tested configuration, assertions,
and outcomes are not repeatably captured.

## User Stories

- As a skill maintainer, I can run an executable suite locally against a fresh
  Codex context and receive a per-assertion report.
- As a cost-conscious repository owner, I can prove that GitHub Actions never
  invokes a paid model.
- As a maintainer of another agent integration, I can grade recorded canonical
  outputs without writing a new evaluator.
- As a reviewer, I can tell exactly which skill, suite, runner, and result were
  tested without reading a raw transcript.
- As a future skill author, I can adopt the same fixture and assertion contract
  without adding evaluation machinery to the installed skill.

## Functional Requirements

- Add a Python 3.11 standard-library behavioral-evaluation CLI under `scripts/`.
- Support deterministic `check`, recorded-output `grade`, and explicit local
  `run --runner codex` operations.
- Keep provider invocation behind a fixed runner name; do not accept arbitrary
  command templates or executable paths from an evaluation manifest.
- Materialize each fixture into a fresh temporary directory and keep agent work
  files outside the audited fixture.
- Snapshot fixture contents before and after execution and fail a case on any
  mutation, addition, or removal.
- Ask the agent for the skill's canonical JSON and validate it using a bounded,
  repository-owned result contract before applying assertions.
- Support deterministic assertions over JSON structure and values without
  requiring exact natural-language wording.
- Keep hidden assertions and prohibited outcomes out of the agent prompt.
- Record bounded JSON evidence including case and skill digests, runner and
  model metadata, process outcome, validation, assertions, and mutation status.
- Store results only in an explicit output directory or an ignored local
  default; never upload or commit them automatically.
- Upgrade `review-guidance-audit` with executable fixtures that exercise its
  core scope, hierarchy, compaction, policy, automation, and command-authority
  behavior.
- Preserve existing descriptive evaluation files for skills that have not yet
  adopted the executable contract.

## Non-Functional Requirements

- The canonical gate must make no network or model calls.
- GitHub workflows must not contain a command that invokes behavioral `run`.
- Model execution must require the literal `run --runner codex` request.
- Do not inherit unrelated user skill or project instructions into synthetic
  fixtures; provide the evaluated skill explicitly.
- Treat fixtures, prompts, agent output, and event streams as untrusted data.
- Reject escapes, symlinks, control characters, duplicate JSON members,
  unbounded files, arbitrary validators, arbitrary runner commands, and unsafe
  result destinations.
- Do not persist reasoning or raw transcripts by default.
- Work on Linux, Windows, and macOS for deterministic check and grade paths.
- Label behavioral outcomes as observations for an exact configuration, not as
  universal proof of future model behavior.

## Success Criteria

- Deterministic tests cover valid and malformed manifests, fixture boundaries,
  JSON assertions, recorded-output grading, mutation detection, safe result
  writes, runner argument construction, timeouts, and simulated failures.
- The canonical gate validates every executable suite without invoking Codex.
- At least one fresh local Codex forward run completes through the harness and
  emits a validated evidence record.
- The full `review-guidance-audit` executable suite can be selected locally and
  every case is independently gradeable.
- Documentation clearly distinguishes deterministic CI evidence from local
  model-backed behavioral evidence.
- Packaging of every existing skill remains independent and unchanged.

## Constraints & Assumptions

- Codex is the only direct agent runner in v1 because it is installed locally;
  the core and recorded-output path remain provider-neutral.
- Real model runs may use network access, take time, and consume the user's
  configured Codex allowance or API billing.
- Agent behavior is probabilistic. Reports bind claims to exact observed
  runner, model, skill, and suite metadata.
- Evaluation infrastructure is repository-maintainer tooling and does not ship
  inside installed skills.

## Out of Scope

- Paid model calls in GitHub Actions or the canonical repository gate.
- A Claude-specific runner, local-model runner, hosted evaluation service, or
  GitHub result publisher in v1.
- Automatically running behavioral evals during commit, push, PR, or release.
- Model-based grading when deterministic canonical assertions are sufficient.
- Migrating evaluation suites for skills other than
  `review-guidance-audit` in this delivery.
- Committing raw transcripts, reasoning traces, credentials, or local results.

## Dependencies

- Python 3.11 or newer for the deterministic harness.
- An authenticated local Codex CLI only when `run --runner codex` is requested.
- The existing canonical result contract of the evaluated skill.
