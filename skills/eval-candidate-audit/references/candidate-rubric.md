# Candidate rubric

## What deserves a candidate

Retain a candidate when selected evidence shows a repeatable repository task or
decision where an eval could measure a useful outcome: incorrect explanations,
failed implementation patterns, missing clarification, review churn,
verification gaps, or avoidable tool friction.

Do not retain generic dissatisfaction, model style preferences, one-off
environment outages, secrets, unrelated product ideas, or issues already fully
measured by an existing case.

## Grouping and recurrence

Group evidence only when the observable pain, desired behavior, and plausible
case boundary are materially the same. Evidence count counts cited events;
independent-session count counts distinct opaque session identities. The helper
derives confidence as low for one independent session, medium for two, and high
for three or more. It never derives importance.

## Existing coverage

Use `duplicate` when an existing case already measures the same behavior,
`extends` when the proposal is best represented as another parameter or phase,
`partial` when only part is covered, and `none` only after checking the supplied
suite. Cite only case IDs present in the frozen context.

Prefer a compact extension or refresh over another overlapping case. A duplicate
normally produces no new candidate unless the evidence supports refreshing or
strengthening the existing case; explain that precisely.

## Behavior and readiness

- `existing`: the intended outcome is already fixed by supplied repository
  behavior, tests, specifications, or owner policy.
- `new`: the proposal selects behavior not established by the evidence.
- `ambiguous`: multiple materially different outcomes remain plausible.

The finalizer derives readiness. New or ambiguous behavior and cost increase or
uncertainty require a decision. Existing behavior with unmet promotion
requirements needs more evidence. Only established, bounded, fully evidenced
proposals can be ready for a consumer to draft.
