---
name: godot-ui-rich-text
description: "Expert blueprint for RichTextLabel with BBCode formatting (bold, italic, colors, images, clickable links) and custom effects. Covers meta tags, RichTextEffect shaders, and dynamic content. Use when implementing dialogue systems OR formatted text. Keywords RichTextLabel, BBCode, [b], [color], [url], meta_clicked, RichTextEffect, dialogue."
---

# Rich Text And BBCode

Use this skill when the task needs formatted text, dialogue markup, or clickable rich content.

Focus:
- `RichTextLabel`
- BBCode tags
- `meta_clicked` link handling
- custom text effects

## Available Scripts

### [custom_bbcode_effect.gd](scripts/custom_bbcode_effect.gd)
Custom `RichTextEffect` examples such as wave, rainbow, shake, and typewriter.

### [rich_text_animator.gd](scripts/rich_text_animator.gd)
Typewriter-style BBCode animator with pausing and event support.

## Load This Skill When

- implementing dialogue text
- formatting UI text with tags
- handling clickable rich-text metadata
- adding animated or custom text effects

## Never Do

- Never forget to enable BBCode before assigning tagged text.
- Never reference images with ambiguous paths.
- Never assume line breaks will render the way plain text does without checking the BBCode behavior.
- Never use URL or meta tags without wiring the click handler.
- Never nest duplicate tags carelessly.
- Never rely on invalid color values.

## Minimal Example

```gdscript
$RichTextLabel.bbcode_enabled = true
$RichTextLabel.text = "[b]Bold[/b] and [i]italic[/i] text"
```

## Common Tags

```bbcode
[b]Bold[/b]
[i]Italic[/i]
[u]Underline[/u]
[color=red]Red text[/color]
[color=#00FF00]Green text[/color]
[center]Centered[/center]
[img]res://icon.png[/img]
[url=data]Clickable link[/url]
```

## Meta Click Handling

```gdscript
func _ready() -> void:
    $RichTextLabel.meta_clicked.connect(_on_meta_clicked)

func _on_meta_clicked(meta: Variant) -> void:
    print("Clicked: ", meta)
```

## Design Guidance

- keep content and markup generation separate when text is data-driven
- sanitize or validate dynamic markup when content comes from tools or external files
- use custom effects sparingly when readability matters

## Reference

- [Godot Docs: BBCode in RichTextLabel](https://docs.godotengine.org/en/stable/tutorials/ui/bbcode_in_richtextlabel.html)

## Related

- [godot-ui-theming](../godot-ui-theming/SKILL.md)
- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
