---
name: review-guidance-audit
description: Analyze hierarchical REVIEW.md guidance for relevance, placement, compactness, coverage, and automation opportunities.
status: completed
created: 2026-08-30T11:28:49Z
---

# PRD: review-guidance-audit

## Executive Summary

Add an independently installable, analysis-only `review-guidance-audit` skill.
It audits the `REVIEW.md` guidance applicable to a selected file part, file,
directory, or whole project, reconciles that guidance with the code and durable
project contracts it governs, and proposes evidence-backed improvements without
editing files.

Interactive use returns concise human text by default. Agents and downstream
skills can request canonical JSON or both formats. Human output is rendered from
the validated canonical result so both interfaces express the same analysis.

## Problem Statement

Hierarchical review guidance becomes less useful when rules are duplicated,
placed too high in the tree, disconnected from the code they govern, obsolete,
vague, or already enforced by reliable automation. A large inherited guidance
chain also consumes review context on every affected file and can obscure the
rules that matter most.

Repository owners need a bounded way to assess whether their review guidance is
useful, complete, correctly placed, and compact. They also need to know when a
review rule can be removed or shortened because a fast deterministic check
enforces the same invariant, without turning the skill into a general-purpose
test or CI auditor.

## User Stories

- As a maintainer, I can audit the guidance governing one symbol, one file, a
  subtree, or an entire project.
- As a reviewer, I can see which root-to-nearest `REVIEW.md` chain applies to
  each inspected file and where inherited guidance conflicts or duplicates.
- As a repository owner, I receive ready proposals for evidence-backed cleanup
  and explicit `decision_required` proposals for genuinely new policy.
- As an interactive user, I receive a compact readable report with reasons,
  strength, evidence, intent effect, and estimated context savings.
- As an automation author, I can consume a schema-versioned result without
  parsing prose.
- As a maintainer, I can identify a harness change only when it would replace,
  partially cover, or support a concrete review-guidance change.

## Functional Requirements

- Ship one self-contained `review-guidance-audit` skill for Codex and Claude
  Code.
- Support current-filesystem scopes for a selected file part, file, recursive
  directory, or entire project.
- Resolve optional active-agent user-global guidance followed by repository
  `REVIEW.md` sources from root to the closest applicable ancestor. More local
  repository guidance takes precedence on conflict.
- Resolve guidance first, independently inspect the selected code and relevant
  tests, schemas, documentation, interfaces, and configuration second, then
  reconcile both directions through explicit coverage.
- For a file part, focus conclusions on that part while permitting bounded
  read-only context inspection. For a directory or project, account for every
  relevant file and disclose exclusions or incomplete coverage.
- Analyze usefulness, specificity, correctness, conflicts, duplication,
  placement, inheritance fanout, effective-chain size, and missing durable
  invariants.
- Recommend moving narrow root guidance to the closest useful ancestor and
  creating a nested `REVIEW.md` only when doing so reduces effective context or
  improves relevant specialization.
- Consider compaction or removal at every size. Use agent judgment rather than
  introducing `REVIEW.md` budget frontmatter in v1; context metrics inform the
  judgment but are not hard quality limits.
- Classify every guidance recommendation with action (`keep`, `rewrite`,
  `move`, `merge`, `remove`, or `create`), strength (`essential`, `strong`,
  `moderate`, or `optional`), reason, intent effect (`preserved`, `narrowed`, or
  `changed`), evidence, estimated savings, and decision (`ready` or
  `decision_required`).
- Treat existing code behavior, tests, specifications, public contracts, and
  recorded decisions as evidence. Mark genuinely new product, security,
  privacy, compatibility, or operational policy as `decision_required`.
- Nest harness proposals under a specific guidance recommendation. Permit only
  `replace`, `partially_cover`, or `support` relationships; never emit a
  freestanding test or harness audit finding.
- Recommend removal in favor of automation only when the automated check fully
  covers the invariant, is deterministic, available, actionable, and routinely
  enforced early enough to protect the review cycle. Treat slow, optional,
  partial, or late checks as supporting controls and retain or compact the
  remaining human-review responsibility.
