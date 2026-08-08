# Grill-me architecture and support

## Purpose

`grill-me` provides a rigorous but constructive questioning loop for decisions,
plans, artifacts, diagnoses, and subjective tradeoffs. It contains no executable
code and does not modify files or external systems by itself.

## Structure

`SKILL.md` holds the universal interaction loop, cadence, guardrails, and final
output contract. `references/mode-lenses.md` holds domain-specific probes and
convergence shapes so an agent loads only the selected mode.

The skill is plain Markdown for Claude Code compatibility. `agents/openai.yaml`
adds Codex UI metadata and is ignored by Claude Code.

## Validation

Repository checks validate frontmatter, metadata, direct links, catalog parity,
and the evaluation schema. Evaluation cases under `evals/grill-me/` cover artifact
grounding, one-question cadence, constructive pressure, and convergence.

Behavioral evaluations are review aids rather than deterministic proof: model and
context differences still require forward-testing after material changes.

## Maintainer checklist

- Keep trigger contexts in the frontmatter description.
- Keep the core loop concise and move mode-specific detail into the direct
  reference.
- Preserve the distinction between pressure-testing reasoning and attacking the
  user.
- Add an evaluation case when adding a mode or changing convergence behavior.
- Validate that `agents/openai.yaml` still matches the skill.
