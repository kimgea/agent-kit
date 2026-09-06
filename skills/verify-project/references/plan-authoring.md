# Plan authoring

Use this reference after the lead has created a canonical context with
`scripts/verification_context.py`. The planning agent returns semantic judgment
only. It never copies or invents command authority, argv, paths, limits,
identifiers, fingerprints, or derived state.

## Semantic plan draft

Return one JSON object with exactly these arrays:

```json
{
  "claims": [
    {
      "key": "stable-local-key",
      "statement": "The selected behavior remains correct.",
      "material": true,
      "target_ids": ["T001"],
      "basis": [
        {
          "kind": "caller",
          "description": "Why this is a target claim.",
          "source_id": "P001",
          "location": null
        }
      ],
      "evidence_requirement": "command"
    }
  ],
  "guidance_interpretations": [],
  "checks": [
    {
      "key": "focused-check",
      "candidate_id": "Q001",
      "tier": "focused",
      "reason": "Why this candidate proves the mapped claim.",
      "claim_keys": ["stable-local-key"],
      "depends_on_keys": [],
      "useful_after_failure": true
    }
  ],
  "limitations": []
}
```

Claims describe target behavior, not merely that a command exits successfully.
Use `static` only when inspected target or contract evidence fully proves the
claim, `command` when execution evidence is required, and `either` when either
kind can be sufficient. Every material command claim needs a selected frozen
candidate or the finalized plan must retain a coverage gap.

Basis `kind` is one of `caller`, `agent_policy`, `verify_guidance`,
`target_content`, `project_contract`, `related_test`, or `reasoning`.
`source_id`, when present, must name a context `P...`, `S...`, or `D...` record.
Locations are canonical repository-relative paths with nullable one-based line
numbers.

## Guidance interpretations

Each interpretation has exactly:

```json
{
  "key": "nested-requirement",
  "source_id": "S003",
  "target_ids": ["T001"],
  "claim_keys": ["stable-local-key"],
  "kind": "required",
  "requirement": "Run the focused parser contract check.",
  "replaces_key": null,
  "replacement_reason": null
}
```

Kinds are `required`, `conditional`, `recommended`, `replacement`, and
`artifact`. Required, conditional, and replacement interpretations map to a
claim. A replacement names the exact broader interpretation key, gives a
reason, applies only to a subset of that rule's targets, and comes from a
strictly closer source in an applicable guidance chain. Guidance never grants
authority.

## Finalize and validate

Finalize with:

```text
python scripts/verification_plan.py finalize --context CONTEXT.json --input DRAFT.json --format json --output PLAN.json
```

The output path must not already exist. The helper revalidates the target,
discovery inputs, protected state, and Git `HEAD`; injects exact candidate
metadata; applies caller caps; derives IDs, fingerprints, coverage,
limitations, summary, and execution state; and fails closed on drift.

Use `validate --input PLAN.json` before a consumer accepts an existing plan.
Use `render --input PLAN.json` for human output. Rendering always starts from
the validated canonical plan.

If finalization rejects a semantic draft, correct only the reported structure
or judgment. Never copy lead-owned values into the draft to work around the
boundary.
