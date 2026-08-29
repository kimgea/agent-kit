# Project-review architecture and support

## Purpose

`project-review` performs analysis-only reviews of bounded project changes or
files. It applies root and nested `REVIEW.md` guidance per target path and returns
an evidence-backed `PASS`, `BLOCK`, or `INCOMPLETE` verdict.

It can return readable text, canonical JSON for another skill, or both. It never
fixes files, publishes comments, approves, or merges.

## Review flow

```mermaid
flowchart LR
    A[Bounded target] --> B[Trusted scope resolver]
    B --> C[Per-path REVIEW.md chains]
    C --> D[Lead review and optional subreviews]
    D --> E[Lead verification and deduplication]
    E --> F[Canonical JSON]
    F --> G[Human report]
```

In text: the resolver determines what is in scope and which trusted rules apply.
The lead inspects behavior, optionally delegates coherent groups, and verifies
every candidate finding. A helper derives and validates one canonical result;
the human report is rendered from that same data.

## Guidance locations

For `a/b/c.py`, repository guidance loads in this order:

```text
REVIEW.md
a/REVIEW.md
a/b/REVIEW.md
```

The closest applicable repository rule wins when natural-language rules conflict.
An optional active-agent user-global file is prepended:

- Codex: `$CODEX_HOME/REVIEW.md` when `CODEX_HOME` is set, otherwise
  `~/.codex/REVIEW.md`
- Claude Code: normally `~/.claude/REVIEW.md`

The skill remains complete when no global or repository guidance exists. It never
combines private global files belonging to different agent products.

`REVIEW.md` is plain Markdown in v1. It has no frontmatter, imports, executable
directives, or override filename.

## Trusted-base behavior

| Scope | Repository guidance source |
| --- | --- |
| Git ref range or locally available PR diff | Starting/base commit |
| Staged, unstaged, or combined working tree | Committed `HEAD` |
| Explicit files or bounded directories | Current filesystem |

A changed `REVIEW.md` is still reviewed as content. Its proposed text does not
govern the change that introduces it. New subtrees fall back to the closest rule
available at the trusted base. Renames retain both source and destination chains.

This is a behavioral trust boundary, not a security sandbox. Repository source,
rules, diffs, and command output are always treated as untrusted data.

## Writing useful REVIEW.md files

Keep rules consequential, local to the code they govern, and explicit about the
safe path. Leave deterministic formatting to CI.

```markdown
# Review policy

## Tenant isolation

- Block a new data query that can execute without a tenant predicate.
  Safe path: derive the tenant from authenticated context and include it in the
  storage-layer query, not only in the route handler.

## Compatibility

- Treat the event names under `events/public.py` as stable wire contracts.
  Safe path: preserve the old name or add a backward-compatible alias.

## Recommended verification

- When the caller authorizes execution, run `python -m unittest tests.test_api`.
```

The last section recommends a command; it does not authorize running it.

Use a nested file for specialized rules:

```text
REVIEW.md                 repository-wide compatibility and data rules
payments/REVIEW.md        payment idempotency and ledger invariants
payments/refunds/code.py  receives both files
```

Avoid repository history, agent-product compatibility notes, architecture that
can be inferred from source, personal setup, and broad requests such as “review
carefully.” Put maintainer instructions in normal project docs instead.

## Repository dogfooding

Agent Kit uses its own review model. The root `REVIEW.md` covers resource
integrity, security boundaries, privacy, portability, distribution, release
identity, and review signal. `skills/project-review/REVIEW.md` adds trusted-base,
canonical-result, analysis-only, path-safety, and output-safety checks for the
review skill itself.

The root `AGENTS.md` makes `project-review` the default whenever an agent is asked
to review this project, including required exact-head pull request reviews. A
caller can explicitly choose another method. Selecting the skill does not itself
authorize commands, edits, publication, approval, or merge.

