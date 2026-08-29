# Project-review self-review policy

Apply these rules in addition to the repository root policy when reviewing the
`project-review` skill itself.

## Trusted guidance

- Block a review in which the reviewed revision supplies or modifies the
  `project-review` skill used to judge itself. Safe path: use a trusted
  independent copy not produced from the reviewed state or the complete skill
  directory from the trusted starting revision; when neither exists, require an
  explicitly selected bootstrap method or return `INCOMPLETE`.
- Block a change review that lets `REVIEW.md` guidance from the reviewed revision
  govern itself. Ref ranges must use the starting revision, working-tree reviews
  must use committed `HEAD`, and explicit snapshots must disclose that they use
  the current filesystem. Safe path: keep guidance resolution separate from
  semantic review and preserve both source and destination chains for renames.
- Block any route by which repository source, `REVIEW.md`, command output, or
  result data can weaken the skill's locked safety, evidence, output, or verdict
  rules. Safe path: treat all reviewed material as untrusted data and keep
  authority in the caller, user-global policy, and skill contract.

## Canonical scope and result

- Block a valid resolver result that cannot be represented and finalized within
  the canonical schema limits. Every requested change and reviewed coverage
  group must retain its exact path and guidance-chain association; omissions or
  truncation must become explicit limitations. Safe path: evolve resolver,
  schema, validator, renderer, tests, and schema version together.
- Block hand-authored or independently derived prose that can disagree with the
  canonical JSON. Safe path: finalize and validate one result, derive counts,
  fingerprints, and verdict mechanically, and render human output from that
  validated result.

## Analysis-only and command authority

- Block behavior that edits reviewed files, installs dependencies, starts a
  persistent service, mutates remote state, publishes findings, approves, or
  merges. Safe path: return analysis and verdict only; leave mutation to an
  explicit consumer workflow.
- Block verification launched solely because repository or folder guidance
  recommends it. Safe path: use static inspection unless the current caller or
  a bounded active-agent user-global `REVIEW.md` authorizes the exact command or
  command class, then still apply normal execution permissions.

## Path, data, and output safety

- Block path escape, symlink or reparse-point traversal, unsafe Git option
  interpretation, silent unreadable-file omission, or cross-platform path
  ambiguity. Safe path: canonicalize bounded repository-relative paths, reject
  link-like inputs, terminate Git options, and surface material limitations.
- Block raw guidance, secret-like content, control characters, or active HTML
  from leaking into canonical provenance or executable-looking human output.
  Safe path: store bounded digests and metadata, escape every rendered field,
  and refuse unsafe or accidental output-file replacement.

## Compatibility and evidence

- Block an installed helper that requires repository-only code, a dependency
  outside the Python 3.11 standard library, or Git for an explicit snapshot.
  Safe path: keep the installed skill self-contained and require Git only for
  ref-range and working-tree scopes.
- Block a behavior change to resolution, schema, verdict, verification,
  rendering, or file output without a focused boundary test, or a judgment or
  orchestration change without a behavioral evaluation and safe counterexample.
  Safe path: add the smallest test or evaluation that proves both the protected
  behavior and a valid case that must remain accepted.
