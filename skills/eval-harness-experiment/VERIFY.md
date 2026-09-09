---
verification:
  risk: high
  default_profile: focused
---

# Eval harness experiment verification

Run the focused deterministic boundary and consumer tests:

```text
python -m unittest tests.test_eval_harness_experiment tests.test_project_eval tests.test_behavioral_eval
python scripts/behavioral_eval.py check --suite eval-harness-experiment
```

Before commit, also run the repository canonical gate from root. Model-backed
evidence is explicit, local, and outside ordinary validation or hosted CI.

