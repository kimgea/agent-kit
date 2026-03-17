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
- `godot-project-foundations`
- `godot-project-templates`
- `godot-resource-data-patterns`
- `godot-signal-architecture`
- `godot-state-machine-advanced`
- `godot-testing-patterns`

Load these for:
- project architecture
- autoload design
- composition patterns
- GDScript style, typing, signal architecture, and node access
- performance work
- debugging and profiling
- project setup and folder conventions
- reusable data and resource modeling
- event-bus and signal topology
- hierarchical state machines
- automated and integration testing

Use:
- `godot-composition` for gameplay entities, actors, combatants, and scene-driven game behavior
- `godot-composition-apps` for tools, apps, menus, dashboards, and UI orchestration
- `godot-gdscript-mastery` for language-level rules that apply regardless of project type
- `godot-project-foundations` when creating or refactoring overall repo and project structure
- `godot-project-templates` when bootstrapping a new Godot project shape
- `godot-resource-data-patterns` when data ownership should live in `Resource` or `RefCounted`
- `godot-signal-architecture` when event flow and decoupling are the main problem
- `godot-state-machine-advanced` when a basic FSM is no longer enough
- `godot-testing-patterns` when the task needs automated verification beyond the local harness

### Gameplay Systems

- `godot-ability-system`
- `godot-combat-system`
- `godot-dialogue-system`
- `godot-economy-system`
- `godot-inventory-system`
- `godot-audio-systems`
- `godot-quest-system`
- `godot-rpg-stats`
- `godot-turn-system`

Load these for:
- combat
- abilities
- dialogue
- inventory
- economy
- audio routing and runtime audio behavior
- quest tracking and progression
- RPG stats, modifiers, and derived values
- turn order, phases, and tactical combat flow

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

### World, Scene Flow, and Content Generation

- `godot-procedural-generation`
- `godot-scene-management`
- `godot-tilemap-mastery`

Load these for:
- procedural level or world generation
- scene loading, transitions, caching, and persistence between scenes
- tile-based world building, autotiling, and runtime tile manipulation

### UI, Text, and Presentation

- `godot-shaders-basics`
- `godot-tweening`
- `godot-ui-containers`
- `godot-ui-rich-text`
- `godot-ui-theming`

Load these for:
- shader-driven visuals and post-processing
- tweened transitions and procedural UI motion
- responsive container-based UI layout
- rich text, BBCode, and dialogue formatting
- theme resources, style boxes, and visual consistency

### Build and Tooling

- `godot-export-builds`
- `godot-mcp-setup`
- `godot-mcp-scene-builder`
- `godot-save-load-systems`
- `godot-server-architecture`

Load these for:
- export pipelines
- MCP setup
- MCP-assisted scene generation
- save/load persistence and migration
- low-level server APIs and RID-based performance work

### Skill Library Maintenance

- `godot-skill-discovery`
- `godot-skill-judge`

Load these only when:
- working on the Godot skill library itself
- validating skill metadata, indexing, or discoverability
- maintaining agent-facing skill quality rather than a game project

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
