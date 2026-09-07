---
name: change-impact-consumers
status: completed
created: 2026-09-06T21:55:08Z
updated: 2026-09-07T10:20:01Z
progress: 100%
prd: .claude/prds/change-impact-consumers.md
github: (will be set on sync)
---

# Epic: change-impact consumers

## Overview

Make `change-impact` a conditional, validated evidence producer for project
review, local verification, and local remediation without imposing its cost on
narrow work or weakening consumer authority.

## Architecture Decisions

- Consumers own the trigger decision, exact target, target comparison, and all
  downstream authority.
- Integration is instruction-level and optional; independently installed skills
  never import one another.
- A trusted producer writes canonical JSON only to lead-owned run space.
- The local harness produces and validates one target-bound advisory for a
  triggered workflow, then proves the bounded consumer does not repeat it;
  paired cases prove the no-advisory skip path.
- Generic bounded `required_commands` evidence remains available for future
  workflows that must prove an agent-executed helper rather than a lead receipt.
- No audit skill integration is included without observed need.

## Technical Approach

Add a concise conditional step and a progressive consumer reference to each
consumer skill. Extend the local behavioral runner with bounded
`required_commands`, then add realistic cross-cutting and self-contained cases.
Finish by aligning versions, public docs, packaging, and retained evidence.

## Task Breakdown Preview

1. Lock the consumer contract and evaluation proof.
2. Integrate `project-review` and its invoke/skip cases.
3. Integrate `verify-project` and its invoke/skip cases.
4. Integrate `review-and-fix` and its invoke/skip cases.
5. Align catalog, docs, versions, and packages.
6. Run focused evidence, dogfood, independent review, and deliver.

## Success Criteria

- Optional integration preserves standalone operation.
- Valid impact evidence improves focused context, claims, and risk assessment.
- Advisory output never widens scope or authority.
- Lead invocation, bounded consumption, non-duplication, and skip behavior are
  demonstrated from retained host and execution evidence.
- Exact final validation and independent review pass.

## Tasks Created

- [x] 001.md - Lock contract and required-command proof (parallel: false)
- [x] 002.md - Integrate project-review (parallel: false)
- [x] 003.md - Integrate verify-project (parallel: false)
- [x] 004.md - Integrate review-and-fix (parallel: false)
- [x] 005.md - Align public and package surfaces (parallel: false)
- [x] 006.md - Evaluate, dogfood, review, and deliver (parallel: false)

Total tasks: 6
Parallel tasks: 0
Sequential tasks: 6
