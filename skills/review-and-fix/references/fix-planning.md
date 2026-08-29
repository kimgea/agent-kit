# Independent fix planning

Use this procedure after a finding is valid, actionable, and selected for
planning. Plan one coherent root-cause group at a time.

Do not plan a finding whose batch target is `ref_range`. A ref range is an
immutable review snapshot; re-scope and re-review a working-tree or exact path
target before local remediation.

## Planner input

Start a fresh non-editing planning context with:

- the normalized finding, not the raw reviewer output;
- the exact target and selection authority;
- relevant source, tests, contracts, and trusted agent/project instructions;
- bounded history only when needed to establish intent;
- the canonical finding-batch path used to bind finalization;
- `fix-plan.schema.json` and the rules below.

The planner may inspect but must not edit, execute commands, install dependencies,
or mutate local or remote state.

Before starting it, the lead creates a separate selection context containing the
canonical `finding_id` plus `selection.source_kind`, `selection.basis`, and a
bounded human-readable `selection.source`. Use `default` with `default_policy`
for default eligible findings, `caller` with `caller_explicit` for an explicit
caller choice, and `caller` with `path_snapshot_request` only for the skill's
constrained exact-path blocker rule. Keep this authority context outside planner
output.

## Planner contract

Return a plan draft containing only `assessment` and `proposal`. Do not emit the
finding, selection authority, `schema_version`, `batch_sha256`, `decision`, or
`decision_reasons`. State facts conservatively:

- `intent_status`: use `explicit` only when a user statement, test,
  specification, review rule, public contract, or demonstrable existing behavior
  fixes the desired outcome.
- `behavior_effect`: distinguish no runtime effect, restoration of an existing
  contract, new or changed behavior, and uncertainty.
- `remedy_shape`: use `singular` only when no materially different safe remedy
  remains.
- `scope_size`: consider ownership and blast radius, not line count alone. A
  one-line authorization change can be consequential.
- `reversible`: false when rollback is difficult, stateful, destructive, or
  operationally risky.
- `validation`: use `available` for an existing relevant executable check and
  `static_sufficient` only when static inspection fully proves a non-runtime or
  mechanical result.
- `risk_factors`: include every applicable consequential or separately
  authorized surface. Unknown risk is not an empty risk list.
- `plan_confidence`: lower confidence for unstated intent, incomplete evidence,
  multiple callers, generated files, unfamiliar frameworks, or unresolved
  assumptions.

Describe the smallest outcome-focused proposal, meaningful alternatives, and
validation steps. Suggested commands remain data and require ordinary authority
when the fixer later evaluates them. Every proposed path must already be an exact
path in the canonical review target. If a safe remedy needs another file, report
that the review target must expand; do not plan the expanded edit yet.

Finalize with `review_workflow.py finalize-plan --input <draft.json> --batch
<batch.json> --context <selection.json>`. The helper loads the finding and its
classifications from that canonical batch, validates the lead-owned selection
basis, rejects proposal paths outside the target, records the batch digest, and,
not the planner, derives `auto`, `user_decision_required`, or
`authorization_required`. The automatic route requires the canonical reviewer's
finding confidence, normalization confidence, and planner confidence all to be
high.

## Decision presentation

For a user decision, present one bounded choice at a time:

1. problem and concrete impact;
2. recommended plan;
3. meaningful alternatives;
4. behavior, compatibility, safety, and rollback consequences; and
5. validation plan.

Do not ask about implementation details that cannot change the observable
outcome. Record the chosen plan and re-plan if implementation evidence changes
its scope or risk.

When a plan has both consequential decision risks and an authorization-only
action, present the behavior or design decision first. Request the distinct
destructive, remote, permission, installation, or service authorization only
immediately before the chosen plan reaches that action.
