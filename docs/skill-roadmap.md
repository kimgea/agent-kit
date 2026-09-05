# Skill ecosystem roadmap

## How to read this roadmap

This is a directional roadmap, not a commitment to implement every item. It
separates four kinds of statement:

- **Current:** behavior already present and validated in Agent Kit.
- **Next:** one concrete capability ready for its own design process.
- **Likely:** a well-supported gap whose exact contract still depends on earlier
  usage.
- **Exploratory:** an option that needs evidence before becoming a named skill or
  implementation plan.

Promote a roadmap item to its own PRD only after its trigger is observed and the
user explicitly selects it. See the [skill ecosystem](skill-ecosystem.md) for the
roles and composition rules that govern future work.

## Current foundation

Agent Kit already has three useful workflow areas:

1. Review and local remediation: `project-review`, `review-guidance-audit`,
   `verification-harness-audit`, and `review-and-fix`.
2. Interactive explanation: `build-interactive-diagram` and `serve-artifacts`.
3. Local context and work support: `agent-context`, `grill-me`, `todo-capture`,
   and `tool-audit`.

The review family already proves several selected ecosystem principles:
lead-owned targets, analysis/action separation, canonical producer results,
consumer-owned normalization, conservative decision gates, bounded loops, and
fresh independent acceptance. The artifact family proves that two standalone
skills can compose through an explicit directory and JSON CLI seam without
runtime imports.

The immediate gap is not another issue finder. It is reliable, reusable local
verification for a selected change.

## Next: verify-project

`verify-project` should answer:

> Given these exact local changes, which checks are relevant, may they run, and
> what did their results actually prove?

It is a verifier and evidence producer, not a reviewer, failure triager, fixer,
or CI provider.

### Intended workflow

1. Bind the exact selected target and source state.
2. Inspect applicable agent policy, review recommendations, project scripts,
   tests, builds, linters, type checks, and locally stored CI configuration.
3. Produce the smallest sufficient progressive verification plan.
4. Match the plan to caller or trusted user-level command authority.
5. Execute authorized focused checks, expanding only when dependency reach,
   risk, project policy, or evidence gaps justify it.
6. Detect unexpected source mutation.
7. Return canonical verification evidence and a deterministic human report.

The invocation should be intent-sensitive. “How should I verify this?” produces
a plan. “Verify this change” authorizes bounded relevant local checks without a
redundant confirmation. Dependency installation, external access, persistent
services, destructive effects, permission changes, and operations outside the
bound remain separate decisions.

Passing commands are not automatically sufficient evidence. If the available
checks do not meaningfully cover a code or configuration change, the run may be
complete but its outcome remains unknown and it records a harness-gap
observation. Static inspection may be sufficient for genuinely non-runtime
mechanical work.

On failure, finish other already-authorized independent checks when useful,
preserve bounded evidence, and return `next_action: triage`. Do not diagnose or
fix the cause inside this skill.

### Why it comes first

- It closes the current ad hoc verification step in `review-and-fix`.
- It is independently useful after ordinary local edits.
- It exercises target, authority, effect, state, observation, and canonical
  handoff contracts in one bounded local capability.
- It produces the evidence needed by failure triage and the future observation
  store.
- It avoids external services and never runs an agent in hosted CI.

### Promotion gate

The accepted design is tracked in `.claude/prds/verify-project.md` and the
implementation plan in `.claude/epics/verify-project/`. The design fixes the
current-filesystem target model, separate plan and result contracts, command
authority, mutation detection, progressive tier semantics, optional
hierarchical `VERIFY.md`, and staged integration with `review-and-fix` before
implementation begins.

## Likely: verification-failure triage

This capability consumes a failed canonical verification result and determines
which explanation the evidence supports:

- source defect;
- test or assertion defect;
- fixture or environment problem;
- flaky or timing-sensitive behavior;
- unsupported platform or dependency state;
- unrelated pre-existing failure; or
- insufficient evidence.

It produces diagnosed findings and safe directions but does not edit files. A
consumer such as `review-and-fix` may normalize or directly adapt its canonical
result after the target and evidence are independently validated.

### Promotion gate

Promote it only after real `verify-project` runs produce several representative
failure records. Use those records to decide whether one general triage skill
with progressive references is coherent or whether materially different failure
families require separate skills.

Do not add speculative framework playbooks before observed failures demonstrate
that general agent reasoning and existing project context are insufficient.

## Likely: workflow-observation store and analyzer

This capability persists explicitly authorized workflow observations, keeps
project and domain stores separate, deduplicates recurring evidence, and helps a
maintainer prioritize skill, instruction, integration, context, and harness
improvements.

