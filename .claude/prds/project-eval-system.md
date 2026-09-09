---
name: project-eval-system
description: Define, run, improve, and retire local agent evaluations through a portable four-skill protocol family.
status: completed
created: 2026-09-08T13:34:04Z
---

# PRD: project-eval-system

## Executive Summary

Build a local-first evaluation system for measuring how well coding agents work
in a repository and for improving the repository harness from evidence. The
system consists of four independently installable skills:

- `project-eval` defines, validates, runs, grades, compares, imports, and exports
  repository evaluations;
- `eval-candidate-audit` analyzes explicitly selected agent sessions and
  proposes deduplicated evaluation candidates;
- `eval-harness-experiment` performs bounded paired experiments on disposable
  harness variants and returns ranked evidence and candidate patches without
  editing the live repository; and
- `eval-suite-audit` analyzes suite usefulness and recommends keeping,
  refreshing, merging, simplifying, demoting, or retiring evaluations.

The four skills share a versioned protocol family rather than one universal
schema. They build on Agent Kit's existing local behavioral-evaluation
principles: deterministic checks in ordinary validation, explicit opt-in model
execution, evaluator-owned targets and hidden grading, disposable workspaces,
bounded sanitized evidence, and canonical human or JSON output.

The first delivery slice must be useful by itself: a maintainer can define one
repository task evaluation, run it locally with Codex, grade it
deterministically, receive readable and structured results, and export or
import a sanitized digest-bound evidence bundle. The other skills follow as
separate milestones over the same contracts.

## Problem Statement

Agent Kit can run executable behavioral suites for individual skills, but it
does not yet provide a reusable installed capability for repositories to:

- describe realistic coding and explanation tasks as durable evaluations;
- compare agents, models, prompts, instructions, or harness variants under the
  same conditions;
- measure correctness, completion, time, and token use without collapsing them
  into a misleading universal score;
- turn repeated session pain points into candidate evaluations;
- improve a harness through controlled experiments instead of intuition; or
- remove obsolete, duplicated, low-value, or unnecessarily expensive cases.

Without these capabilities, evaluation knowledge remains scattered across
manual tests, transcripts, issue memories, and one-off experiments. Suites can
grow indefinitely, improvements can overfit visible examples, and measurements
from different machines or configurations can be compared as if they were
equivalent.

## Users and User Stories

### Repository maintainer

As a repository maintainer, I can define an explanation, implementation, or
multi-phase trajectory evaluation with explicit success criteria, hidden
grader evidence, supported environments, importance, and a bounded run profile.

Acceptance criteria:

- The committed case contains everything required for another maintainer to run
  it on another machine, except the selected agent/model installation and
  credentials.
- The evaluated agent cannot read or modify hidden expected answers, graders,
  holdouts, or control-plane results.
- Unsupported platforms or missing declared capabilities are reported as
  `not_applicable` or `unavailable`, not as false failures.

### Agent or model evaluator

As an evaluator, I can run the same selected cases across agents, models,
reasoning settings, or harness variants and compare quality-gated results with
recorded provenance.

Acceptance criteria:

- Every result identifies the exact case, suite, fixture, harness, runner,
  agent, model, reasoning, instruction, and relevant environment configuration
  when available.
- Correctness and forbidden effects remain hard gates; time and tokens compare
  only variants that meet the configured quality threshold.
- A single run is labeled as one observation rather than stability evidence.

### Harness improver

As a maintainer, I can select an objective, edit surfaces, and total budget,
then let an experiment test several variants in disposable workspaces and
return a ranked candidate without changing my active checkout.

Acceptance criteria:

- Baseline and candidate run as a paired comparison under the same measured
  conditions.
- A clear improvement requires a predeclared objective, configured tolerance,
  required repetitions, no required-case failure, no material guardrail
  regression, and no budget or forbidden-effect breach.
- Tradeoffs, noisy results, and unresolved consequential decisions are returned
  as such rather than silently choosing a winner.

### Session reviewer

As a maintainer, I can explicitly select one or more sessions for analysis and
receive privacy-preserving candidate evaluations whose recurrence and evidence
strength are tracked independently from owner-assigned importance.

Acceptance criteria:

- Session analysis is explicit or enabled by project policy; it is never a
  mandatory global end-of-session action.
