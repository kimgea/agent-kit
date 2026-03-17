---
name: godot-turn-system
description: "Expert blueprint for turn-based combat with turn order, action points, phase management, and timeline systems for strategy/RPG games. Covers speed-based initiative, interrupts, and simultaneous turns. Use when implementing turn-based combat OR tactical systems. Keywords turn-based, initiative, action points, phase, round, turn order, combat."
---

# Turn System

Use this skill when the task needs initiative order, phases, action points, or timeline-based combat flow.

Focus:
- deterministic turn order
- action-point validation
- round and phase management
- interrupts and timeline variations

## Available Scripts

### [active_time_battle.gd](scripts/active_time_battle.gd)
Active Time Battle framework with async action support.

### [timeline_turn_manager.gd](scripts/timeline_turn_manager.gd)
Timeline turn manager with interrupts and simultaneous actions.

## Load This Skill When

- building turn-based or tactical combat
- deciding between round order and timeline systems
- adding action points or per-turn resource limits
- handling online or delayed-input turn constraints

## Never Do

- Never recalculate initiative more often than the design requires.
- Never leave tie-breaking nondeterministic.
- Never spend action points without validating the cost first.
- Never encode many phases as ad hoc integer switches.
- Never allow endless waiting for player input in a networked or shared-turn game.
- Never emit end-of-turn events before cleanup is complete.

## Basic Turn Manager

```gdscript
extends Node

signal turn_started(combatant: Node)
signal turn_ended(combatant: Node)
signal round_ended

var combatants: Array[Node] = []
var turn_order: Array[Node] = []
var current_turn_index: int = 0

func start_combat(participants: Array[Node]) -> void:
    combatants = participants
    calculate_turn_order()
    start_next_turn()

func calculate_turn_order() -> void:
    turn_order = combatants.duplicate()
    turn_order.sort_custom(func(a, b): return a.speed > b.speed)

func start_next_turn() -> void:
    if current_turn_index >= turn_order.size():
        current_turn_index = 0
        round_ended.emit()
        calculate_turn_order()

    var current := turn_order[current_turn_index]
    turn_started.emit(current)
```

## Action Points

```gdscript
@export var max_action_points: int = 3
var current_action_points: int = 3

func start_turn() -> void:
    current_action_points = max_action_points

func can_perform_action(cost: int) -> bool:
    return current_action_points >= cost

func perform_action(cost: int) -> bool:
    if not can_perform_action(cost):
        return false
    current_action_points -= cost
    return true
```

## Turn Phases

```gdscript
enum Phase { DRAW, MAIN, END }

var current_phase: Phase = Phase.DRAW

func advance_phase() -> void:
    match current_phase:
        Phase.DRAW:
            current_phase = Phase.MAIN
        Phase.MAIN:
            current_phase = Phase.END
        Phase.END:
            TurnManager.end_turn()
            current_phase = Phase.DRAW
```

## Design Guidance

- break speed ties with a deterministic secondary key
- keep the turn owner responsible only for its own action window
- let the manager own order, cleanup, and phase transitions
- use explicit timeout policy for networked or asynchronous multiplayer

## Related

- [godot-combat-system](../godot-combat-system/SKILL.md)
- [godot-rpg-stats](../godot-rpg-stats/SKILL.md)
- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
