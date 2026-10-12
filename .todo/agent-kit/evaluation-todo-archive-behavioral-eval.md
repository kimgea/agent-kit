---
repo: agent-kit
domain: evaluation
status: todo
created: 2026-10-12
source: "Agent Kit self-pilot, 2026-10-12"
priority: normal
---

# Grade todo capture finish and archive behavior

## Why

The executable todo-capture suite covers capture routing but does not detect a lost resolution or a stale active index after done.

## Where

- evals/todo-capture/suite.json - retained project-eval cases
- evals/todo-capture/cases.json - descriptive finish-with-history case

## What to do

Add one executable lifecycle case that captures a pointer, finishes it with a resolution, and grades archive retention and active-index removal.

## Constraints

- Keep the fixture disposable and model-backed execution opt-in.

## Out of scope

Do not add remote issue providers or change the todo runtime for this eval.

## Links

- docs/todo-capture.md
