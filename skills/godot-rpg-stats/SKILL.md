---
name: godot-rpg-stats
description: "Expert blueprint for RPG stat systems (attributes, leveling, modifiers, damage formulas) using Resource-based stats, stackable modifiers, and derived stat calculations. Use when implementing character progression OR equipment/buff systems. Keywords stats, attributes, leveling, modifiers, CharacterStats, derived stats, damage calculation, XP."
---

# RPG Stats

Use this skill when the task needs attributes, leveling, buffs, debuffs, or derived combat values.

Focus:
- resource-based stat containers
- modifier stacks with stable IDs
- derived stat calculation
- progression and level-up flow

## Available Scripts

### [stat_resource.gd](scripts/stat_resource.gd)
Resource-based stat system with caching and dirty flags.

### [modifier_stack_stats.gd](scripts/modifier_stack_stats.gd)
Modifier system with additive and multiplicative stacking.

## Load This Skill When

- building progression systems
- adding equipment or status modifiers
- defining damage, crit, or derived-value formulas
- needing reusable stat data across characters

## Never Do

- Never use integer percentage math where fractional precision matters.
- Never mutate stats silently when UI or other systems depend on updates.
- Never rely on additive modifiers alone if scaling balance matters.
- Never add removable modifiers without stable IDs.
- Never let progression formulas grow without bounds or review.
- Never allow derived stats to go invalid or negative unless the design requires it.

## Core Stats Resource

```gdscript
class_name Stats
extends Resource

signal stat_changed(stat_name: String, old_value: float, new_value: float)
signal level_up(new_level: int)

@export var level: int = 1
@export var experience: int = 0
@export var experience_to_next_level: int = 100
@export var strength: int = 10
@export var dexterity: int = 10
@export var intelligence: int = 10
@export var vitality: int = 10

var attack_power: int:
    get: return strength + (vitality / 2)
var magic_power: int:
    get: return intelligence * 3
var critical_chance: float:
    get: return dexterity * 0.01

var modifiers: Dictionary = {}
```

## Experience And Leveling

```gdscript
func add_experience(amount: int) -> void:
    experience += amount
    while experience >= experience_to_next_level:
        level_up_character()

func level_up_character() -> void:
    level += 1
    experience -= experience_to_next_level
    experience_to_next_level = int(experience_to_next_level * 1.5)
    strength += 2
    dexterity += 2
    intelligence += 2
    vitality += 2
    level_up.emit(level)
```

## Modifier Pattern

```gdscript
func add_modifier(stat_name: String, modifier_id: String, value: float) -> void:
    if not modifiers.has(stat_name):
        modifiers[stat_name] = {}
    modifiers[stat_name][modifier_id] = value

func remove_modifier(stat_name: String, modifier_id: String) -> void:
    if modifiers.has(stat_name):
        modifiers[stat_name].erase(modifier_id)
```

## Equipment Integration

```gdscript
extends Item
class_name EquipmentItem

@export var stat_bonuses: Dictionary = {
    "strength": 5,
    "dexterity": 3
}

func on_equip(stats: Stats) -> void:
    for stat_name in stat_bonuses:
        stats.add_modifier(stat_name, "equipment_" + id, stat_bonuses[stat_name])
```

## Status Effects

```gdscript
class_name StatusEffect
extends Resource

@export var effect_id: String
@export var duration: float
@export var stat_modifiers: Dictionary = {}
```

## Design Guidance

- keep base stats and runtime modifiers distinct
- prefer typed or validated stat keys
- centralize level-up and recalculation rules
- emit change signals when visible values move

## Related

- [godot-resource-data-patterns](../godot-resource-data-patterns/SKILL.md)
- [godot-turn-system](../godot-turn-system/SKILL.md)
- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
