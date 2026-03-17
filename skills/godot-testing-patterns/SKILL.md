---
name: godot-testing-patterns
description: "Expert blueprint for testing patterns using GUT (Godot Unit Test), integration tests, mock/stub patterns, async testing, and validation techniques. Covers assert patterns, signal testing, and CI/CD integration. Use when implementing tests OR validating game logic. Keywords GUT, unit test, integration test, assert, mock, stub, GutTest, watch_signals, TDD."
---

# Testing Patterns

Use this skill when the task needs automated validation, not just manual playtesting.

Focus:
- GUT-based unit and integration tests
- deterministic test setup and cleanup
- signal, async, and mock/stub testing
- headless test execution for local runs or CI

## Available Scripts

### [integration_test_base.gd](scripts/integration_test_base.gd)
Base class for GUT integration tests with auto-cleanup and scene helpers.

### [headless_test_runner.gd](scripts/headless_test_runner.gd)
Headless test runner with JUnit XML output and exit code handling.

## Load This Skill When

- adding or fixing automated tests
- validating game logic before or after a behavior change
- checking signal emission, async flows, or integration paths
- wiring headless test execution into a workflow

## Do Not Use This Skill As

- a replacement for gameplay verification, capture, or reporting
- a substitute for architecture guidance outside testing
- a reason to test private implementation details

## Never Do

- Never test private or unstable internals when public behavior is what matters.
- Never share state between tests. Use `before_each()` for fresh setup.
- Never use fixed sleeps as your main timing strategy. Prefer GUT helpers or frame stepping.
- Never skip cleanup in `after_each()`.
- Never test randomness without seeding.
- Never assert signal emission without calling `watch_signals()` first when using GUT signal assertions.

## Installation

1. Install `GUT - Godot Unit Test` from AssetLib.
2. Enable it in `Project Settings -> Plugins`.
3. Create `res://test/`.

## Basic Test

```gdscript
# test/test_player.gd
extends GutTest

var player: CharacterBody2D

func before_each() -> void:
    player = preload("res://entities/player/player.tscn").instantiate()
    add_child(player)

func after_each() -> void:
    player.queue_free()

func test_initial_health() -> void:
    assert_eq(player.health, 100, "Player should start with 100 health")

func test_take_damage() -> void:
    player.take_damage(25)
    assert_eq(player.health, 75, "Health should be 75 after 25 damage")

func test_cannot_have_negative_health() -> void:
    player.take_damage(200)
    assert_gte(player.health, 0, "Health should not go below 0")
```

## Running Tests

```text
# Via the GUT panel in the editor
# Or from the command line:
godot --headless -s addons/gut/gut_cmdln.gd
```

## Assertion Patterns

```gdscript
# Equality
assert_eq(actual, expected, "message")
assert_ne(actual, not_expected, "message")

# Comparison
assert_gt(value, min_value, "should be greater")
assert_lt(value, max_value, "should be less")
assert_gte(value, min_value, "should be >= min")
assert_lte(value, max_value, "should be <= max")

# Boolean
assert_true(condition, "should be true")
assert_false(condition, "should be false")

# Null
assert_not_null(object, "should exist")
assert_null(object, "should be null")

# Arrays
assert_has(array, element, "should contain element")
assert_does_not_have(array, element, "should not contain")

# Signals
watch_signals(object)
assert_signal_emitted(object, "signal_name")
```

## Testing Signals

```gdscript
func test_death_signal() -> void:
    watch_signals(player)

    player.take_damage(100)

    assert_signal_emitted(player, "died")
    assert_signal_emitted_with_parameters(player, "died", [player])
```

## Testing Async Behavior

```gdscript
func test_delayed_action() -> void:
    player.start_ability()

    await wait_seconds(1.0)

    assert_true(player.ability_active, "Ability should be active after delay")
```

Prefer `wait_frames()` or signal-driven synchronization when the system under test advances frame-by-frame.

## Mock and Stub Patterns

```gdscript
func test_with_mock() -> void:
    var mock_enemy := double(Enemy).new()
    stub(mock_enemy, "get_damage").to_return(50)

    player.collide_with(mock_enemy)

    assert_eq(player.health, 50, "Should take mocked damage")
```

## Integration Testing

```gdscript
# test/integration/test_combat_system.gd
extends GutTest

func test_player_kills_enemy() -> void:
    var level := preload("res://levels/test_arena.tscn").instantiate()
    add_child(level)

    var player := level.get_node("Player")
    var enemy := level.get_node("Enemy")

    for i in range(5):
        player.attack(enemy)
        await wait_frames(1)

    assert_true(enemy.is_dead, "Enemy should be dead")
    assert_gt(player.score, 0, "Player should have score")

    level.queue_free()
```

## Validation Helpers

```gdscript
class_name Validation

static func assert_valid_health(health: int) -> void:
    assert(health >= 0 and health <= 100, "Invalid health: %d" % health)

static func assert_valid_position(pos: Vector2, bounds: Rect2) -> void:
    assert(bounds.has_point(pos), "Position out of bounds: %s" % pos)
```

## Test Organization

```text
test/
|-- unit/
|   |-- test_player.gd
|   |-- test_enemy.gd
|   `-- test_inventory.gd
|-- integration/
|   |-- test_combat.gd
|   `-- test_save_load.gd
`-- fixtures/
    |-- test_level.tscn
    `-- mock_data.tres
```

## Best Practices

### Test Edge Cases

```gdscript
func test_edge_cases() -> void:
    player.take_damage(0)
    assert_eq(player.health, 100)

    player.take_damage(-10)
    assert_eq(player.health, 100)
```

### Isolate Tests

```gdscript
func before_each() -> void:
    player = create_fresh_player()
```

### Test Critical Paths First

```text
Priority:
1. Core gameplay
2. Save/load behavior
3. Scene and level transitions
4. UI interactions
```

## Manual Testing Checklist

```markdown
## Gameplay
- [ ] Player can move in all directions
- [ ] Jump height feels right
- [ ] Enemies respond to player
- [ ] Damage numbers are correct

## UI
- [ ] All buttons work
- [ ] Text is readable
- [ ] Responsive on different resolutions

## Audio
- [ ] Music plays
- [ ] SFX trigger correctly
- [ ] Volume levels balanced

## Performance
- [ ] Maintains 60 FPS
- [ ] No stuttering
- [ ] Memory stable
```

## Reference

- [GUT Documentation](https://github.com/bitwes/Gut)

## Related

- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
