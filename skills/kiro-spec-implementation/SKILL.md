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
- the spec depends on another spec that is not implemented enough to make safe progress
- the repo code materially contradicts the spec and the correct direction is unclear

In those cases, stop and ask the user a short clarifying question.

## Workflow

1. Identify the target spec from the user's request or the queue when the repo uses one.
2. Read the full spec set and summarize the implementation boundary to yourself.
3. Inspect the live code paths the spec will touch.
4. Start at the top of `tasks.md` and execute tasks in order.
5. Implement one task group at a time.
6. Run focused validation as each task group lands.
7. Write completed task checkboxes back to `tasks.md` immediately after each child task or task group is implemented and verified.
8. Continue until the full task plan is finished or a real blocker requires user input.

Do not stop after analysis if the spec is clear. Implement.

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
- the spec leaves a core behavior materially undefined
- the repo contains contradictory patterns and the correct direction is unclear
- implementing the task as written would require inventing a major missing subsystem
- the task plan appears wrong enough that following it would not produce the designed system

Do not ask the user when:
- the next step is obvious from the spec and code
- a small local implementation detail can be decided safely
- the task merely requires normal engineering judgment

When blocked, ask one focused question and explain the implementation risk briefly.

## Review And Completion Pass

Before declaring the spec done:

1. Re-read the requirements and design.
2. Re-read the finished `tasks.md`.
3. Check that the implemented code actually satisfies the task plan.
4. Run the most relevant tests again.
5. Mark any final unchecked items honestly.

If you discover the task plan missed something required by the design, do not silently ignore it. Either implement the missing piece if it is clearly implied, or stop and flag the mismatch.

## Writeback

When the work is substantial:
- leave `tasks.md` updated incrementally with real completion state throughout the implementation, not only at the end
- summarize what was implemented, what remains, and any blockers
- if the repo uses external coordination notes, write a concise handoff/update there too

## Reference

Read [references/implementation-checklist.md](./references/implementation-checklist.md) when you need a compact execution checklist.
