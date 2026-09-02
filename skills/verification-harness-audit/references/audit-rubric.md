# Verification harness audit rubric

Use this rubric after the resolver freezes the selected harness boundary and
applicable guidance. It organizes semantic inspection; it is not a checklist
whose mere completion proves quality. Report only evidence-backed weaknesses in
the selected harness.

## Start from protection, not file presence

Build a small evidence map for each material existing requirement in scope:

1. What specification, supported behavior, public or compatibility promise,
   safety boundary, or required workflow fixes the intended outcome?
2. Which selected check is supposed to protect it?
3. Which assertion, diagnostic, fixture, or build failure distinguishes the
   protected behavior from a broken implementation?
4. Which ordinary command actually selects that check?
5. At what feedback tier does it run, on which relevant platforms, and how is a
   failure made visible and actionable?

The presence of a test file, CI job, coverage number, command name, or green
record does not answer these questions by itself. Prefer evidence that a
meaningful violation fails and the supported behavior passes.

## Coverage of existing requirements

Inspect whether the harness represents the important supported cases in the
selected boundary:

- positive behavior and material negative/error behavior;
- boundary values, state transitions, failure paths, and compatibility cases;
- public interfaces and serialized/schema contracts;
- platform-specific behavior the project claims to support;
- regression fixtures for an existing documented or demonstrated invariant;
- expected failures, skips, quarantines, and exclusions that remove protection;
- mocks, fakes, snapshots, or substitutions that bypass the behavior they claim
  to exercise; and
- generated fixtures or golden files whose provenance and update path can hide
  unintended changes.

Do not invent a missing product requirement. If deciding what should be
protected would create or change policy, use `decision_required` and a
non-essential strength.

## Assertion and diagnostic strength

Trace what a selected check actually proves:

- Reject assertions that only prove execution, non-null output, broad type, or
  an unrelated side effect when a stronger existing contract is available.
- Check whether assertions inspect the meaningful value, failure category,
  state change, ordering, or persisted artifact.
- Distinguish intentional snapshots from snapshots so broad that unrelated
  churn is accepted mechanically.
- Confirm negative cases fail for the intended reason instead of any exception
  or nonzero exit.
- Look for helpers that swallow failures, unconditional retries, permissive
  matchers, expected-failure markers, or allow-failure configuration.
- Require diagnostics to identify the failing responsibility well enough for an
  ordinary contributor or agent to act.

An exact mutation experiment is useful evidence only when already authorized;
do not edit production or harness files to perform one in this analysis-only
skill.

## Discoverability and command wiring

Determine whether contributors and agents can find and run the protection:

- Is there one documented routine command or a clearly indexed small set?
- Do aggregators, task runners, package scripts, and validation wrappers select
  the checks they claim to select?
- Are file patterns, tags, filters, test discovery, working directories, and
  environment assumptions aligned?
- Can a check exist yet remain disconnected from the canonical local or
  pre-merge command?
- Are required tools already declared and installed by the project's ordinary
  setup, rather than being silently fetched by validation?
- Does a local command materially match the locally stored CI invocation?

Report a disconnected check as a harness defect only when the existing workflow
already requires it. A proposal to create a new mandatory gate is a policy
decision.

## Feedback timing and tier placement

Classify current and recommended placement as `routine`, `pre_merge`,
`integration`, `release`, `manual`, `unknown`, or `absent`.

- Routine checks should be deterministic, bounded, and useful during ordinary
  editing.
- Pre-merge checks may be broader but should still provide actionable feedback
  before integration.
- Integration or release checks can protect environment-dependent or expensive
  behavior, but they do not replace fast protection for the same invariant when
  a bounded earlier check is feasible.
- Manual checks are evidence only for what their recorded procedure actually
  covers; do not describe them as automatic.

Static indicators such as a broad command, large fixture tree, network-shaped
configuration, or high retry count can support an inferred timing risk. Call a
check observed slow only from an authorized recorded duration or a fresh
caller-supplied timing source with provenance. Avoid universal duration
thresholds; relate timing to the documented feedback role.

## Determinism and flakiness

Inspect sources of unstable outcomes:

- wall-clock time, random seeds, locale, timezone, filesystem order, ports, and
  ambient environment;
- shared mutable state, order dependence, leftover files, caches, and parallel
  workers;
- asynchronous waiting, races, fixed sleeps, and eventually-consistent systems;
- network, external services, undeclared tools, and mutable dependencies;
- retries that conceal first failures or turn a broken check green; and
- platform-specific path, newline, encoding, permission, or process behavior.

These patterns establish an `inferred_risk`, not observed flakiness. Use an
`observed_defect` for flakiness only with authorized repeated-run evidence or a
fresh bounded failure/history source that demonstrates variable outcomes.

