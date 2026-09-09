# Eval candidate audit verification guidance

Run the focused deterministic contract tests:

```text
python -m unittest tests.test_eval_candidate_audit
```

Validate the skill directory and model-free evaluation definitions before the
repository-wide gate. When prompt, rubric, schema, or semantic behavior changes,
run the fresh local model-backed suite before release; never invoke a paid model
from hosted CI.

Finish an exact delivery snapshot with:

```text
python scripts/agent_kit.py check
```
