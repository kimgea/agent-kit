---
name: godot-scene-management
description: "Expert blueprint for scene loading, transitions, async (background) loading, instance management, and caching. Covers fade transitions, loading screens, dynamic spawning, and scene persistence. Use when implementing level changes OR dynamic content loading. Keywords scene, loading, transition, async, ResourceLoader, change_scene, preload, PackedScene, fade."
---

# Scene Management

Use this skill when the task involves scene transitions, loading flow, or dynamic scene instancing.

Focus:
- synchronous versus async loading
- transition orchestration
- safe scene switching
- pooling and persistence patterns

## Available Scripts

### [async_scene_manager.gd](scripts/async_scene_manager.gd)
Async loader with progress reporting and transition callbacks.

### [scene_pool.gd](scripts/scene_pool.gd)
Pooling helper for frequently spawned scenes.

### [scene_state_manager.gd](scripts/scene_state_manager.gd)
State preservation across transitions using a persist-group pattern.

> For loading screens and non-blocking transitions, read [async_scene_manager.gd](scripts/async_scene_manager.gd) first.

## Load This Skill When

- switching levels or major screens
- background-loading a scene
- spawning many repeated scene instances
- preserving state across scene changes

## Never Do

- Never call blocking `load()` in hot gameplay paths when the scene should be preloaded or loaded asynchronously.
- Never ignore async load failure states.
- Never change scenes while cleanup-sensitive systems are still active.
- Never switch scenes directly from a locked-tree context if deferred change is safer.
- Never instantiate a scene without validating the loaded resource.
- Never leave large numbers of dynamic instances unfreed.

## Immediate Scene Change

```gdscript
get_tree().change_scene_to_file("res://levels/level_2.tscn")
```

Or:

```gdscript
var next_scene := load("res://levels/level_2.tscn")
get_tree().change_scene_to_packed(next_scene)
```

## Fade Transition

```gdscript
extends CanvasLayer

signal transition_finished

func change_scene(scene_path: String) -> void:
    $AnimationPlayer.play("fade_out")
    await $AnimationPlayer.animation_finished

    get_tree().change_scene_to_file(scene_path)

    $AnimationPlayer.play("fade_in")
    await $AnimationPlayer.animation_finished

    transition_finished.emit()
```

## Async Loading Pattern

```gdscript
extends Node

var loading_status: int = 0
var progress := []

func load_scene_async(path: String) -> void:
    ResourceLoader.load_threaded_request(path)

    while true:
        loading_status = ResourceLoader.load_threaded_get_status(path, progress)

        if loading_status == ResourceLoader.THREAD_LOAD_LOADED:
            var scene := ResourceLoader.load_threaded_get(path)
            get_tree().change_scene_to_packed(scene)
            break

        if loading_status == ResourceLoader.THREAD_LOAD_FAILED:
            push_error("Failed to load scene: " + path)
            break

        await get_tree().process_frame
```

## Loading Screen Pattern

```gdscript
@onready var progress_bar: ProgressBar = $ProgressBar

func load_scene(path: String) -> void:
    show()
    ResourceLoader.load_threaded_request(path)

    var progress := []
    while true:
        var status := ResourceLoader.load_threaded_get_status(path, progress)

        if status == ResourceLoader.THREAD_LOAD_LOADED:
            var scene := ResourceLoader.load_threaded_get(path)
            get_tree().change_scene_to_packed(scene)
            break
        elif status == ResourceLoader.THREAD_LOAD_FAILED:
            push_error("Failed to load scene: " + path)
            break

        progress_bar.value = progress[0] * 100
        await get_tree().process_frame

    hide()
```

## Dynamic Instancing

```gdscript
const ENEMY_SCENE := preload("res://enemies/goblin.tscn")

func spawn_enemy(position: Vector2) -> void:
    var enemy := ENEMY_SCENE.instantiate()
    enemy.global_position = position
    add_child(enemy)
```

Use pooling if the instances are short-lived and frequent.

## Reference

- [Godot Docs: Change Scenes Manually](https://docs.godotengine.org/en/stable/tutorials/io/background_loading.html)

## Related

- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
