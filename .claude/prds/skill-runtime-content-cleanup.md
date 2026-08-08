---
name: skill-runtime-content-cleanup
description: Keep installed skill context focused on everyday runtime decisions.
status: completed
created: 2026-08-07T06:44:18Z
---

# PRD: skill-runtime-content-cleanup

## Executive Summary

Reduce the context loaded by `todo-capture` and `tool-audit` without changing
their behavior or safety boundaries. Keep universal operating instructions in
`SKILL.md`, route operation-specific detail to direct references, and keep
compatibility evidence and extension guidance in repository maintainer docs.

## Problem Statement

The repository documents a runtime-versus-maintainer content boundary, but two
installed skills still load compatibility explanations, implementation details,
and extension instructions on every invocation. Some of that material duplicates
existing files under `docs/`, while report-specific guidance in `tool-audit` is
useful only for a subset of profiles.

## User Stories

- As an agent using a skill, I receive the commands, safety rules, and decisions
  needed for the current task without unrelated maintenance context.
- As an agent interpreting a specialized report, I can load the relevant caveats
  from one directly linked reference.
- As a maintainer, I can find extension, validation, and compatibility guidance in
  repository documentation that is not shipped as always-loaded runtime context.
- As a Codex or Claude Code user, I retain behaviorally relevant cross-agent
  details such as shared storage, agent-specific state, and transcript semantics.

## Functional Requirements

1. Remove maintainer-only and duplicated prose from `todo-capture/SKILL.md` and
   `tool-audit/SKILL.md`.
2. Preserve permission-preview, safe-dispatcher, privacy, and data-integrity
   requirements in the runtime instructions.
3. Preserve cross-agent information only when it changes runtime behavior.
4. Route profile-specific `tool-audit` interpretation guidance through a direct
   progressive-disclosure reference.
5. Put skill-specific extension guidance in the existing `docs/<skill>.md` files
   and the general placement rule in `CONTRIBUTING.md`.
6. Keep skill frontmatter and Codex UI metadata concise and synchronized.

## Non-Functional Requirements

- Preserve plain Markdown and dependency-free Python compatibility.
- Do not change script behavior, permission surfaces, storage formats, or command
  classifications.
- Keep each installed skill independently usable without repository docs.
- Keep local links, catalog metadata, evaluations, and canonical checks valid.

## Success Criteria

- A simple inventory or todo operation no longer loads maintainer-only sections.
- Every moved runtime detail remains discoverable through a direct skill link.
- Maintainer-only guidance exists in repository docs without runtime duplication.
- `python scripts/agent_kit.py check` passes.
- Required pull-request checks pass and the resulting commit is present on `main`.

## Constraints & Assumptions

- Existing scripts and their tested safety boundaries are authoritative.
- The existing compatibility matrix remains the source of support claims.
- The repository uses local CCPM records without requiring GitHub issue sync for
  every focused maintenance change.

## Out of Scope

- Changing `grill-me`, whose progressive disclosure is already appropriate.
- Changing todo storage, tool-audit report calculations, permissions, or CLI
  interfaces.
- Adding skill-local README, installation, changelog, or contributor files.

## Dependencies

- Existing skill docs, evaluations, and the canonical repository validator.
