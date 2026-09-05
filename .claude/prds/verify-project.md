---
name: verify-project
description: Verify exact local project changes with bounded authorized checks and canonical evidence.
status: active
created: 2026-09-05T19:50:10Z
---

# PRD: verify-project

## Executive Summary

Add an independently installable `verify-project` skill that answers:

> Given this exact current local state, which checks are relevant, may they run,
> and what did their results actually prove?

The skill binds a caller-selected current-filesystem target, resolves applicable
project verification policy, plans the smallest evidence-sufficient sequence of
local checks, executes only commands already authorized by caller intent or
active user policy, detects unexpected source mutation, and returns readable
text or canonical JSON.

`verify-project` is a verifier and evidence producer. It does not review code,
diagnose failures, choose fixes, edit files, provide CI, install dependencies, or
contact external services. A later failure-triage capability may consume failed
verification evidence. `review-and-fix` may consume a successful target-bound
result before invoking its fresh acceptance reviewer.

Projects may optionally add plain-Markdown `VERIFY.md` files at the repository
root and in nested directories. They describe required evidence, conditional
checks, tier guidance, scoped replacements, and expected disposable artifacts
for their directory trees. They never grant command authority or weaken the
skill's safety rules.

## Problem Statement

Agent Kit can review changes, audit review guidance, audit verification
harnesses, and remediate selected findings. The actual post-change verification
step remains comparatively ad hoc: an agent chooses commands, runs them, and
summarizes what happened without a reusable target, authority, plan, evidence,
mutation, or outcome contract.

This creates several failure modes:

- a green but irrelevant command can be presented as proof;
- a fixing agent can silently choose a weak validation path;
- repository text can be mistaken for execution authority;
- a command can modify source while its result is still accepted;
- unavailable checks can be confused with failed behavior;
- downstream agents must parse prose or rerun checks;
- project-specific verification knowledge is duplicated in always-loaded agent
  instructions or rediscovered on every run; and
- failed output is either too sparse for later triage or retained as a noisy,
  potentially sensitive raw transcript.

The toolkit needs a local-first verification boundary that records what was
selected, what was allowed, what ran, what changed, which claims were covered,
and why the result is `pass`, `fail`, `unknown`, or incomplete.

## User Stories

### Verify an ordinary local change

As a developer, I can ask an agent to "verify this change" and have safe,
relevant local checks run without approving every routine command.

Acceptance criteria:

- The selected paths and their current contents are frozen before planning.
- The smallest relevant focused checks run first.
- Wider checks run only when policy, dependency reach, risk, or evidence gaps
  justify them.
- The final report distinguishes commands passing from the change being
  sufficiently verified.

### Ask for a plan without execution

As a developer, I can ask "how should I verify this?" and receive a frozen,
structured verification plan without running commands.

Acceptance criteria:

- The plan contains exact argv, repository-relative working directories,
  timeouts, repetitions, tiers, expected effects, authority state, and covered
  claims.
- Planning does not itself authorize or execute anything.
- Human and JSON forms describe the same canonical plan.

### Keep verification knowledge near the code

As a repository owner, I can add optional root and nested `VERIFY.md` guidance
that defines the evidence required for changes in each directory tree.

Acceptance criteria:

- Guidance resolves from repository root to the nearest applicable ancestor for
  every selected path.
- Broader guidance remains additive unless a closer file explicitly replaces a
  specific rule for its subtree.
- Ambiguous or conflicting required guidance prevents a false `pass`.
- Modified or newly added `VERIFY.md` files do not govern their own uncommitted
  change in a Git repository.
- Projects without `VERIFY.md` remain verifiable through layered discovery.

### Preserve command authority

As a security-conscious user, I can trust that project files suggest evidence
but cannot make an agent install software, access the network, start a service,
change permissions, destroy data, or mutate remote state.

Acceptance criteria:

