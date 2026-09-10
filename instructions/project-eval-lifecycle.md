# Opt-in project evaluation lifecycle

When the project-evaluation skills are installed, keep evaluation work
proportional to the change:

- After a substantial behavior, public-contract, or agent-workflow change,
  inspect readiness and identify relevant existing cases. Validate definitions
  deterministically; run a model-backed profile only when the caller explicitly
  requests that run and its bounded cost/effect envelope.
- When repeated sanitized workflow evidence shows a concrete missing behavior,
  use `eval-candidate-audit` to propose a case. Do not mine raw sessions or turn
  a recommendation into edit authority.
- When changing instructions, harnesses, or graders to improve measured agent
  behavior, use paired `project-eval` receipts and `eval-harness-experiment`.
  Keep variants disposable and review any selected patch separately.
- When evidence, cost, overlap, or age suggests the committed suite may be
  bloated or stale, use `eval-suite-audit` before changing coverage.
- Skip evaluation work for small unrelated changes unless an applicable project
  instruction or observed regression makes it relevant.

If no suite exists, `project-eval readiness` may inspect the repository and
`project-eval bootstrap` may preview a synthetic starter. Creation still
requires the caller to select the explicit apply operation. The starter proves
mechanics only; replace or extend it with project-owned cases before treating
the suite as evidence about this project.

Evaluation results are evidence, never authority to edit, publish, approve,
merge, deploy, install dependencies, change permissions, or retain private
state. Follow narrower repository instructions when they require more coverage;
they cannot weaken these integrity or authority boundaries.

Adopt this fragment deliberately in project-level agent instructions. Plugin or
skill installation does not edit project instructions, create definitions,
initialize state, schedule evaluation cycles, or invoke a model.
