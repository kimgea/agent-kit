---
name: godot-signal-architecture
description: "Expert blueprint for signal-driven architecture using \"Signal Up, Call Down\" pattern for loose coupling. Covers typed signals, signal chains, one-shot connections, and AutoLoad event buses. Use when implementing event systems OR decoupling nodes. Keywords signal, emit, connect, CONNECT_ONE_SHOT, CONNECT_REFERENCE_COUNTED, event bus, AutoLoad, decoupling."
---

# Signal Architecture

Use this skill when the task needs decoupled communication, event flow, or clear ownership boundaries.

Focus:
- `signal up, call down`
- typed signals
- parent-mediated orchestration
- AutoLoad event buses for cross-scene events

## Available Scripts

### [global_event_bus.gd](scripts/global_event_bus.gd)
AutoLoad event bus with typed signals and connection management.

### [signal_debugger.gd](scripts/signal_debugger.gd)
Runtime signal connection analyzer for scene hierarchies.

### [signal_spy.gd](scripts/signal_spy.gd)
Testing utility for tracking emissions and counts.

> For event-bus work, read [global_event_bus.gd](scripts/global_event_bus.gd) first.

## Load This Skill When

- child nodes need to notify parents or managers
- systems should react to events without tight coupling
- multiple scenes need shared events through an AutoLoad
- the task involves signal ownership, connection lifetime, or debugging duplicate emissions

## Use Signals For

- UI input flowing into game logic
- child-to-parent notifications
- score, inventory, combat, or quest events
- cross-scene communication through a bus

## Use Direct Calls For

- parent-controlled child behavior
- local one-to-one interactions
- direct access to child properties or methods

## Never Do

- Never create circular signal dependencies.
- Never skip signal typing in Godot 4.x when typed parameters are known.
- Never leave connections alive after their owner is gone.
- Never assume `_ready()` is enough for dynamically spawned nodes.
- Never use signals for parent-to-child control when a direct call is clearer.
- Never hide side effects inside signal emission order.
- Never prefer string-based signal names over direct typed references.

## Pattern 1: Define Typed Signals

```gdscript
extends CharacterBody2D

signal health_changed(new_health: int, max_health: int)
signal died()
signal item_collected(item_name: String, item_type: int)
```

Avoid:

```gdscript
signal health_changed
signal died
```

## Pattern 2: Emit On State Changes

```gdscript
extends CharacterBody2D

signal health_changed(current: int, maximum: int)
signal died()

var max_health: int = 100
var health: int = 100:
    set(value):
        health = clamp(value, 0, max_health)
        health_changed.emit(health, max_health)
        if health <= 0:
            died.emit()

func take_damage(amount: int) -> void:
    health -= amount
```

Emit first. Cleanup after listeners have had a chance to react.

## Pattern 3: Connect In The Parent

```gdscript
extends Node2D

@onready var player: CharacterBody2D = $Player
@onready var ui: Control = $UI

func _ready() -> void:
    player.health_changed.connect(_on_player_health_changed)
    player.died.connect(_on_player_died)

func _on_player_health_changed(current: int, maximum: int) -> void:
    ui.update_health_bar(current, maximum)

func _on_player_died() -> void:
    ui.show_game_over()
    get_tree().paused = true
```

## Pattern 4: AutoLoad Event Bus

```gdscript
# events.gd
extends Node

signal level_completed(level_number: int)
signal player_spawned(player: Node2D)
signal boss_defeated(boss_name: String)

Events.level_completed.emit(3)
Events.level_completed.connect(_on_level_completed)
```

Use this for cross-scene events, not as a replacement for all local signal wiring.

## Pattern 5: Signal Chains

```gdscript
# enemy.gd
signal died(score_value: int)

func _on_health_depleted() -> void:
    died.emit(100)
    queue_free()

# combat_manager.gd
func _ready() -> void:
    for enemy in get_tree().get_nodes_in_group("enemies"):
        enemy.died.connect(_on_enemy_died)

func _on_enemy_died(score_value: int) -> void:
    GameManager.add_score(score_value)
    Events.enemy_killed.emit()
```

## Pattern 6: One-Shot Connections

```gdscript
timer.timeout.connect(_on_timer_timeout, CONNECT_ONE_SHOT)

func _on_timer_timeout() -> void:
    print("This only fires once")
```

## Pattern 7: Structured Payloads

```gdscript
signal picked_up(item_data: Dictionary)

func _on_player_enter() -> void:
    picked_up.emit({
        "name": item_name,
        "type": item_type,
        "value": item_value,
        "icon": item_icon
    })
```

Use small typed parameter lists when possible. Use a dictionary or resource payload when the event data is naturally grouped.

## Best Practices

### Descriptive Names

```gdscript
signal button_pressed()
signal enemy_defeated(enemy_type: String)
signal animation_finished(animation_name: String)
```

Avoid vague names like `done()` or `finished()` when multiple meanings are possible.

### Avoid Circular Dependencies

Bad:
- `A` requests data from `B`
- `B` depends on a signal from `A`

Good:
- a parent or AutoLoad mediates the flow

### Clean Up Connections

```gdscript
func _ready() -> void:
    player.died.connect(_on_player_died)

func _exit_tree() -> void:
    if player and player.died.is_connected(_on_player_died):
        player.died.disconnect(_on_player_died)
```

Or:

```gdscript
player.died.connect(_on_player_died, CONNECT_REFERENCE_COUNTED)
```

### Group Related Signals

```gdscript
# Combat
signal health_changed(current: int, max_health: int)
signal died()
signal respawned()

# Movement
signal jumped()
signal landed()
signal direction_changed(direction: Vector2)

# Inventory
signal item_added(item: Dictionary)
signal item_removed(item: Dictionary)
signal inventory_full()
```

## Testing Signals

```gdscript
func test_health_signal() -> void:
    var signal_emitted := false
    var received_health := 0

    player.health_changed.connect(
        func(current: int, _max: int):
            signal_emitted = true
            received_health = current
    )

    player.health = 50

    assert(signal_emitted, "Signal was not emitted")
    assert(received_health == 50, "Health value incorrect")
```

## Common Gotchas

Issue: signal is not firing
- Check the connection target and code path.
- Verify the emitter is actually reached.

Issue: signal fires multiple times
- Check for repeated connections.
- Use `CONNECT_ONE_SHOT` where appropriate.

Issue: callback runs on a freed node
- Disconnect in `_exit_tree()`.
- Or use `CONNECT_REFERENCE_COUNTED`.

## Reference

- [Godot Docs: Signals](https://docs.godotengine.org/en/stable/getting_started/step_by_step/signals.html)
- [Godot Docs: Scene Organization](https://docs.godotengine.org/en/stable/tutorials/best_practices/scene_organization.html)

## Related

- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
