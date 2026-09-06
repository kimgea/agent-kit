# Result authoring

Use this reference when preparing the semantic draft passed to
`impact_result.py finalize`.

## Draft ownership

The draft contains exactly:

- `conclusion`: concise evidence-backed overall explanation;
- `inspected_target_paths`: selected target paths whose relevant content was
  actually inspected;
- `inspected_context_paths`: frozen context paths actually inspected;
- `impacts`: semantic relationship records without IDs or fingerprints; and
- `limitations`: semantic evidence or analysis limitations.

Do not repeat target, context, guidance, limits, versions, source state, digests,
coverage, counts, completion, or status. The finalizer owns them.

## Impact record

Each impact contains:

- `source_target_paths`: one or more exact `target.paths` entries;
- `affected_locations`: one or more target or context locations;
- `relationship`: one rubric relationship kind;
- `reach`: `direct`, `indirect`, or `possible`;
- `confidence`: `high`, `medium`, or `low`;
- `title`, `consequence`, and `reason`;
- `evidence`: bounded evidence records with frozen locations;
- `safe_direction`: the next bounded investigation, not a mandatory fix; and
- `consumer_purposes`: one or more advisory downstream purposes.

Locations use canonical repository-relative POSIX paths and optional 1-based
inclusive line bounds. A line range must refer to embedded UTF-8 text and stay
within its normalized content.

Evidence kinds are `source`, `contract`, `guidance`, `test`, `configuration`,
`history`, and `reasoning`. Reasoning must connect cited evidence; it cannot
replace missing source evidence.

## Limitations

Use one of:

- `target_unreadable`;
- `context_missing`;
- `context_unreadable`;
- `evidence_ambiguous`;
- `dynamic_resolution`;
- `analysis_limit`; or
- `other`.

Set `material: true` when the gap prevents reliable analysis of one or more
selected targets. Name affected target or frozen-context paths. Do not call a
normal absence of unrelated context a limitation.

## Completion

The finalizer derives `INCOMPLETE` when a target is uninspected or any resolver
or semantic limitation is material. Otherwise it derives `COMPLETE`.
Impacts do not affect completion by their count or confidence.
