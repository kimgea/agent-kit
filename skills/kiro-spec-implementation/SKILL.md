---
name: kiro-spec-implementation
description: Implement existing Kiro-style feature specs in a target repository by reading the spec root, the target spec's `requirements.md`, `design.md`, and `tasks.md`, then executing tasks in order, validating each task group, and updating task checkboxes progressively as work lands, only after code and verification are complete. Use when a repository already has Kiro-style specs such as `.kiro/specs` and the user wants implementation rather than spec authoring.
---

# Kiro Spec Implementation

Implement one existing Kiro-style spec in the target workspace.

This repo packages the skill. Do not assume `agent-kit` itself contains `.kiro/specs` examples.

## Inputs

- Target workspace path
- Spec root path
- Spec id or folder name
- Requested target from the queue, if the repo uses one

## Resolve The Spec Root

1. Use the path the user gives when they give one.
2. Otherwise, use `.kiro/specs` only when that path already exists in the target workspace.
3. If the workspace uses another Kiro-style spec location, use the observed repo-local convention.
4. Treat queue files such as `IMPLEMENTATION_QUEUE.md` and bootstrap files such as `.config.kiro` as optional project conventions, not universal requirements.

## Load Order

1. Read the implementation queue only when the spec root has one and it helps identify the target spec.
2. Read the target spec folder:
   - `requirements.md`
   - `design.md`
   - `tasks.md`
3. Read the nearest already-implemented or neighboring specs that define upstream dependencies.
4. Read the relevant current code before editing.
5. Read tests covering the same subsystem when they exist.

Do not start implementation from `tasks.md` alone. The tasks are the execution plan, but the requirements and design define the actual intent.

## Preconditions

Do not proceed with implementation when any of these are true:

- `tasks.md` is missing
- `design.md` is missing
- `requirements.md` is missing
- the target spec cannot be identified safely from the repo or the user's request
- the task plan and design disagree in a way that changes implementation shape
- the dependency scan (see below) found unresolvable cross-spec references
- the repo code materially contradicts the spec and the correct direction is unclear

In those cases, stop and ask the user a short clarifying question.

## Dependency Scan

After reading the spec files and before writing any code, scan `requirements.md` and `design.md` for **explicit references to other specs or external definitions**. Look for phrases like:

- "defined in spec X" / "see spec X"
- "defined by the Y spec" / "from the Y module/system"
- "see [other-spec-name]"
- any mention of a schema, type, or interface whose definition is delegated to another named spec or document

**What counts as a cross-spec dependency:** A reference is a dependency only when the spec explicitly names another spec, document, or external definition as the source of truth for a type, schema, behavior, or configuration. Examples:

- "The `Event` schema is defined in the monitoring-events spec" → **dependency** (explicitly names another spec as source of truth)
- "Events are passed as `Event` objects with a `type` and `message` field" → **not a dependency** (the spec defines the shape inline, even if briefly)
- "Uses SMTP to send email" → **not a dependency** (a technology choice, not a cross-spec reference)

**What to do when you find a dependency:**

1. Try to resolve it: check if the referenced spec exists in the spec root, or if the referenced type/module already exists in the codebase.
2. If the dependency resolves (the spec or code exists), read it and continue.
3. If the dependency does **not** resolve — the referenced spec doesn't exist and the type/schema is not defined anywhere in the codebase — **stop and ask the user**. Tell them which spec or definition is missing and what you need to proceed. Do not invent the missing schema yourself.

This matters because implementing against a schema you invented will create technical debt the moment the real spec lands. It is better to clarify upfront than to build on assumptions.

## Workflow

1. Identify the target spec from the user's request or the queue when the repo uses one.
2. Read the full spec set (requirements, design, tasks).
3. **Run the dependency scan** described above. If unresolved dependencies are found, stop here and ask the user.
4. Inspect the live code paths the spec will touch.
5. **Write a pre-implementation summary** to `tasks.md` (see below) confirming scope, dependencies, and boundaries.
6. Start at the top of `tasks.md` and execute tasks in order.
7. Implement one task group at a time.
8. Run focused validation as each task group lands.
9. Write completed task checkboxes back to `tasks.md` immediately after each child task or task group is implemented and verified.
10. Continue until the full task plan is finished or a real blocker requires user input.

Do not stop after analysis if the spec is clear and dependencies are resolved. Implement.

### Pre-Implementation Summary

Before writing any code, append a short summary block to the top of `tasks.md` (above the first task). This confirms you have read and understood the spec. Use this format:

```md
<!-- Implementation context
- Spec: [spec name]
- Dependencies resolved: [list any cross-spec refs and how they were resolved, or "none"]
- Key boundaries: [1-2 sentence summary of what is in/out of scope]
- Existing code reviewed: [list files inspected]
-->
```

