---
name: godot-procedural-generation
description: "Expert blueprint for procedural content generation (dungeons, terrain, loot, levels) using FastNoiseLite, random walks, BSP trees, Wave Function Collapse, and seeded randomization. Use when creating roguelikes, sandbox games, or dynamic content. Keywords procedural, generation, FastNoiseLite, Perlin noise, BSP, drunkard walk, Wave Function Collapse, seeding."
---

# Procedural Generation

Use this skill when the task needs repeatable generated content rather than authored layouts.

Focus:
- seeded randomness
- generation algorithms and validation
- caching expensive generated data
- deterministic behavior where required

## Available Scripts

### [wfc_level_generator.gd](scripts/wfc_level_generator.gd)
Wave Function Collapse implementation with adjacency rules.

## Load This Skill When

- generating dungeons, terrain, maps, or loot
- choosing between noise, BSP, random walk, or WFC approaches
- making generation deterministic for saves, replays, or multiplayer

## Never Do

- Never leave RNG seeding implicit when determinism matters.
- Never let each multiplayer client generate from its own local timing.
- Never ship a generator without a validity check.
- Never call expensive noise or generation code every frame unless the task truly requires it.
- Never ignore WFC contradiction handling.
- Never block the main thread with large generation jobs if the result can be staged or deferred.

## Random Walk Dungeon

```gdscript
func generate_dungeon(width: int, height: int, fill_percent: float = 0.4) -> Array:
    var grid := []
    for y in height:
        var row := []
        for x in width:
            row.append(1)
        grid.append(row)

    var x := width / 2
    var y := height / 2
    var floor_tiles := 0
    var target_floor := int(width * height * fill_percent)

    while floor_tiles < target_floor:
        if grid[y][x] == 1:
            grid[y][x] = 0
            floor_tiles += 1

        match randi() % 4:
            0: x = clampi(x + 1, 0, width - 1)
            1: x = clampi(x - 1, 0, width - 1)
            2: y = clampi(y + 1, 0, height - 1)
            3: y = clampi(y - 1, 0, height - 1)

    return grid
```

## FastNoiseLite Terrain

```gdscript
var noise := FastNoiseLite.new()

func generate_terrain(width: int, height: int) -> Array:
    noise.seed = randi()
    noise.frequency = 0.05

    var terrain := []
    for y in height:
        var row := []
        for x in width:
            var value := noise.get_noise_2d(x, y)
            var tile: int
            if value < -0.2:
                tile = 0
            elif value < 0.2:
                tile = 1
            else:
                tile = 2
            row.append(tile)
        terrain.append(row)

    return terrain
```

## BSP Rooms

```gdscript
class_name BSPRoom

var x: int
var y: int
var width: int
var height: int
var left: BSPRoom = null
var right: BSPRoom = null

func split(min_size: int = 6) -> bool:
    if left or right:
        return false

    var split_horizontal := randf() > 0.5
    if width > height and float(width) / float(height) >= 1.25:
        split_horizontal = false
    elif height > width and float(height) / float(width) >= 1.25:
        split_horizontal = true

    var max := (height if split_horizontal else width) - min_size
    if max <= min_size:
        return false

    var split_pos := randi_range(min_size, max)
    return true
```

## Validation Rules

- prove the map is traversable
- keep generation inputs serializable
- separate template data from generated output
- record the seed when the run must be reproducible

## Related

- [godot-scene-management](../godot-scene-management/SKILL.md)
- [godot-tilemap-mastery](../godot-tilemap-mastery/SKILL.md)
- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
