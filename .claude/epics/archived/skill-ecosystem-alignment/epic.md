---
name: skill-ecosystem-alignment
status: completed
created: 2026-09-03T18:45:24Z
updated: 2026-09-05T09:36:20Z
progress: 100%
prd: .claude/prds/skill-ecosystem-alignment.md
github: null
---

# Epic: skill-ecosystem-alignment

## Overview

Turn the selected ecosystem decisions into durable, concrete documentation and
an evidence-based capability roadmap. Inventory existing resources without
changing their runtime behavior, then connect the new design to the repository's
existing architecture and contributor entry points.

## Architecture Decisions

- Keep skill source flat and independently installable.
- Classify skills by one primary role plus explicit secondary capabilities.
- Group installations by useful workflow rather than internal role.
- Use a tiered contract with a shared envelope and family-specific payloads.
- Exchange explicit artifacts through focused orchestrators; do not silently
  chain skills or build a universal orchestrator.
- Keep target, authority, selection, persistence, and cumulative loop budget in
  a lead-owned envelope.
- Require canonicalization before action or authoritative acceptance while
  keeping advisory use of third-party output flexible.
- Use fresh agents only at bias-sensitive judgment boundaries.
- Keep workflow observations evidence-backed, storage-neutral, and distinct from
  project findings.
- Align existing skills incrementally after the design is reviewed.

## Technical Approach

### Current-state inventory

Read `toolkit.toml`, skill entrypoints, and current maintainer documentation.
Classify every skill by role, effects, structured surface, review awareness,
bundle, optional bridges, and fitness. Map other cataloged resources into
instruction, policy, template, tool, hook, adapter, and evaluation infrastructure.

### Ecosystem architecture

Document the concrete paths from discovery through normalization, planning,
decision, action, verification, and fresh acceptance. Define output, provenance,
authority, compatibility, third-party, observation, model-routing, and bounded
continuation rules without publishing a not-yet-implemented schema.

### Roadmap

Separate one concrete next capability from likely follow-ups and exploratory
ideas. Give every promotion a real evidence trigger and keep provider-specific
publishing outside the local-first core.

### Integration and review

Link the design from existing architecture and README material, validate all
repository documentation, then use an independent trusted-base project review
before delivery.

## Implementation Strategy

1. Freeze the catalog and classify the current toolkit.
2. Write the stable ecosystem architecture from the selected decisions.
3. Write the non-binding roadmap and migration candidates.
4. Integrate navigation, validate, independently review, and deliver.

## Task Breakdown Preview

- Task 001: Inventory current capabilities and infrastructure.
- Task 002: Author the stable ecosystem architecture.
- Task 003: Author the horizon roadmap and migration candidates.
- Task 004: Integrate navigation, validate, review, and deliver.

## Dependencies

- Completed review-audit-fix integration on `main`.
- Current catalog and skill-specific documentation.

## Success Criteria (Technical)

- Every cataloged resource is accounted for.
- Current behavior and future direction are visibly distinguished.
- Composition and authority rules are concrete enough to guide later PRDs.
- No installed skill or package surface changes in this phase.
- Canonical repository validation and independent review pass.

## Estimated Effort

- Size: M
- Hours: 5-8

## Tasks Created

- [x] 001.md - Inventory current capabilities and infrastructure
- [x] 002.md - Author the stable ecosystem architecture
- [x] 003.md - Author the horizon roadmap and migration candidates
- [x] 004.md - Integrate navigation, validate, review, and deliver

Total tasks: 4
Parallel tasks: 0
Sequential tasks: 4
Estimated total effort: 5-8 hours
