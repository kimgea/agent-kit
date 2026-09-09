---
name: project-eval-system
status: completed
created: 2026-09-08T13:34:04Z
updated: 2026-09-09T01:51:46Z
progress: 100%
prd: .claude/prds/project-eval-system.md
github: (will be set on sync)
---

# Epic: project-eval-system

## Overview

Deliver a coordinated four-skill evaluation system over Agent Kit's proven
local behavioral-evaluation boundaries. The first vertical slice defines and
runs repository evaluations through `project-eval`; later slices mine candidate
cases, curate suite lifecycle, and perform bounded paired harness experiments.

## Architecture Decisions

- Keep canonical skill sources flat under `skills/`; package the four skills as
  one workflow plugin while preserving standalone archives.
- Keep every installed skill self-contained. Compose through canonical JSON and
  portable bundles, never repository-only or cross-skill runtime imports.
- Let `project-eval` own suite execution, optional private history, comparison,
  import/export, and selected eval-definition maintenance.
- Keep `eval-candidate-audit`, `eval-suite-audit`, and
  `eval-harness-experiment` storage-neutral. They write only an explicitly
  selected result or candidate-patch destination.
- Use separate schemas per artifact family with compatible shared envelope
  concepts; do not introduce one global protocol version.
- Use explicit repository manifests under a selected eval root, with
  `evals/project/` as the recommended convention. Do not introduce hierarchical
  `EVAL.md` guidance.
- Keep the evaluator control plane, hidden graders, holdouts, expected behavior,
  and result capture outside the evaluated agent's workspace.
- Use deterministic-first grading and make qualitative judgment blinded and
  advisory.
- Support a fixed tested Codex adapter in v1 and agent-neutral recorded-output
  grading. Do not claim a Claude adapter before live evidence exists.
- Run offline and hermetically by default. Networked cases require a separate
  explicit profile and authorization.
- Treat imported bundles as validated external evidence, never authority.
- Require paired baseline/candidate observations before claiming harness
  improvement.
- Keep scheduled GitHub runs, publisher credentials, automatic PR creation, and
  hosted model calls as future adapters outside this epic.

## Technical Approach

### Protocol and definition core

Define bounded JSON schemas and deterministic validators for suite/case
definitions, run results, evidence bundles, candidate recommendations,
experiment results, and suite lifecycle recommendations. Share stable naming and
provenance semantics in documentation and conformance fixtures while allowing
each schema to version independently.

### Evaluation engine

Build a Python 3.11 standard-library engine inside `project-eval` that:

- resolves an explicit suite and profile;
- freezes definitions, fixtures, transforms, graders, target state, and runner
  configuration;
- prepares a sanitized disposable workspace;
- executes fixed trusted grading and optional agent adapters;
- enforces cumulative invocation, time, token/cost, network, write, and effect
  bounds;
- records host-observed or clearly attributed measurements; and
- emits canonical run receipts plus deterministic human output.

Reuse security and portability patterns from `scripts/behavioral_eval.py`, but
do not import that repository-only helper from an installed skill. Extend the
repository harness to behaviorally test the new skills rather than making it
their runtime.

### Case construction

Support explanation, implementation, and trajectory cases. Add evaluator-owned
transforms for goal-derived reconstruction and a constrained fact responder for
clarification. Add calibration that proves start failure, golden success,
protected-source non-leakage, and alternative-solution tolerance.

### Private evidence and bundles

Use OS-native private state with a Git-common-directory opaque namespace link.
Store immutable JSON receipts and content-addressed bounded evidence with atomic
writes and a rebuildable index. Add deterministic safe archive export/import;
an imported receipt retains external provenance and cannot become baseline or
mutation authority by validation alone.

### Analysis-only producers

Implement candidate and lifecycle audits with lead-owned contexts and canonical
finalizers. Candidate audit accepts selected sanitized session evidence and
proposes deduplicated cases. Lifecycle audit accepts definitions plus explicitly
selected compatible evidence and recommends compact, evidence-preserving suite
maintenance.

### Experimentation

Implement a bounded experiment orchestrator that accepts a predeclared
objective, editable surfaces, suites, comparison profile, and budget. It
materializes baseline and variants independently, ranks only quality-qualified
results, and returns candidate patches without changing the active checkout.

## Implementation Strategy

1. Freeze protocol, path, archive, and private-state boundaries before model
   execution.
2. Implement deterministic case preparation and grading, including adversarial
   boundary tests.
3. Add one fixed Codex runner and prove process, secret, control-plane, and
   mutation containment.
4. Deliver the minimum useful `project-eval` workflow with explanation and
   implementation cases plus portable evidence.
5. Build candidate and lifecycle producers independently over frozen contracts.
6. Add paired experiment orchestration after comparison semantics have real
   results to consume.
7. Dogfood all four skills, add behavioral evaluations, align documentation and
   packaging, and deliver through independent review.

## Task Breakdown Preview

- 001: Define protocol, manifests, private state, and portable bundles.
- 002: Implement isolated case preparation, deterministic grading, and
  calibration.
- 003: Add the fixed Codex runner, budgets, measurement, and containment.
- 004: Deliver `project-eval` workflows and the first realistic suites.
- 005: Deliver `eval-candidate-audit` for selected session evidence.
- 006: Deliver `eval-suite-audit` for evidence-backed suite maintenance.
- 007: Deliver `eval-harness-experiment` with paired comparisons.
- 008: Integrate the workflow plugin, dogfood cases, documentation, packaging,
  and delivery evidence.

## Dependencies

- Existing catalog, plugin generation, packaging, and canonical validation.
- Existing local behavioral-evaluation harness as tested repository
  infrastructure and a source of established containment patterns.
- Existing canonical result, lead-owned target, consumer-owned adaptation,
  review, and verification conventions.
- Python 3.11 or newer.
- A local authenticated Codex CLI only for explicit model-backed test runs.

## Success Criteria (Technical)

- The minimum vertical slice runs from a fresh clone without private state.
- All canonical artifacts reject malformed, oversized, drifting, or
  authority-forging input and render human output from validated JSON.
- Evaluated agents cannot observe or mutate control-plane definitions, graders,
  holdouts, results, credentials, or the active checkout.
- Portable bundles round-trip across clean checkouts with exact member digests
  and retain external-evidence classification.
- Deterministic checks and behavioral cases cover explanation, implementation,
  reconstruction, clarification trajectory, suite trimming, candidate
  deduplication, paired improvement, tradeoffs, and stopping rules.
- Hosted CI runs only deterministic validation and never invokes an agent model.
- The four skills package independently and as one coherent plugin.

## Estimated Effort

Eight staged tasks. Tasks 005 and 006 may proceed in parallel after the
`project-eval` contracts stabilize. All model-backed evidence remains explicit,
local, bounded work.

## Tasks Created

- [x] 001.md - Define protocols, state, and portable bundles (parallel: false)
- [x] 002.md - Build isolated case preparation and grading (parallel: false)
- [x] 003.md - Add the fixed Codex runner and measurement (parallel: false)
- [x] 004.md - Deliver the project-eval vertical slice (parallel: false)
- [x] 005.md - Add eval candidate audit (parallel: true)
- [x] 006.md - Add eval suite lifecycle audit (parallel: true)
- [x] 007.md - Add paired harness experimentation (parallel: true)
- [x] 008.md - Integrate, dogfood, validate, and deliver (parallel: false)

Total tasks: 8
Parallel tasks: 3
Sequential tasks: 5
Estimated total effort: 50-70 hours
