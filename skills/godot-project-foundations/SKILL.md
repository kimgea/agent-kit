---
name: godot-project-foundations
description: "Expert blueprint for Godot 4 project organization (feature-based folders, naming conventions, version control). Enforces snake_case files, PascalCase nodes, %SceneUniqueNames, and .gitignore best practices. Use when starting new projects or refactoring structure. Keywords project organization, naming conventions, snake_case, PascalCase, feature-based, .gitignore, .gdignore."
---

# Project Foundations

Use this skill when the task involves project structure, naming, or long-term maintainability.

Focus:
- feature-based folder layout
- consistent naming
- stable node references
- version-control and import hygiene

## Available Scripts

### [project_bootstrapper.gd](scripts/project_bootstrapper.gd)
Scaffolds feature folders and a Godot-friendly `.gitignore`.

### [scene_naming_validator.gd](scripts/scene_naming_validator.gd)
Scans for file and node naming violations.

### [dependency_auditor.gd](scripts/dependency_auditor.gd)
Checks for circular scene dependencies and coupling issues.

### [feature_scaffolder.gd](scripts/feature_scaffolder.gd)
Generates feature folders with base scenes, scripts, and subfolders.

Use `dependency_auditor.gd` only when auditing a larger project or diagnosing loading/coupling problems.

## Load This Skill When

- starting a new Godot project
- refactoring folder structure
- enforcing naming or organization conventions
- reducing brittle scene dependencies

## Never Do

- Never organize the project primarily by file type.
- Never mix naming conventions without a clear rule.
- Never commit `.godot/` or other generated/import artifacts.
- Never rely on deep hardcoded node paths when `%UniqueName` or better ownership is available.
- Never leave raw design-source folders importable if they should be ignored by Godot.

## Naming Conventions

- Files and folders: `snake_case`
- Nodes: `PascalCase`
- C# scripts: `PascalCase` to match class names
- Stable scene references: prefer `%UniqueName` for frequently accessed nodes

## Recommended Layout

```text
project.godot
common/
entities/
|-- player/
|   |-- player.tscn
|   |-- player.gd
|   `-- player_sprite.png
`-- enemy/
ui/
|-- main_menu/
levels/
addons/
```

Group by feature or domain responsibility, not by asset type.

## Version Control

- Add a Godot-aware `.gitignore`.
- Ignore `.godot/` and import artifacts.
- Use `.gdignore` in folders that should not be imported by the editor.

## Workflow: New Project Bootstrap

1. Ensure `project.godot` exists.
2. Create core folders such as `entities/`, `ui/`, `levels/`, and `common/`.
3. Add `.gitignore`.
4. Scaffold the first feature folder instead of creating global `scripts/` or `sprites/` roots.

## Reference

- Official docs: `tutorials/best_practices/project_organization.rst`
- Official docs: `tutorials/best_practices/scene_organization.rst`

## Related

- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
