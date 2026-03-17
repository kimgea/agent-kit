---
name: godot-resource-data-patterns
description: "Expert blueprint for data-oriented design using Resource/RefCounted classes (item databases, character stats, reusable data structures). Covers typed arrays, serialization, nested resources, resource caching. Use when implementing data systems OR inventory/stats/dialogue databases. Keywords Resource, RefCounted, ItemData, CharacterStats, database, serialization, @export, typed arrays."
---

# Resource And Data Patterns

Use this skill when the task needs reusable, inspector-friendly data definitions.

Focus:
- `Resource` for saved or reusable data
- `RefCounted` for runtime-only helpers
- typed exports and arrays
- safe duplication and serialization boundaries

## Available Scripts

### [data_factory_resource.gd](scripts/data_factory_resource.gd)
Resource factory with type validation and batch creation.

### [resource_pool.gd](scripts/resource_pool.gd)
Pooling helper for resource-heavy hot paths.

### [resource_validator.gd](scripts/resource_validator.gd)
Checks resources for missing exports and invalid configuration.

> For item, stat, or config systems, read [data_factory_resource.gd](scripts/data_factory_resource.gd) first.

## Load This Skill When

- building item, ability, dialogue, or stat databases
- deciding between `Resource`, `RefCounted`, and `Node`
- exporting typed data for inspector editing
- defining save-friendly data boundaries

## Never Do

- Never mutate a shared loaded resource when you need per-instance runtime state.
- Never use untyped arrays where the element type is known.
- Never forget `@export` for editor-driven configuration.
- Never put node lifecycle assumptions into a plain `Resource`.
- Never serialize direct node references into persistent data.
- Never save resources without checking the return value.

## Type Selection

| Type | Use when | Serializable | Save to disk | Inspector-friendly |
|------|----------|--------------|--------------|--------------------|
| `Resource` | reusable data definitions | yes | yes | yes |
| `RefCounted` | runtime-only helpers | no | no | no |
| `Node` | scene-tree behavior | scene-owned | scene-owned | yes |

## When To Use Resources

- item definitions
- character or enemy stats
- ability data
- dialogue data
- reusable configuration

## When To Use RefCounted

- temporary calculations
- runtime-only helpers
- non-scene objects that do not need editor persistence

## Pattern 1: Custom Resource

```gdscript
extends Resource
class_name ItemData

@export var item_name: String = ""
@export var description: String = ""
@export_enum("Weapon", "Consumable", "Armor") var item_type: int = 0
@export var icon: Texture2D
@export var value: int = 0
@export var stackable: bool = false
@export var max_stack: int = 1
```

Create instances from the inspector:
1. `New Resource -> ItemData`
2. Fill the exported fields
3. Save as a `.tres`

## Pattern 2: Runtime Copy Of Template Data

```gdscript
extends Resource
class_name CharacterStats

@export var max_health: int = 100
@export var max_mana: int = 50
@export var strength: int = 10
@export var defense: int = 5
@export var speed: float = 100.0

var current_health: int = max_health:
    set(value):
        current_health = clampi(value, 0, max_health)

var current_mana: int = max_mana:
    set(value):
        current_mana = clampi(value, 0, max_mana)

func duplicate_stats() -> CharacterStats:
    var stats := CharacterStats.new()
    stats.max_health = max_health
    stats.max_mana = max_mana
    stats.strength = strength
    stats.defense = defense
    stats.speed = speed
    stats.current_health = current_health
    stats.current_mana = current_mana
    return stats
```

```gdscript
@export var stats: CharacterStats

func _ready() -> void:
    if stats:
        stats = stats.duplicate_stats()
```

## Typed Arrays

```gdscript
@export var items: Array[ItemData] = []
```

Prefer this over:

```gdscript
@export var items: Array = []
```

## Serialization Boundary

- store plain values, IDs, resource paths, or `NodePath` values
- do not store direct `Node` references in persistent resource data

## Reference

- [Godot Docs: Resources](https://docs.godotengine.org/en/stable/tutorials/scripting/resources.html)

## Related

- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
