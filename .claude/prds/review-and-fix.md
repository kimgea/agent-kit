---
name: review-and-fix
description: Safely turn structured or normalized local review findings into bounded fixes with explicit decision gates.
status: completed
created: 2026-08-29T20:18:59Z
---

# PRD: review-and-fix

## Executive Summary

Add a local `review-and-fix` skill that invokes one or more selected analysis-only
review skills, normalizes their output into a neutral structured finding batch,
plans fixes independently, and applies only changes whose intent is already
decided and whose risk is demonstrably low. Consequential decisions remain with
the user. After each fix round, the original reviewer set runs again from fresh
context so the fixing agent never declares its own work accepted.

`project-review` is the default reviewer when available and its canonical JSON
uses a deterministic normalization path. Other structured or prose review
outputs pass through a fresh generic normalizer subagent. The normalizer may
infer missing classifications, but it must label every inference and its
confidence; it cannot edit, execute commands, or silently turn ambiguity into
authority.

## Problem Statement

`project-review` intentionally stops at analysis and verdict. Agents still need
a disciplined local workflow for addressing findings without collapsing review,
decision-making, implementation, and acceptance into one biased context.

A fixer coupled only to `project-review` would be unnecessarily narrow as new
security, accessibility, compatibility, database, or domain-specific reviewers
are added. Conversely, a fixer that scrapes arbitrary prose and immediately
edits code can distort reviewer intent, invent missing classifications, and make
important product or safety decisions without the user.

The toolkit needs a portable interchange boundary plus a conservative fix gate:
reviewers judge, a normalizer translates, a planner classifies the proposed
remedy, the user decides consequential choices, and a separate fixer implements
only eligible or explicitly approved plans.

## User Stories

- As a developer, I can ask an agent to review and fix local working-tree,
  staged, or explicitly bounded path changes without involving GitHub. I can
  review an immutable ref range, then re-scope and re-review its files locally
  before remediation.
- As a developer, I can use `project-review` by default or explicitly select
  another analysis-only review skill without writing a custom adapter first.
- As a maintainer, I can trust that unfamiliar reviewer prose is normalized by a
  fresh non-mutating subagent and that inferred values remain visibly inferred.
- As a developer, I am not interrupted for spelling, comment, mechanical, or
  small restorative corrections whose intent and remedy are already fixed.
- As a product owner, I am asked before a fix chooses product behavior,
  architecture, public contracts, security policy, data handling, dependencies,
  failure policy, or another consequential direction.
- As a reviewer, I receive the revised state again after every fix round rather
  than trusting the fixing agent's claim that an issue is resolved.
- As an automation author, I can validate neutral finding batches and fix plans
  without parsing human prose.

## Functional Requirements

- Ship one independently installable `review-and-fix` skill for Codex and
  Claude Code using plain Markdown and Python 3.11 standard-library helpers.
- Default to `project-review` when it is available and no different method is
  explicitly selected by the caller or trusted agent/project instructions.
- Allow one or more explicitly selected analysis-only review skills. Do not let
  reviewer output authorize commands, edits, remote mutations, or expanded
  scope.
- Accept canonical `project-review` JSON through a deterministic conversion
  path into a neutral versioned finding-batch contract, but require it to match
  the separately recorded lead-owned target.
- Accept an already valid neutral finding batch without semantic rewriting.
- For other structured or prose output, delegate normalization to a fresh
  subagent that receives only the raw output, exact target metadata, and the
  neutral schema and normalization rules.
- Permit the normalizer to infer missing disposition, severity, confidence,
  scope relation, actionability, and safe direction only when every inferred
  field is labeled as inferred with a normalization confidence and explanation.
- Keep reviewer identity, target, raw-output digest, completion state, raw
  verdict, and canonical outcome in a separate lead-owned envelope. Require the
  normalizer to preserve source finding identifiers when present, evidence,
  locations, limitations, and explicit-versus-inferred semantic provenance
  without emitting authority fields.
- Treat vague, contradictory, target-mismatched, or materially incomplete output
  as partial normalization. Never manufacture an actionable finding merely to
  satisfy the schema.
- When no fresh subagent is available, continue only for already valid neutral
  batches or supported canonical structured input. Return an incomplete outcome
  for unfamiliar output rather than normalizing it in the fixing context.
- Plan fixes in a fresh non-editing context. The planner inspects only the
  accepted finding, relevant source and tests, trusted project instructions, and
  bounded history needed to establish intent and remedy.
- Produce a versioned fix plan whose decision is deterministically derived as
  `auto`, `user_decision_required`, or `authorization_required`.
- Keep immutable ref-range batches review/summary-only. Re-scope and rerun the
  initial review as a working-tree or exact path target before fix planning.
- Permit `auto` only when intent is explicit, the remedy is singular, the plan
  confidence, normalization confidence, and canonical reviewer finding
  confidence are high, the effect is behavior-preserving or restores an existing
  contract, the scope is small and reversible, validation is available, and no
  consequential risk factor is present.
