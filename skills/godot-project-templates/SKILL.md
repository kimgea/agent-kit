---
name: godot-project-templates
description: "Expert blueprint for genre-specific project boilerplates (2D platformer, top-down RPG, 3D FPS) including directory structures, AutoLoad patterns, and core systems. Use when bootstrapping new projects or migrating architecture. Keywords project templates, boilerplate, 2D platformer, RPG, FPS, AutoLoad, scene structure."
---

# Project Templates

Use this skill when the task needs a starting architecture for a new Godot project or a major restructuring.

Focus:
- genre-oriented project scaffolds
- AutoLoad ownership
- scene and system boundaries
- adapting templates instead of copying them blindly

## Available Scripts

### [base_game_manager.gd](scripts/base_game_manager.gd)
AutoLoad template for game state, pausing, and scene flow.

## Load This Skill When

- bootstrapping a new project
- picking a structure for a platformer, RPG, or FPS
- migrating from an ad hoc layout to a clearer architecture

## Never Do

- Never hardcode scene paths in many unrelated places.
- Never forget to register required AutoLoads.
- Never pause the full tree without planning which UI should still process.
- Never reuse a template without adapting it to the actual game loop.

## Platformer Template

```text
my_platformer/
|-- project.godot
|-- autoloads/
|   |-- game_manager.gd
|   |-- audio_manager.gd
|   `-- scene_transitioner.gd
|-- scenes/
|   |-- main_menu.tscn
|   |-- game.tscn
|   `-- pause_menu.tscn
|-- entities/
|   |-- player/
|   |   |-- player.tscn
|   |   |-- player.gd
|   |   `-- player_states/
|   `-- enemies/
|       |-- base_enemy.gd
|       `-- goblin/
|-- levels/
|-- ui/
|-- audio/
`-- resources/
```

## RPG Template

```text
my_rpg/
|-- autoloads/
|   |-- game_data.gd
|   |-- dialogue_manager.gd
|   `-- inventory_manager.gd
|-- entities/
|   |-- player/
|   |-- npcs/
|   `-- interactables/
|-- maps/
|-- systems/
|   |-- combat/
|   |-- dialogue/
|   |-- quests/
|   `-- inventory/
|-- ui/
`-- resources/
```

## Template Guidance

- Put cross-scene orchestration in AutoLoads only when it truly spans the whole game.
- Keep genre systems grouped by responsibility.
- Reuse shared systems through `common/` or `systems/`, not through random cross-folder coupling.

## Example AutoLoad

```gdscript
extends Node

signal game_started
signal game_paused(paused: bool)
signal level_completed

var current_level: int = 1
var score: int = 0
var is_paused: bool = false

func start_game() -> void:
    score = 0
    current_level = 1
    SceneTransitioner.change_scene("res://levels/level_1.tscn")
    game_started.emit()

func pause_game(paused: bool) -> void:
    is_paused = paused
    get_tree().paused = paused
    game_paused.emit(paused)
```

## Related

- [godot-project-foundations](../godot-project-foundations/SKILL.md)
- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