## Isolation and mutation safety

Check that validation cannot damage or silently depend on durable state:

- writes stay in a declared disposable directory;
- cleanup owns only artifacts created by that check and does not follow links or
  broad unresolved paths;
- concurrent runs do not share names, ports, databases, or state unsafely;
- tests do not mutate source, tracked fixtures, user configuration, credentials,
  or remote services;
- environment variables and secrets are minimized, redacted, and never copied
  into reports; and
- timeouts terminate the full owned process tree without leaving services.

This audit may recommend isolation improvements but must not provision a
service, alter permissions, or run a destructive probe.

## Redundancy and maintenance burden

Separate useful defense in depth from duplicate noise:

- Two checks are redundant when they protect the same invariant at the same
  useful tier with no meaningful independence or diagnostic benefit.
- Similar checks may both be valuable when they exercise different layers,
  platforms, failure modes, or implementations.
- Prefer one canonical helper or fixture when copy-pasted variants drift.
- Consider update cost, opaque generated data, brittle internal coupling,
  oversized fixtures, and assertions that fail on harmless refactors.
- Recommend removal only when remaining protection is demonstrably equivalent
  or better; otherwise strengthen, deduplicate, or move tier.

Do not optimize for the fewest tests or the highest raw coverage percentage.

## Platform coverage and local CI parity

Locally stored CI configuration is auditable project data. Inspect its syntax
only as needed to understand verification wiring:

- triggers and path filters;
- job dependencies, matrices, platform and runtime versions;
- conditional steps, allow-failure behavior, timeouts, and cancellation;
- command arguments, working directories, environment, and declared services;
- caches or restored artifacts that can affect correctness or reproducibility;
  and
- differences between documented local commands and configured CI commands.

Never infer current remote settings, secrets, runner images, historical pass
rates, branch rules, or provider behavior not represented in the selected local
files. Do not call a provider API. Describe provider-specific improvement only
for the selected project configuration; this skill does not publish general
GitHub, GitLab, or other provider policy.

## Failure visibility

Confirm that a failing check cannot be silently converted into success:

- shell pipelines and wrappers preserve the intended exit status;
- background work is awaited and its failure collected;
- logs or summaries retain the actionable failure while excluding secrets;
- skipped, xfailed, quarantined, ignored, or allowed-failure checks are visible;
- aggregation reports which responsibility failed; and
- timeouts and crashes are distinguishable from an assertion failure.

Missing remote telemetry is not itself a local harness defect. Audit only the
failure path demonstrated by local scripts and configuration.

## Evidence calibration

Use the narrowest evidence kind that matches the inspected fact. Direct artifact
evidence needs an exact location in text actually inspected or applicable
repository guidance actually loaded. Command evidence needs a lead-owned
executed command record. Caller-supplied timing, failure, or history evidence
needs its lead-owned source ID, digest, observation time, supply time, and
freshness assessment.

- `observed_defect`: directly demonstrated by inspected artifacts, an authorized
  command result, or compatible fresh supplied evidence.
- `inferred_risk`: a bounded pattern makes failure plausible, but behavior was
  not directly observed.
- `improvement_opportunity`: worthwhile clarity, speed, maintenance, or defense
  in depth without a demonstrated current defect.

Keep confidence separate from impact and strength. Record contradictions or
stale evidence as limitations. Never quote raw logs, transcripts, secrets,
private guidance bodies, or hidden reasoning.

## Strength, readiness, and safe direction

- `essential`: a verified defect leaves an existing material contract or
  required workflow unprotected. It must be `ready`, `observed_defect`, and
  supported by non-reasoning evidence.
- `strong`: a clear material improvement with durable value, including a
  high-confidence risk whose exact policy is already fixed.
- `moderate`: a bounded quality, timing, reliability, or maintenance gain.
- `optional`: worthwhile polish with low urgency or marginal benefit.

Use `ready` only when existing evidence fixes the intended outcome. Use
`decision_required` for new or changed product, security, privacy,
compatibility, platform, dependency, operational, or failure policy. If the
intent is uncertain, do not choose the policy for the user.

State a safe direction as the desired verification outcome and acceptance
evidence. Mention materially different alternatives. Name possible harness paths
only inside the selected harness boundary. Do not prescribe an exact patch
unless the evidence leaves one genuinely mechanical solution.

## Final coverage check

Before finalization, confirm that:

- every requested target is inspected or has a material exclusion/limitation;
- every inventory path is classified exactly once;
- every affected location belongs to its exact target, including part ranges;
- contextual defects are absent from recommendations;
- every nested guidance citation applies to at least one affected target;
- every command and supplied source reference exists in the lead-owned context;
- every material omission makes coverage incomplete; and
- duplicate recommendations are merged without losing distinct evidence or
  target ownership.