- Raw transcripts and private content are not committed or embedded in portable
  results.
- A candidate explains the observed pain point, proposed task shape, evidence,
  overlap with existing cases, confidence, and promotion requirements.

### Suite curator

As a suite curator, I can identify cases that no longer protect unique behavior
and receive evidence-backed lifecycle recommendations without automatically
losing meaningful coverage.

Acceptance criteria:

- Age, consistently passing results, or lack of recent failures are not enough
  by themselves to retire a case.
- Retirement identifies the removed behavior, duplicate or replacement
  coverage, fixture obsolescence, lack of unique agent-behavior value, or cost
  without unique coverage.
- Behavior-preserving ready maintenance may be applied during an explicitly
  authorized trim operation; meaningful coverage loss requires a user decision.

### Tool and skill consumer

As another agent, skill, or CLI, I can request canonical JSON rather than prose,
validate a compatible schema version, and consume results without inheriting
target, command, mutation, publication, or acceptance authority.

Acceptance criteria:

- Human output is rendered from the same validated canonical result.
- Unknown third-party agent outputs can be imported only through a
  consumer-owned adapter or fresh bounded normalization step.
- Imported bundles are evidence only and cannot establish a baseline or
  authorize changes by themselves.

## Functional Requirements

### Protocol family

- Define independently versioned JSON schemas for suite and case definitions,
  run results, portable evidence bundles, candidate recommendations, lifecycle
  recommendations, and experiment results.
- Share stable identifiers, target snapshots, configuration digests, evidence
  references, completion/outcome/next-action axes, limitations, and bounded
  observation semantics without creating a mega-schema.
- Require consumers to declare compatible schema versions and reject unknown
  incompatible major versions.
- Treat every imported manifest, result, bundle, transcript extract, agent
  output, and repository fixture as untrusted data.

### Repository-owned evaluation definitions

- Use explicit committed suite and case manifests under a repository eval root;
  do not introduce hierarchical `EVAL.md` instruction loading.
- Support explanation tasks, bounded implementation tasks, and multi-phase
  trajectory tasks.
- Let a trajectory define intake, clarification, specification, planning,
  implementation, verification, and final-report phases while remaining one
  canonical scenario with phase-specific views.
- Support goal-derived reconstruction cases from a pinned known-good revision
  plus a host-owned removal transform, ticket prompt, deliberately retained
  neighboring examples, and hidden behavioral grading.
- Calibrate reconstruction cases by proving the prepared start fails the target
  grader, the golden state passes, protected implementation/history does not
  leak, and materially different correct solutions can pass.
- Support structured hidden stakeholder facts and a constrained responder for
  clarification evaluations; the responder may reveal only the answer mapped to
  a natural-language question and must not invent facts or dump the full brief.
- Declare case importance as `required`, `important`, `standard`, or
  `exploratory`; recurrence does not silently change importance.
- Declare supported or required platforms, tools, and capabilities per case.

### Trusted grading and holdouts

- Evaluate correctness with deterministic-first layered graders: built-in
  assertions, hidden host-side repository grader scripts, and fixed project
  check commands represented as executable plus argv, environment, timeout, and
  effect metadata.
- Never accept arbitrary inline shell, interpreter evaluation, executable path,
  or command template from an untrusted manifest.
- Keep hidden stable holdouts and protected regression cases distinct from
  visible development cases; do not generate a new random split for each run.
- Allow a blinded qualitative judge only as advisory evidence. The judge sees
  the answer, rubric, and allowed reference context but not worker identity,
  model, variant, or expected winner.
- Never let qualitative judgment override a deterministic failure.

### Local execution and measurement

- Provide suite-defined `smoke`, `compare`, and `confidence` run profiles with
  bounded cases, repetitions, invocations, models, time, tokens, cost when
  enforceable, writes, and effects.
- Treat one explicit run request as authorization for its configured bounded
  envelope; count retries against that envelope and never expand it silently.
- Materialize every case into a disposable isolated workspace separate from the
  active checkout and evaluator control plane.
- Give the evaluated agent only the task and sanitized project snapshot. Keep
  manifests, expected diffs, expected answers, graders, holdouts, results, and
  credentials inaccessible and unmodifiable.
- Use repository exports without eval definitions or Git history for ordinary
  cases. Use purpose-built sanitized history only for a declared
  history-dependent case.
