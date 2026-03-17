# Godot Task Spec Template

Use this structure when giving `godot-task` a unit of work.

```md
# Task: <short id or title>

## Goal

One or two sentences describing the intended outcome.

## Targets

- scenes/example_scene.tscn
- scripts/example_controller.gd
- test/test_example_task.gd

## Requirements

- Describe gameplay, visuals, constraints, and asset usage.
- State whether the task is 2D or 3D.
- State any fixed camera, movement, UI, or performance constraints.
- State what must not change.

## Verify

- Describe the evidence that should prove the task is complete.
- Include what should be visible in screenshots or over time.
- Include any behavioral checks that should be asserted in the harness.

## Available Nodes

- Optional.
- List exact node paths and types if the script must rely on an existing scene structure.
- Example: `Player/Camera3D : Camera3D`

## Inputs

- Optional.
- List allowed input actions if the task depends on project-defined input actions.
- Example: `move_left`, `move_right`, `jump`

## Script Attachments

- Optional.
- Map scene nodes to script paths when the scene builder should attach scripts.
- Example: `Player -> res://scripts/player_controller.gd`

## Notes

- Optional.
- Add assumptions, asset caveats, or implementation hints that matter.
```

## Guidance

- Keep `Targets` exact.
- Keep `Requirements` specific enough that the agent does not invent behavior.
- Use `Verify` to describe what success looks like in screenshots and behavior.
- Omit optional sections when they are unnecessary.
