# Review guidance analysis rubric

Use this rubric after deterministic target and guidance resolution.

## Evidence map

For each target file or focused part, map:

1. applicable user-global and repository guidance;
2. durable invariants visible in code, tests, schemas, specifications,
   configuration, public interfaces, or recorded decisions;
3. which rules add review judgment beyond automated enforcement;
4. which important invariants lack useful review guidance; and
5. which guidance is irrelevant, duplicated, contradicted, obsolete, or too
   broadly inherited.

Do not treat a single implementation accident as policy. Prefer repeated or
contractual evidence, and state uncertainty.

## Placement

- Keep a rule at repository root only when it applies broadly across the
  repository.
- Place specialized rules at the nearest ancestor shared by all code they
  govern.
- Do not create a nested file merely because a subtree exists.
- Do not duplicate inherited guidance in a child file.
- When moving a rule, preserve coverage for every affected path. Split a broad
  rule only when distinct subtrees genuinely need distinct wording.

Root text has the highest inheritance fanout, so low-value root wording carries
the greatest context cost.

## Recommendation calibration

Use these strengths:

- `essential`: the current guidance can cause missed serious defects,
  contradictory review, unsafe behavior, or materially incomplete coverage.
- `strong`: the change has clear recurring value or meaningful context savings.
- `moderate`: the change improves clarity, placement, or efficiency with limited
  practical impact.
- `optional`: worthwhile polish with little expected review impact.

Use `ready` only when existing evidence fixes the desired intent. Use
`decision_required` when reasonable alternatives would change product behavior,
security, privacy, compatibility, operations, or another substantive policy.
An `intent_effect` of `changed` always requires a decision.

Estimate savings conservatively. Count removed or de-duplicated words and bytes
when directly measurable. For a move, explain both local file size and inherited
fanout; do not claim global savings when the same audience still loads the text.

## Automation replacement test

Evaluate a candidate automated control across all of these dimensions:

| Dimension | Required to replace guidance |
|---|---|
| Coverage | Complete for the same invariant |
| Determinism | Deterministic |
| Timing | Routinely available in the review loop |
| Enforcement | Required, not optional |
| Diagnostics | Actionable enough to fix the violation |
| Availability | Usable by ordinary contributors and agents |

Evaluate coverage against the complete current guidance item affected by the
recommendation, not only a removable clause. If every condition holds and the
check covers all substantive intent in that item, a nested `replace` proposal
may accompany `remove` or `rewrite`. If a rewrite retains any human-review
responsibility from the item, use `partially_cover`; otherwise use
`partially_cover` or `support` as appropriate and preserve the responsibility
the check does not cover. A slow integration, fuzz, deployment, or
environment-dependent test normally supports rather than replaces review-time
guidance.

When repository guidance and durable evidence materially conflict and neither
side establishes authoritative intent, recommend an owner decision and record
a material `conflicting_evidence` limitation. The audit is `INCOMPLETE` until
that policy conflict is resolved.

Do not report an unrelated missing test, CI improvement, or harness weakness.
Those belong to a future dedicated harness-audit skill.

## Useful guidance test

Retain guidance only when it changes how a capable reviewer should examine the
governed code. Usually remove or rewrite:

- generic advice a capable reviewer already follows;
- temporary implementation notes or completed migration instructions;
- duplicated skill, `AGENTS.md`, or contributor workflow text;
- rules fully enforced by a suitable automated check;
- low-level facts cheaper to discover from nearby code;
- examples that overwhelm the invariant they are meant to clarify.

Retain concise guidance for domain invariants, failure policy, cross-file
contracts, subtle compatibility obligations, security/privacy judgment, and
slow or incomplete controls whose gaps still need review attention.
