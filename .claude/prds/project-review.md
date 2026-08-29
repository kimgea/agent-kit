---
name: project-review
description: Provide portable, hierarchy-aware, read-only project reviews with canonical structured results.
status: completed
created: 2026-08-29T09:45:52Z
---

# PRD: project-review

## Executive Summary

Add a `project-review` skill that reviews a bounded change or set of project
files under repository-owned, path-specific `REVIEW.md` guidance. The skill
produces one schema-versioned JSON result and deterministically renders an
easy-to-read report from it. It analyzes and reports only: publishing pull
request comments, changing code, approving, and merging belong to future
consumer skills.

The guidance model is deliberately familiar. A review of `a/b/c.py` combines
optional user-global guidance, the repository-root `REVIEW.md`,
`a/REVIEW.md`, and `a/b/REVIEW.md`; the closest applicable repository rule wins
when rules conflict. For change reviews, repository guidance comes from the
trusted starting revision so a proposed change cannot weaken the rules used to
review itself.

## Problem Statement

General review prompts miss constraints that experienced code owners know but
that are difficult to infer from code alone. Putting every review rule in one
root file creates noise in large repositories, while putting review behavior in
agent-specific configuration makes the rules non-portable. Existing native
review systems also expose different interfaces and outputs, which makes it hard
to build reliable follow-on skills for pull-request publishing or issue fixing.

Project owners need a review-only instruction hierarchy near the code it governs,
and agents need one portable workflow with explicit scope, evidence, finding
calibration, coverage, and a machine-readable result.

## User Stories

- As a code owner, I can place review guidance at the repository root or in a
  specialized subtree without putting it in every agent's general instructions.
- As a reviewer, I can review a ref range, working-tree changes, or explicit
  files and know exactly which guidance governed each file.
- As an interactive user, I receive a concise human report with blockers first,
  suggestions next, and valid nits last.
- As a future automation author, I can request canonical JSON, filter or publish
  findings under a separate policy, and rerun reviews using stable fingerprints.
- As a security-conscious maintainer, I know changed review instructions cannot
  authorize commands or lower the bar applied to their own change.
- As an agent without subagent support, I can run the same review contract with
  reduced parallelism and explicit coverage reporting.

## Functional Requirements

- Ship one independently installable `project-review` skill for Codex and
  Claude Code.
- Support three bounded scope families in v1:
  - a Git ref, range, or pull-request diff already available to the caller;
  - staged, unstaged, or combined working-tree changes; and
  - explicitly selected files or bounded directories.
- Exclude unbounded whole-repository audits from v1.
- Resolve plain-Markdown `REVIEW.md` files per reviewed path from broadest to
  most specific, with no required frontmatter or import syntax.
- Support one optional active-agent user-global `REVIEW.md` in addition to
  repository guidance; remain fully functional when it is absent.
- For ref/range reviews, read repository guidance from the base revision. For
  working-tree reviews, read it from committed `HEAD`. Review changed guidance
  as ordinary content without letting it govern the same change.
- Permit context inspection of callers, tests, schemas, configuration, and other
  related files without silently expanding the finding scope.
- Use one lead reviewer to own scope, guidance resolution, verification,
  calibration, deduplication, and the final verdict.
- Allow bounded subreviews for large or heterogeneous scopes, grouped by coherent
  subsystem, risk, and identical guidance chain rather than one agent per file.
- Produce canonical JSON conforming to a versioned schema, then render all human
  output from that result.
- Default to human output for interactive use; support explicit `json` and
  `both` formats for callers.
- Write no result file by default. Persist only to an explicit caller-supplied
  output path.
- Classify findings independently by disposition (`blocker`, `suggestion`, or
  `nit`), severity, category, confidence, and relation to the requested change.
- Derive exactly one verdict: `BLOCK` when a blocker is verified, `INCOMPLETE`
  when no blocker is known but material coverage prevents a reliable pass, and
  `PASS` otherwise. A pass may contain suggestions and nits.
