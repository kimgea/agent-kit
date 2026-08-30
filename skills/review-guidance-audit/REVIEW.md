# Review-guidance-audit review policy

Use these additional rules for the installed skill under this directory.

## Scope and provenance

- Block a resolver change that permits an escaped, ambiguous, control-bearing,
  or link-following target or guidance path. Safe path: preserve canonical
  repository-relative paths, no-follow reads, bounded traversal, and negative
  tests.
- Block a result path that lets an agent-authored draft supply or alter authority
  fields, or that finalizes against resolver context whose current target,
  scope, or guidance has drifted. Safe path: copy authority only from lead-owned
  context, rerun the bundled resolver from its stored selection, and reject any
  mismatch before accepting the draft.
- Block a recommendation whose guidance reference is not applicable to every
  affected target, whose evidence escapes the target, declared context, or
  repository guidance, or whose file-part evidence misses the exact part. Safe
  path: bind provenance, target IDs, paths, and evidence to resolver-owned scope.

## Recommendation integrity

- Block a ready recommendation that changes substantive intent or silently
  establishes new product, security, privacy, compatibility, or operational
  policy. Safe path: mark it `decision_required` and describe the evidence and
  alternatives.
- Block a relocation that loses governed paths or places narrow guidance above
  unrelated code. Safe path: validate the destination as a shared applicable
  ancestor and preserve affected-path coverage.
- Block a canonical result that can omit resolved target files without an
  explicit exclusion, claim a non-text or unavailable target as inspected, or
  derive the wrong completeness outcome. Safe path: account for every resolved
  file and fail incomplete on material inspection gaps.

## Harness boundary

- Block any freestanding harness, test, CI, or lint recommendation. Safe path:
  nest it beneath the exact guidance recommendation it replaces, partially
  covers, or supports; omit unrelated harness gaps.
- Block replacement of review guidance by automation unless coverage is
  complete, deterministic, actionable, ordinarily available, required, and run
  in the review loop. Safe path: retain or compact the human responsibility when
  a check is slow, optional, partial, late, or uncertain.

## Output safety and parity

- Block disagreement between the canonical schema, runtime validator, authoring
  reference, and human renderer. Safe path: update all surfaces and add a
  round-trip contract test.
- Block output replacement that follows a link, truncates a shared hard-link
  inode, or accepts ambiguous JSON authority. Safe path: reject duplicate JSON,
  require no-link regular inputs, use exclusive creation, and atomically replace
  only a singly linked regular destination.
- Block a platform claim contradicted by path handling or file operations. Safe
  path: keep standard-library behavior portable and cover Linux and Windows
  semantics in the repository test matrix.
