---
name: eval-lifecycle-bootstrap
description: Make the local project-evaluation workflow discoverable and safely adoptable without hidden repository mutations or model runs.
status: completed
created: 2026-09-10T10:47:43Z
---

# PRD: eval-lifecycle-bootstrap

## Executive Summary

Close the activation gap in the shipped project-evaluation workflow. Add a
deterministic readiness operation, a preview-first bootstrap that creates a
small valid starter suite only after explicit apply confirmation, and an
optional project instruction fragment that tells agents when evaluation work is
worth considering. Plugin installation continues to install capabilities only;
it never edits a repository, initializes private state, or invokes a model.

## Problem Statement

The evaluation skills have strong contracts once selected, but a newly installed
plugin does not tell an agent whether the current repository is ready, help the
owner create the first valid suite, or provide durable project-level lifecycle
triggers. This makes the workflow easy to overlook and leaves setup to manual
copying even though the safe setup shape is deterministic.

## User Stories

### Inspect readiness without changing the repository

As a repository owner, I can ask `project-eval` whether a selected project has a
valid suite and receive useful human or JSON output without model calls, state
initialization, or filesystem mutation.

### Preview and explicitly apply a minimal setup

As a repository owner, I can preview the exact starter files and their digests,
then create them only with an explicit apply-and-confirm operation. Existing or
partial evaluation content is never overwritten or silently merged.

### Adopt useful lifecycle guidance

As a project owner, I can deliberately add a compact instruction fragment that
guides agents toward relevant eval maintenance after substantial behavior
changes or recurring friction, while avoiding eval work for small unrelated
changes and keeping all model execution explicit.

## Functional Requirements

- Add `project-eval readiness` with human and canonical JSON output.
- Distinguish ready, not configured, incomplete/invalid, and unsafe states.
- Add `project-eval bootstrap` whose default behavior is a non-mutating preview.
- Require both `--apply` and `--yes` for creation; refuse either flag alone.
- Create a complete, cross-platform, deterministically validated starter suite
  using skill-local assets.
- Refuse overwrites, links/reparse points, unexpected partial content, path
  escapes, and changes to files outside the selected evaluation root.
- Make preview output list every destination, byte size, and SHA-256 digest.
- Keep private state initialization and model execution separate and explicit.
- Add an optional project instruction fragment; do not edit `AGENTS.md`
  automatically.
- Improve skill/plugin discovery prompts and public documentation.
- Add focused runtime, safety, catalog, packaging, and behavioral coverage.

## Non-Functional Requirements

- Installed `project-eval` remains independently usable with Python 3.11 and the
  standard library only.
- Human output is derived from the same deterministic result used for JSON.
- Preview and apply remain bounded and fail closed on ambiguous filesystem state.
- The starter demonstrates mechanics, not meaningful coverage of the adopting
  project, and documentation must say so plainly.
- Hosted CI runs deterministic tests only; model-backed evals remain local and
  explicitly requested.

## Success Criteria

- A fresh temporary repository can preview, apply, validate, and grade the
  starter case without a model call.
- A second apply reports non-mutating `not_needed`; a partial destination or
  link-like path is blocked without modifying existing content.
- An already configured valid suite reports `ready` and a malformed suite
  reports `invalid` with an actionable reason.
- The optional instruction fragment expresses the agreed lifecycle triggers and
  authority boundaries in compact form.
- Canonical repository validation and an independent trusted-base review pass.

## Out of Scope

- Automatically editing project `AGENTS.md` files.
- Automatically running model evals after installation, bootstrap, coding, or CI.
- Scheduling evaluations or integrating with a hosted provider.
- Generating project-specific cases from source code or session history.
- Initializing or retaining private local evidence state.
- Publishing a release in this phase.

## Dependencies

- Existing `project-eval` suite and case-control contracts.
- Existing no-follow filesystem helpers bundled with `project-eval`.
- Existing project-evaluation plugin and catalog generation.
