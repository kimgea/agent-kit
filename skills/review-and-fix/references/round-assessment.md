# Fresh review round assessment

Run this helper only after the same reviewer set has completed a fresh rerun and
every result has been independently normalized and finalized.

## Input

Pass one JSON object to `review_workflow.py assess-round --input <round.json>`:

```json
{
  "round": 1,
  "expected_reviewers": [
    {"reviewer": "project-review", "reviewer_version": "1.0.0"}
  ],
  "previous_batches": ["<complete canonical batch before the fix>"],
  "current_batches": ["<complete canonical batch after the fix>"]
}
```

Replace each quoted batch placeholder with the actual canonical JSON object.
`round` is the fix round just completed and must be `1`, `2`, or `3`.
`expected_reviewers` is the exact identity set fixed before the first review;
order does not matter, but duplicates are invalid. Include one previous and one
current batch per reviewer.

All batches must have identical target metadata. A changed reviewer identity or
version stops as `reviewer_set_drift`; changed target metadata stops as
`target_drift`. A partial, incomplete, unknown-disposition, or triage-needed
current result stops as `incomplete_review`. A `ref_range` target stops as
`ref_range_review_only`; re-scope and re-review a working-tree or path snapshot
before fixing rather than changing the range's immutable head.

## Output

The helper returns:

```json
{
  "round": 1,
  "action": "accept",
  "reason": "reviewer_pass",
  "previous_blocker_fingerprints": ["<sha256>"],
  "current_blocker_fingerprints": []
}
```

`action` is `accept`, `continue`, or `stop`. Acceptance requires a complete
fresh result with high-confidence normalization, canonical source outcome
`pass`, and no remaining blocker dispositions. A non-pass result without
blockers stops as `reviewer_not_passed`; an empty blocker list never overrides
the reviewer outcome. Suggestions and nits do not block acceptance when the
reviewer still returns pass, but remain visible in the final summary. Identical
blocker fingerprints stop as `no_material_progress`; remaining changed blockers
continue before round three and stop as `maximum_rounds_reached` on round three.
