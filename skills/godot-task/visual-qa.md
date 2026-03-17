# Visual Quality Assurance

Use manual visual review to inspect screenshots against the task goal and, when available, `reference.png`.

This skill does not use API-backed screenshot analysis. Visual QA is performed by the agent directly from the captured frames.

## What To Check

Check these in order:

1. Task goal: does the scene match the task's verify description?
2. Visual consistency: if `reference.png` exists, compare palette, scale relationships, camera angle, composition, and visual density.
3. Visual quality: clipping, floating objects, missing textures, wrong assets, text overflow, overlapping UI, broken composition, implausible motion.
4. Harness output: any `ASSERT FAIL` lines in stdout mean the task is not complete.

## Static Scenes

For decoration, terrain, menus, or other mostly static output:

- pick one or more representative frames
- avoid the first frame if initialization artifacts are likely
- inspect composition, placement, scale, readability, and obvious bugs

## Dynamic Scenes

For motion, animation, physics, or gameplay:

- inspect a sequence of representative frames
- compare consecutive frames for jitter, teleporting, stuck entities, broken collisions, animation mismatch, or camera problems
- use enough frames to cover the important part of the interaction

## Reporting

When visual review is complete, report:

- `VQA report: manual review`
- which frames were inspected
- whether the result passes or fails visual review
- the issues found, if any

## Handling Failures

When visual review fails:

- fix issues that are clearly local, such as placement, scale, materials, clipping, or camera framing
- re-capture screenshots and review again
- stop when the remaining problem is upstream, architectural, or no longer converging
