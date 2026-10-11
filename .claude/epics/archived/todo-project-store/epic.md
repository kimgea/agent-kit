---
name: todo-project-store
status: completed
created: 2026-10-11T19:00:59Z
updated: 2026-10-11T19:00:59Z
progress: 100%
prd: .claude/prds/todo-project-store.md
---

# Epic: todo-project-store

## Overview

Deliver one independently reviewable project-store route for `todo-capture`.

## Architecture Decisions

- Keep `todo_safe.py` fixed to the private store and its generated permissions.
- Put project routing in a separate approval-gated entry point that reads only
  one Git-root configuration file and selects a fixed `.todo/` path.
- Reuse the existing entry format and lifecycle implementation through the
  direct helper, with no provider abstraction before a real external backend.

## Technical Approach

Add a versioned TOML route, repository-store ownership marker and lock ignore,
negative boundary tests, runtime guidance, maintainer documentation, catalog
version, and descriptive behavioral evaluation cases.

## Task Breakdown

- `001.md`: implement and validate the project-store slice.

## Success Criteria

The PRD acceptance cases pass, repository validation is green, and the change
receives independent exact-head review before merge.
