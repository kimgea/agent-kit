---
name: godot-task
description: Execute a single Godot development task: generate scenes and/or scripts, validate in Godot, capture evidence, and verify visually.
---

# Godot Task Executor

Use this skill to complete one Godot implementation task end to end.

This skill directory is `skills/godot-task/`. Load files progressively. Read each file when its phase begins instead of loading everything up front.

## Trust Boundary

This skill runs Godot commands against the target project, including headless import, validation, scene-builder scripts, and test harness scripts.

Use it only on:

- trusted Godot workspaces, or
- isolated sandboxes where running project code is acceptable

Do not treat this skill as safe for arbitrary untrusted projects.

## Minimum Read Path

Start with this order:

1. `SKILL.md`
2. `quirks.md`
3. one of:
   - `scene-generation.md` if the task writes `.tscn`
   - `script-generation.md` if the task writes `.gd`
   - `coordination.md` if it writes both
4. `test-harness.md` before writing the verification script
5. `capture.md` before capturing evidence
6. `visual-qa.md` before final screenshot review
7. `task-spec-template.md` only when the incoming task spec is missing structure or is ambiguous
8. `specialist-skills.md` when the task clearly matches a specialist domain

Read `gdscript.md` only when you need syntax or engine-specific coding guidance.
Read `doc_api/` only when you need a class reference.
Read `specialist-skills.md` when you need to decide which smaller Godot skill to load.

## File Roles

| File | Purpose | When to read |
|------|---------|--------------|
| `quirks.md` | Workflow-specific Godot gotchas and fallback notes | Before writing any code |
| `gdscript.md` | GDScript syntax reference plus compact fallback patterns | Only when syntax or implementation details are unclear |
| `scene-generation.md` | Building `.tscn` files via headless GDScript builders | Targets include `.tscn` |
| `script-generation.md` | Writing runtime `.gd` scripts for node behavior | Targets include `.gd` |
| `coordination.md` | Ordering scene and script generation | Targets include both `.tscn` and `.gd` |
| `test-harness.md` | Writing `test/test_{id}.gd` verification scripts | Before writing the test harness |
| `capture.md` | Screenshot and video capture with GPU detection | Before capturing screenshots |
| `visual-qa.md` | Manual screenshot review guidance | The task has visual output |
| `task-spec-template.md` | Preferred shape for incoming task specs | When the task spec is underspecified or inconsistent |
| `specialist-skills.md` | Routing guide for smaller Godot specialist skills | When the task is domain-specific |
| `doc_api/_common.md` | Index of common Godot classes | Need API ref; start here |
| `doc_api/_other.md` | Index of remaining Godot classes | Need API ref; class is not in `_common.md` |
| `doc_api/{ClassName}.md` | Full API reference for a single Godot class | Need API ref; look up one specific class |

Bootstrap `doc_api` when needed:

```bash
bash skills/godot-task/tools/ensure_doc_api.sh
```

Execute one development task from `PLAN.md` or an equivalent task specification:

$ARGUMENTS

## Expected Task Spec

This skill does not require a file literally named `PLAN.md`, but it does require task information with equivalent fields.

Preferred fields:

- `Goal`: what the task should achieve
- `Targets`: output file paths to create or modify
- `Requirements`: constraints, mechanics, visuals, and asset usage rules
- `Verify`: what evidence should prove the task is complete
- `Available Nodes`: optional exact node paths and types the script may rely on
- `Inputs`: optional allowed input actions
- `Script Attachments`: optional mapping from scene nodes to script paths

If one of these sections is missing, infer only what is safe and state the assumption.
If the task spec is underspecified, use `task-spec-template.md` as the canonical shape.

If the task is small, do not read every reference file. Read only the minimum files needed for the current phase.

If the task is clearly about animation, cameras, combat, inventory, debugging, performance, exports, testing, save/load, UI, shaders, data modeling, state machines, or another specialist domain, load the relevant skill from `specialist-skills.md` before falling back to broad internal references.

## Workflow

1. Analyze the task. Read the task's targets to determine what to generate:
   - `scenes/*.tscn` targets -> generate scene builder scripts
   - `scripts/*.gd` targets -> generate runtime scripts
   - Both -> generate scenes first, then scripts
2. Import assets. Run `timeout 60 godot --headless --import` so new textures, GLBs, or resources produce `.import` files. Re-run after modifying existing assets.
3. Generate scene files.
4. Generate runtime scripts.
5. Validate. Run `timeout 60 godot --headless --quit` to check for parse errors across the project.
6. Fix reported errors and repeat validation until clean.
7. Generate the test harness implementing the task's verify scenario.
8. Capture screenshots or video evidence.
9. Verify visually:
   - Task goal: does the output match the verify description?
   - Visual consistency: if `reference.png` exists, compare palette, scale, camera angle, and visual density.
   - Visual quality and logic: look for clipping, floating objects, wrong assets, text overflow, or overlapping UI.
   - Also check harness stdout for `ASSERT FAIL`.
   - If any check fails, fix the scene, script, or test and repeat from step 3.
10. Perform manual visual QA on the captured evidence.
11. Store final evidence in `screenshots/{task_folder}/` before reporting completion.

## Iteration Tracking

Steps 3-10 form an implement -> capture -> verify loop.

There is no fixed iteration limit. Use judgment:

- If there is real progress, keep going.
- If you hit a fundamental limitation such as a wrong architecture, missing engine feature, or broken assumption, stop early.
- Stop when you are repeating the same category of fix without converging.

## Reporting

Always end with:

- Screenshot path: `screenshots/{task_folder}/`
- The best representative frames, for example `frame0003.png`
- One line per chosen frame describing what it shows
- Visual QA result, or `skipped` if the task is non-visual

On failure, also include:

- What is still wrong
- What you tried
- Your best guess at the root cause

If this skill is being used from a larger workflow, the caller decides whether to replan, rescope, or accept the current result.

## Core Commands

```bash
# Import new or modified assets before scene builders:
timeout 60 godot --headless --import

# Compile a scene builder and produce .tscn output:
timeout 60 godot --headless --script <path_to_gd_builder>

# Parse-check all project scripts:
timeout 60 godot --headless --quit 2>&1
```

Common error handling:

- `Parser Error`: fix the reported GDScript syntax error
- `Invalid call` or `method not found`: wrong node type or API usage; look up the class in `doc_api`
- `Cannot infer type`: often caused by `:=` with `instantiate()` or polymorphic math helpers
- Script hangs: scene builder likely forgot `quit()`

## Project Memory

Read `MEMORY.md` before starting when it exists. It may contain previous discoveries, workarounds, asset details, or architectural decisions.

After finishing, write back durable findings that future agents will need.
