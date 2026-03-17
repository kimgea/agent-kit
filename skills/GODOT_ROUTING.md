# Godot Skill Routing

Purpose: define the default entry path for Godot work in this repo.

## Default Rule

Use `godot-task` as the general entrypoint for Godot implementation work.

Use `godot-master` as a broad fallback reference when:
- the right specialist skill is unclear
- the task spans many domains
- architecture is still being decided

Do not use `godot-master` as the default starting skill for ordinary implementation tasks.

## Entry Rules

For most Godot coding tasks:
1. load `skills/godot-task/SKILL.md`
2. follow its minimum read path
3. load specialist skills only when the task clearly matches their domain

For broad Godot research or architecture tasks:
1. load `skills/godot-master/SKILL.md`
2. identify the relevant specialist skills
3. switch to `godot-task` if the work becomes an implementation task

## Recommended Baseline Set

Do not load every Godot skill by default.

Recommended core set:
- `godot-task`
- `godot-master`
- `godot-gdscript-mastery`
- `godot-project-foundations`
- `godot-testing-patterns`

Reason:
- `godot-task` covers execution workflow
- `godot-master` helps when the right specialist skill is unclear
- `godot-gdscript-mastery` covers language-level rules
- `godot-project-foundations` covers project structure and naming
- `godot-testing-patterns` covers automated validation

Add specialist skills only when the project or task clearly needs them.

If a bundle is available for the project type, prefer the bundle over manually assembling the same set.

Current Godot bundles:
- `godot-core`
- `godot-ui`

## When To Add More Skills

Add a specialist skill when one or more of these is true:
- the task is clearly in that domain
- the project has a durable subsystem in that domain
- the same kind of work appears repeatedly
- `godot-task` is routing into that area often
- the project has bugs or design pressure concentrated in that area

Common examples:
- UI-heavy project -> prefer `godot-ui`, or add `godot-ui-containers`, `godot-ui-theming`, `godot-ui-rich-text`, `godot-tweening`, and `godot-composition-apps`
- RPG or quest-heavy project -> `godot-quest-system`, `godot-rpg-stats`, `godot-turn-system`
- action or platforming project -> `godot-input-handling`, `godot-characterbody-2d`, `godot-camera-systems`, `godot-2d-animation`
- shader or VFX-heavy project -> `godot-shaders-basics`, `godot-particles`
- procgen project -> `godot-procedural-generation`, `godot-tilemap-mastery`
- architecture-heavy project -> `godot-signal-architecture`, `godot-autoload-architecture`, `godot-state-machine-advanced`
- persistence-heavy project -> `godot-save-load-systems`

## Selection Rule

Use this rule when deciding whether the project needs another skill:

- If the project only touches the area once or lightly, keep the core set and load the specialist skill only for that task.
- If the area is central to the game or keeps recurring, treat that specialist skill as part of the project's normal set.
- If you are unsure, start without it and add it after the first real task exposes the need.

## Skill Roles

### `godot-task`

Owns:
- task intake
- workflow order
- validation loop
- evidence capture
- reporting
- routing to specialist skills

### Specialist Godot Skills

Own:
- domain patterns
- API choices
- common pitfalls
- implementation recipes for one area

Examples:
- animation
- cameras
- input
- physics
- quests
- shaders
- save/load
- UI
- testing

### `godot-master`

Owns:
- broad fallback reference
- cross-domain orientation
- high-level Godot guidance when no narrower starting point is obvious

## Practical Examples

Use `godot-task` first for:
- implementing a player controller
- fixing UI behavior
- adding a quest system
- building a shader-driven effect
- debugging a Godot feature in a real project

Use `godot-task` plus one specialist skill for:
- animation task -> `godot-task` + `godot-2d-animation`
- testing task -> `godot-task` + `godot-testing-patterns`
- save/load task -> `godot-task` + `godot-save-load-systems`
- architecture-heavy signal work -> `godot-task` + `godot-signal-architecture`

Use `godot-ui` for:
- UI-heavy game projects
- HUD, menus, overlays, and app-like flows that are central to the project
- projects where layout, theming, text rendering, and UI motion are part of the core workload

Use `godot-master` first for:
- "what Godot pattern should we use here?"
- "which skill should handle this task?"
- "how should this project be structured before implementation starts?"

## Repository Rule

When adding or editing Godot skills:
- keep `godot-task` as the workflow entrypoint
- keep specialist skills narrow and domain-owned
- avoid making specialist skills depend on `godot-task`
- avoid duplicating specialist content in `godot-task` unless it is needed as fallback
