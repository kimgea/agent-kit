# Agent Kit verification

## Required for pass

- After the final commit is assembled, run `python scripts/agent_kit.py
  validate-range --base BASE_SHA --head HEAD_SHA`. It may select the
  documentation profile only for changes confined to top-level maintainer
  documents, `docs/**/*.md`, `.claude/**/*.md`, and the pull-request template.
- Run `python scripts/agent_kit.py check` for source, catalog, skill, guidance,
  schema, workflow, test, evaluation, packaging, unknown, or unclassifiable
  changes, and for release preparation.
- Use focused standard-library unit tests while iterating, then rely on the
  selected final profile. The full profile checks catalog parity, links,
  generated-file hygiene, schemas, evaluation fixtures, Python compilation,
  and the complete test suite. The documentation profile checks repository
  controls, all local Markdown links, generated-file hygiene, and CCPM tracking
  consistency without compiling or running unrelated unit tests.
- For platform-sensitive path, locking, process, or permission behavior, retain
  Linux and Windows coverage. A local Linux result does not establish native
  Windows behavior.

## Conditional expansion

- Rebuild all package forms and verify checksums and standalone self-containment
  when skill membership, plugin grouping, runtime files, or packaging changes.
- Run the affected deterministic behavioral suite after changing a canonical
  producer, consumer adapter, grader, or evaluation contract.
- Run fresh model-backed behavioral evaluations locally only when semantic skill
  behavior changes or retained evidence no longer matches the final harness.
  Never add agent-model execution to hosted CI.
- Apply the additional permission-boundary proofs in `AGENTS.md` when changing
  installers, permission setup, safe dispatchers, hooks, or command
  classification.
- A push to `main`, a release, an empty range, or any failure to classify the
  exact range uses the full profile. Never manually relabel a mixed change as
  documentation-only.

## Expected disposable artifacts

- Python bytecode caches, `.eval-results/`, and package output under `dist/` may
  be created by declared checks. They are disposable outputs, not authority to
  modify source, fixtures, configuration, guidance, or pre-existing user data.
- Use a separately allocated empty run-owned temporary directory for other
  transient check output. Do not treat every ignored path as writable.
