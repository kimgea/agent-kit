---
name: godot-gdscript-mastery
description: "Expert GDScript best practices including static typing (var x: int, func returns void), signal architecture (signal up call down), unique node access (%NodeName, @onready), script structure (extends, class_name, signals, exports, methods), and performance patterns (dict.get with defaults, avoid get_node in loops). Use for code review, refactoring, or establishing project standards. Trigger keywords: static_typing, signal_architecture, unique_nodes, @onready, class_name, signal_up_call_down, gdscript_style_guide."
---

# GDScript Mastery

Expert guidance for writing performant, maintainable GDScript following official Godot standards.

## NEVER Do

- **NEVER use dynamic typing for performance-critical code** — `var x = 5` is 20-40% slower than `var x: int = 5`. Type everything.
- **NEVER call parent methods from children ("Call Up")** — Use "Signal Up, Call Down". Children emit signals, parents call child methods.
- **NEVER use `get_node()` in `_process()` or `_physics_process()`** — Caches with `@onready var sprite = $Sprite`. get_node() is slow in loops.
- **NEVER access dictionaries without `.get()` default** — `dict["key"]` crashes if missing. Use `dict.get("key", default)` for safety.
- **NEVER skip `class_name` for reusable scripts** — Without `class_name`, you can't use as type hints (`var item: Item`). Makes code harder to maintain.
---

## Available Scripts

> **MANDATORY**: Read the appropriate script before implementing the corresponding pattern.

### [advanced_lambdas.gd](scripts/advanced_lambdas.gd)
Higher-order functions in GDScript: filter/map with lambdas, factory functions returning Callables, typed array godot-composition, and static utility methods.

### [type_checker.gd](scripts/type_checker.gd)
Scans codebase for missing type hints. Run before releases to enforce static typing standards.

### [performance_analyzer.gd](scripts/performance_analyzer.gd)
Detects performance anti-patterns: get_node() in loops, string concat, unsafe dict access.

### [signal_architecture_validator.gd](scripts/signal_architecture_validator.gd)
Enforces "Signal Up, Call Down" pattern. Detects get_parent() calls and untyped signals.

> **Do NOT Load** performance_analyzer.gd unless profiling hot paths or optimizing frame rates.


---

## Core Directives

### 1. Strong Typing
Always use static typing. It improves performance and catches bugs early.
**Rule**: Prefer `var x: int = 5` over `var x = 5`.
**Rule**: Always specify return types for functions: `func _ready() -> void:`.

### 2. Signal Architecture
- **Connect in `_ready()`**: Preferably connect signals in code to maintain visibility, rather than just in the editor.
- **Typed Signals**: Define signals with types: `signal item_collected(item: ItemResource)`.
- **Pattern**: "Signal Up, Call Down". Children should never call methods on parents; they should emit signals instead.

### 3. Node Access
- **Unique Names**: Use `%UniqueNames` for nodes that are critical to the script's logic.
- **Onready Overrides**: Prefer `@onready var sprite = %Sprite2D` over calling `get_node()` in every function.

### 4. Code Structure
Follow the standard Godot script layout:
1. `extends`
2. `class_name`
3. `signals` / `enums` / `constants`
4. `@export` / `@onready` / `properties`
5. `_init()` / `_ready()` / `_process()`
6. Public methods
7. Private methods (prefixed with `_`)

## Common "Architect" Patterns

### The "Safe" Dictionary Lookup
Avoid `dict["key"]` if you aren't 100% sure it exists. Use `dict.get("key", default)`.

### Variant Inference Traps

Avoid `:=` when the right-hand side is Variant-typed or polymorphic.

```gdscript
# WRONG: polymorphic helpers return Variant
var amount := abs(speed)
var blend := clamp(value, 0.0, 1.0)
var lowest := min(a, b)

# CORRECT: add an explicit type or use plain =
var amount: float = abs(speed)
var blend: float = clamp(value, 0.0, 1.0)
var lowest = min(a, b)

# WRONG: instantiate() is treated as Variant for inference
var scene: PackedScene = load("res://enemy.tscn")
var enemy := scene.instantiate()

# CORRECT
var scene: PackedScene = load("res://enemy.tscn")
var enemy = scene.instantiate()
```

Apply the same rule to array and dictionary element access when the result type is not statically known.

### Value Types vs Reference Types

Many Godot built-in math and transform types are copied by value.

```gdscript
# WRONG: modifying the parameter does not update the caller
func collect(node: Node, result: AABB) -> void:
    result = result.merge(node.get_aabb())

# CORRECT: return the value or write into a mutable container
func merge_aabb(result: AABB, other: AABB) -> AABB:
    return result.merge(other)

func collect(node: Node, out: Array) -> void:
    out.append(node.get_aabb())
```

Rules:
- `bool`, `int`, `float`, `Vector2`, `Vector3`, `AABB`, `Transform2D`, `Transform3D`, and similar built-ins are value types.
- `Array`, `Dictionary`, `Object`, `Resource`, and other reference-based containers carry shared state unless duplicated.
- When you need out-parameters, return the value explicitly or write into a mutable container.

### Scene Unique Nodes
When building complex UI, always toggle "Access as Scene Unique Name" on critical nodes (Labels, Buttons) and access them via `%Name`.

### Annotation Pitfalls

Annotations are useful, but a few combinations create brittle scripts.

```gdscript
# GOOD: resolve optional nodes explicitly
var optional_label: Label = null

func _ready() -> void:
    optional_label = get_node_or_null("OptionalLabel")

# BAD: conditional @onready lookup is easy to misread and harder to debug
@onready var maybe_label = $OptionalLabel if has_node("OptionalLabel") else null
```

Rules:
- Use `@onready` for stable node references that should exist when the node enters the tree.
- For optional nodes, prefer a typed nullable variable plus `get_node_or_null()` in `_ready()`.
- Avoid mixing `@export` and `@onready` for the same value; `@onready` will overwrite the exported assignment.
- Use `class_name` for reusable scripts that should appear as types in other scripts or inspector fields.

### Ready-Order Signal Timing

Sibling nodes do not become ready simultaneously in the way many projects assume.

```gdscript
func _ready() -> void:
    producer.value_changed.connect(_on_value_changed)

    # If producer may already have emitted in its own _ready(),
    # replay the current state manually after connecting.
    if producer.has_method("get_current_value"):
        _on_value_changed(producer.get_current_value())
```

Rules:
- Connect signals in `_ready()`, not at script top or in scene builders.
- If sibling A may emit during its `_ready()`, sibling B must reconcile current state after connecting.
- Do not assume scene-tree child order is a safe event-delivery mechanism.

## Reference
- Official Docs: `tutorials/scripting/gdscript/gdscript_styleguide.rst`
- Official Docs: `tutorials/best_practices/logic_preferences.rst`


### Related
- Master Skill: [godot-master](../godot-master/SKILL.md)
