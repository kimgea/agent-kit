# Result authoring contract

Create a JSON draft containing exactly `summary`, `coverage`,
`recommendations`, and `limitations`. The finalizer supplies all authority
fields, identifiers, fingerprints, counts, and status.

```json
{
  "summary": {
    "conclusion": "Concise evidence-backed conclusion."
  },
  "coverage": {
    "complete": true,
    "inspected_paths": ["src/example.py"],
    "excluded": [],
    "context_paths": ["tests/test_example.py"]
  },
  "recommendations": [
    {
      "action": "rewrite",
      "strength": "strong",
      "decision": "ready",
      "intent_effect": "preserved",
      "title": "Keep only the human-review remainder",
      "reason": "A fast required validator covers syntax, while semantic compatibility still needs review.",
      "current_guidance": [
        {
          "source_kind": "repository",
          "path": "REVIEW.md",
          "sha256": "COPY_FROM_RESOLVED_CONTEXT",
          "start_line": 10,
          "end_line": 12
        }
      ],
      "destination": {
        "source_kind": "repository",
        "path": "REVIEW.md"
      },
      "affected_targets": ["T001"],
      "affected_paths": ["src/example.py"],
      "evidence": [
        {
          "kind": "test",
          "description": "The required local validator rejects malformed syntax.",
          "location": {
            "path": "tests/test_example.py",
            "start_line": 8,
            "end_line": 20
          }
        }
      ],
      "estimated_savings": {
        "words": 18,
        "bytes": null,
        "basis": "Removes the syntax procedure while preserving the compatibility rule."
      },
      "proposed_text": "Review changes for compatibility with existing consumers.",
      "harness_changes": [
        {
          "relationship": "partially_cover",
          "kind": "validator",
          "summary": "Keep the existing syntax validator required in the review loop.",
          "reason": "It covers syntax but not compatibility judgment.",
          "coverage": "partial",
          "timing": "review_loop",
          "speed": "fast",
          "enforcement": "required",
          "determinism": "deterministic",
          "availability": "ordinary",
          "diagnostics": "actionable",
          "paths": ["tests/test_example.py"]
        }
      ]
    }
  ],
  "limitations": []
}
```

## Fields and invariants

- `coverage` must account for every resolved target file exactly once as
  inspected or excluded. A material exclusion makes `complete` false.
- A resolver record whose `inspection_kind` is not `text` cannot appear in
  `inspected_paths`; exclude it with a material reason. Resolver limitations
  preserve the resulting `INCOMPLETE` status.
- `context_paths` lists related repository files read as evidence. It does not
  expand the audit target.
- `action`: `keep`, `rewrite`, `move`, `merge`, `remove`, or `create`.
- `strength`: `essential`, `strong`, `moderate`, or `optional`.
- `decision`: `ready` or `decision_required`.
- `intent_effect`: `preserved`, `narrowed`, or `changed`. Changed intent always
  requires a decision.
- `current_guidance` must copy exact source kind, path, digest, and bounded line
  range from an applicable loaded source. It is empty only for `create`.
- `destination` is required for `rewrite`, `move`, `merge`, and `create`; it is
  null for `keep` and `remove`. Repository destinations must be applicable
  ancestor `REVIEW.md` paths for every affected target.
- `affected_paths` must stay inside the resolver-owned target.
- `affected_targets` must cite the resolver-owned target IDs governing those
  paths. A file-part recommendation must cite evidence inside its exact range.
- Evidence kinds are `guidance`, `code`, `test`, `specification`,
  `documentation`, `configuration`, `history`, or `reasoning`. Evidence
  locations must be target, context, or repository-guidance paths.
- `proposed_text` is required for `rewrite`, `move`, `merge`, and `create`; it is
  null for `keep` and `remove`.
- Estimated word and byte savings may be null when they cannot be measured;
  always explain the basis.
- Harness changes exist only inside a guidance recommendation. Relationships
  are `replace`, `partially_cover`, or `support`.
- `replace` is valid only for complete deterministic coverage that is required
  and fast in the review loop, ordinarily available, and actionably diagnosed;
  it is valid only with a `remove` or `rewrite` action.
- Limitation codes are `scope_truncated`, `target_unreadable`,
  `part_unreadable`, `guidance_unreadable`, `guidance_budget`,
  `coverage_incomplete`, `context_unavailable`, `evidence_missing`,
  `conflicting_evidence`, or `other`.

Use [review-guidance-result.schema.json](review-guidance-result.schema.json) for
the finalized canonical format. Never add `schema_version`, `context_sha256`,
`status`, target data, guidance provenance, context metrics,
`recommendation_id`, `fingerprint`, or derived summary counts to the draft.
