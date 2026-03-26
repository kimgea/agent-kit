# Implementation Checklist

## Before Coding

- Resolve the spec root from the user's path or the repo's existing convention.
- Read `IMPLEMENTATION_QUEUE.md` only when the spec root has one and it helps identify the target spec.
- Read the target spec's `requirements.md`, `design.md`, and `tasks.md`.
- **Run the dependency scan**: look for explicit cross-spec references ("defined in spec X", "see spec Y"). Try to resolve each one. If a referenced spec or type does not exist in the repo, stop and ask the user.
- Read the relevant existing code and nearby specs.
- **Write the pre-implementation summary** to `tasks.md` (HTML comment block listing spec name, resolved dependencies, boundaries, files inspected).
- Confirm the spec is implementable without a major ambiguity.

## During Implementation

- Follow `tasks.md` in order.
- Allow only small local reorders needed for correctness.
- Implement one task group at a time.
- Keep code aligned with the design boundary.
- Run focused validation as each task group lands.
- Update `tasks.md` checkboxes only after implementation plus verification.
- Save `tasks.md` immediately after each completed child task or verified task group.
- On resume, re-read `tasks.md` and continue from the first honest unchecked item.

## Stop And Ask When

- a cross-spec dependency cannot be resolved (the referenced spec or type does not exist)
- the required spec files are incomplete or missing
- a core behavior is still materially ambiguous
- the task plan and design disagree in a way that changes implementation shape
- the repo contradicts the spec and the correct direction is unclear

## Before Finishing

- Re-read the requirements and design.
- Re-read the updated `tasks.md`.
- Verify the implemented code matches the completed task items.
- Run the most relevant tests again.
- Leave blocked or incomplete items unchecked.
- Annotate the definition-of-done line in `tasks.md` with actual pass/fail state.
