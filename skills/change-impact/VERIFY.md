# Change-impact verification guidance

For changes under this skill, prefer the focused local checks below before the
repository-wide final gate.

## Focused contract checks

Run the change-impact unit tests and its behavioral-harness adapter tests:

```text
python -m unittest tests.test_change_impact tests.test_behavioral_eval.ChangeImpactContractTests
```

Validate the model-free behavioral suite definition:

```text
python scripts/behavioral_eval.py check --suite change-impact
```

When the skill's semantic behavior, prompt, schema, or grading contract changes,
run a fresh local model-backed change-impact suite before release. Do not put
model execution in hosted CI.

## Final delivery

Run the repository's canonical gate once the exact delivery snapshot is frozen:

```text
python scripts/agent_kit.py check
```
