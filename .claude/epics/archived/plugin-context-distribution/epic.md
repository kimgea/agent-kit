---
name: plugin-context-distribution
status: completed
created: 2026-08-10T13:08:12Z
updated: 2026-08-14T06:12:02Z
progress: 100%
prd: .claude/prds/plugin-context-distribution.md
github: null
---

# Epic: plugin-context-distribution

## Overview

Extend the existing catalog-driven lifecycle with generated plugin distribution
and add an independently installable, read-only context resolver.

## Architecture Decisions

- Keep `skills/` canonical and plugin trees generated under ignored output.
- Preserve existing standalone packaging as the default interface.
- Use explicit catalog mappings and exact private-context registrations.
- Keep shared context optional so every existing skill remains independent.

## Technical Approach

Upgrade catalog validation, add deterministic plugin and marketplace builders,
scaffold `agent-context`, implement its resolver and schemas, then update release,
agent, maintainer, and user documentation.

## Implementation Strategy

Build and test the packaging boundary first, then the resolver boundary. Finish
with integrated validation, plugin validation, documentation, and release checks.

## Task Breakdown Preview

1. Add CCPM and catalog foundations.
2. Implement plugin and marketplace packaging.
3. Implement the agent-context skill and resolver.
4. Update documentation, contracts, and release behavior.
5. Complete validation and close the epic.

## Dependencies

The context and packaging implementations share catalog and validation code, so
catalog decisions land before their final integration.

## Success Criteria (Technical)

- Catalog schema, generated manifests, marketplace paths, archive bytes, context
  precedence, and refusal paths have deterministic tests.
- Existing lifecycle tests stay green.
- The canonical gate passes on the final tree.

## Estimated Effort

Large, approximately one focused implementation cycle.

## Tasks Created

- [x] 001.md - Add tracking and catalog schema (parallel: false)
- [x] 002.md - Build plugin distribution (parallel: false)
- [x] 003.md - Build agent context resolution (parallel: false)
- [x] 004.md - Update contracts and documentation (parallel: false)
- [x] 005.md - Validate and close delivery (parallel: false)

Total tasks: 5
Parallel tasks: 0
Sequential tasks: 5
Estimated total effort: 16 hours