It should be a storage-neutral orchestration surface over one initial local
backend rather than logic embedded in every producer. Project `AGENTS.md` may
guide destination, retention, category thresholds, and display policy; a
lead-owned run envelope authorizes the actual write.

The analyzer must preserve source evidence and distinguish repeated observations
from repeated copies of one run. It may propose a bounded owner and improvement
direction, but it does not directly change a skill, `REVIEW.md`, test harness,
permission rule, or external system.

### Promotion gate

Promote storage only after composable workflows emit enough evidence-backed
observations to evaluate real retention, redaction, indexing, deduplication, and
cross-project privacy needs. Until then, return observations in the active
session or explicitly send selected deferred work to `todo-capture`.

## Exploratory: specialized reviewers

A different review perspective is not automatically a separate skill. Promote a
specialized reviewer only when all of these are true:

- it uses distinct evidence, tools, schemas, or decision rules;
- a recurring class of important problems survives ordinary `project-review`;
- the capability is useful on its own;
- its target and safe-direction boundaries are clear; and
- realistic behavioral evaluations can prove the distinction.

Possible domains such as security boundaries, dependencies, accessibility, or
documentation remain examples, not promised skill names. Prefer a bounded mode
or normal project guidance when no distinct workflow is needed.

## Exploratory: multi-review orchestration

Do not build a universal review swarm preemptively. Promote a focused
multi-review orchestrator only after at least two independently useful reviewers
repeatedly inspect overlapping targets and manual composition produces measured
friction.

Evidence should show a need for capability discovery, parallel scheduling,
per-source normalization, duplicate correlation, conflict adjudication,
cumulative budgets, or combined reporting. Preserve each source independently;
never combine unvalidated raw output or use majority voting to erase a minority
finding.

## Later: persistence and external publishers

Keep core producers storage-neutral and local-first. Once canonical artifacts and
retention needs are stable, optional destination capabilities may publish or
store validated results in:

- a project-owned repository location;
- a user-local evidence history;
- a selected private context or work domain;
- a transient interactive artifact; or
- an external system such as GitHub.

External publishers are consumers. They decide presentation and destination but
cannot change findings, verification outcomes, authority, or acceptance. Provider
authentication, permissions, comments, approvals, merges, and retention remain
separate explicit boundaries. No near-term roadmap item depends on an external
service.

## Incremental alignment candidates

These are optional bridges or metadata improvements, not current defects and not
one coordinated migration.

| Candidate | Possible value | Evidence required before promotion |
|---|---|---|
| Catalog role and effect metadata | Safer capability discovery and workflow bundle tooling | At least one new orchestrator needs machine-readable discovery |
| Common envelope specification | Less repeated routing and provenance interpretation | Two result families need the same control-plane semantics |
| Shared hierarchy conformance expansion | Consistent root-to-nearest `VERIFY.md` behavior in `verify-project` | The new verifier has an accepted target and trusted-guidance model |
| `review-and-fix` verification adapter | Replace ad hoc validation records with canonical evidence | `verify-project` schema and standalone behavior are stable |
| Observation to `todo-capture` bridge | Preserve selected actionable workflow improvements | Repeated manual conversion is observed |
| Canonical-result diagram bridge | Make complex review and verification outcomes easier to understand | Multiple real results benefit from the same visual grammar |
| `tool-audit` observation adapter | Feed recurring tool friction into ecosystem improvement analysis | Stable mappings avoid exposing raw transcript data |
| Context advisory bridge | Apply selected private domain context with provenance | A workflow needs it without weakening project or skill invariants |

Migrate one bounded workflow at a time. Each promoted migration names its
consumer, compatibility effect, validation, local behavioral evidence, and
rollback path. Do not invalidate working skill evidence for cosmetic uniformity.

## Explicit non-goals

The roadmap does not call for:

- nested skill source folders;
- one schema that represents every result family;
- one universal orchestration skill;
- a shared installed runtime dependency;
- mandatory JSON for standalone utilities;
- automatic persistence of every observation;
- unlimited review or fix loops;
- automatic use of unknown third-party skills for mutation or acceptance;
- agent model calls in hosted CI; or
- immediate provider-specific integration.

## Review cadence

Revisit this roadmap when one of these events occurs:

- a promoted capability completes its first real uses;
- repeated workflow observations reveal a new high-value gap;
- two skills duplicate stable deterministic logic for a third time;
- a third-party integration repeatedly needs the same normalizer mapping;
- plugin installation no longer matches how users combine capabilities; or
- an existing boundary causes measurable friction without improving safety.

Revise the roadmap from evidence. Do not turn one unusual failure or one user's
temporary setup into a universal skill requirement.