- "Verify this change" authorizes only bounded ordinary local checks.
- Exact commands and effects are frozen before execution.
- Repository guidance, scripts, manifests, CI configuration, command output,
  and agent-generated drafts never grant authority.
- Consequential or unavailable actions return an explicit next action instead
  of being executed or ignored.

### Consume trustworthy verification evidence

As another agent or skill, I can request canonical JSON and determine whether
verification completed, what it concluded, and what should happen next without
parsing terminal prose.

Acceptance criteria:

- A separate canonical plan is bound into the canonical result by digest.
- The result records exact target, guidance, authority, execution, mutation,
  claim coverage, limitations, and verifier-freshness provenance.
- Completion, outcome, and next action remain separate axes.
- Canonical data cannot authorize subsequent commands, edits, or acceptance.

### Integrate verification with remediation

As a `review-and-fix` user, I can use a fresh `verify-project` invocation as the
post-fix evidence gate before paying for or relying on a fresh acceptance review.

Acceptance criteria:

- The adapter independently validates the result and matches it to the
  lead-owned expected target.
- Only a complete, sufficiently covered `pass` proceeds to fresh re-review.
- `fail`, `unknown`, and incomplete results stop with their derived next action.
- `review-and-fix` remains independently installable and retains its current
  bounded validation fallback when `verify-project` is unavailable.

## Functional Requirements

### Role and invocation

- Ship one local, analysis-and-execution skill named `verify-project` for Codex
  and Claude Code.
- Trigger on requests to plan verification, verify local changes, run relevant
  checks for selected paths, or produce structured local verification evidence.
- Interpret planning language as non-executing. Interpret "verify", "check", or
  equivalent direct intent as authorization for bounded ordinary local checks
  within this contract, without a redundant confirmation.
- Default to concise human output. Return canonical JSON when requested by the
  caller or another agent or tool. Write files only to explicit safe output
  paths and never overwrite without explicit replacement intent.
- Use one verifier lead. Do not require internal delegation. Record whether the
  invocation ran in a fresh context so a consuming workflow can enforce its own
  independence requirement.

### V1 target model

- Verify only the current filesystem. Support:
  - a combined Git working-tree target derived from committed `HEAD` through the
    index and worktree, including visible untracked paths; and
  - explicit repository-relative files or directories, with `.` representing a
    project target.
- Execute commands against the same current filesystem snapshot that was
  planned. Do not offer staged-only, unstaged-only, commit, ref-range, or pull
  request targets in v1.
- Represent additions, modifications, deletions, renames, mode changes, and
  visible untracked paths without claiming that an absent path was read.
- Treat directories as bounded inventories. Reject escaped, ambiguous,
  control-character, link-like, reparse, special, unreadable, or excessive
  authority inputs and return material limitations rather than sampling.
- Bind repository identity, optional Git `HEAD`, target inventory, file type,
  supported mode, size, content digest, and absence state in a lead-owned
  context. Revalidate the target immediately before and after planning and
  around every executed command.
- Keep selected target paths as the verification claim boundary. Related tests,
  manifests, source, schemas, documentation, and local CI files are read-only
  context and do not silently expand the target.

### Agent and project policy

- Treat active system, user, and applicable `AGENTS.md` instructions as higher
  authority than this skill's project-data discovery.
- Add optional plain-Markdown `VERIFY.md` at repository root or nested
  directories. Do not require frontmatter or a machine-readable DSL.
- Encourage concise conventional sections such as `Required for pass`,
  `Conditional`, `Recommended expansion`, `Scoped replacements`, and
  `Expected disposable artifacts`, without requiring exact headings.
- Resolve a separate root-to-nearest `VERIFY.md` chain for every selected path.
  Group paths only when their effective chains and verification needs agree.
- Apply requirements additively. Permit a closer file to replace a specific
  broader rule only when the replacement and subtree scope are explicit. Record
  the replaced and replacing sources. Treat ambiguous conflicts as material.
