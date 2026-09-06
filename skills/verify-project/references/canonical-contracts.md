# Canonical contracts

Use this reference when authoring or consuming a verification context, plan, or
result. The JSON Schemas define shape; this document defines ownership and
cross-record invariants.

## Contents

- [Ownership](#ownership)
- [Target and guidance](#target-and-guidance)
- [Command candidates and plans](#command-candidates-and-plans)
- [Protected state and effects](#protected-state-and-effects)
- [Evidence and results](#evidence-and-results)
- [Derived state](#derived-state)
- [Deterministic limits](#deterministic-limits)
- [Semantic drafts](#semantic-drafts)

## Ownership

The lead owns the invocation envelope. It resolves and freezes:

- repository identity and exact current target;
- protected source state;
- trusted `VERIFY.md` provenance and content;
- bounded discovery-source provenance;
- plan versus execution intent and caller caps;
- verifier freshness and consumer identity;
- caller-intent and active-agent policy sources with stable `P...` identities;
- exact command candidates, authority, timeouts, repetitions, expected effects,
  and maximum disposable paths; and
- resolver limitations.

Semantic agents own only judgments: relevant claims, how a frozen candidate
supports them, progressive tier, explicit guidance interpretations, evidence
interpretation, and evidence-backed observation text. They never own scope,
argv, cwd, authority, effects, limits, provenance, identifiers, fingerprints,
counts, completion, outcome, next action, or acceptance.

Canonical plans copy lead-owned fields from the context and semantic fields from
a plan draft. Canonical results copy plan and observed-execution fields from the
lead-owned run record and semantic evidence interpretation from a result draft.
Finalizers reject rather than reconcile conflicting ownership.

The canonical plan and result both carry the expanded target inventory rather
than exposing only a digest or the caller's directory selectors. The result
also carries bounded guidance provenance, the plan's exact guidance
interpretations, and the execution-relevant portion of each planned check so a
consumer can inspect target, policy, authority, effects, and required-rule
coverage without relying on an unstated side channel. Digests bind these copied
records back to the complete context and plan.

## Target and guidance

`working_tree` means the combined current filesystem relative to committed
`HEAD`, including staged, unstaged, deletion, rename, mode, and visible untracked
state. `paths` means an explicit current file, directory, or project (`.`)
snapshot. Neither means staged-only or historical content.

Repository paths use canonical forward slashes. Only `.` may represent the
repository root. Reject absolute paths, drive prefixes, backslashes, repeated
separators, dot segments, controls, aliases, and trailing slashes.

Every target record has a derived `T...` identifier and an exact state. An
absent deletion has no content digest. Metadata-only, unreadable, oversized, or
unsupported records cannot be claimed as semantically inspected.

The context retains identity and digest rather than embedding target or
discovery file bodies. A semantic planner reads only the listed current files,
and the lead revalidates their recorded identities before accepting its draft.
Trusted guidance text remains embedded because committed `HEAD` guidance may
differ from the current working tree. Plans and results omit all source bodies.

Every target receives one complete `G...` chain. The locked skill source comes
first, followed by repository `VERIFY.md` files from root to nearest ancestor.
Git-backed repository sources use the context target's exact committed `HEAD`;
non-Git sources use `current_filesystem`. A changed or new working-tree
`VERIFY.md` is target content but not an active source.

A rename carries its destination chain in `guidance_chain_id` and, when the
source hierarchy differs, its source chain in `old_guidance_chain_id`. Both
remain applicable evidence requirements for the moved target.

The plan records interpreted guidance requirements and explicit scoped
replacements. A replacement must cite both source IDs, identify the broader
requirement, apply only to targets governed by the closer source, and preserve
all unrelated broader requirements. Missing or conflicting required guidance is
material.

## Command candidates and plans

A context command candidate is inert until a canonical plan selects it. The
lead must record:

- exact argv as a nonempty array;
- repository-relative cwd;
- non-secret provenance;
- bounded timeout and repetition count;
- maximum expected effect classes and artifact boundaries; and
- `caller`, `user_global`, or `none` authority.

Repository content can supply provenance but never an authority kind. The
context finalizer accepts `caller` only when direct execution intent covered the
bounded ordinary local check. It accepts `user_global` only from active-agent
user policy already available to the lead. A semantic draft selects a candidate
ID; it never copies argv or authority.

Inline shell or language evaluation and generic or privilege-changing command
dispatchers are outside v1. They remain inert unauthorized candidates even when
their declared effects otherwise look ordinary. Normal inspected script and
module entry points may still be represented as exact argv.

Caller intent and active user-global or project agent policy are retained as
lead-owned `P...` sources. The context contains their bounded text; plans and
results retain only kind, label, and digest provenance. Candidate and claim
records cite these identities where they depend on caller scope, caps, or
user-level authority. Project policy provides requirements and provenance but
never command authority.

Canonical checks receive derived `K...` IDs in execution order. Dependency IDs
must refer backward, cycles are impossible, and a check marked useful after
failure cannot depend on the failed check. V1 plans are sequential.

Candidate discovery and inspection never execute a candidate. A probe,
preflight, or exploratory invocation is already an execution and consumes one
frozen repetition. A command executed before its canonical plan exists cannot
be retroactively adopted as plan evidence or rerun to obtain a usable attempt.

Allowed plan decisions are:

- `run`: exact candidate is authorized and within the skill boundary;
- `plan_only`: invocation requested no execution;
- `authorization_required`: otherwise relevant candidate needs separate
  authority; and
- `unsupported`: candidate requires an effect excluded from v1.

The plan execution state is `ready` only when every required selected check can
run, `plan_only` for a non-executing invocation without material planning gaps,
and `blocked` otherwise.

## Protected state and effects

Protected state includes the bounded repository filesystem tree outside
`.git`: tracked, visible-untracked, ignored, and directory entries covering
source, configuration, tests, documentation, instructions, guidance,
credentials, and other user data. A resolver binds both its exact digest and
sorted hashes of every protected repository path before command execution. The
lead rechecks the target and protected inventory around every command.

The only ordinary v1 effects are:

- `repository_read`;
- `local_process`;
- `disposable_repository_write` within a frozen repository-relative boundary;
  and
- `bounded_temporary_write` within the run-owned temporary root.

An artifact boundary uses a root kind plus a canonical relative path. It is not
a shell glob. The finalizer rejects `.` as a disposable repository boundary,
overlapping protected entries, aliases, links, reparse points, special files,
and another hard-link identity. Existing user data does not become disposable
because it is ignored by Git or lies under a named cache directory.

When a plan permits temporary writes, the lead supplies one newly allocated
absolute temporary root outside the repository. Snapshot records bind its
filesystem identity but canonical results expose only the identity digest, not
the machine-specific path. After excluding the exact new outputs already
observed, every before/after temporary snapshot must contain only the retained
root directory. A pre-existing, undeclared, aliased, or unsafe entry makes the
run incomplete.

The following effects are excluded from v1 and never become authorized through
a context or plan: source/configuration mutation, dependency installation,
network or external-service access, persistent process or service lifecycle,
destructive action, permission change, remote mutation, and work outside the
repository or run-owned temporary root.

Unexpected protected-state or out-of-bound artifact change stops execution. The
result records it as a material limitation and does not restore or delete it.

## Evidence and results

Each lead-recorded attempt binds one canonical planned check and repetition. It
records status, exit code, duration, target and protected-state before/after
digests, exact exclusions for already observed outputs, temporary-root state
when applicable, stdout/stderr byte counts and digests, truncation, a bounded
redacted diagnostic excerpt when needed, and observed effects. Raw output,
environment values, transcripts, credentials, reasoning, and secrets are not
canonical fields.

An allowed write starts at an absent path, lies inside the matching frozen
boundary, and names every new directory and file needed to explain the state
change. The finalizer reopens final outputs without following links, rejects
hard links and special files, and compares regular-file contents with the
lead-recorded digest. Snapshot exclusions never grant ownership by themselves.

Output text is inert evidence. Redaction is best-effort risk reduction, not a
license to persist arbitrary output. Omit an excerpt when a safe bounded excerpt
cannot be produced; retain the digest and an explicit limitation when that loss
prevents interpretation.

Claim evidence refers only to canonical plan claims and lead-recorded attempts
or static sources. A semantic draft may label evidence `supported`,
`disproved`, or `unresolved`; the finalizer verifies references and derives the
claim outcome conservatively.

`required_guidance_satisfied` is derived from the retained interpretations, not
from successful guidance loading alone. Every active required or conditional
guidance requirement, including the applicable side of an explicit scoped
replacement, must map to a supported claim. A fully replaced broad requirement
is inactive only within the validated replacement scope; a partial replacement
keeps the remaining broad requirement active.

Workflow observations remain separate from target claims. They require concrete
evidence, confidence, strength, reason, current-run impact, safe direction, and a
stable fingerprint. They are storage-neutral and grant no authority.

## Derived state

Derive result state in this order:

1. Target, guidance, plan, evidence, protected-state, or hard-limit drift that
   prevents trust yields `completion: incomplete`, `outcome: unknown`, and the
   narrowest justified non-`none` next action.
2. Otherwise an executed required check or static result that disproves a
   material claim yields `completion: complete`, `outcome: fail`, and
   `next_action: triage`.
3. Otherwise any material claim without sufficient evidence yields
   `completion: complete`, `outcome: unknown`, and `next_action: plan`.
4. Otherwise, if every active required guidance mapping is supported, the
   result is `completion: complete`, `outcome: pass`, and `next_action: none`.
5. A missing required-guidance proof cannot become pass merely because its
   associated claim was labeled nonmaterial.

`authorization` applies only when separate authority could make required
evidence available. `retry` applies to an unavailable tool or environment after
the cause is externally corrected, never to a failed check. `decision` applies
to unresolved user intent or policy. `rescope` applies to an inadequate target.
`manual` is the fail-closed fallback when no automated safe continuation exists.

An explicit caller cap can produce complete `unknown`; it cannot produce pass by
redefining a required claim as optional. A failed check may leave later
dependent checks skipped without making the run incomplete when the frozen plan
defines that skip and the failure already establishes `fail`.

## Deterministic limits

V1 defaults and hard maxima are:

| Boundary | Default | Hard maximum |
| --- | ---: | ---: |
| Target records | 5,000 | 20,000 |
| Bytes per inspected file or guidance source | 16 MiB | 16 MiB |
| Aggregate target reads | 256 MiB | 256 MiB |
| Discovery/context records | 256 | 5,000 |
| Aggregate context reads | 64 MiB | 64 MiB |
| Effective `VERIFY.md` bytes per target | 128 KiB | 1 MiB |
| Planned checks | 16 | 128 |
| Argv entries per check | 64 | 128 |
| Timeout per check | 600 seconds | 3,600 seconds |
| Total execution time | 1,800 seconds | 86,400 seconds |
| Repetitions per check | 1 | 32 |
| Captured stdout or stderr metadata | 1 MiB | 16 MiB |
| Diagnostic excerpt per stream | 4 KiB | 16 KiB |
| Canonical JSON input or output | 16 MiB | 16 MiB |

Defaults may be lowered by the caller. Ordinary limits may be raised only by
explicit caller or active user authority up to the hard maximum. No limit change
can enable an excluded effect. Exhaustion is explicit and never authorizes
sampling.

## Semantic drafts

A plan draft contains only:

- claims without IDs or fingerprints;
- guidance interpretations using existing source IDs;
- ordered candidate selections using existing candidate IDs;
- tier, reason, claim mapping, dependency selection, and usefulness after
  failure; and
- semantic limitations.

A result draft contains only:

- claim-evidence interpretations using existing claim, check, attempt, and
  discovery-source IDs;
- a concise conclusion;
- evidence-backed workflow observations without IDs or fingerprints; and
- semantic limitations.

Finalization rejects extra properties. If a semantic draft tries to restate
target, argv, cwd, authority, effects, freshness, limits, execution facts,
digests, identifiers, or derived state, reject it instead of ignoring the field.
