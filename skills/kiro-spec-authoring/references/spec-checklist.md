# Spec Checklist

## Before Writing

- Resolve the target spec root.
- Read the target spec folder if it already exists.
- Read the implementation queue only when the workspace has one.
- Read 1-3 nearby specs that are structurally similar when they exist.
- Confirm which phase the user asked for.
- Write only that phase.

## Requirements Checklist

- Define the scope clearly.
- State what is in scope now.
- State what is explicitly deferred.
- Keep the content implementation-agnostic.
- Capture the user decisions already made.
- Create `.config.kiro` only when the target workspace already uses it or the user asks for it.

## Design Checklist

- Include architecture or flow diagrams when useful.
- Include module or file structure when the work should be a separate system.
- Show ownership boundaries with adjacent systems.
- Include concrete examples in the formats the target repo actually uses.
- Prefer depth over summary.
- Avoid format-specific examples unless they match the target system.
- Battle-test the design against real examples when the domain has them.

## Tasks Checklist

- Follow the pattern of the stronger existing task files when examples exist.
- Use numbered phases.
- Add subtasks where needed.
- Include checkpoints.
- Trace task groups back to requirements when the spec uses requirement IDs.
- Include validation and testing tasks for the critical boundaries.
- Check that the plan would actually produce the designed system.

## Stop Gates

- After `requirements.md`, stop and wait for the user.
- After `design.md`, stop and wait for the user.
- After `tasks.md`, stop and wait for the user before starting the next spec.