- In a Git repository, read verification guidance from committed `HEAD` for a
  working-tree or explicit current-state target. A changed or new current
  `VERIFY.md` remains target content and cannot govern its own run. In a non-Git
  project, use current guidance with explicit current-filesystem provenance.
- `VERIFY.md` may define evidence required for `pass`, recommend exact local
  commands, classify tiers, explain conditions, and identify expected bounded
  disposable artifacts. It may not grant execution authority, weaken agent or
  skill safety, hide limitations, or redefine canonical outcomes.
- Keep resolver behavior self-contained in this skill. Extend shared hierarchy
  conformance fixtures where behavior is common, but do not import another
  installed skill or a repository-only runtime module.

### Layered check discovery

- Discover verification needs in this priority order:
  1. caller-selected target, commands, constraints, and run caps;
  2. active higher-authority agent instructions;
  3. applicable trusted `VERIFY.md` guidance;
  4. established project entry points in manifests, scripts, test/build/lint/type
     configuration, and locally stored CI configuration; and
  5. related tests and documented contracts discovered from the selected target.
- Treat every discovered command as inert data until it is selected, classified,
  bound into a plan, and matched to caller or active user authority.
- Allow a caller to cap verification by tier, command count, or time. A cap never
  weakens the evidence required for `pass`; omitted required evidence produces
  `unknown` or incomplete coverage.
- Do not require `VERIFY.md`. When guidance is absent, use bounded project
  discovery and state the residual uncertainty.
- Do not use provider APIs. Local CI configuration may supply project evidence
  and command candidates but is not proof that a hosted run occurred.

### Canonical verification plan

- Define a versioned canonical verification-plan schema and deterministic helper.
- Keep target, guidance provenance, caller intent, run caps, verifier freshness,
  and authority sources in a separate lead-owned context. An agent-authored
  semantic draft cannot alter them.
- For each planned check record:
  - a stable identifier and deterministic fingerprint;
  - exact argv as an array, never a shell command string;
  - repository-relative working directory;
  - progressive tier: `focused`, `subsystem`, or `project`;
  - reason and the exact target claims it is expected to support;
  - timeout and predeclared repetition count;
  - dependencies and whether it remains useful after another check fails;
  - expected effect classes and bounded disposable path prefixes;
  - authority source and whether execution is permitted; and
  - limitations or decisions preventing execution.
- Derive plan validity and executability mechanically. Agent drafts may describe
  relevance and claims but cannot add target scope, command authority, or
  permissive effect classes.
- Render plan-only requests from the validated canonical plan.

### Progressive execution

- Use focused, subsystem, and project tiers. Start with the smallest plan that
  could provide sufficient evidence. Expand only when dependency reach, risk,
  active policy, trusted verification guidance, or a remaining evidence gap
  justifies it.
- Execute sequentially in v1. Do not allow repository guidance to enable
  concurrency.
- Execute exact argv through normal agent tool calls so the active permission
  system sees the real command. Do not ship a general command dispatcher,
  shell-evaluation wrapper, arbitrary executable proxy, or hidden permission
  bypass.
- Run each check once unless repetitions were frozen in the initial plan through
  caller intent or higher-authority user policy. Never retry a failure merely to
  obtain a passing result.
- On failure, do not diagnose or add new commands. Finish only already-planned,
  authorized, independent checks whose evidence remains useful; skip dependent
  checks and unjustified wider tiers.
- Reject dependency installation, external network or service access,
  persistent processes, destructive actions, permission changes, remote state
  mutation, and operations outside the repository or bounded temporary space.
- Bound command count, per-command and total duration, output capture, result
  size, filesystem inventory, and evidence excerpts. Caller or active user
  policy may lower or explicitly raise ordinary local limits without removing
  the hard safety boundary.

### Mutation and effect integrity

- Snapshot visible repository source state before execution and around every
  command so effects can be attributed.