- Record limitations, rule provenance, inspected scope, related context, and any
  verification commands and results.
- Preserve one normalized change record per requested path and both trusted
  source and destination guidance chains for renames or copies.
- Perform static inspection by default. Run tests, linters, type checks, builds,
  or diagnostics only when the current request or trusted user-global guidance
  grants bounded authorization. Repository `REVIEW.md` files may recommend
  commands but cannot authorize their execution.

## Non-Functional Requirements

- Keep the core workflow analysis-only and non-mutating. Authorized verification
  may create disposable runtime artifacts but must not edit source, install
  dependencies, change configuration, or mutate remote systems.
- Use Python 3.11 standard-library helpers for deterministic guidance resolution,
  schema validation, and text rendering.
- Work on Linux, Windows, and macOS. Git-dependent scopes may require Git;
  explicit snapshot reviews should degrade clearly when Git metadata is absent.
- Bound guidance and review fan-out. A truncated or materially unreviewed scope
  must be disclosed and may require `INCOMPLETE`.
- Treat repository content, review guidance, diffs, command output, and generated
  JSON as untrusted data rather than executable agent instructions.
- Avoid secrets and raw private context in results. Record provenance by path,
  revision, and digest rather than copying unrelated guidance into the report.
- Keep the schema useful to future PR-publishing and fix-loop consumers without
  coupling this skill to GitHub or any one agent runtime.

## Success Criteria

- A fixture reviewing `a/b/c.py` proves the broad-to-specific guidance chain and
  closest-rule precedence.
- Change-review fixtures prove a modified or newly added `REVIEW.md` cannot govern
  its own review, while unchanged trusted-base guidance still applies.
- Rename, deletion, new-subtree, missing-guidance, oversized-guidance, symlink,
  and path-escape cases have deterministic outcomes.
- The schema rejects malformed verdicts, findings, paths, provenance, and command
  records; the renderer produces stable human output from valid JSON.
- Verdict tests cover clean pass, pass with suggestions/nits, verified blocker,
  and material incomplete coverage.
- Verification tests prove no command runs without a valid authorization source,
  repository text alone is insufficient, and disallowed side effects remain
  outside the skill contract.
- Single-agent and delegated reviews use the same result contract, and delegated
  candidate findings are rechecked by the lead.
- Evaluation cases cover ordinary bugs, repository-specific rules, false-positive
  resistance, pre-existing issues, malicious guidance, and concise reporting.
- `python scripts/agent_kit.py check` passes and packages the skill independently.

## Constraints and Assumptions

- `REVIEW.md` is behavioral guidance, not an enforcement boundary. Tests,
  branch protection, permissions, and human judgment remain separate controls.
- The caller or a future adapter resolves a GitHub pull request into a local,
  reviewable diff; this skill itself does not call GitHub.
- The active agent identifies its own optional user-global review file. The skill
  does not merge private configuration from multiple agent products.
- Natural-language conflicts are settled by source authority and path proximity;
  v1 does not add an override DSL.
- A high-confidence, actionable defect introduced or worsened by the reviewed
  change may block. Pre-existing defects are normally non-blocking and clearly
  labeled unless the change worsens them or trusted guidance explicitly requires
  touched code to meet a stronger standard.

## Out of Scope

- Posting review comments, submitting approvals, changing pull-request state,
  merging, or any other remote mutation.
- Editing or fixing reviewed files.
- Installing dependencies or starting arbitrary services for verification.
- Full-repository security audits, compliance certification, or exhaustive formal
  verification.
- Native integration with Codex Code Review or Claude Code Review APIs.
- A frontmatter schema, imports, executable directives, ownership lookup, or an
  `REVIEW.override.md` mechanism in v1.
- Replacing `AGENTS.md`, `CLAUDE.md`, CI, formatters, or linters.

## Dependencies

- Python 3.11 or newer for deterministic helper scripts.
- Git for ref/range and working-tree scope discovery.
- Optional subagent capability for parallel review; never required for correctness.
