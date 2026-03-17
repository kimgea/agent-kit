# Godot Specialist Skill Routing

Use `godot-task` as the workflow skill. Load specialist skills only when the task actually needs their domain knowledge.

## Routing Rules

- Load specialist skills before large reference files when the task clearly matches a specialist domain.
- Keep `godot-task` in charge of task intake, workflow order, validation, capture, and reporting.
- Treat the embedded guidance in `godot-task` as fallback until the specialist skill has proven better in practice.
- Do not make specialist skills depend on `godot-task`.

## Specialist Skills By Domain

### Animation and VFX

- `godot-2d-animation`
- `godot-animation-player`
- `godot-animation-tree-mastery`
- `godot-particles`

Load these for:
- sprite animation
- skeletal or cutout animation
- animation state machines
- animation sync and transitions
- particle-driven feedback

### Camera, Input, Movement, and Physics

- `godot-camera-systems`
- `godot-input-handling`
- `godot-characterbody-2d`
- `godot-2d-physics`
- `godot-navigation-pathfinding`

Load these for:
- player movement
- camera behavior
- collision and physics response
- pathfinding and navigation
- input architecture

### Architecture and Code Quality

- `godot-autoload-architecture`
- `godot-composition`
- `godot-composition-apps`
- `godot-gdscript-mastery`
- `godot-debugging-profiling`
- `godot-performance-optimization`

Load these for:
- project architecture
- autoload design
- composition patterns
- GDScript style and correctness
- performance work
- debugging and profiling

### Gameplay Systems

- `godot-ability-system`
- `godot-combat-system`
- `godot-dialogue-system`
- `godot-economy-system`
- `godot-inventory-system`
- `godot-audio-systems`

Load these for:
- combat
- abilities
- dialogue
- inventory
- economy
- audio routing and runtime audio behavior

### Loops and Mechanics

- `godot-game-loop-collection`
- `godot-game-loop-harvest`
- `godot-game-loop-time-trial`
- `godot-game-loop-waves`
- `godot-mechanic-revival`
- `godot-mechanic-secrets`

Load these for:
- core gameplay loops
- progression mechanics
- collect/harvest/wave/time-trial structures
- revival or death-loop mechanics
- secrets and hidden systems

### Build and Tooling

- `godot-export-builds`
- `godot-mcp-setup`
- `godot-mcp-scene-builder`

Load these for:
- export pipelines
- MCP setup
- MCP-assisted scene generation

### Broad Reference

- `godot-master`

Load this only when:
- the task spans multiple domains at once
- the architecture decision is still unclear
- no narrower specialist skill is enough

## Suggested Loading Order

When the task is narrow:
1. `godot-task`
2. one or two specialist skills
3. `gdscript.md` or `doc_api/` only if needed

When the task is broad:
1. `godot-task`
2. `godot-master`
3. only the specialist skills required by the chosen approach
