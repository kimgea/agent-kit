---
name: skill-ecosystem-alignment
description: Define how Agent Kit capabilities compose, remain independently useful, and grow through evidence-backed future skills.
status: completed
created: 2026-09-03T18:45:24Z
---

# PRD: skill-ecosystem-alignment

## Executive Summary

Document a coherent ecosystem for Agent Kit before adding another skill. Keep
skills independently installable and physically flat, group them into useful
workflow bundles, and define explicit handoffs between context providers,
discoverers, normalizers, decision gates, actors, verifiers, acceptance
reviewers, and presenters. Inventory the current toolkit against role-appropriate
contracts and publish a non-binding roadmap led by local verification,
verification-failure triage, and workflow-observation analysis.

This phase changes documentation and tracking only. It identifies bounded
migration candidates without changing any installed skill's runtime behavior,
schema, metadata, permissions, or package membership.

## Problem Statement

Agent Kit now contains several proven local workflows, but their relationships
have grown incrementally. The project-review family already separates analysis,
normalization, remediation, verification evidence, and fresh acceptance in
important places; the artifact, context, decision-support, todo, and tool-audit
skills form other useful workflows. Without an ecosystem-level design, future
skills may duplicate orchestration, invent incompatible status or provenance
formats, depend directly on siblings, force irrelevant JSON contracts onto
standalone utilities, or accumulate into one overly broad workflow.

The repository needs a stable architecture that explains how capabilities may
compose without creating a closed ecosystem. Third-party skills must remain
usable through consumer-owned normalization, and project-specific policy must be
able to guide useful observations without granting itself mutation or command
authority.

## User Stories

### Understand the current toolkit

As a user or maintainer, I can see how every current skill and supporting
resource fits into the toolkit without reading every implementation.

Acceptance criteria:

- Every cataloged skill has a primary role, optional secondary capabilities,
  effect class, composition surface, workflow bundle, and fitness state.
- Standalone skills are not treated as deficient for omitting irrelevant
  structured handoffs.
- Tools, hooks, policies, templates, instructions, adapters, schemas, and
  evaluations are mapped as supporting infrastructure rather than peer skills.

### Compose skills safely

As an agent or workflow author, I can pass work between skills through explicit,
validated artifacts while preserving target, provenance, authority, limitations,
and fresh-agent independence.

Acceptance criteria:

- The design defines a small common envelope and family-specific payloads.
- The lead or orchestrator owns target, authority, context identity, selection,
  loop budget, and persistence authority.
- Producers may provide evidence, impact, constraints, and a safe direction but
  cannot authorize or own a concrete fix plan.
- Canonical results are the semantic source of truth and human output is rendered
  from them when a skill supports structured composition.
- Consumer-owned deterministic adapters handle known stable formats; a fresh
  non-editing normalizer handles unfamiliar structured or prose output.
- Direct free-agent consumption remains available for advisory work, but
  mutation or authoritative acceptance requires validated canonicalization.
- Third-party skills remain eligible through explicit selection and conservative
  normalization rather than membership in Agent Kit.

### Preserve meaningful user control

As a user, I make consequential decisions without repeatedly confirming an
intention I already expressed.

Acceptance criteria:

- Effect declarations distinguish local reads, outputs, workspace edits,
  command execution, temporary services, dependency installation, permission
  changes, external reads, and remote mutation.
- A lead-owned authority envelope may cover bounded routine work across stages.
- A stage requests attention only for materially new scope, risk, behavior,
  authority, or policy decisions.
- Repeated workflows have cumulative budgets, explicit stopping conditions, and
  structured last-run and continuation status.

### Improve the toolkit from real workflow evidence

As a maintainer, I can retain useful evidence about harness gaps and workflow
friction without mixing it with findings about the reviewed project.

Acceptance criteria:

- A shared, optional workflow-observation model is documented separately from
  target findings.
- Observations require concrete evidence, source-stage provenance, confidence,
  strength, reason, a stable duplicate identity, and bounded output.
- `AGENTS.md` may tune categories, thresholds, limits, destination preference,
  and retention, but cannot remove integrity invariants or authorize storage.
- Producers remain storage-neutral; persistence belongs to a separately
  authorized future capability.

### Grow from a deliberate roadmap

