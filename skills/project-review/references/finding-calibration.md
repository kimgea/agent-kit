# Finding calibration

Use this reference while converting verified issues into the canonical result.

## Contents

- [Required bar](#required-bar)
- [Disposition](#disposition)
- [Severity](#severity)
- [Confidence](#confidence)
- [Relation to scope](#relation-to-scope)
- [Noise controls](#noise-controls)

## Required bar

Report a finding only when all of these are true:

- a specific behavior, contract, or trusted review rule is violated;
- the affected path and relevant lines are identifiable, unless genuinely
  file-wide;
- the impact follows from inspected evidence rather than speculation;
- a safe remediation direction can be stated without redesigning the project;
- the finding is not merely a formatter, linter, or personal-style preference.

Verify delegated candidates in the lead before including them. If a material
claim cannot be verified, record a limitation; use `INCOMPLETE` when that gap
prevents a reliable pass.

## Disposition

- `blocker`: a high-confidence issue that must be addressed before accepting the
  reviewed change. It is introduced or worsened by the change, or a trusted rule
  explicitly requires touched code to meet the cited standard.
- `suggestion`: a valid, actionable improvement that does not prevent acceptance.
  This includes relevant pre-existing issues that the change does not worsen.
- `nit`: a valid low-impact polish improvement. Show nits last.

A finding's disposition is a review decision, not an impact score. A serious
pre-existing issue can have high severity and remain a suggestion for this change.

## Severity

- `critical`: likely exploitation, irreversible data loss, severe privacy breach,
  or widespread unrecoverable outage.
- `high`: serious correctness, security, compatibility, or availability failure
  affecting important users or contracts.
- `medium`: bounded functional, reliability, testing, or maintainability defect
  with a credible operational effect.
- `low`: minor impact, localized maintainability cost, or polish.

Use `low` for every nit. Do not inflate severity to express confidence or urgency.

## Confidence

- `high`: directly demonstrated by code flow, a focused check, or an explicit
  trusted rule with no material unresolved premise.
- `medium`: strong evidence exists, but one non-decisive premise remains.
- `low`: plausible lead that needs more evidence.

Every blocker must have high confidence. A low-confidence suspicion should
usually be omitted or represented as an evidence limitation, not a finding.

## Relation to scope

- `introduced`: absent at the trusted base and caused by the reviewed change.
- `worsened`: existed at the base, but the change materially increases its reach,
  probability, or impact.
- `pre_existing`: relevant and verified, but not worsened by the change.
- `uncertain`: available evidence cannot establish the relation.

Use `blocking_basis: change` for introduced or worsened blockers. Use
`blocking_basis: touched_code_policy` only when the governing trusted guidance
explicitly establishes that stronger standard. Otherwise use `null`.

An uncertain relation cannot block. If resolving it is necessary to decide
whether the change is acceptable, return `INCOMPLETE`.

## Noise controls

Omit:

- purely subjective naming or style preferences;
- formatting, import order, spelling, or lint violations already enforced by an
  available deterministic check;
- vague requests for more tests without a missing behavior or risk;
- hypothetical failures that require an unstated or implausible premise;
- duplicate symptoms of one root cause; and
- unrelated pre-existing defects found only while browsing context.

Prefer one root-cause finding with related locations over repeated file-by-file
comments. Keep titles imperative and specific, evidence factual, and safe
directions outcome-focused rather than prescribing an unnecessary rewrite.
