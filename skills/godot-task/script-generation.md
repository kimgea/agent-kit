# Script Generation

Runtime scripts define node behavior - movement, combat, AI, signals, and game logic. They attach to nodes in scenes and run when the game plays.

Use specialist skills before broad fallback rules:

- `godot-gdscript-mastery` for script structure, typing, signals, node access, and style rules
- `godot-composition` for gameplay entity architecture
- `godot-composition-apps` for app, tool, and UI orchestration
- `godot-input-handling` when the script reads actions or input events
- `godot-resource-data-patterns` when the script should operate on `Resource` or `RefCounted` data models
- `godot-signal-architecture` when event flow and decoupling are central to the script
- `godot-state-machine-advanced` when the script implements hierarchical or stacked state behavior
- `godot-testing-patterns` when the task also requires reusable automated verification
- domain skills such as `godot-characterbody-2d`, `godot-animation-player`, `godot-animation-tree-mastery`, `godot-2d-physics`, `godot-audio-systems`, `godot-navigation-pathfinding`, `godot-rpg-stats`, `godot-turn-system`, or `godot-quest-system` when the script's behavior is specific to that domain

Keep this file focused on generation-time constraints: matching the target node type, using the task spec correctly, and avoiding scene-builder/runtime confusion.

## Script Output Requirements

Generate a `.gd` file that:
1. `extends {NodeType}` matching the node it attaches to
2. Uses proper Godot lifecycle methods
3. References sibling/child nodes via correct paths
4. Defines and connects signals as needed

## Script Template

```gdscript
extends {NodeType}
## {script_path}: {Brief description}

# Signals
signal health_changed(new_value: int)
signal died

# Node references (resolved at _ready)
@onready var sprite: Sprite2D = $Sprite2D
@onready var collision: CollisionShape2D = $CollisionShape2D

# State
var _current_health: int

func _ready() -> void:
    _current_health = max_health

func _physics_process(delta: float) -> void:
    pass
```

**Script section ordering:** signals -> @onready vars -> private state -> lifecycle methods -> public methods -> private methods -> signal handlers

Prefer `godot-gdscript-mastery` for the canonical rationale behind this layout. Use the ordering here as the minimum generation contract.

## VehicleBody3D

```gdscript
extends VehicleBody3D

@export var max_engine_force := 150.0
@export var max_steer := 0.5
var _steer_target := 0.0

func _physics_process(delta: float) -> void:
    var fwd: float = Input.get_axis("brake", "accelerate")
    _steer_target = Input.get_axis("steer_right", "steer_left") * max_steer
    steering = move_toward(steering, _steer_target, 2.0 * delta)
    var spd: float = linear_velocity.length()
    engine_force = fwd * max_engine_force * clampf(5.0 / maxf(spd, 0.1), 0.5, 5.0)
```

## Script Constraints

- `extends` MUST match the node type this script attaches to
- Use `@onready` for node refs, NOT `get_node()` in `_process()`. See `godot-gdscript-mastery`.
- ONLY use input actions from the task spec's `Inputs` section. Never invent action names. If none are declared, use direct key checks.
- Connect signals in `_ready()`, NOT in scene builders (scripts aren't instantiated at build-time). See `godot-gdscript-mastery` and `godot-composition`.
- **Sibling signal timing:** `_ready()` fires on children in order. If sibling A emits in its `_ready()`, sibling B hasn't connected yet. Fix: after connecting, check if the emitter already has data and call the handler manually. See `godot-gdscript-mastery`.
- Do NOT use `preload()` for scenes/resources that may not exist yet - use `load()`. Add spawned children to `get_parent()`, not `self`.
- When "Available Nodes" section is provided, use ONLY the exact paths and types listed - do not guess or invent node names
- **CRITICAL: NEVER use `:=` with polymorphic math functions** - `abs`, `sign`, `clamp`, `min`, `max`, `floor`, `ceil`, `round`, `lerp`, `smoothstep`, `move_toward`, `wrap`, `snappedf`, `randf_range`, `randi_range` return Variant (work on multiple types). Use explicit types: `var x: float = abs(y)` not `var x := abs(y)`