- Run hermetically and offline by default with preinstalled, vendored, or
  trusted local-cache dependencies. Permit a separate explicit networked
  profile with reduced reproducibility and separate authorization.
- Fully support one fixed Codex runner in v1. Keep recorded-output grading and
  result import agent-neutral. Do not claim a Claude runner until it has live
  behavioral evidence.
- Record measurements as `host_observed`, `runner_reported`, or `unavailable`.

### Comparison and improvement decisions

- Keep correctness and forbidden effects as hard gates.
- Compare completion across configured repetitions and then important-case
  performance; compare time and tokens only among variants meeting the quality
  threshold.
- Preserve Pareto tradeoffs instead of forcing all dimensions into one weighted
  score.
- Require paired baseline and candidate runs under matching agent, model,
  environment, cases, and budget before claiming repository improvement.
- Label a candidate `clear_improvement` only when it improves the predeclared
  objective beyond its tolerance across the required repetitions while keeping
  all required cases passing, avoiding material guardrail regressions, and
  staying inside effect and resource limits.
- Return `tradeoff`, `inconclusive`, `no_improvement`, or `incomplete` when those
  are the supported conclusions.

### Private state and portable evidence

- Store private run history in the OS-native user state directory, using a
  private opaque project link in the Git common directory so worktrees share
  state while fresh clones remain independent by default.
- Permit cross-clone linking only through an explicit user operation. A
  repository manifest or `AGENTS.md` cannot redirect the private state root.
- Use immutable canonical JSON receipts, content-addressed bounded evidence,
  atomic writes, a small rebuildable index, and configured age/size retention;
  do not require a database in v1.
- Delete disposable workspaces, raw transcripts, raw event streams, prompts,
  reasoning, and unbounded errors after grading.
- Retain compact scores, configuration and content digests, measurements,
  bounded redacted failure evidence, aggregate trends, and explicitly pinned or
  referenced evidence.
- Export a bounded deterministic bundle containing a canonical manifest,
  sanitized receipts and evidence, and a digest for every member.
- Import only after validating paths, types, sizes, schema versions, member
  digests, provenance, and sanitization. An imported bundle remains evidence,
  never authority.

### `project-eval`

- Discover and validate explicit repository suite definitions.
- Run selected profiles, grade recorded outputs, compare compatible runs, and
  render concise human or canonical JSON output.
- Export and import portable evidence bundles.
- Apply only selected, ready, behavior-preserving eval-definition maintenance;
  new behavior, ambiguous policy, meaningful coverage loss, consequential
  effects, and material cost increases require a decision.

### `eval-candidate-audit`

- Analyze only explicitly selected sessions or project-opted-in eligible
  sessions.
- Return prose or canonical candidate JSON without editing eval definitions.
- Deduplicate related pain points and record evidence count, independent-session
  count, confidence, proposed importance, and overlap with existing cases.
- Allow automatic drafting during an authorized improve-evals workflow only for
  explicit existing behavior with one clear bounded case shape; require a
  decision for new or ambiguous behavior or material cost.

### `eval-harness-experiment`

- Accept a caller-selected objective, editable harness surfaces, suites,
  comparison profile, and cumulative budget.
- Generate and test variants only in disposable workspaces.
- Stop on budget exhaustion, target achievement, repeated lack of progress,
  scope or source drift, forbidden effects, or a consequential decision.
- Return ranked paired evidence and candidate patches; never edit the active
  checkout, publish, approve, merge, or deploy.

### `eval-suite-audit`

- Inspect committed definitions plus explicitly supplied compatible run or
  candidate evidence.
- Return evidence-backed `keep`, `refresh`, `merge`, `simplify`, `demote`, or
  `retire` recommendations with strength, reason, confidence, unique coverage,
  replacement coverage, cost effect, and limitations.
- Check overlap before proposing a new case and prefer extending,
  parameterizing, or replacing an existing case when that retains intent more
  compactly.
- Recommend compaction or removal whenever it improves signal, even below a
  size threshold, while searching more aggressively as suite cost and context
  grow.

## Non-Functional Requirements

- Keep all four skills independently installable and self-contained. They may
  exchange files through versioned protocols but must not import repository-only
  code or another installed skill at runtime.
