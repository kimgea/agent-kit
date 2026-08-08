---
name: skill-runtime-content-cleanup
status: completed
created: 2026-08-07T06:44:18Z
updated: 2026-08-07T14:27:23Z
progress: 100%
prd: .claude/prds/skill-runtime-content-cleanup.md
github: null
---

# Epic: skill-runtime-content-cleanup

## Overview

Align the installed skill bodies with the repository's progressive-disclosure
contract while preserving all runtime behavior and safety requirements.

## Architecture Decisions

- Keep universal action selection and guardrails in each `SKILL.md`.
- Put operation-specific runtime interpretation in a direct bundled reference.
- Keep extension procedures, compatibility evidence, and validation guidance in
  repository maintainer docs.
- Retain cross-agent facts only where they affect storage, paths, permissions, or
  report interpretation.

## Technical Approach

Condense `todo-capture/SKILL.md`, create a routed `tool-audit` report guide,
condense `tool-audit/SKILL.md`, and update existing maintainer documentation and
metadata. Validate links, frontmatter, tests, catalog versions, and the complete
repository gate.

## Implementation Strategy

Make the content changes as one coordinated task because the skill bodies,
maintainer docs, catalog versions, and validation evidence form one review unit.

## Dependencies

None.

## Success Criteria (Technical)

- Installed skill bodies contain no extension or compatibility-maintenance
  sections.
- `tool-audit` routes specialized interpretation to one direct reference.
- Safety-critical instructions remain in the always-loaded body.
- The canonical repository check and GitHub CI pass.

## Estimated Effort

Small, documentation-focused change with no runtime code modifications.

## Tasks Created

- [x] 001.md - Separate runtime skill guidance from maintainer documentation

Total tasks: 1
Parallel tasks: 0
Sequential tasks: 1
Estimated total effort: 2 hours
