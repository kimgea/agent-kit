---
name: godot-tweening
description: "Expert blueprint for programmatic animation using Tween for smooth property transitions, UI effects, camera movements, and juice. Covers easing functions, parallel tweens, chaining, and lifecycle management. Use when implementing UI animations OR procedural movement. Keywords Tween, easing, interpolation, EASE_IN_OUT, TRANS_CUBIC, tween_property, tween_callback."
---

# Tweening

Use this skill when the task needs procedural motion or lightweight UI animation without authored tracks.

Focus:
- tween lifecycle management
- easing and transition choices
- chaining versus parallel execution
- reusable motion patterns

## Available Scripts

### [juice_manager.gd](scripts/juice_manager.gd)
Tween-based effect presets for bounce, shake, pulse, and similar polish effects.

## Load This Skill When

- animating UI reactions
- adding camera or object motion procedurally
- sequencing small feedback effects
- replacing overkill animation setups with concise tween code

## Never Do

- Never keep spawning conflicting tweens on the same target without cleanup.
- Never create tweens every frame unless that is the explicit design.
- Never expect sequential tween calls to run in parallel unless you set that behavior.
- Never use a tween for an instant property set.
- Never forget cleanup or signal handling when the tween result matters.
- Never default to linear easing for UI feedback without reason.

## Basic Tween

```gdscript
func _ready() -> void:
    var tween := create_tween()
    tween.tween_property(self, "position", Vector2(100, 100), 2.0)
```

## Common Patterns

### Property Animation

```gdscript
var tween := create_tween()
tween.tween_property($Sprite, "modulate:a", 0.0, 1.0)
tween.tween_property($Sprite, "position:x", 200, 1.0)
```

### Callback

```gdscript
var tween := create_tween()
tween.tween_property($Sprite, "position", Vector2(100, 0), 1.0)
tween.tween_callback(queue_free)
```

### Interval

```gdscript
var tween := create_tween()
tween.tween_property($Label, "modulate:a", 0.0, 0.5)
tween.tween_interval(1.0)
tween.tween_property($Label, "modulate:a", 1.0, 0.5)
```

### Easing

```gdscript
var tween := create_tween()
tween.set_ease(Tween.EASE_IN_OUT)
tween.set_trans(Tween.TRANS_CUBIC)
tween.tween_property($Sprite, "position:x", 200, 1.0)
```

## Common Easing Choices

- `EASE_IN + TRANS_QUAD`: acceleration
- `EASE_OUT + TRANS_QUAD`: deceleration
- `EASE_IN_OUT + TRANS_CUBIC`: smooth UI motion
- `EASE_OUT + TRANS_BOUNCE`: punchy feedback

## Parallel Tweens

```gdscript
var tween := create_tween()
tween.set_parallel(true)
tween.tween_property($Sprite, "position", Vector2(100, 100), 1.0)
tween.tween_property($Sprite, "scale", Vector2(2, 2), 1.0)
```

## UI Hover Example

```gdscript
func _on_mouse_entered() -> void:
    var tween := create_tween()
    tween.tween_property(self, "scale", Vector2(1.1, 1.1), 0.2)

func _on_mouse_exited() -> void:
    var tween := create_tween()
    tween.tween_property(self, "scale", Vector2.ONE, 0.2)
```

## Design Guidance

- keep one owner responsible for replacing or canceling active tweens
- use tween callbacks for workflow boundaries only when animation completion matters
- prefer tweens for short procedural motion, not for large authored animation graphs

## Related

- [godot-ui-containers](../godot-ui-containers/SKILL.md)
- [godot-ui-theming](../godot-ui-theming/SKILL.md)
- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
