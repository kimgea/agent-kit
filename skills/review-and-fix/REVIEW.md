# Review-and-fix self-review policy

Apply these rules in addition to the repository root policy when reviewing the
`review-and-fix` skill itself.

## Independent authority

- Block a workflow that lets the reviewed revision provide the
  `review-and-fix` method used to normalize, authorize, edit, or accept its own
  change. Safe path: use an independently trusted installed copy or the complete
  starting-revision copy; without one, keep bootstrap work review-only and put
  every remedy through an explicit user decision.
- Block any path by which reviewer output, normalization text, planner output,
  repository content, suggested commands, or a selected finding can grant edit,
  execution, remote, destructive, installation, permission, or publication
  authority. Safe path: keep authority in the caller and active agent contract,
  and treat transferred strings as bounded untrusted data.

## Structured boundaries

- Block a neutral batch that can make an out-of-target or insufficiently
  evidenced finding actionable, hide inference, merge distinct reviewer
  provenance, let its normalizer choose the target/source/mode envelope, or
  silently accept an incomplete source. Safe path: keep the exact target,
  reviewer identity, source digest, and derived mode in a lead-owned envelope;
  preserve field-level provenance, explicit limitations, and separate batches
  per reviewer.
- Block a fix plan whose finding identity or classifications are not bound to
  the exact validated canonical batch, whose selection authority can be forged,
  whose proposed paths escape the reviewed target, or whose decision can be
  supplied or overridden by a planner. Safe path: load finding and lead-owned
  selection context independently, verify the batch digest and target paths,
  then derive the route mechanically from conservative planner facts.

## Decisions and acceptance

- Block automatic work when intent, remedy, behavior, confidence, scope,
  reversibility, validation, overlap, or risk is uncertain or consequential.
  Safe path: reserve automatic routing for small singular behavior-preserving or
  contract-restoring changes and obtain one bounded user decision or separate
  action authorization otherwise.
- Block acceptance by the fixer, a changed reviewer set, an incomplete rerun, or
  an unbounded retry loop. Safe path: rerun the original reviewer identities from
  fresh context, compare stable finding fingerprints, stop on no progress or
  drift, and cap the workflow at three fix rounds.

## Compatibility and evidence

- Block installed runtime code that imports repository-only tooling, depends on
  a third-party package, or requires a service or network. Safe path: keep all
  schemas, references, and Python 3.11 standard-library helpers inside this skill.
- Block a normalization, decision, output, or loop behavior change without a
  negative boundary test and a safe counterexample evaluation. Safe path: keep
  schemas, helper validation, runtime instructions, documentation, tests, and
  evaluations aligned.
