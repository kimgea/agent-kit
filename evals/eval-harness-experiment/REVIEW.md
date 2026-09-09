# Eval harness experiment eval review guidance

- Keep model prompts neutral: they may name the selected workflow but must not
  reveal the expected classification or hidden holdout outcome.
- Require the trusted deterministic helper command and target-bound validator;
  prose that merely repeats the prompt is not evidence.
- Preserve counterexamples for holdout overfit, noise, cost below quality,
  forbidden effects, and repeated no progress.
