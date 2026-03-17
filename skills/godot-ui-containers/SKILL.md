---
name: godot-ui-containers
description: "Expert blueprint for responsive UI layouts using Container nodes (HBoxContainer, VBoxContainer, GridContainer, MarginContainer, ScrollContainer). Covers size flags, anchors, split containers, and dynamic layouts. Use when building adaptive interfaces OR implementing responsive menus. Keywords Container, HBoxContainer, VBoxContainer, GridContainer, size_flags, EXPAND_FILL, anchors, responsive."
---

# UI Containers

Use this skill when layout responsiveness matters more than hand-placed control coordinates.

Focus:
- container-driven layout
- size flags
- anchors and margins
- grid and scroll behavior

## Available Scripts

### [responsive_layout_builder.gd](scripts/responsive_layout_builder.gd)
Builder for breakpoint-based responsive layouts.

### [responsive_grid.gd](scripts/responsive_grid.gd)
Grid helper that adapts column count to available width.

## Load This Skill When

- building menus, HUD panels, inventory screens, or settings screens
- replacing brittle manual UI positioning
- debugging layout expansion or scroll behavior

## Never Do

- Never manually position children that live under a container and expect that position to stick.
- Never forget the relevant size flags on expanding controls.
- Never use `GridContainer` without explicitly setting its column strategy.
- Never stack containers so deeply that the layout becomes opaque and expensive.
- Never rely on default spacing if the screen clearly needs controlled separation.
- Never use `ScrollContainer` without a bounded child layout.

## Basic VBox Example

```gdscript
$VBoxContainer.add_theme_constant_override("separation", 10)
```

## Responsive Layout Pattern

```gdscript
func _ready() -> void:
    $MarginContainer.set_anchors_preset(Control.PRESET_FULL_RECT)
    $MarginContainer.add_theme_constant_override("margin_left", 20)
    $MarginContainer.add_theme_constant_override("margin_right", 20)
```

## Size Flags

```gdscript
button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
button.size_flags_vertical = Control.SIZE_SHRINK_CENTER
```

## Practical Guidance

- Use `VBoxContainer` and `HBoxContainer` for linear groups.
- Use `GridContainer` for inventories and tiled option sets.
- Use `MarginContainer` to create outer breathing room.
- Use `ScrollContainer` when the content should stay bounded while overflowing.

## Reference

- [Godot Docs: GUI Containers](https://docs.godotengine.org/en/stable/tutorials/ui/gui_containers.html)

## Related

- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