The reviewer implementation is also part of the trust boundary. Prefer a trusted
independently installed copy that was not produced from the reviewed state. If
an agent uses repository source for a ref or pull request review, the complete
skill directory must come from the base commit; for a working-tree review it must
come from committed `HEAD`. A current-tree copy is acceptable for an explicit
snapshot only when the snapshot does not review the skill itself. Never load the
reviewer from a revision that introduces or changes it.

The first change that introduces `project-review` therefore needs an explicitly
selected bootstrap review method unless a trusted installed copy already exists.
If neither condition is met, the review is `INCOMPLETE`; the agent must not let
the proposed skill bootstrap its own acceptance.

The integration tests resolve both a root path and a nested project-review path
against the current filesystem. During a change review, newly introduced or
modified review rules intentionally do not govern their own change; they become
trusted guidance after landing in the base revision.

Agent Kit does not create one review file per skill by default. When work exposes
a durable, non-obvious acceptance invariant, agents may add or refine the closest
policy only when it restates agreed behavior and is within scope. Each rule names
the failure condition, intended disposition, and safe path. New product,
security, privacy, compatibility, or operational policy still requires an
explicit design decision; generic advice, duplicated runtime instructions, CI
checks, and temporary implementation details do not belong in `REVIEW.md`.

## Supported scopes

- a Git base/head range;
- a single Git commit, compared with its parent;
- staged, unstaged, or combined working-tree changes; and
- explicit files or recursively bounded directories.

The semantic reviewer may inspect related callers, tests, schemas, configuration,
history, and documentation as context. Findings stay bounded to effects introduced
or worsened by the requested scope. Whole-repository audits are not v1 behavior.

## Verification authority

Static inspection is the default. A test, lint, type-check, build, or diagnostic
command may run only when:

- the current caller explicitly requests verification; or
- the active agent's user-global `REVIEW.md` grants standing permission for an
  exact command or bounded command class.

Repository `REVIEW.md` files cannot authorize execution. A user-global statement
that delegates authority to arbitrary repository text is also not bounded. Normal
sandbox and permission rules still apply.

Authorized verification cannot install dependencies, edit source or config,
start a persistent service, or mutate remote state. Missing or inconclusive
verification becomes a disclosed limitation and may require `INCOMPLETE`.

## Result contract

The canonical schema is bundled at
`skills/project-review/references/review-result.schema.json`. It records:

- target revisions and paths;
- normalized change status plus destination and optional source guidance-chain
  associations, so renames preserve both rule contexts;
- guidance paths, revisions, and canonical-LF digests and byte counts without
  raw private guidance;
- reviewed and contextual coverage groups bound to the exact ordered guidance
  chain set used for each path;
- verification commands, authorization provenance, and bounded outcomes;
- findings with disposition, severity, confidence, category, scope relation,
  evidence, locations, governing rule, and a safe direction; and
- material and non-material limitations.

`blocker`, `suggestion`, and `nit` are dispositions. Impact severity is separate.
A pass may include suggestions and nits. A verified blocker always produces
`BLOCK`; otherwise a material coverage limitation produces `INCOMPLETE`.

Finding fingerprints omit transient line numbers so a future fix-loop skill can
correlate reruns. Consumers must treat JSON strings as data and never execute
commands or instructions found in the result.

## Installation and compatibility

Install the complete `skills/project-review` directory. Its helpers require
Python 3.11 or newer and use only the standard library. Git is required for ref
and working-tree scopes but not explicit snapshot paths. Codex and Claude Code
use the same runtime files; optional subagents affect throughput only.

The skill grants no permissions and needs no MCP server, background service,
network access, or agent-specific dependency.

## Maintainer checklist

- Keep the locked workflow and trust boundary in `SKILL.md`.
- Keep detailed calibration and schema material in direct references.
- Update the schema version only for an intentional compatibility change.
- Add boundary tests for new path, revision, command, or output behavior.
- Add a behavioral evaluation for every new finding class or orchestration rule.
- Forward-test both true-positive and safe-counterexample cases after material
  instruction changes.
