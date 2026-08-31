# Behavioral evaluation review policy

Use these additional rules for evaluation manifests and synthetic fixtures.

- Block a behavioral claim whose expected assertions are shown to the evaluated
  agent, whose fixture is materially unlike the claimed workflow, or whose
  grader depends on exact generated prose when a stable structured decision can
  be checked. Safe path: keep expectations grader-only, use a compact realistic
  repository, and assert canonical fields, paths, provenance, and observable
  effects.
- Block a committed fixture or result containing real user, machine, repository,
  credential, or transcript data. Safe path: keep fixtures synthetic and minimal
  and keep local run evidence under the ignored result directory.
- Block any suite data that selects executable commands, validators, schemas, or
  agent binaries. Safe path: add a reviewed fixed adapter in repository code and
  boundary tests for every executable surface.
- Block a normal validation or hosted workflow that invokes a paid or remote
  model. Safe path: keep real agent execution behind the explicit local
  `behavioral_eval.py run --runner ...` operation and test CI text for absence.
- Block a result accepted without binding it to lead-owned target context or
  checking fixture mutation. Safe path: resolve authority before agent
  invocation, retain its digest, independently compare it during grading, and
  fail the case on any audited-fixture change.
