---
name: agent-toolkit-hardening
status: completed
created: 2026-08-04T09:08:56Z
updated: 2026-08-06T19:20:59Z
progress: 100%
prd: .claude/prds/agent-toolkit-hardening.md
github: null
---

# Epic: agent-toolkit-hardening

## Overview

Deliver the repository contract, toolkit tooling, normalized skills, complete CI,
immutable packaging, and protected GitHub delivery described in the PRD.

## Architecture Decisions

- Keep each skill self-contained; centralize only repository lifecycle tooling.
- Use reviewed TOML as the resource registry and emit JSON for agents.
- Make every global mutation dry-run by default and ownership-aware when applied.
- Keep repository tooling dependency-free and cross-platform.

## Technical Approach

Implement `scripts/agent_kit.py`, validate the catalog and resource tree, use
temporary directories for compilation and package tests, and store installation
ownership state outside deployed skills. Use one CI workflow and a separate
tag-triggered release workflow.

## Implementation Strategy

Build the repository contract first, then lifecycle tooling and tests, then skill
normalization, CI/release automation, and finally GitHub delivery controls.

## Dependencies

- GitHub authentication is needed only for final PR, release, and settings work.

## Success Criteria (Technical)

- The PRD success criteria pass locally and in GitHub Actions.
- No installed skill imports repository-only code.
- Permission installers remain outside automatic permission surfaces.

## Estimated Effort

Large repository-wide change spanning tooling, skills, tests, docs, and delivery.

## Tasks Created

- [x] 001.md - Repository contract, catalog, legal, and reusable resources
- [x] 002.md - Cross-platform toolkit lifecycle CLI and tests
- [x] 003.md - Skill normalization, privacy coverage, and evaluations
- [x] 004.md - Unified CI, packaging, release, and user documentation
- [x] 005.md - Publish, protect GitHub, release, and completion audit

Total tasks: 5
Parallel tasks: 2
Sequential tasks: 3
Estimated total effort: 18 hours
