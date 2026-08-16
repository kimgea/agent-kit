# Project agent contract

## Scope

- Treat this repository as the source of truth.
- Preserve unrelated user changes.
- Keep mutations within the requested task and repository.

## Workflow

1. Read the relevant source, tests, and project instructions.
2. Use read-only inspection to establish current behavior.
3. Make the smallest coherent implementation that satisfies the full request.
4. Add or update tests for behavior and safety boundaries.
5. Run the project validation gate and inspect the final diff.

## Tool use

- Use `rg` and `rg --files` for search and discovery.
- Use patch-based edits for hand-authored files.
- Prefer purpose-specific read tools over general mutation-capable interfaces.
- Do not broaden automatic permissions to suppress prompts.

## Delivery

- Work from a non-default branch.
- Never force-push or bypass required checks.
- Use a pull request for remote delivery and summarize validation evidence.
- After creating or materially updating a pull request, dispatch a separate
  reviewer agent for the exact head commit before merge.
- Address actionable review findings and repeat review on the updated head. If
  the review is clean and the user authorized delivery into the default branch,
  the reviewer agent should approve when the forge permits and merge through
  required checks. Never claim formal approval when the active identity cannot
  approve its own pull request.

Replace this template's generic validation guidance with the project's exact
commands before adopting it.
