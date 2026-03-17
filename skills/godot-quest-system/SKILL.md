---
name: godot-quest-system
description: "Expert blueprint for quest  tracking systems (objectives, progress, rewards, branching chains) using Resource-based quests, signal-driven updates, and AutoLoad managers. Use when implementing RPG quests or mission systems. Keywords quest, objectives, Quest Resource, QuestObjective, signal-driven, branching, rewards, AutoLoad."
---

# Quest System

Use this skill when the task needs structured objectives, progress tracking, and reward delivery.

Focus:
- resource-based quest definitions
- signal-driven progress updates
- AutoLoad or manager ownership
- persistence of active and completed quests

## Available Scripts

### [quest_manager.gd](scripts/quest_manager.gd)
Quest tracker with objective progression and reward distribution.

### [quest_graph_manager.gd](scripts/quest_graph_manager.gd)
Graph-style quest manager for branching quest structures.

## Load This Skill When

- implementing quests, missions, or objective chains
- tracking progress from combat, collection, travel, or dialogue events
- adding persistence for active and completed quests

## Never Do

- Never store durable quest state only inside scene nodes.
- Never rely on unchecked string IDs.
- Never leave quest-completion signals connected after the quest is done.
- Never poll every frame for objective completion when events can drive updates.
- Never forget to save quest progress.
- Never assume every objective in an array is valid.

## Quest Resource

```gdscript
class_name Quest
extends Resource

signal progress_updated(objective_id: String, progress: int)
signal completed

@export var quest_id: String
@export var quest_name: String
@export_multiline var description: String
@export var objectives: Array[QuestObjective] = []
@export var rewards: Array[QuestReward] = []
@export var required_level: int = 1

func is_complete() -> bool:
    return objectives.all(func(obj): return obj != null and obj.is_complete())

func check_completion() -> void:
    if is_complete():
        completed.emit()
```

## Objective Resource

```gdscript
class_name QuestObjective
extends Resource

enum Type { KILL, COLLECT, TALK, REACH }

@export var objective_id: String
@export var type: Type
@export var target: String
@export var required_amount: int = 1
@export var current_amount: int = 0

func progress(amount: int = 1) -> void:
    current_amount = mini(current_amount + amount, required_amount)

func is_complete() -> bool:
    return current_amount >= required_amount
```

## Quest Manager

```gdscript
extends Node

signal quest_accepted(quest: Quest)
signal quest_completed(quest: Quest)
signal objective_updated(quest: Quest, objective: QuestObjective)

var active_quests: Array[Quest] = []
var completed_quests: Array[String] = []

func accept_quest(quest: Quest) -> void:
    if quest.quest_id in completed_quests:
        return

    active_quests.append(quest)
    quest.completed.connect(func(): _on_quest_completed(quest))
    quest_accepted.emit(quest)

func _on_quest_completed(quest: Quest) -> void:
    active_quests.erase(quest)
    completed_quests.append(quest.quest_id)
    for reward in quest.rewards:
        reward.grant()
    quest_completed.emit(quest)
```

## Event Integration

```gdscript
func _on_enemy_died() -> void:
    QuestManager.update_objective("kill_bandits", "kill_bandit", 1)

func _on_collected() -> void:
    QuestManager.update_objective("gather_herbs", "collect_herb", 1)

func interact() -> void:
    DialogueManager.start_dialogue(dialogue_id)
    QuestManager.update_objective("find_elder", "talk_to_elder", 1)
```

## Persistence Guidance

- save active quests
- save completed quest IDs
- save objective progress
- restore signal wiring after load

## Related

- [godot-resource-data-patterns](../godot-resource-data-patterns/SKILL.md)
- [godot-signal-architecture](../godot-signal-architecture/SKILL.md)
- [godot-task](../godot-task/SKILL.md)
- [godot-master](../godot-master/SKILL.md)
