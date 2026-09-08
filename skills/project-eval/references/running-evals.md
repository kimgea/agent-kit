# Running project evaluations

Case validation, preparation, grading, reconstruction calibration, and bounded
clarification are deterministic operations. They do not invoke an agent. Use
`validate-case`, then `prepare-case` with an explicit workspace root and
`--context-output`, both outside the repository and separate from each other.
Pass only the returned workspace to a worker. Keep the prepared-case receipt in
the evaluator-owned host area.

Grade with `grade-case`. Built-in assertions read the resulting workspace.
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

The fixed Codex runner and comparison workflow are delivered by later
milestones of the same versioned interface.

Never interpret validation success as a model-backed behavioral result. A real
run must name an explicit suite, profile, agent adapter, model, and bounded
configuration. A single repetition is one observation rather than stability
evidence.

When comparison support is available, require paired baseline and candidate
runs under matching relevant conditions. Correctness and forbidden effects are
hard gates. Compare time and token measurements only among variants meeting the
quality threshold, and retain tradeoffs or inconclusive outcomes rather than
forcing a winner.
