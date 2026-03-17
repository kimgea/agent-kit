---
name: godot-save-load-systems
description: "Expert blueprint for save/load systems using JSON/binary serialization, PERSIST group pattern, versioning, and migration. Covers player progress, settings, game state persistence, and error recovery. Use when implementing save systems OR data persistence. Keywords save, load, JSON, FileAccess, user://, serialization, version migration, PERSIST group."
---

# Save And Load Systems

Use this skill when the task needs durable persistence across sessions.

Focus:
- `user://` storage
- versioned save schemas
- validation and recovery
- node-to-data extraction instead of saving scene objects directly

## Available Scripts

### [save_migration_manager.gd](scripts/save_migration_manager.gd)
Versioned migration support for changing save schemas safely.

### [save_system_encryption.gd](scripts/save_system_encryption.gd)
Encrypted and compressed save helper for harder-to-edit save files.

> For production save systems, read [save_migration_manager.gd](scripts/save_migration_manager.gd) first.

## Load This Skill When

- adding player progress or settings persistence
- storing world or session state
- migrating old save formats
- deciding between JSON and binary save strategies

## Never Do

- Never ship a save format without a version field.
- Never use absolute OS paths instead of `user://`.
- Never try to serialize live nodes directly.
- Never trust loaded data without validation and defaults.
- Never save large binary blobs into JSON unless the tradeoff is explicit.
- Never save on unstable timing paths when a deliberate checkpoint is available.

## Pattern 1: JSON Save Manager

```gdscript
extends Node

const SAVE_PATH := "user://savegame.save"

func save_game(data: Dictionary) -> void:
    var save_file := FileAccess.open(SAVE_PATH, FileAccess.WRITE)
    if save_file == null:
        push_error("Failed to open save file: " + str(FileAccess.get_open_error()))
        return

    var json_string := JSON.stringify(data, "\t")
    save_file.store_line(json_string)
    save_file.close()

func load_game() -> Dictionary:
    if not FileAccess.file_exists(SAVE_PATH):
        return {}

    var save_file := FileAccess.open(SAVE_PATH, FileAccess.READ)
    if save_file == null:
        push_error("Failed to open save file: " + str(FileAccess.get_open_error()))
        return {}

    var json_string := save_file.get_as_text()
    save_file.close()

    var json := JSON.new()
    var parse_result := json.parse(json_string)
    if parse_result != OK:
        push_error("JSON parse error: " + json.get_error_message())
        return {}

    return json.data as Dictionary
```

## Pattern 2: Extract Data From Nodes

```gdscript
extends CharacterBody2D

var health: int = 100
var score: int = 0
var level: int = 1

func save_data() -> Dictionary:
    return {
        "health": health,
        "score": score,
        "level": level,
        "position": {
            "x": global_position.x,
            "y": global_position.y
        }
    }

func load_data(data: Dictionary) -> void:
    health = data.get("health", 100)
    score = data.get("score", 0)
    level = data.get("level", 1)
    if data.has("position"):
        global_position = Vector2(data.position.x, data.position.y)
```

## Pattern 3: Root Save Payload

```gdscript
func save_game_state() -> void:
    var save_data := {
        "version": "1.0.0",
        "timestamp": Time.get_unix_time_from_system(),
        "player": $Player.save_data()
    }
    SaveManager.save_game(save_data)
```

## JSON Vs Binary

Use JSON when:
- the save format should be inspectable
- iteration speed matters more than compactness
- save size is modest

Use binary when:
- the save is large
- speed or compactness matters more
- the data structure is stable enough to justify extra tooling

## Validation Rules

- default missing fields defensively
- reject impossible values
- migrate old versions before normal load logic
- keep serialization and gameplay state separate

## Reference

- [Godot Docs: Saving Games](https://docs.godotengine.org/en/stable/tutorials/io/saving_games.html)

## Related

- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
