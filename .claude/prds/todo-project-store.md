---
name: todo-project-store
description: Let Git projects select a repository-owned todo destination while preserving the private default.
status: completed
created: 2026-10-11T19:00:59Z
---

# PRD: todo-project-store

## Executive Summary

Allow a project to keep consciously deferred pickup pointers in its own Git
tree. Keep the existing private shared store as the default and preserve the
fixed dispatcher's automatic permission boundary.

## Problem Statement

The current skill organizes entries by repository name but stores them only in
one machine-local directory during normal use. Project collaborators cannot
review or carry those entries with the repository, and installing a skill inside
a repository does not provide a deliberate storage choice.

## User Stories

- As a project owner, I can opt into repository-owned todo files through a small
  project config, so I can review and commit selected entries with the project.
- As an agent, I can inspect the selected destination before writing, so I can
  report the exact location and honor the user's requested scope.
- As a user without project config, I keep the established private-store behavior.

## Functional Requirements

- Recognize only a versioned configuration at the Git root; route from nested
  worktree directories to that same root.
- Keep the repository data layout compatible with existing entry and index
  commands, with a fixed `.todo/` directory and a project-specific vocabulary.
- Reject unknown backends, malformed or symlinked config, foreign `.todo/`
  content, and caller-supplied destination overrides without private fallback.
- Keep project routing outside automatically generated permission rules.
- Preserve add, list, show, check, and archive behavior, including concurrent
  locking and an ignored runtime lock file.

## Non-Functional Requirements

- Keep the skill self-contained and standard-library based on supported Python
  versions, with Linux and Windows-compatible Git-root resolution.
- Never stage, commit, publish, or sync a captured entry automatically.
- Validate routing and safety boundaries through deterministic tests and
  descriptive skill evaluations without model execution in CI.

## Success Criteria

- A configured synthetic Git project can capture, list, show, check, and archive
  an entry from a nested directory with no write to the private store.
- No-config and explicit-private routes preserve the old destination.
- Invalid project state blocks the operation without writing elsewhere.
- Generated permission rules still name only the fixed private dispatcher.

## Constraints & Assumptions

Project configuration selects a destination but grants no command authority.
The existing user and repository permission model still governs writes. A
repository store may contain project-owned information, so the project owner
decides whether to commit its entries.

## Out of Scope

GitHub Issues, Jira, Linear, cross-store synchronization, migration of existing
private entries, automatic staging or commits, and model-backed eval runs.

## Dependencies

The existing todo entry format and CLI, Git for project-root discovery, and
Python 3.11 or newer for TOML parsing.