As a project owner, I can distinguish the next proven gap from likely and
exploratory ideas without treating every candidate as a commitment.

Acceptance criteria:

- `verify-project` is the concrete next capability.
- Verification-failure triage and workflow-observation storage/analysis are
  likely follow-ups in that order.
- Specialized reviewers require a distinct method, repeated need, standalone
  value, and behavioral proof.
- Multi-review orchestration remains exploratory until overlapping reviewers
  and recorded coordination friction demonstrate value.
- External publishers remain later optional adapters; the near-term roadmap is
  local and provider-neutral.

## Functional Requirements

- Keep source skill directories flat under `skills/`.
- Use documentation and plugin bundles to express capability families and useful
  workflows.
- Keep a single skill as the default ownership, versioning, and standalone
  installation boundary.
- Define a tiered ecosystem contract: a small baseline for every skill and
  stronger canonical contracts only for composable workflows.
- Define primary roles with namespaced secondary capabilities.
- Define explicit orchestrated handoffs; skills do not silently chain themselves.
- Define separate common state axes for completion, outcome, and next action.
- Keep schema versions independent per producer and require consumers to declare
  supported versions.
- Define required and optional capabilities for focused orchestration skills.
- Permit automatic selection only for trusted or explicitly approved compatible
  capabilities; unknown installed skills remain directly usable and advisory.
- Define fresh-agent requirements at bias-sensitive judgment boundaries and a
  risk-based fallback when independent contexts are unavailable.
- Define progressive local verification, evidence sufficiency, and failure
  handoff without implementing `verify-project` in this phase.
- Define fitness-based inventory states: aligned composable, aligned standalone,
  partially aligned, migration candidate, and intentionally exempt.
- Identify optional bridges for standalone skills without making them mandatory.

## Non-Functional Requirements

- The documents must use plain language, concrete examples, and compact diagrams
  so users do not need to reconstruct the architecture from abstract terminology.
- Existing skill-specific documentation remains authoritative for detailed
  behavior, security, compatibility, tests, and maintenance.
- Shared specifications and conformance tests are preferred over runtime imports;
  installed skills remain self-contained.
- The design must preserve current security, privacy, provenance, and permission
  boundaries.
- The roadmap must distinguish current fact, selected direction, migration
  candidate, and exploratory idea.
- No documentation may claim that planned schemas, metadata, adapters, skills, or
  storage backends already exist.

## Success Criteria

- `docs/skill-ecosystem.md` captures the selected architecture, current resource
  inventory, role model, handoff model, trust boundaries, output model, and
  optional bridges.
- `docs/skill-roadmap.md` records next, likely, and exploratory horizons plus
  evidence-based promotion criteria.
- README and architecture navigation lead readers to both documents without
  duplicating their contents.
- Every current cataloged resource appears in the inventory or an explicitly
  described infrastructure category.
- `python scripts/agent_kit.py check` passes without model execution.
- An independent trusted-base project review finds no blocker before delivery.

## Constraints & Assumptions

- This is a design and inventory phase, not a runtime migration.
- `toolkit.toml` remains the current catalog source of truth. Proposed ecosystem
  metadata fields are migration candidates, not active schema in this phase.
- Composable skills prefer deterministic adapters for repeated stable producer
  formats and fresh normalizer agents for unfamiliar output.
- Cheap models may normalize bounded mechanical structures when the launching
  environment supports model selection; ambiguous or consequential semantics
  require a stronger fresh context or an incomplete stop.
- Repository `REVIEW.md`, `AGENTS.md`, code, and configuration may recommend
  commands but do not create execution authority.
- Clear caller intent can authorize a bounded class of routine local work without
  a redundant second confirmation.

## Out of Scope

- Implementing `verify-project` or any other new skill.
- Changing existing skill schemas, runtime helpers, prompts, or permissions.
- Adding ecosystem metadata fields to `toolkit.toml` or changing packaging.
- Migrating current skills to new handoff contracts.
- Creating an evidence database or persistence backend.
- Running agents in hosted CI.
- Adding provider-specific GitHub, GitLab, cloud, or CI integrations.
- Publishing a release.

## Dependencies

- Current `toolkit.toml` resource and plugin inventory.
- Existing skill and maintainer documentation.
- Existing project-review, review-and-fix, audit, artifact, context, todo, and
  tool-audit contracts.