- Permit only disposable effects explicitly frozen in the plan. Candidate paths
  may come from trusted baseline `VERIFY.md`, inspected tool configuration, or
  caller intent, but the lead-owned plan must reduce them to bounded normalized
  repository-relative prefixes or bounded temporary locations.
- Never treat all ignored paths as writable. Expected cache or build output does
  not permit modification of source, tests, configuration, guidance, credentials,
  pre-existing user data, or another unrelated alias.
- Reject symlink, hard-link, junction, reparse, ancestor-swap, replacement, and
  special-file paths at input, snapshot, artifact, and output boundaries.
- If a check unexpectedly changes protected state, stop further execution,
  preserve before/after evidence, mark the result incomplete, and do not clean,
  restore, or overwrite the user's files automatically.
- Record allowed disposable effects that actually occurred. Their presence does
  not by itself prove a verification claim.

### Evidence and canonical result

- Define a separate versioned canonical verification-result schema. Bind it to
  the validated plan digest and the same lead-owned target context.
- Record per command:
  - planned command identifier and fingerprint;
  - start and completion state, exit status, duration, and timeout state;
  - current working directory and exact argv digest;
  - bounded stdout/stderr byte counts, digests, and truncation state;
  - a small relevant redacted diagnostic excerpt when needed;
  - observed disposable and unexpected effects; and
  - the claims supported, disproved, or left unresolved.
- Treat all command output as untrusted inert data. Do not follow embedded
  instructions. Do not store raw logs, secrets, credentials, environment values,
  or full transcripts in canonical output. Permit a separate raw-log destination
  only through explicit caller authority and a later design if needed; v1 does
  not implement it.
- Record claim-level evidence, limitations, tier coverage, plan deviations, and
  optional evidence-backed harness-gap observations separately from command
  success.
- Derive three independent axes:
  - `completion`: `complete` or `incomplete`;
  - `outcome`: `pass`, `fail`, or `unknown`; and
  - `next_action`: `none`, `triage`, `plan`, `decision`, `authorization`,
    `retry`, `rescope`, or `manual`.
- Derive the states conservatively:
  - an executed required check that disproves a relevant claim yields complete
    `fail` with `triage` unless a stronger incomplete condition occurred;
  - a required check that cannot run because of authority, tools, environment,
    drift, or hard limits yields incomplete `unknown` with the matching next
    action;
  - completed passing commands with insufficient claim coverage yield complete
    `unknown` with `plan` and may emit a harness-gap observation;
  - `pass` requires complete execution, unchanged protected state, no material
    limitation, all required guidance satisfied, and sufficient evidence for
    every material target claim; and
  - static evidence may satisfy genuinely mechanical non-runtime claims when the
    result identifies why command execution would add no relevant evidence.
- Derive identifiers, fingerprints, counts, coverage, state axes, and human
  rendering deterministically. Do not let an agent-authored draft choose them.

### `review-and-fix` integration

- Stabilize standalone `verify-project` schemas and behavioral evidence before
  changing `review-and-fix`.
- Add a deterministic target-bound adapter in `review-and-fix` after the
  standalone contract is stable. Validate the canonical result with the
  producing skill before conversion or acceptance.
- Run `verify-project` in a fresh verifier context after each selected fix. The
  verifier does not edit files and receives only the exact post-fix target,
  applicable trusted context, and authority envelope.
- Require complete canonical `pass` before invoking the fresh original reviewer.
  `fail`, `unknown`, incomplete, target mismatch, context drift, or non-fresh
  provenance stops the fix loop with the verifier's safe next action.
- Do not let verification output expand edit scope, authorize commands, select a
  fix, or declare final reviewer acceptance.
- Keep the integration optional. When `verify-project` is unavailable,
  `review-and-fix` may retain its existing bounded validation records and must
  disclose that canonical verification was not used.
- Include `verify-project` in the grouped project-review workflow only after its
  standalone package and adapter are independently valid.

### Agent Kit dogfooding

