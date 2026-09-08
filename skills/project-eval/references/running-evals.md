# Running project evaluations

Case validation, preparation, grading, reconstruction calibration, and bounded
clarification are deterministic operations. They do not invoke an agent. Use
`validate-case`, then `prepare-case` with an explicit workspace root and
`--context-output`, both outside the repository and separate from each other.
Pass only the returned workspace to a worker. Keep the prepared-case receipt in
the evaluator-owned host area.

Grade with `grade-case`. Built-in assertions read the resulting workspace.
Use exact file/JSON assertions for simple artifacts. The fixed
`python_mapping_lookup` assertion is available for the narrow Python contract
where one named top-level function must return `mapping_argument[key_argument]`;
it parses syntax and does not execute fixture code.
Repository checks are a small evaluator-owned registry and require
`--allow-project-checks`; manifests never supply argv, an executable, a shell
fragment, or an interpreter expression. Hidden grading uses the same fixed
evaluator-owned registry and requires `--allow-hidden-grader`; repository files
are never executed as graders. Output is retained only as a bounded digest and
fixed status summary.

Ordinary fixtures copy only their selected visible source and reject Git
history, eval definitions, links, and control-plane state at any depth. This
includes `control.json`, `.git`, `.agent-kit`, `.eval-results`, `evals`,
`hidden`, `holdout(s)`, `expected(-results)`, `golden`, `alternatives`, and
grader names. `grade-case` accepts `--prepared`, not an arbitrary workspace
path, and revalidates its case, control, fixture, workspace object identity, and
receipt digests before observing results. A history case must
declare `sanitized-history` and supplies explicit snapshot directories from
which the host constructs a new deterministic repository. Reconstruction cases
start from a declared golden tree plus declarative removals; run
`calibrate-reconstruction` before use. Trajectory facts remain in hidden
control, and `respond` returns one uniquely matched fact or no answer.

`runner-info` freezes the local Codex launcher bytes, version/help contract,
and bundled adapter without invoking a model. `run-codex-attempt` is an
explicit one-attempt primitive: it accepts only a validated prepared receipt,
a case selected by the named suite profile, an explicit model and reasoning
effort, and a private host root outside both repository and worker workspace.
The adapter launches `codex exec` in a fresh ephemeral context, ignores user
configuration and exec-policy rules, disables subagents and web search, denies
approvals, and selects a restricted permission profile. That profile denies
ambient filesystem reads, reopens only the sanitized workspace plus minimal
runtime paths, denies system temporary roots, and keeps command networking off
unless both the committed profile and caller allow it. Raw prompts, events,
stderr, and final messages are deleted after their bounded hashes and
measurements are derived.

Each attempt freezes the adapter and launcher identities, argv, environment,
agent instructions/skills, model, reasoning, platform, network, and effects.
The host observes duration, commands, workspace mutations, and process exit;
Codex may report token use; cost is unavailable until the runner provides it.
An unavailable metric is explicit and cannot be treated as an enforced cap.
Retries use the same in-memory `BudgetLedger` as first attempts. Timeout or
operator failure kills and reaps the complete POSIX process group or Windows
job before mutation grading continues.

Use `run-codex-profile` for the normal end-to-end Codex workflow. It validates
every selected fixture before the first model call, freezes the complete
case/repetition schedule, and uses a fresh disposable workspace per
observation. The one selected profile is the caller's bounded execution
authority. Pass `--allow-project-checks`, `--allow-hidden-grader`, or
`--allow-network` only when the selected profile and caller both authorize the
corresponding effect. Add `--store` only after an explicit `state-init`; without
it, the canonical result is returned or written to the explicit output only.

Use `grade-recorded-case` for Claude, another agent, or manually supplied
workspace output. That path performs the same deterministic grading without
discovering Codex and returns an empty direct-runner compatibility list.

Never interpret validation success as a model-backed behavioral result. A real
run must name an explicit suite, profile, agent adapter, model, and bounded
configuration. A single repetition is one observation rather than stability
evidence.

`compare-runs` requires exact suite, target, profile, configuration, case,
repetition, fixture, and grader identity. Use it for repeat observations under
the same conditions. Correctness and forbidden effects are hard gates. It
compares completion and important-case performance first, exposes duration and
token dimensions only after both sides pass the quality gate, and retains
tradeoffs or inconclusive outcomes rather than forcing a winner. A later paired
harness experiment owns the controlled one-variable variant boundary.
