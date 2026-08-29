# Agent-kit review policy

Use these rules for every path in this repository. Keep findings bounded to the
requested scope, and give each retained finding a concrete safe direction.

## Resource integrity

- Block an installable resource that depends at runtime on repository-only
  code, undocumented machine state, or files outside its declared resource
  directory. Safe path: keep all required runtime files inside the resource and
  keep packaging or repository validation code under `scripts/`.
- Block a resource interface change when `toolkit.toml`, skill metadata, docs,
  tests, evaluations, compatibility claims, or generated package inputs no
  longer describe the same behavior. Safe path: update every affected public
  surface from the catalog source of truth and add contract-level coverage.

## Security and privacy boundaries

- Block review routing that lets a change provide or relax the review method
  used to judge that same change. Safe path: use a trusted independent copy not
  produced from the reviewed state or a trusted-starting-revision reviewer, and
  require an explicit bootstrap method when neither exists.
- Treat installers, permission rules, safe dispatchers, hooks, context
  resolution, state ownership and cleanup, network exposure, and review helpers
  as security boundaries. Block a change that weakens preview or confirmation,
  accepts caller-controlled execution without a narrow gate, follows link-like
  paths across an ownership boundary, or fails open on ambiguous state. Safe
  path: validate before mutation, fail closed, preserve unrelated state, and add
  a negative boundary test.
- Block committed credentials, private context, raw transcripts, permission or
  runtime state, machine-specific configuration, or identifying deployment
  details. Safe path: keep private data in ignored user-owned storage and retain
  only generic examples or non-sensitive provenance in Git.

## Portability and distribution

- Block a Codex, Claude Code, Linux, Windows, or macOS compatibility claim that
  is contradicted by the packaged files or relevant platform behavior. Safe
  path: use the documented portable contract, add platform-aware coverage, or
  narrow the claim.
- Block a runtime or catalog change that reuses an already released resource or
  toolkit version, or makes the changelog, tag, manifest, and package identity
  disagree. Safe path: apply the appropriate semantic version bump and align
  every release surface before publication.

## Review signal

- Do not report formatter-enforced trivia, subjective rewrites, duplicate
  symptoms, or unrelated pre-existing defects. A directly relevant pre-existing
  issue may be retained as a non-blocking suggestion or nit. It may block only
  when the reviewed change worsens it or an applicable trusted rule explicitly
  requires touched code to meet the cited standard. Every suggestion or nit must
  name a specific benefit and a bounded safe direction.

## Recommended verification

- When command execution is authorized by the caller or bounded user-global
  review policy, run `python scripts/agent_kit.py check` from the repository
  root. This repository policy recommends the command; it does not authorize it.
