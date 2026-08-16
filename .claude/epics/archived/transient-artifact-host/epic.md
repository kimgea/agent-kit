---
name: transient-artifact-host
status: completed
created: 2026-08-15T10:38:42Z
updated: 2026-08-15T11:02:49Z
progress: 100%
prd: .claude/prds/transient-artifact-host.md
github: null
---

# Epic: transient-artifact-host

## Overview

Deliver a transient, local-first web artifact service plus an interactive-diagram
producer skill, with optional tailnet-only sharing through Tailscale Serve.

## Architecture Decisions

- Make a dependency-free CLI/background service the runtime core and a skill the
  agent-facing interface; defer MCP and Docker adapters until they provide value.
- Store copied static bundles in private OS-native state with TTLs and random IDs.
- Bind to loopback and use Tailscale Serve only as an explicit network adapter.
- Support static framework output directly and proxy only an already-running
  loopback service; never accept executable commands.
- Package the two related skills together as one plugin while keeping each skill
  independently installable.

## Technical Approach

Implement the host and lifecycle boundary first, then Tailscale ownership and
security checks. Add a code-native diagram starter and concise producer workflow.
Finish with catalog integration, behavior evaluations, documentation, packaging,
and live loopback/Tailscale-safe smoke tests.

## Task Breakdown Preview

1. Record architecture and distribution contracts.
2. Implement the artifact service and lifecycle.
3. Implement Tailscale integration and security boundary tests.
4. Add the interactive-diagram producer and shared handoff.
5. Integrate, validate, package, and document delivery.

## Dependencies

The producer consumes the host CLI contract but must retain a path-only fallback.
Tailscale exposure depends on a locally running host, not the reverse.

## Success Criteria (Technical)

- The PRD requirements and adversarial tests pass on the final branch.
- Static and proxied artifacts work through the same stable viewer URL model.
- Installation and packaging preserve standalone and grouped-plugin behavior.
- The canonical repository gate passes and the final diff is reviewable.

## Estimated Effort

Large, approximately one focused implementation cycle.

## Tasks Created

- [x] 001.md - Record architecture and distribution contracts
- [x] 002.md - Implement artifact service and lifecycle
- [x] 003.md - Implement Tailscale and security boundaries
- [x] 004.md - Build interactive diagram producer
- [x] 005.md - Integrate validate package and document

Total tasks: 5
Parallel tasks: 0
Sequential tasks: 5
Estimated total effort: 16 hours
