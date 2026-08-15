---
name: transient-artifact-host
description: Create, serve, and share short-lived interactive web artifacts from agent conversations.
status: completed
created: 2026-08-15T10:38:42Z
---

# PRD: transient-artifact-host

## Executive Summary

Add an agent-friendly artifact host for short-lived visual and interactive output.
An agent can publish a static HTML bundle, a multipage site, or a static framework
build and return a browser URL without committing generated output. A separate
producer skill creates polished interactive diagrams and hands them to the host.
The service is local by default and can be exposed to the user's tailnet through
an explicit, preview-first Tailscale Serve setup.

## Problem Statement

Remote SSH conversations are limited by terminal rendering. Existing repository
or documentation hosting is too permanent and cumbersome for exploratory diagrams,
temporary dashboards, and other visual explanations. Agents need a predictable
way to create a transient web artifact, let the user open it from another device,
and later expire or revoke it without turning the conversation output into a
maintained project.

## User Stories

- As a remote SSH user, I can open an agent-created artifact in a local or tailnet
  browser using a named HTTPS URL.
- As an agent, I can publish a single page, multipage directory, Vite/React build,
  or Next.js static export without learning a deployment platform.
- As a user, I can list, expire, or immediately revoke artifacts and inspect what
  is currently shared.
- As a producer-skill author, I can call one stable CLI contract instead of
  embedding hosting logic in every skill.
- As a security-conscious user, I get loopback-only defaults and an explicit
  preview before persistent Tailscale configuration changes.

## Functional Requirements

- Ship a self-contained `serve-artifacts` skill with a Python 3.11 standard-library
  CLI and HTTP service.
- Publish copied static bundles under unguessable IDs with TTL metadata; support
  single-page, multipage, and optional SPA fallback behavior.
- Serve artifacts through isolated viewer pages with restrictive browser headers,
  no directory listing, and no remote management endpoints.
- Reject symlinks, path escapes, unsafe file types, excessive file counts, and
  excessive bundle sizes before publication.
- Provide start, foreground serve, status, list, publish, revoke, stop, doctor,
  and cleanup operations with machine-readable output where agents need it.
- Provide a preview-first Tailscale Serve setup/removal command that owns only the
  `/agent-artifacts` route and never uses Funnel.
- Support proxy records only for an explicitly supplied already-running loopback
  HTTP service. Never accept or execute a build or server command.
- Ship a self-contained `build-interactive-diagram` skill with a reusable HTML,
  CSS, and JavaScript starter that can operate without the host and publish through
  it when available.
- Package both related skills in one optional Codex plugin while preserving their
  standalone skill archives and independent usefulness.

## Non-Functional Requirements

- Use only Python 3.11 standard-library dependencies at runtime.
- Keep generated artifacts and runtime state in private OS-native user directories,
  outside Git repositories and agent installation trees.
- Work on Linux, Windows, and macOS; Tailscale integration is optional and detected
  at runtime.
- Remain useful without Tailscale, Codex plugins, an MCP server, Docker, Node, or a
  framework toolchain.
- Keep lifecycle operations deterministic, bounded, and safe under concurrent CLI
  use and stale process state.

## Success Criteria

- Local smoke tests publish and render a static interactive artifact, navigate a
  second page, enforce SPA fallback, expire/revoke content, and proxy a loopback app.
- Security tests reject links, escapes, invalid targets, and oversized input while
  proving the management surface is not exposed over HTTP.
- Tailscale tests prove dry-run is non-mutating, apply/remove use exact owned flags,
  unrelated Serve configuration is preserved, and public Funnel is never invoked.
- Both skill archives and the grouped plugin package validate deterministically.
- `python scripts/agent_kit.py check` passes without changing the worktree.

## Constraints & Assumptions

- Framework support means hosting build output. Vite `dist/` and Next.js
  `output: export` directories are first-class static bundles.
- Dynamic Next.js or other application servers remain owned by their producer;
  the host can proxy an already-running loopback URL but does not supervise it.
- The random artifact URL is a capability link within the local machine or tailnet,
  not an authentication system.
- Tailscale ACLs and grants remain the user's network authorization boundary.

## Out of Scope

- Internet-public hosting, Tailscale Funnel, cloud deployment, or repository Pages.
- Running package managers, framework builds, arbitrary commands, or containers.
- Durable documentation hosting, collaborative editing, databases, SSR lifecycle
  management, authentication, analytics, or artifact synchronization.
- An MCP server in the initial release; the CLI is the stable future adapter seam.

## Dependencies

- Python 3.11 or newer.
- Optional Tailscale CLI and tailnet HTTPS support for remote named URLs.
