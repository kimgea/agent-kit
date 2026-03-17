---
name: godot-state-machine-advanced
description: "Expert blueprint for hierarchical finite state machines (HSM) and pushdown automata for complex AI/character behaviors. Covers state stacks, sub-states, transition validation, and state context passing. Use when basic FSMs are insufficient OR implementing layered AI. Keywords state machine, HSM, hierarchical, pushdown automata, state stack, FSM, AI behavior."
---

# Advanced State Machines

Use this skill when a flat FSM is no longer enough.

Focus:
- hierarchical state machines
- pushdown state stacks for interrupt/resume flows
- validated transitions
- explicit enter and exit ownership

## Available Scripts

### [hsm_logic_state.gd](scripts/hsm_logic_state.gd)
Base class for hierarchical state machines with stack management and validation.

### [pushdown_automaton.gd](scripts/pushdown_automaton.gd)
Stack-based machine for interrupt-resume flows such as pause menus, hit-stun, or cutscenes.

> Read [hsm_logic_state.gd](scripts/hsm_logic_state.gd) before implementing hierarchical AI behavior.

## Load This Skill When

- a character or AI has layered modes and sub-modes
- interruptions must temporarily override a current state
- transitions need validation and explicit context passing
- a simple enum-and-switch FSM is becoming brittle

## Never Do

- Never enter a new state before the old state has exited cleanly.
- Never push onto a state stack without a defined pop path.
- Never trigger re-entrant transitions from inside `exit()` unless your framework explicitly supports it.
- Never transition to states that have not been validated or registered.
- Never forget to update child states in a hierarchical machine.
- Never rely on raw strings in call sites when constants, enums, or node references are available.

## Minimal Hierarchical Machine

```gdscript
class_name HierarchicalState
extends Node

signal transitioned(from_state: String, to_state: String)

var current_state: Node
var state_stack: Array[Node] = []

func _ready() -> void:
    for child in get_children():
        child.state_machine = self

    if get_child_count() > 0:
        current_state = get_child(0)
        current_state.enter()

func transition_to(state_name: String) -> void:
    if not has_node(state_name):
        return

    var new_state := get_node(state_name)

    if current_state:
        current_state.exit()

    transitioned.emit(current_state.name if current_state else "", state_name)
    current_state = new_state
    current_state.enter()

func push_state(state_name: String) -> void:
    if current_state:
        state_stack.append(current_state)
        current_state.exit()

    transition_to(state_name)

func pop_state() -> void:
    if state_stack.is_empty():
        return

    var previous_state := state_stack.pop_back()
    transition_to(previous_state.name)
```

## Base State Contract

```gdscript
class_name State
extends Node

var state_machine: HierarchicalState

func enter() -> void:
    pass

func exit() -> void:
    pass

func update(delta: float) -> void:
    pass

func physics_update(delta: float) -> void:
    pass

func handle_input(event: InputEvent) -> void:
    pass
```

## When To Use A Hierarchical Machine

- shared parent logic exists across multiple child states
- a super-state owns common movement, targeting, or animation policy
- child states refine a broader mode like `Combat`, `Movement`, or `Menu`

## When To Use A Pushdown Stack

- a temporary interrupt should return to the previous state
- examples include pause, dialog, hit-stun, lock-on, and cutscene control

## Transition Guidance

- Validate the target state before transition.
- Keep transition side effects explicit.
- Do not mutate machine topology during active transition flow.
- Prefer constants or enums for externally requested states.

## Best Practices

1. One state per file.
2. Keep `enter()` and `exit()` symmetric.
3. Pass only the context a state needs.
4. Let the machine own transition policy.
5. Use signals or a manager to report state changes outward.

## Reference

- Related: `godot-characterbody-2d`
- Related: `godot-animation-player`

## Related

- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