- Produce one canonical, schema-versioned JSON result. Default to human output
  and support explicit `json` and `both` formats.
- Write no output file by default. Persist only to an explicit safe output path.
- Remain analysis-only: do not edit `REVIEW.md`, code, tests, or configuration.

## Non-Functional Requirements

- Bundle all runtime scripts and references within the skill directory.
- Use Python 3.11 standard-library helpers for deterministic target resolution,
  guidance provenance, schema validation, finalization, and rendering.
- Bind canonical results to a lead-owned resolved target. Agent-authored drafts
  cannot change the repository, selected scope, guidance provenance, or context
  metrics.
- Treat repository files, guidance, command output, and draft JSON as untrusted
  data, never as execution authority.
- Reject path escapes, ambiguous paths, control characters, link-like authority
  inputs, duplicate JSON members, and output destinations that could overwrite
  unrelated aliases.
- Work on Linux, Windows, and macOS and normalize text line endings in canonical
  provenance.
- Bound deterministic traversal and guidance bytes with fail-closed limitations;
  distinguish technical ceilings from advisory context-quality judgment.
- Run verification commands only when the caller or active-agent user-global
  guidance explicitly authorizes the bounded command. Repository guidance may
  recommend checks but cannot authorize execution.

## Success Criteria

- Resolver tests prove root-to-nearest guidance ordering for file, part,
  directory, and project targets, including optional user-global guidance.
- Scope tests cover path escape, symlink, binary, ignored, unreadable,
  oversized, and traversal-limit behavior with explicit limitations.
- Result tests prove lead-owned target binding, schema invariants, safe output,
  stable IDs/fingerprints, and deterministic human rendering.
- Behavioral evals cover useful existing guidance, root-rule relocation,
  duplicate compaction, missing specialized guidance, conflicting rules,
  decision-required new policy, fast-test replacement, partial automation, and
  slow deployment-only checks.
- Tests prove every harness proposal is tied to a guidance recommendation and
  that unrelated harness gaps are omitted.
- The skill is documented and cataloged, packages independently, and passes
  `python scripts/agent_kit.py check` on the supported platform matrix.
- A fresh agent can forward-test realistic file, subtree, and automation cases
  and produce valid outputs without seeing expected conclusions.

## Constraints and Assumptions

- `REVIEW.md` remains plain freeform Markdown in v1; this skill adds no
  frontmatter, import, or override syntax.
- The skill analyzes the current filesystem. Historical or pull-request review
  guidance remains the responsibility of `project-review` or a future adapter.
- The resolver intentionally duplicates only the small current-filesystem
  hierarchy contract needed for independent installation. Shared extraction is
  deferred until a third real consumer justifies it.
- Context size has no universal semantic threshold. The result records source
  and effective-chain measurements and lets the reviewer weigh relevance,
  fanout, and potential savings.

## Out of Scope

- Editing or automatically applying guidance or harness changes.
- General test-suite, CI, lint, or harness audits unrelated to a proposed
  `REVIEW.md` improvement.
- GitHub reads, comments, reviews, approvals, merges, or storage integration.
- Git history, pull-request diff, or trusted-base change review.
- A machine-readable metadata format inside `REVIEW.md`.
- Automatically converting recurring review pain points into policy.

## Future Extensions

- Accept optional, storage-neutral canonical evidence describing recurring pain
  points and harness gaps from review-and-fix cycles. An upstream adapter will
  retrieve and normalize repository-, GitHub-, or system-stored data; this skill
  will not know where the data lives.
- Bind future evidence to the caller-selected repository and scope, preserve
  provenance and freshness, treat it as untrusted supporting evidence, and
  classify observations before suggesting guidance. Historical evidence will
  never retarget the audit or become policy automatically.
- Keep storage adapters and a general harness-audit skill separate from this
  skill.

## Dependencies

- Python 3.11 or newer for deterministic helpers.
- Optional Git only for honoring tracked and ignored-file boundaries during
  broad current-filesystem discovery; explicit file targets remain usable
  without Git.