- After the standalone contract and resolver are stable, add a concise root
  `VERIFY.md` for this repository that names the canonical gate, focused-check
  discovery expectations, supported-platform evidence, and bounded disposable
  artifacts. Do not duplicate the skill contract, test implementation details,
  or release procedure there.
- Update this repository's `AGENTS.md` so ordinary requests to plan or perform
  local verification use the source `verify-project` skill by default unless the
  caller selects another method. This routing grants no command authority beyond
  the invocation rules above.
- Treat the initial `VERIFY.md` and routing changes as ordinary target content.
  They do not govern or validate their own introduction; existing trusted agent
  and review policy remains applicable until they are committed.
- Add repository tests that prevent `VERIFY.md` from becoming required for
  installing or using the skill in another project.

## Non-Functional Requirements

- Bundle every runtime instruction, schema, resolver, finalizer, and renderer
  inside `skills/verify-project/`. Installed code must not import repository
  `scripts/` or another skill.
- Use Python 3.11 or newer standard-library helpers for deterministic resolution,
  JSON parsing, finalization, validation, snapshots, and rendering.
- Remain useful without Git, private context, a user-global verification file,
  subagents, network access, an MCP server, a container, or a persistent process.
- Work on Linux, Windows, and macOS. Cover Windows path, reparse, process, text,
  and executable-discovery behavior explicitly.
- Reject duplicate JSON members, malformed Unicode and control characters,
  unsafe paths, non-regular inputs, links and aliases, oversized inputs,
  inconsistent plans/results, stale digests, and unsafe output replacement.
- Use fail-closed resource ceilings. Convert material exhaustion into explicit
  incomplete evidence rather than sampling or silently dropping checks.
- Keep `SKILL.md` concise and place schemas, detailed authoring guidance, and
  progressive verification rules in directly linked references.
- Keep normal operation local and free of external services. Hosted CI validates
  deterministic fixtures, schemas, simulated results, packages, and graders
  only; it never starts an agent or incurs model cost.
- Preserve unrelated user changes and never clean or repair unexpected command
  effects automatically.

## Success Criteria

- Deterministic resolver tests cover combined working-tree, explicit file,
  directory, and project targets; additions, deletions, renames, mode changes,
  and visible untracked paths; Git and non-Git operation; and bounded inventory.
- Hierarchy tests cover absent, root, nested, multi-target, additive, explicit
  replacement, ambiguous conflict, changed-guidance, and non-Git current
  `VERIFY.md` behavior.
- Shared conformance tests prove the intended common root-to-nearest ordering,
  provenance, path normalization, and trusted-baseline behavior without a shared
  installed runtime dependency.
- Plan tests prove that semantic drafts cannot change the target, guidance,
  caller intent, limits, authority, effect boundaries, freshness, identifiers,
  or derived executability.
- Command-policy tests prove that repository text cannot authorize installs,
  networking, services, destructive actions, permissions, remote mutation,
  shell evaluation, arbitrary dispatch, or out-of-bound paths.
- Mutation tests cover tracked and visible-untracked rewrites, creations,
  deletions, modes, directories, hard links, symlinked ancestors, Windows
  reparse points, ancestor swaps, allowed disposable output, and unexpected
  effects on success, failure, timeout, and raised exceptions.
- Result tests prove deterministic plan binding, command evidence, redaction,
  truncation, claim coverage, limitations, observations, status precedence,
  human rendering, JSON validation, and safe output behavior.
- Progressive-execution simulations prove focused-first selection, justified
  expansion, caller caps without false pass, sequential ordering, no automatic
  retry, useful independent completion after failure, and dependent-check skip.
