---
name: kiro-spec-authoring
description: Create or revise Kiro-style feature specs with gated `requirements.md`, `design.md`, and `tasks.md` phases. Use when a target repository already keeps specs in a Kiro-style folder such as `.kiro/specs`, or when the user explicitly wants to establish that workflow, including spec review, battle-testing, and queue maintenance.
---

# Kiro Spec Authoring

Write one Kiro-style spec phase at a time in the target workspace.

This repo packages the skill. Do not assume `agent-kit` itself contains `.kiro/specs` examples.

## Inputs

- Target workspace path
- Spec root path
- Spec id or folder name
- Requested phase, if the user already chose one

## Resolve The Spec Root

1. Use the path the user gives when they give one.
2. Otherwise, use `.kiro/specs` only when that path already exists in the target workspace.
3. If the workspace has no existing Kiro-style spec root, confirm whether to create `.kiro/specs` or to use another repo-specific location.
4. Treat queue files such as `IMPLEMENTATION_QUEUE.md` and bootstrap files such as `.config.kiro` as optional project conventions, not universal requirements.

## Workflow

1. Read the target spec folder if it already exists.
2. Read the implementation queue only when the target workspace has one.
3. Read 1-3 nearby specs when the workspace already has them.
4. Determine the phase to work on:
   - `requirements.md`
   - `design.md`
   - `tasks.md`
5. If the user did not specify a phase, default to `requirements.md`.
6. Create or update only that phase.
7. Stop after that phase and wait for the user before writing the next one.
8. Update the queue only when the queue exists and the user asked for queue management or the new spec must be registered.

If the target repo has no strong local examples, fall back to `references/spec-checklist.md` instead of inventing repo lore.

## Phase Rules

### Requirements

- Write clear scope, capabilities, and boundaries.
- Use stable requirement IDs when the repo already uses them or when traceability will matter in `tasks.md`.
- Keep the file implementation-agnostic.
- Separate current scope from explicit deferrals.
- Capture product decisions already made by the user. Do not silently invent missing behavior.
- Create `.config.kiro` only when the target workspace already uses it or the user explicitly asks for it.

### Design

- Make the design concrete enough that implementation can be planned without guessing.
- Include architecture or flow diagrams when multiple moving parts need coordination.
- Include likely module, file, or ownership boundaries when they reduce ambiguity.
- Prefer examples shaped like the target repo's actual runtime artifacts.
- Use JSON, YAML, code, or framework-specific examples only when that format matches the target system.
- Show how the feature fits adjacent systems instead of treating it as isolated.
- Battle-test the design against real scenarios, source docs, or worked examples when they exist.

### Tasks

- Mirror the strongest task structure already present in the target workspace when examples exist.
- Organize work into numbered phases.
- Add subtasks, checkpoints, and validation steps where they materially reduce ambiguity.
- Trace task groups back to requirements when the spec uses requirement IDs.
- Make tasks implementation-shaped so another agent can build the designed system from the plan.
- Tighten the plan if review shows the current tasks would not actually produce the requirements or design.

## Do Not

- Do not write `design.md` or `tasks.md` early for convenience.
- Do not create queue files, bootstrap files, or directory conventions unless the target repo already uses them or the user asks for them.
- Do not claim local repo conventions that were not observed.
- Do not start the next spec in a queue without explicit user direction.

## Battle Testing

Use battle testing when the user asks to pressure-test a spec.

- Read the source material the spec must satisfy.
- Test whether the current phase survives concrete examples and edge cases.
- Report the pressure points clearly.
- Patch the current phase before advancing if the review exposes a real ambiguity or contradiction.

## Reference

Read [references/spec-checklist.md](./references/spec-checklist.md) for the compact review checklist and stop gates.
