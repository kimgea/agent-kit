# Verify project

`verify-project` plans or performs evidence-driven local verification for an
exact current-filesystem target. It answers three separate questions:

1. Did the verification workflow complete?
2. What did the evidence establish about the selected change?
3. What kind of next action is justified?

It is not a code reviewer, failure triager, fixer, command proxy, CI provider,
or external-service integration. Passing commands are evidence only when they
cover the material claims selected for the target.

## Modes and target

Use plan mode for questions such as “how should I verify this?” Use execution
mode when the caller directly asks to verify or check selected local changes.
That direct request authorizes bounded ordinary local checks; it does not
authorize dependency installation, networking, persistent services,
destructive actions, permission changes, remote mutation, or work outside the
repository and one run-owned temporary root.

V1 accepts either:

- the combined current Git working tree relative to committed `HEAD`; or
- explicit current files, directories, or `.` for the project.

It does not claim staged-only, commit, ref-range, pull-request, or historical
verification. Related tests and configuration provide context without silently
expanding the target.

## Hierarchical verification guidance

An optional `VERIFY.md` can describe evidence requirements near the code. For
each selected file, guidance loads from repository root to the nearest ancestor.
Broader requirements accumulate unless a closer file explicitly names the
broader rule it replaces and the subtree where the replacement applies.

In a Git repository, committed `HEAD` supplies repository guidance. A new or
changed working-tree `VERIFY.md` is target content, not active policy for its
own introduction. Non-Git projects use current guidance with explicit
provenance. The installed skill remains complete without any `VERIFY.md`.

Good guidance states required evidence, conditions for broader checks, scoped
replacements, and exact expected disposable artifact prefixes. It does not
copy the skill contract, grant command authority, or embed general release
procedure.

## Canonical workflow

The installed standard-library helpers separate lead-owned facts from semantic
agent judgment:

1. `verification_context.py` freezes target, repository state, guidance,
   discovery sources, policy provenance, command candidates, limits, and
   authority.
2. A semantic planner selects only frozen candidate IDs and maps them to target
   claims. `verification_plan.py` injects exact commands and mechanically
   derives the canonical plan.
3. The active agent executes each authorized exact argv visibly through its
   ordinary tool interface. `verification_result.py snapshot` binds state
   immediately before and after every command.
4. A semantic evidence pass classifies canonical claims.
   `verification_result.py` binds execution facts, derives completion/outcome/
   next action, validates the result, and renders human output.

The JSON Schemas live beside the skill references. Human reports are rendered
from the same validated canonical plan or result; they are not a parallel
source of truth.

Representative helper flow:

```bash
python skills/verify-project/scripts/verification_context.py \
  --repo . --mode execute --direct-execution-intent \
  --candidate-input /lead-owned/candidates.json \
  --output /lead-owned/context.json \
  paths src/module.py

python skills/verify-project/scripts/verification_plan.py finalize \
  --context /lead-owned/context.json \
  --input /lead-owned/plan-draft.json \
  --format json --output /lead-owned/plan.json

python skills/verify-project/scripts/verification_result.py snapshot \
  --plan /lead-owned/plan.json --output /lead-owned/before.json

python skills/verify-project/scripts/verification_result.py finalize \
  --plan /lead-owned/plan.json --run /lead-owned/run.json \
  --input /lead-owned/result-draft.json \
  --format json --output /lead-owned/result.json
```

The examples use separate lead-owned files outside the repository so project
commands cannot replace control-plane inputs or evidence. Every output is
create-only. The helper scripts never dispatch an arbitrary project command.
The resolver also leaves inline evaluation and generic or privilege-changing
dispatchers unauthorized; use exact inspected project scripts or module entry
points instead.

## Progressive evidence and failure behavior

Checks use `focused`, `subsystem`, and `project` tiers. Start with the smallest
plan that could establish all material claims. Expand only when dependency
reach, risk, trusted policy, or an evidence gap requires it.

Execution is sequential. Repetitions and dependencies are frozen before the
first command. A non-passing attempt is terminal; the verifier does not retry
for a green result, diagnose the failure, or add commands. It may finish only
already-planned independent checks whose evidence remains useful after failure.

The result keeps these axes independent:

| Completion | Outcome | Meaning |
|---|---|---|
| `complete` | `pass` | Every material claim and active required guidance mapping is supported, and state stayed safe |
| `complete` | `fail` | Executed evidence disproved a material claim |
| `complete` | `unknown` | Work finished but evidence coverage was insufficient |
| `incomplete` | `unknown` | Required evidence could not be obtained or trusted |

An unavailable check is not a failed change. An irrelevant green check is not
a pass. Explicit caller caps can produce `unknown`, but never weaken the pass
contract.

## Mutation boundary

The resolver inventories protected visible repository state, including
pre-existing ignored and untracked data. Only exact new outputs within frozen
repository or temporary artifact boundaries are disposable. The snapshots and
finalizer reject aliases, links, reparse points, hard links, special files,
pre-existing paths presented as new, out-of-bound effects, and digest mismatch.

When temporary output is planned, the lead supplies one empty directory outside
the repository. The canonical result retains only a hashed filesystem identity.
The verifier reports unexpected mutation and stops; it never cleans, restores,
or overwrites user files automatically.

## Consumers and local evaluation

Direct use defaults to concise text. Another skill or agent can request
canonical JSON and independently validate its target, provenance, coverage,
completion, outcome, and next action. The result does not authorize edits,
commands, publication, or acceptance.

`review-and-fix` is the first shipped consumer. Its deterministic adapter
freezes and invokes the trusted installed producer's validators over the exact
context, plan, and result before applying its own cross-binding checks. It then
requires a fresh, target-matched, complete, sufficiently covered `pass` before
invoking the fresh acceptance reviewer. Other outcomes stop with the verifier's
derived next action.

Deterministic tests and graders run in the canonical local gate and hosted CI.
Fresh model-backed behavioral evaluations are opt-in local maintainer runs; no
agent model is invoked by GitHub Actions.

Validate the executable suite without a model:

```bash
python scripts/behavioral_eval.py check --suite verify-project
```

Run the fresh behavioral evaluation locally when the skill, harness, fixtures,
or acceptance contract changes materially:

```bash
python scripts/behavioral_eval.py run --suite verify-project \
  --runner codex --model gpt-5.6-sol --reasoning-effort medium
```

The local run freezes skill, helper, suite, fixture, target, context, plan, and
result digests. It retains compact canonical evidence and grader outcomes, not
raw transcripts. Hosted CI validates the suite, adapters, schemas, and selected
stored evidence without invoking or paying for an agent model.

## Installation

Install the complete `skills/verify-project` directory. Runtime helpers use only
Python 3.11 standard-library modules and import only files shipped inside that
directory. Git is required for combined working-tree scope and improves
discovery; explicit non-Git path verification remains supported.
Working-tree rename matching hashes bounded file bytes locally and never invokes
repository-configured clean filters before command authority is established.