- Use Python 3.11 standard-library runtime code unless a later reviewed decision
  justifies a dependency.
- Keep skill entrypoints concise and route mode-specific instructions to direct
  references.
- Fail closed on malformed, oversized, incomplete, drifting, unsafe, or
  ambiguous authority state.
- Reject path traversal, link/reparse escapes, unsafe archives, control
  characters, duplicate JSON members, hostile Unicode display, unbounded
  retention, and output races.
- Preserve unrelated repository, user, and private state on every failure path.
- Keep model calls out of the canonical repository gate, ordinary hosted CI,
  commits, pushes, releases, and installation.
- Support deterministic validation on Linux and Windows and avoid claiming
  untested runner behavior on macOS or Claude.
- Use agent-independent semantics and record exact runner/model identity rather
  than treating one provider as the protocol.

## Success Criteria

- A fresh clone on another machine can validate and run a committed suite
  without any copied private state.
- The first vertical slice defines and runs at least one explanation case and
  one bounded implementation case through Codex in disposable workspaces.
- Deterministic graders reject target drift, hidden-evidence access, unexpected
  mutations, forbidden commands, incomplete output, schema drift, and false
  success claims.
- Human and JSON reports are generated from the same canonical result.
- Exported bundles import on another clean checkout, reproduce their canonical
  receipts, and remain visibly classified as external evidence rather than
  authority.
- A reconstruction case proves start-fails/golden-passes/no-leakage/alternative-
  solution acceptance.
- A clarification trajectory proves question-to-fact mapping without responder
  invention or full-brief leakage.
- An experiment demonstrates paired baseline and candidate execution, clear
  improvement classification, tradeoff/inconclusive handling, and no live-tree
  mutation.
- Candidate and lifecycle audits produce canonical, bounded, deduplicated
  recommendations without modifying definitions by default.
- Focused behavioral suites demonstrate the four skills' intended decisions,
  including safe counterexamples and structured consumer handoffs.
- The canonical Agent Kit gate passes on Linux and Windows without invoking a
  model.

## Constraints and Assumptions

- The existing `scripts/behavioral_eval.py` remains repository-maintainer
  infrastructure and a source of proven patterns; installed skills cannot
  import it.
- Codex is available for live v1 runner evidence. Claude compatibility remains
  a provider-neutral import target until it can be tested directly.
- Model execution consumes local allowance or API billing and therefore remains
  explicit and budgeted.
- Agent behavior is probabilistic. Claims are observations bound to exact
  configurations, not universal guarantees.
- Project `AGENTS.md` may opt eligible sessions into candidate analysis and set
  reporting or storage policy, but cannot weaken privacy, authority, integrity,
  or bounded-retention invariants.

## Out of Scope

- Running agents or paid model-backed experiments in GitHub Actions in v1.
- A scheduled GitHub optimizer, result publisher, bot identity, automatic PR
  creation, approval, merge, deployment, or external evidence service.
- A first-class Claude runner without live access and repeatable evidence.
- One global score that hides quality, cost, or reliability tradeoffs.
- Arbitrary runner, grader, command-template, inline-shell, or executable plugin
  selection from untrusted manifests.
- Automatic analysis or persistence of every agent session.
- Sharing private local history as a requirement for cross-machine operation.
- Letting an imported bundle, producer output, repository instruction, or test
  grant mutation, command, publication, or acceptance authority.
- Replacing existing language/framework test systems or project-specific CI.

## Future Extension Boundary

A later GitHub or other scheduler adapter may run the same local CLI from the
trusted default branch, execute bounded paired experiments in isolated workers,
and open a draft PR only for a clear improvement. Such an adapter must keep the
evaluated agent separate from write credentials, use hidden holdouts, publish
only sanitized canonical evidence, request narrow repository permissions, and
never approve or merge its own proposal. The v1 protocol and portable bundle
must make this possible without including provider-specific behavior now.

## Dependencies

- Existing Agent Kit catalog, packaging, validation, and plugin-generation
  infrastructure.
- Existing local behavioral-evaluation harness patterns and synthetic fixtures.
- Existing project-review, verification, and consumer-owned adaptation
  conventions.
- Python 3.11 or newer for deterministic runtime helpers.
- An explicitly selected local agent runner only for model-backed executions.