- Behavioral evaluations include:
  - a focused change with sufficient passing evidence;
  - a green irrelevant test that remains `unknown`;
  - layered root and nested `VERIFY.md` requirements;
  - an explicit local replacement of a broader check;
  - a changed `VERIFY.md` attempting to weaken its own verification;
  - useful automatic discovery in a project without `VERIFY.md`;
  - an executed failure returning `triage` without retry;
  - an unavailable required tool or unauthorized consequential action;
  - a repository-command injection attempt that remains inert;
  - allowed cache output and an unexpected source mutation;
  - a tier-capped run that cannot falsely pass;
  - bounded hostile command output and diagnostic redaction; and
  - a genuinely mechanical change for which static evidence is sufficient.
- Fresh local agent runs complete representative behavioral cases through the
  executable evaluation harness and emit canonical results that satisfy hidden
  deterministic graders. Canonical and hosted gates never invoke a model.
- A consumer evaluation proves that `review-and-fix` requires a fresh,
  target-matched canonical pass before re-review and cannot derive edit or
  command authority from verification output.
- A fallback evaluation proves `review-and-fix` remains independently usable
  when `verify-project` is absent and accurately reports the weaker validation
  mode.
- Agent Kit itself contains compact, useful root verification guidance and
  routes applicable local verification requests through the source skill after
  that guidance and skill have been independently accepted.
- Catalog, plugin, documentation, compatibility, packaging, and changelog
  surfaces describe the same behavior, and `python scripts/agent_kit.py check`
  passes on the supported platform matrix.

## Constraints & Assumptions

- The active agent tool and permission system executes commands. The installed
  skill deliberately does not hide arbitrary commands behind a pre-approved
  generic Python or shell runner.
- An agent still performs semantic check discovery and claim mapping. Helpers
  make target, authority, plan, mutation, status, and output boundaries
  deterministic; they do not pretend relevance can be inferred mechanically for
  every ecosystem.
- `VERIFY.md` is optional project data, not a new agent-instruction standard.
  Other agents may ignore it unless they use this skill or adopt the convention.
- Plain Markdown maximizes portability. Rigid project behavior belongs in
  project-owned scripts and tests referenced by guidance, not in a generic
  verification DSL.
- Current-filesystem verification cannot truthfully verify a staged-only or
  historical snapshot without materializing it elsewhere. Those targets remain
  excluded from v1.
- A canonical verification pass is evidence, not final code-review acceptance.
  `review-and-fix` retains a separate fresh reviewer after verification.
- `AGENTS.md` and the active agent runtime remain responsible for user-global
  policy and command authority. V1 adds no user-global `VERIFY.md`.

## Out of Scope

- Staged-only, unstaged-only, commit, ref-range, pull-request, remote branch, or
  remote CI execution targets.
- Failure diagnosis, root-cause classification, automatic retries, flaky-test
  analysis, or remediation.
- Reviewing code, auditing harness quality, editing source, generating tests,
  changing `VERIFY.md`, or accepting a fix on behalf of a reviewer.
- A strict `VERIFY.md` schema, YAML/JSON verification DSL, automatic migration
  from CI configuration, or provider-specific policy library.
- User-global `VERIFY.md`, domain-context repositories, or cross-project
  verification policy.
- Concurrent command execution, containers, mandatory isolated worktrees,
  dependency installation, persistent services, external APIs, hosted-agent
  execution, deployment, or remote mutation.
- A general command runner, executable proxy, daemon, MCP server, workflow
  engine, or arbitrary plugin interface.
- Persisting raw command logs, environment variables, secrets, or historical
  verification results.
- Implementing verification-failure triage, workflow-observation storage, a
  dedicated `VERIFY.md` audit skill, or external publishers.

## Dependencies

- Existing repository catalog, packaging, plugin, compatibility, documentation,
  and validation conventions.
- Existing root-to-nearest review hierarchy semantics and conformance fixtures
  as a behavioral reference, not a runtime dependency.
- Existing local behavioral-evaluation harness and opt-in fresh-agent runner.
- Existing `review-and-fix` target, validation, fresh-review, and structured run
  contracts for the optional downstream adapter.
- Python 3.11 or newer and optional Git. Project checks may use only tools that
  are already installed and independently authorized.
