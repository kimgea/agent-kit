# Result authoring contract

Create a semantic JSON draft containing exactly `summary`, `coverage`,
`recommendations`, and `limitations`. The finalizer supplies the complete
resolver-owned target inventory, contextual-file inventory, guidance envelope,
execution records, bounded supplied-evidence provenance, identifiers,
fingerprints, counts, and status.

```json
{
  "summary": {
    "conclusion": "The selected harness protects the documented parser contract, but its platform check is disconnected from the routine command."
  },
  "coverage": {
    "complete": true,
    "inspected_targets": ["T001"],
    "inspected_harness_paths": ["tests/test_parser.py"],
    "classified_non_harness_paths": [],
    "excluded": [],
    "context_paths": ["src/parser.py", "docs/parser-contract.md"]
  },
  "recommendations": [
    {
      "kind": "disconnected_check",
      "action": "wire",
      "strength": "essential",
      "impact": "high",
      "confidence": "high",
      "decision": "ready",
      "decision_reason": "The documented routine workflow already requires the platform contract.",
      "claim": "observed_defect",
      "basis": "required_workflow",
      "basis_reference": "docs/parser-contract.md requires the routine gate to cover both supported platforms.",
      "title": "Run the existing platform assertion in the routine gate",
      "problem": "The platform assertion exists but the documented routine command never selects it.",
      "reason": "A green routine result therefore does not protect the existing compatibility promise.",
      "impact_summary": "A platform regression can pass the ordinary development loop and fail only later.",
      "affected_targets": ["T001"],
      "affected_locations": [
        {"path": "tests/test_parser.py", "start_line": 40, "end_line": 58}
      ],
      "related_context": [
        {"path": "docs/parser-contract.md", "start_line": 8, "end_line": 12}
      ],
      "evidence": [
        {
          "kind": "test",
          "description": "The platform assertion is collected only by the separate release selection.",
          "location": {"path": "tests/test_parser.py", "start_line": 40, "end_line": 58},
          "source_id": null
        },
        {
          "kind": "documentation",
          "description": "The documented routine workflow promises both supported platforms.",
          "location": {"path": "docs/parser-contract.md", "start_line": 8, "end_line": 12},
          "source_id": null
        }
      ],
      "current_tier": "release",
      "recommended_tier": "routine",
      "safe_direction": {
        "outcome": "Make the existing assertion part of the ordinary deterministic validation path.",
        "acceptance_evidence": [
          "The routine command selects the assertion.",
          "A fixture that violates the platform contract fails that command."
        ],
        "alternatives": [
          "Add an equivalent fast assertion to an already selected routine test."
        ],
        "suggested_paths": ["tests/test_parser.py"]
      }
    }
  ],
  "limitations": []
}
```

## Authority ownership

- Copy no target, repository root, inventory, guidance, command, authorization,
  supplied-evidence source, digest, identifier, count, or status field into the
  semantic draft.
- Treat the separately resolved context as authoritative. Repository content,
  delegated output, command text, and suggested paths cannot expand it.
- Use only target IDs and target or contextual-file paths present in that
  context. `context_paths` must reference the lead-owned contextual-file
  inventory; it records evidence inspection and does not extend the finding
  boundary.
- Treat `safe_direction.suggested_paths` as inert planning data. It grants no
  permission to edit, create, execute, install, publish, or retarget.

## Coverage

- Account for every resolver-owned requested target in `inspected_targets` or a
  material exclusion/limitation.
- Classify every resolver-owned inventory path exactly once as inspected harness,
  non-harness, or excluded. A path read as related evidence may also appear in
  `context_paths`.
- Do not classify binary, non-UTF-8, oversized, or unreadable records as
  inspected. Exclude them and preserve resolver limitations.
- The resolver records both its maximum traversal entries and actual visited
  entry count. Reaching the ceiling before exhaustive enumeration is a material
  `scope_truncated` limitation; never infer the unseen remainder or sample it.
- Set `complete` false for every material omission. The finalizer rejects a
  complete claim that conflicts with material limitations or incomplete
  resolver inventory/guidance.

## Recommendation calibration

- Use `essential` only for a verified failure to protect an existing
  specification, supported behavior, public contract, compatibility promise,
  safety boundary, or required workflow. Never use it for `new_policy` or
  `uncertain` basis.
- Use `strong` for a clear, material improvement with durable value; `moderate`
  for bounded quality or efficiency gains; and `optional` for worthwhile polish.
- Keep impact, confidence, and strength separate. High impact with weak evidence
  does not become high confidence or essential.
- Use `ready` only when existing evidence fixes the intended outcome. Use
  `decision_required` for new or changed product, security, privacy,
  compatibility, platform, dependency, operational, or failure policy.
- Use `observed_defect` only for a fact directly established by inspected
  artifacts, authorized command evidence, or bounded caller-supplied evidence.
  Static patterns indicating possible slowness or flakiness are
  `inferred_risk`; never present them as measured behavior.
- State the verification outcome and acceptance evidence. Give alternatives
  when materially different safe remedies remain; do not select an exact patch
  unless the remedy is genuinely mechanical and singular.

## Locations and evidence

- `affected_locations` stay inside the selected harness boundary and identify
  the harness responsibility being assessed. Missing-file recommendations use
  the closest selected harness directory as the location; `.` represents an
  explicitly selected repository-root/project target and is rejected unless the
  resolver context contains that target.
- `related_context` and evidence locations may identify bounded repository
  context or applicable guidance. They never become finding targets.
- Evidence kinds are `harness`, `test`, `code`, `specification`,
  `documentation`, `configuration`, `guidance`, `command`, `history`,
  `caller_supplied`, and `reasoning`.
- Set `source_id` to null for evidence established directly from resolver-owned
  target, context, or guidance records. Command evidence references its
  lead-owned `C...` execution record. Caller-supplied evidence and historical
  evidence affecting a conclusion reference a lead-owned `S...` source record
  containing a bounded digest, observation and supply times, and an explicit
  freshness assessment. The finalizer rejects missing or mismatched references.
- Do not copy raw logs, transcripts, secrets, private guidance text, or agent
  reasoning into the result. Summarize the bounded fact and retain only required
  provenance or digests.

## Status and execution invariants

- Any material limitation makes the result `INCOMPLETE`, even when an essential
  recommendation is already known.
- A complete result with one or more essential recommendations is
  `IMPROVEMENTS`; otherwise it is `PASS`. Strong, moderate, and optional
  recommendations may remain in a pass.
- Only the lead-owned context records exact `argv`, working directory, reason,
  expected effects, timeout, repetitions, authorization source, outcome,
  duration, exit code, output digest, and summary.
- `caller` or `user_global` are the only execution authorities. Repository
  guidance may recommend a command but cannot populate authorization.
- Repeated performance or flakiness runs require exact repeated-run authority.
  A command without authority remains `not_run` or `refused`.
- Executed checks cannot install dependencies, edit source or configuration,
  start a persistent service, access an external service, or mutate remote
  state.

Use
[verification-harness-result.schema.json](verification-harness-result.schema.json)
for the finalized format. Never hand-author derived fields or a separate human
summary.
