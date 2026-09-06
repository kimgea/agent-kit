# Change-impact review policy

Use these additional rules for changes under this skill directory.

## Target and context integrity

- Block any path that lets the semantic analyst author, replace, or widen the
  selected target, frozen context, trusted guidance provenance, limits, or
  context digest. Those fields must come only from the deterministic resolver.
- Block target sampling, ambiguous partial coverage, or a complete result that
  omits an unreadable selected path. An excessive or unsafe boundary must fail
  closed with a material limitation or no sampled target.
- Block evidence or affected locations outside selected targets, explicitly
  frozen context, and applicable frozen guidance. Search results and inferred
  adjacency are not frozen evidence.

## Impact semantics

- Block impact records that assert defects, fixes, mandatory scope, command
  authority, or acceptance. The skill maps relationships; downstream consumers
  independently own review, verification, edit, and decision authority.
- Block speculative reach without concrete source or contract evidence. Use a
  calibrated possible relationship only when evidence anchors it; otherwise
  omit it or return a material evidence limitation.
- Block a consumer-purpose mapping that silently turns context into a selected
  target or required claim. Candidate purposes remain advisory.

## Runtime and output safety

- Block unbounded reads, executable repository configuration during discovery,
  link or reparse traversal, hard-linked authority inputs, unsafe output
  replacement, duplicate JSON members, or target/context drift.
- Block disagreement among runtime validation, JSON Schema, authoring
  references, human rendering, behavioral grading, and package contents.
- Block platform claims contradicted by Linux or Windows path and output
  behavior. Preserve standard-library portability and targeted negative tests.