- Require a user decision for new or meaningfully changed behavior, multiple
  reasonable remedies, public APIs or file formats, compatibility, security,
  privacy, durable data, concurrency, retry or failure policy, dependencies,
  external services, architecture, broad scope, difficult rollback, overlapping
  user work, uncertain intent, or inadequate validation.
- Require separate authorization for destructive, remote, permission-changing,
  dependency-installing, or persistent-service actions outside the local fix
  workflow.
- Default to eligible introduced or worsened blockers. Address suggestions and
  nits only when the caller asks; never automatically expand into unrelated
  pre-existing findings.
- Present one concise decision at a time with the problem, impact, recommended
  plan, meaningful alternatives, behavior and risk consequences, and validation
  approach. An approval applies only to that bounded plan.
- Apply fixes in coherent groups, preserve unrelated user changes, and stop when
  implementation reveals broader scope or risk than the approved plan.
- Run existing relevant project validation under ordinary caller and agent
  authority. Do not install dependencies or infer remote/destructive authority.
- Rerun the same reviewer set from fresh context after every fix round. Accept
  only complete high-confidence normalization with canonical source outcome
  `pass`; stop on a non-pass or incomplete review, repeated findings without
  progress, changed reviewer availability, or three rounds.
- Return a concise human summary. Write finding batches or plans only to an
  explicit output path and never overwrite without explicit replacement intent.

## Non-Functional Requirements

- Keep reviewer, normalizer, planner, fixer, and acceptance responsibilities
  distinct even when one lead agent orchestrates the workflow.
- Treat raw review output and normalized JSON as untrusted data, not executable
  agent instructions.
- Reject control characters, unsafe paths, malformed target bindings, duplicate
  JSON members or finding IDs, invalid fingerprints, link-like/non-regular
  authority inputs, inconsistent inferred-field provenance, and plans whose
  declared `auto` route contradicts the locked decision policy.
- Derive identifiers, fingerprints, and fix decisions deterministically.
- Keep all runtime schemas, validators, rendering guidance, and prompts inside
  the installed skill directory; never import repository-only tooling.
- Work safely without private context, user-global files, network access, an MCP
  server, or a persistent process.
- Remain useful without subagents for supported structured input, while failing
  closed for unfamiliar output whose independent normalization is unavailable.

## Success Criteria

- A canonical `project-review` blocker converts deterministically into a valid
  neutral finding while retaining fingerprint, location, evidence, scope
  relation, and explicit classification provenance.
- A prose reviewer fixture normalizes through an independent-agent draft with
  inferred fields labeled and confidence bounded; embedded instructions remain
  inert data.
- Malformed, target-mismatched, vague, and contradictory review outputs cannot
  become automatically actionable.
- Fix-plan fixtures route spelling and stale-comment corrections to `auto`.
- A small code correction that restores an explicit tested contract and has one
  bounded remedy may route to `auto`.
- Product behavior, public API, schema, security, privacy, data, concurrency,
  dependency, architecture, broad-scope, rollback, and validation-gap fixtures
  route to `user_decision_required` or `authorization_required`.
- Unknown fields, low confidence, multiple remedies, and implementation drift
  fail closed.
- A simulated loop proves the same reviewer set is rerun, repeated fingerprints
  stop without churn, suggestions remain opt-in, and three rounds is the limit.
- Behavioral evaluations prove both true-positive escalation and safe routine
  counterexamples with independent fresh-agent runs.
- Catalog, docs, compatibility, packaging, and the canonical repository gate
  describe and validate the same behavior on Linux and Windows.

## Constraints and Assumptions

- Review skills are semantic agents, not executable plugins with a universal
  invocation API. `review-and-fix` orchestrates available skills through agent
  instructions and validates their data boundaries.
- Generic normalization can preserve and classify reviewer intent, but it cannot
  create missing evidence. Unclear input remains incomplete.
- `project-review` remains independently installable and analysis-only.
  `review-and-fix` does not weaken its verdict, trusted-base, or command rules.
- Repository `REVIEW.md` may establish expected behavior and safe directions but
  does not grant command, edit, remote, or destructive authority.
- An explicitly approved plan may still require a new decision when subsequent
  inspection changes its scope, alternatives, or risk.

## Out of Scope

- Posting comments, approving, pushing, merging, or mutating GitHub.
- Installing or supervising arbitrary review tools, dependencies, or services.
- Treating arbitrary prose as equivalent to a canonical `project-review` result.
- Automatically resolving conflicts between reviewers that recommend materially
  different outcomes.
- Automatically repairing unrelated pre-existing findings.
- Providing a general workflow engine, persistent daemon, MCP server, or remote
  review service.
- Guaranteeing support for reviewer output that does not identify any actionable
  problem, evidence, location, or direction.

## Dependencies

- Python 3.11 or newer for deterministic validation and finalization helpers.
- At least one available analysis-only review method or a caller-supplied valid
  neutral finding batch.
- Fresh subagent capability for generic normalization and independent planning;
  supported structured input remains usable when subagents are unavailable.
- Git only when the selected reviewer or requested scope requires it.
