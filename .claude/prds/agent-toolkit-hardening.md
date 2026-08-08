---
name: agent-toolkit-hardening
description: Turn agent-kit into a safe, discoverable, cross-platform toolkit repository.
status: completed
created: 2026-08-04T09:08:56Z
---

# PRD: agent-toolkit-hardening

## Executive Summary

Upgrade the repository from a small collection of skills into a reusable toolkit
that agents can safely discover, validate, install, update, remove, evaluate, and
release across Codex and Claude Code on Linux, Windows, and macOS.

## Problem Statement

The retained skills have strong local safety boundaries, but the repository lacks
an agent-readable operating contract, one validation/install interface, immutable
releases, legal and security metadata, comprehensive CI, and protected delivery.

## User Stories

- As an agent, I can discover resources and compatibility through a stable JSON
  interface without scraping prose.
- As a maintainer, I can run one command that validates every resource and test.
- As a user, I can preview an installation or removal before any global file is
  changed and recover removed deployments.
- As a reviewer, I can identify changes to permission boundaries and require the
  correct checks before merge.
- As a Codex or Claude user, I can install a tagged skill on a supported OS and
  then separately review any permission proposal.

## Functional Requirements

1. Add shared Codex/Claude repository instructions and a machine-readable catalog.
2. Add cross-platform list, doctor, check, package, install, and uninstall commands.
3. Keep installations and permission grants separate and dry-run by default.
4. Validate every skill, link, catalog record, evaluation, and safety boundary.
5. Normalize `grill-me` with progressive disclosure and Codex metadata.
6. Add security, licensing, provenance, ownership, release, and contribution docs.
7. Use unified Linux/Windows CI and immutable release artifacts with checksums.
8. Protect `main`, restrict Actions, and enable dependency update automation.

## Non-Functional Requirements

- Use Python 3.11+ standard library only.
- Preserve independent skill installation and Claude compatibility.
- Support paths containing spaces and non-default agent homes.
- Avoid network access during validation and tests.
- Preserve private runtime data and reject installation drift.

## Success Criteria

- `python scripts/agent_kit.py check` passes from a clean checkout.
- All three skills pass structural validation and all repository tests pass on
  Ubuntu and Windows with Python 3.11 and 3.13.
- Install/update/remove lifecycle tests prove dry-run, ownership, drift, and
  recoverability behavior.
- GitHub `main` requires CI and PR-based changes; Actions are pinned/restricted.
- A `v1.0.0` release provides deterministic per-skill archives and checksums.

## Constraints & Assumptions

- `gh-api-get` is mandatory for read-only GitHub REST API access.
- Global writes and GitHub mutations require explicit user authorization.
- GitHub authentication may need to be restored before remote delivery.

## Out of Scope

- Automatically granting skill runtime permissions during installation.
- Supporting Python versions older than 3.11.
- Uploading transcripts, todo data, or other runtime state.
- Building a hosted marketplace service.

## Dependencies

- Git, Python 3.11+, and GitHub Actions.
- GitHub CLI authentication for PR, release, and repository settings.
