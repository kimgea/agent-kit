# Intake Workflow

Use intake as a temporary staging area, not as a permanent store.

Processing flow:

1. place raw material in `05 Intake/To Process`
2. read it as source material, not truth
3. extract durable conclusions into `30 Designs`, `40 Requirements`, `50 Decisions`, `60 Reference`, or `70 Project Areas`
4. link the durable notes to the raw source when useful
5. move the processed raw batch to `65 Sources`

Processing heuristics:

- synthesize by concept cluster, not file-by-file, when that produces cleaner knowledge
- preserve contracts, data shapes, authoring models, state models, and pseudocode when they matter for future design
- drop code paths, PR sequencing, and low-level implementation details unless they change design reasoning
- keep historical source files only as fallback reference, not as the working knowledge layer

When multiple old docs overlap:

- prefer one higher-order reference note over many mirrored notes
- record durable decisions separately in `50 Decisions`
- keep alternatives in `20 Explorations` only if they still matter
