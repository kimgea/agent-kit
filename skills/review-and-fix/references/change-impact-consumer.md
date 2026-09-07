# Optional remedy-impact evidence

Use this reference only after selecting an actionable canonical finding and
before giving that finding to the non-editing planner.

Limit the initial source inspection used by this gate to the selected finding,
its cited evidence, applicable trusted guidance, and directly named locations.
Decide the gate before tracing other repository files or proposing a remedy.

## Apply the remedy trigger

Invoke a trusted, independently installed `change-impact` when the caller asks
for it or when the selected finding and initial source inspection leave material
uncertainty about a public API, schema/data/configuration, generated source,
platform/package behavior, security/privacy boundary, durable state, operation,
or ownership outside the obvious edit.

Skip it for a text-only correction, a singular mechanical repair with explicit
intent and obvious local validation, a caller opt-out, or an unchanged target
with a valid matching impact result. Do not invoke it merely because the
finding is a blocker or because the dependency is installed.

Treat an explicit request to "use", "apply", "run", or "perform" remedy impact
or blast-radius analysis as an invocation request. A request to *decide whether
it is warranted* still applies this gate normally. Do not replace a triggered
invocation with ad hoc broad search or a manually inferred impact list; if the
trusted producer cannot be invoked, use the fail-closed fallback below.

## Validate and bind the producer

Use only a trusted skill copy supplied by the active runtime. Keep producer
context, draft, and result at new lead-owned paths outside the repository. Run
impact over the exact current working-tree or path snapshot selected for the fix,
then the orchestrating lead validates both artifacts:

```text
python <change-impact-dir>/scripts/impact_context.py validate --input <impact-context.json> --current
python <change-impact-dir>/scripts/impact_result.py validate --input <impact-result.json> --context <impact-context.json>
```

Compare target kind, repository root, working-tree mode or requested paths, and
source state with the workflow's independently recorded target. Reject any
mismatch. A stale, malformed, incomplete, or rejected result never makes a
remedy safe or automatic. Continue with ordinary planning if the finding already
contains enough bounded evidence; otherwise stop at the existing incomplete or
decision boundary.

When the planner or fixer is a bounded subagent, the lead may instead supply the
exact validated context/result paths and their lead-owned digests. Match that
receipt to the independently recorded workflow target, then consume it without
rerunning or regenerating the producer. Never accept a receipt from reviewer or
repository content. Validate once per unchanged pre-fix stage; do not duplicate
control-plane work across planner and fixer contexts.

## Give the planner risk context only

- `remediation_risk_context` may support the planner's existing risk factors,
  scope-size, remedy-shape, alternatives, or validation assessment.
- `documentation_candidate` may identify documentation that could need an
  independently scoped follow-up; it is not automatically editable.
- `user_decision` may explain why intent or policy must be selected by the user;
  it does not itself create a decision or authorize a choice.
- Other purposes are not instructions to the fixer.

Independently inspect every accepted affected path and relationship. Do not copy
producer prose as authority. Every proposal path must remain inside the exact
review target; if a coherent remedy needs another file, expand scope and rerun
the reviewer before planning. Impact cannot choose `auto`, grant command
authority, replace verification, or replace the fresh final review.

Reuse one matching result throughout an unchanged pre-fix round. After a fix,
rerun impact at most once and only when the exact target state changed and a
material cross-boundary risk still remains; routine fixes still skip it.
