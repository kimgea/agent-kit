---
name: godot-shaders-basics
description: "Expert blueprint for shader programming (visual effects, post-processing, material customization) using Godot's GLSL-like shader language. Covers canvas_item (2D), spatial (3D), uniforms, built-in variables, and performance. Use when implementing custom effects OR stylized rendering. Keywords shader, GLSL, fragment, vertex, canvas_item, spatial, uniform, UV, COLOR, ALBEDO, post-processing."
---

# Shader Basics

Use this skill for custom materials, post-processing, and stylized effects.

Focus:
- `canvas_item` shaders for 2D
- `spatial` shaders for 3D
- uniforms and editor-friendly parameters
- built-in variables and performance tradeoffs

## Available Scripts

### [vfx_port_shader.gdshader](scripts/vfx_port_shader.gdshader)
Shader template with parameter validation and common effect patterns.

### [shader_parameter_animator.gd](scripts/shader_parameter_animator.gd)
Runtime shader uniform animation without `AnimationPlayer`.

## Load This Skill When

- implementing custom visual effects
- adding shader-driven UI or sprite effects
- building reusable materials with tweakable uniforms
- debugging performance or correctness in shader code

## Never Do

- Never put expensive math in `fragment()` unless the cost is justified.
- Never pass unnormalized vectors into operations that expect normalized input.
- Never rely on dynamic branching when `mix()`, `step()`, or `smoothstep()` will do.
- Never modify `UV` without thinking about wrap or clamp behavior.
- Never use `TIME` without an explicit speed factor.
- Never expose colors without `: source_color` when you want an editor color picker.

## Minimal 2D Shader

```glsl
shader_type canvas_item;

void fragment() {
    vec4 tex_color = texture(TEXTURE, UV);
    COLOR = tex_color * vec4(1.0, 0.5, 0.5, 1.0);
}
```

Apply to a `Sprite2D`:
1. Select the node.
2. Set `Material -> New ShaderMaterial`.
3. Set `Shader -> New Shader`.
4. Paste the shader code.

## Common 2D Effects

### Dissolve

```glsl
shader_type canvas_item;

uniform float dissolve_amount : hint_range(0.0, 1.0) = 0.0;
uniform sampler2D noise_texture;

void fragment() {
    vec4 tex_color = texture(TEXTURE, UV);
    float noise = texture(noise_texture, UV).r;

    if (noise < dissolve_amount) {
        discard;
    }

    COLOR = tex_color;
}
```

### Wave Distortion

```glsl
shader_type canvas_item;

uniform float wave_speed = 2.0;
uniform float wave_amount = 0.05;

void fragment() {
    vec2 uv = UV;
    uv.x += sin(uv.y * 10.0 + TIME * wave_speed) * wave_amount;
    COLOR = texture(TEXTURE, uv);
}
```

### Outline

```glsl
shader_type canvas_item;

uniform vec4 outline_color : source_color = vec4(0.0, 0.0, 0.0, 1.0);
uniform float outline_width = 2.0;

void fragment() {
    vec4 col = texture(TEXTURE, UV);
    vec2 pixel_size = TEXTURE_PIXEL_SIZE * outline_width;

    float alpha = col.a;
    alpha = max(alpha, texture(TEXTURE, UV + vec2(pixel_size.x, 0.0)).a);
    alpha = max(alpha, texture(TEXTURE, UV + vec2(-pixel_size.x, 0.0)).a);
    alpha = max(alpha, texture(TEXTURE, UV + vec2(0.0, pixel_size.y)).a);
    alpha = max(alpha, texture(TEXTURE, UV + vec2(0.0, -pixel_size.y)).a);

    COLOR = mix(outline_color, col, col.a);
    COLOR.a = alpha;
}
```

## Basic 3D Shader

```glsl
shader_type spatial;

void fragment() {
    ALBEDO = vec3(1.0, 0.0, 0.0);
}
```

## Toon Shading

```glsl
shader_type spatial;

uniform vec3 base_color : source_color = vec3(1.0);
uniform int color_steps = 3;

void light() {
    float ndotl = dot(NORMAL, LIGHT);
    float stepped = floor(ndotl * float(color_steps)) / float(color_steps);
    DIFFUSE_LIGHT = base_color * stepped;
}
```

## Screen-Space Effect Example

```glsl
shader_type canvas_item;

uniform float vignette_strength = 0.5;

void fragment() {
    vec4 color = texture(TEXTURE, UV);
    vec2 center = vec2(0.5, 0.5);
    float dist = distance(UV, center);
    float vignette = 1.0 - dist * vignette_strength;
    COLOR = color * vignette;
}
```

## Uniform Patterns

```glsl
uniform float intensity : hint_range(0.0, 1.0) = 0.5;
uniform vec4 tint_color : source_color = vec4(1.0);
uniform sampler2D noise_texture;
```

```gdscript
material.set_shader_parameter("intensity", 0.8)
```

## Built-in Variables

### `canvas_item`

- `UV`: texture coordinates
- `COLOR`: output color
- `TEXTURE`: current texture
- `TIME`: time since start
- `SCREEN_UV`: screen coordinates

### `spatial`

- `ALBEDO`: base color
- `NORMAL`: surface normal
- `ROUGHNESS`: roughness value
- `METALLIC`: metallic value

## Best Practices

### Use Uniforms for Tuning

```glsl
// Good: adjustable
uniform float speed = 1.0;

void fragment() {
    COLOR.r = sin(TIME * speed);
}
```

```glsl
// Avoid hardcoded tuning values unless the effect is fixed by design
void fragment() {
    COLOR.r = sin(TIME * 2.5);
}
```

### Keep Performance in Mind

- Move reusable calculations out of hot shader paths when possible.
- Prefer textures or uniforms over repeated heavy math.
- Test on representative hardware if the effect covers much of the screen.

### Comment the Intent

```glsl
// Water wave effect.
// Creates horizontal distortion from a sine wave.
uniform float wave_amplitude = 0.02;
```

## Reference

- [Godot Docs: Shading Language](https://docs.godotengine.org/en/stable/tutorials/shaders/shader_reference/shading_language.html)
- [Godot Docs: Your First Shader](https://docs.godotengine.org/en/stable/tutorials/shaders/your_first_shader/your_first_2d_shader.html)

## Related

- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
