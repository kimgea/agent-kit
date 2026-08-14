---
name: plugin-context-distribution
description: Ship per-skill plugins, a generated marketplace, and layered private context resolution.
status: completed
created: 2026-08-10T13:08:12Z
---

# PRD: plugin-context-distribution

## Executive Summary

Make each installable agent-kit skill available as an independent Codex/ChatGPT
plugin while preserving standalone Codex and Claude Code skill distribution. Add
an optional `agent-context` skill that resolves public defaults plus explicitly
registered private context sources without writing configuration or context data.

## Problem Statement

The toolkit can package and install individual skills, but it cannot produce
plugin manifests or a marketplace. Skills also lack a safe, shared mechanism for
public defaults and private home, work, domain, or repository context. Committing
packaged copies would create competing sources of truth, while implicit context
discovery would create privacy and predictability risks.

## User Stories

- As a user, I can install one selected skill as a plugin without installing all
  skills. Acceptance: a valid per-skill plugin archive is generated.
- As a user, I can browse all released plugins through one marketplace bundle.
  Acceptance: the bundle lists every selected plugin with valid local paths.
- As a Codex or Claude Code user, I can keep using standalone skill archives and
  the ownership-aware installer. Acceptance: existing lifecycle commands remain
  compatible.
- As a context user, I can register separate private context repositories and
  resolve them through exact project mappings. Acceptance: precedence and
  provenance are deterministic and no private source is committed.
- As a maintainer, I edit each skill only in `skills/`. Acceptance: plugin trees
  exist only as ignored deterministic output.

## Functional Requirements

- Extend the catalog with explicit plugin and marketplace metadata.
- Generate standalone skill, per-skill plugin, and marketplace artifacts for a
  selected subset or all installable skills.
- Add a read-only `agent-context` resolver with validation and deterministic
  layered merging.
- Preserve locked public invariants and symbolic-only secret references.
- Keep compatibility, installation, testing, and release guidance in repository
  documentation rather than runtime skill bodies.

## Non-Functional Requirements

- Use only Python 3.11 standard-library dependencies.
- Produce byte-for-byte deterministic archives with complete checksums.
- Reject symlinks, path escapes, malformed schemas, duplicates, and unknown IDs.
- Keep tests network-free and cover Linux and Windows path behavior.
- Never modify installed skills, global agent configuration, or private context.

## Success Criteria

- One selected skill, multiple selected skills, and all skills package correctly.
- Generated plugins pass the plugin validator.
- Context tests cover every precedence level and security rejection path.
- `python scripts/agent_kit.py check` passes without changing the worktree.

## Constraints & Assumptions

- Plugins are skills-only in this release; no MCP, app, hook, UI asset, or
  authentication integration is added.
- One plugin maps to one skill initially, while the catalog can express future
  coherent groupings.
- Private context is stored outside the public repository in separately
  registered repositories or directories.

## Out of Scope

- Publishing to the universal public plugin directory.
- Installing or enabling a local marketplace automatically.
- Writing, syncing, or editing private context sources.
- Heuristic context discovery, glob matching, caches, telemetry, and MCP servers.

## Dependencies

- Existing `toolkit.toml`, deterministic packaging, skill metadata, release
  workflow, and canonical validation gate.
