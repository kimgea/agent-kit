# Post-fix verification adapter

Use this profile after an applied fix and before the original reviewer runs
again. Verification is evidence, not review acceptance, edit authority, or
permission to execute a command.

## Select the profile before fixing

Record one lead-owned `verification_profile` in the review-and-fix run context:

- `verify_project` when an independently trusted `verify-project` installation
  is available; or
- `bounded_validation_fallback` when it is unavailable.

The fixer cannot switch profiles. The fallback preserves the existing bounded
validation workflow, but the final result labels that canonical verification
was not used.

## Produce a fresh verification result

For `verify_project`, start a fresh verifier after the exact fix is applied.
Resolve the same current path set or combined working-tree target with
`--fresh-context --consumer review-and-fix`. The verifier may receive only
lead-owned caller/agent policy and command candidates appropriate to that exact
post-fix target. It cannot expand the edit target or add execution authority.

Validate the canonical plan and result with the producer's own installed
helpers before using the consumer adapter:

```text
python <verify-project-dir>/scripts/verification_plan.py validate --input <plan.json>
python <verify-project-dir>/scripts/verification_result.py validate --input <result.json>
python <review-and-fix-dir>/scripts/review_workflow.py adapt-verification \
  --input <result.json> \
  --context <context.json> \
  --plan <plan.json> \
  --target <review-target.json>
```

The adapter independently checks the exact lead target projection, canonical
context and plan digests, producer/version/consumer provenance, fresh-context
claim, target/context/plan stability, evidence sufficiency, protected state,
and exact-plan adherence. Its compact output intentionally omits commands,
claims, proposed edits, and authority.

## Apply the gate

Only `state: passed`, `reason: verified_pass`, and
`fresh_review_eligible: true` permits the original reviewer set to run again.
Every other state stops first:

- `failed` preserves the verifier's `triage` or other safe next action;
- `unknown` preserves the evidence-gap next action;
- `incomplete` preserves or derives a safe action for unavailable evidence,
  target/context/plan drift, unsafe mutation, or a non-fresh verifier; and
- a missing result after a fix stops as `verification_required`.

Supply the same three canonical producer files to both run finalization and
later validation:

```text
python <review-and-fix-dir>/scripts/review_workflow.py finalize-run \
  --input <run-draft.json> \
  --context <run-context.json> \
  --verification-context <context.json> \
  --verification-plan <plan.json> \
  --verification-result <result.json>
```

The canonical workflow result retains only their canonical digests and derived
gate state. Keep the producer files only when the caller requests a durable
structured result that must be revalidated later.

## Fallback

When `verify-project` is absent, use the existing plan-bound validation records.
Command validation still requires caller or user-global authority recorded in
the lead-owned context; static validation remains limited to plans that declared
it sufficient. A successful fallback may proceed to fresh review, but the final
record remains `profile: bounded_validation_fallback` with reason
`verify_project_unavailable`. Do not describe it as canonical verification.
