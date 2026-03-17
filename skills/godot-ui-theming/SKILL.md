---
name: godot-ui-theming
description: "Expert blueprint for UI themes using Theme resources, StyleBoxes, custom fonts, and theme overrides for consistent visual styling. Covers StyleBoxFlat/Texture, theme inheritance, dynamic theme switching, and font variations. Use when implementing consistent UI styling OR supporting multiple themes. Keywords Theme, StyleBox, StyleBoxFlat, add_theme_override, font, theme inheritance, dark mode."
---

# UI Theming

Use this skill when the task needs a consistent visual language across multiple UI controls.

Focus:
- `Theme` resources
- `StyleBox` reuse
- font management
- inheritance and selective overrides

## Available Scripts

### [global_theme_manager.gd](scripts/global_theme_manager.gd)
Theme manager for switching variants and handling fallbacks.

### [ui_scale_manager.gd](scripts/ui_scale_manager.gd)
Scaling helper for DPI and resolution-sensitive UI.

## Load This Skill When

- establishing a shared UI look
- supporting theme variants
- replacing ad hoc per-node overrides
- working with fonts, styleboxes, and reusable color choices

## Never Do

- Never create duplicate `StyleBox` instances per node when the style belongs in a shared theme.
- Never break inheritance accidentally by assigning themes at the wrong level.
- Never hardcode colors everywhere when the theme should own them.
- Never use per-node theme overrides for a style that is meant to be global.
- Never churn theme changes every frame.

## Basic Workflow

1. Open `Project Settings -> GUI -> Theme`.
2. Create a `Theme` resource.
3. Assign it at the appropriate root `Control`.
4. Let child controls inherit unless a local override is intentional.

## StyleBox Pattern

```gdscript
var style := StyleBoxFlat.new()
style.bg_color = Color.DARK_BLUE
style.corner_radius_all = 5

$Button.add_theme_stylebox_override("normal", style)
```

Prefer storing shared versions of this in a `Theme` resource instead of rebuilding them repeatedly.

## Font Loading

```gdscript
var font := load("res://fonts/my_font.ttf")
$Label.add_theme_font_override("font", font)
$Label.add_theme_font_size_override("font_size", 24)
```

## Theme Ownership Guidance

- Put global style rules in the shared `Theme`.
- Use local overrides only for one-off exceptions.
- Keep semantic colors and font choices centralized.

## Reference

- [Godot Docs: GUI Theming](https://docs.godotengine.org/en/stable/tutorials/ui/gui_skinning.html)

## Related

- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
