---
name: godot-server-architecture
description: "Expert blueprint for low-level server access (RenderingServer, PhysicsServer2D/3D, NavigationServer) using RIDs for maximum performance. Bypasses scene tree overhead for procedural generation, particle systems, and voxel engines. Use when nodes are too slow OR managing thousands of objects. Keywords RenderingServer, PhysicsServer, NavigationServer, RID, canvas_item, body_create, low-level, performance."
---

# Server Architecture

Use this skill when scene-tree nodes are the bottleneck and lower-level Godot servers are justified.

Focus:
- RID lifecycle
- direct RenderingServer and PhysicsServer usage
- performance-critical systems
- knowing when not to use server APIs

## Available Scripts

### [headless_manager.gd](scripts/headless_manager.gd)
Dedicated-server lifecycle and headless optimization manager.

### [rid_performance_server.gd](scripts/rid_performance_server.gd)
RID wrapper for batch-oriented server operations.

## Load This Skill When

- profiling shows node overhead is the bottleneck
- managing very large counts of render or physics objects
- building low-level systems such as voxel, particle, or simulation-heavy subsystems

## Never Do

- Never leak RIDs.
- Never mix node and server ownership for the same simulated object without a very explicit design.
- Never start with server APIs for normal gameplay code.
- Never call server APIs on invalid RIDs.
- Never optimize into server APIs before profiling.
- Never use RenderingServer as a replacement for normal UI controls.

## RenderingServer Example

```gdscript
var canvas_item := RenderingServer.canvas_item_create()
RenderingServer.canvas_item_set_parent(canvas_item, get_canvas_item())

var texture_rid := load("res://icon.png").get_rid()
RenderingServer.canvas_item_add_texture_rect(
    canvas_item,
    Rect2(0, 0, 64, 64),
    texture_rid
)
```

## PhysicsServer2D Example

```gdscript
var body_rid := PhysicsServer2D.body_create()
PhysicsServer2D.body_set_mode(body_rid, PhysicsServer2D.BODY_MODE_RIGID)

var shape_rid := PhysicsServer2D.circle_shape_create()
PhysicsServer2D.shape_set_data(shape_rid, 16.0)

PhysicsServer2D.body_add_shape(body_rid, shape_rid)
```

## When To Use Servers

Use servers for:
- very large populations
- custom rendering paths
- highly specialized simulation systems

Use nodes for:
- standard gameplay entities
- UI
- prototyping
- systems that benefit from editor visibility and scene-tree tooling

## Core Rule

If the server API path is chosen, make ownership explicit:
- who creates the RID
- who updates it
- who frees it

## Reference

- [Godot Docs: Using Servers](https://docs.godotengine.org/en/stable/tutorials/performance/using_servers.html)

## Related

- [godot-performance-optimization](../godot-performance-optimization/SKILL.md)
- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