This block is a quick sanity check, not a report. Keep it to 3-5 lines. Its purpose is to make the "read before code" step observable and to catch misunderstandings early.

## Task Processing Rules

Treat `tasks.md` as the implementation contract.

- Parent tasks define the phase boundary.
- Child tasks define the concrete work.
- Requirement traceability lines tell you what behavior must exist when that task is done.
- Checkpoints are review gates, not optional notes.

Follow the written order unless a small local reorder is required for correctness.

Allowed:
- creating a helper file slightly earlier because multiple subtasks need it
- writing tests just before or just after the code they validate
- doing a small prerequisite refactor needed to make the task possible

Not allowed:
- skipping ahead because a later task looks easier
- silently dropping tasks that feel redundant
- implementing a different architecture than the design without asking

### Marking tasks complete

Update `tasks.md` on disk as work finishes. Do not batch checkbox updates until the end of the spec.

Rules:
- Mark a child checkbox complete only after the code is implemented and verified at the level the task implies.
- Mark a parent checkbox complete only after all of its child work is complete.
- Save the checkbox change to `tasks.md` immediately after finishing each completed child item.
- If a task group has no child items, save its checkbox change immediately after that group is implemented and verified.
- Re-read `tasks.md` from disk when resuming work and continue from the first honest unchecked item.
- Leave blocked or partially done items unchecked.
- If you must stop mid-spec, keep the checklist honest.

If the task file uses a checkbox structure like:

```md
- [ ] 2. Implement subsystem
 - [ ] 2.1 Create runtime object
 - [ ] 2.2 Add validation
```

then:
- mark `2.1` and `2.2` individually as they finish
- mark `2.` only after both are done
- save the file after each checkbox change instead of waiting for the whole phase to finish

## Do

Implement what the spec says.

- Keep refactors scoped to what the spec requires.
- Keep the architecture within the design boundary.
- Preserve shared-module boundaries when the design calls for them.

Before editing:
- inspect current modules, data classes, and call sites
- inspect neighboring specs when the new system plugs into earlier spec work
- inspect existing tests and fixtures

Prefer integration with the repo's current patterns over greenfield invention.

After each meaningful task group:
- run focused tests if they exist
- add tests when the task plan calls for them
- do lightweight structural verification when tests are not available yet
- confirm the implemented seam still matches the design
- persist the matching `tasks.md` completion state before moving to the next item

Do not mark tasks complete based only on reading or code-writing. Verify.

Aim for small, reviewable slices:
- data objects
- validators
- services
- integration seams
- tests
- fixtures

Avoid giant unverified dumps of code that try to finish the whole spec at once.

## Do Not

- Do not assume `.kiro/specs` exists when the repo uses another spec root.
- Do not assume `IMPLEMENTATION_QUEUE.md` exists.
- Do not implement from `tasks.md` alone.
- Do not silently change the designed architecture when the spec disagrees with the code.
- Do not mark tasks complete without real verification.

## Failure Modes

Stop and ask the user when:
- the dependency scan found a cross-spec reference that cannot be resolved (the referenced spec or type does not exist anywhere in the repo)
- the spec leaves a core behavior materially undefined
- the repo contains contradictory patterns and the correct direction is unclear
- implementing the task as written would require inventing a major missing subsystem
- the task plan appears wrong enough that following it would not produce the designed system

Do not ask the user when:
- the next step is obvious from the spec and code
- a small local implementation detail can be decided safely
- the task merely requires normal engineering judgment
- a technology or library is mentioned (e.g. "uses SMTP", "uses Twilio") — these are implementation details you can handle with standard patterns

When blocked, ask one focused question and explain the implementation risk briefly.

## Review And Completion Pass

Before declaring the spec done:

1. Re-read the requirements and design.
2. Re-read the finished `tasks.md`.
3. Check that the implemented code actually satisfies the task plan.
4. Run the most relevant tests again.
5. Mark any final unchecked items honestly.
6. Update the `tasks.md` definition-of-done line to reflect the actual state. If the definition of done says "All checkboxes marked, all checkpoints pass, pytest green", confirm each of those things is actually true, and annotate it (e.g. append ✓ or note what remains).

If you discover the task plan missed something required by the design, do not silently ignore it. Either implement the missing piece if it is clearly implied, or stop and flag the mismatch.

## Writeback

When the work is substantial:
- leave `tasks.md` updated incrementally with real completion state throughout the implementation, not only at the end
- summarize what was implemented, what remains, and any blockers
- if the repo uses external coordination notes, write a concise handoff/update there too

## Reference

Read [references/implementation-checklist.md](./references/implementation-checklist.md) when you need a compact execution checklist.
