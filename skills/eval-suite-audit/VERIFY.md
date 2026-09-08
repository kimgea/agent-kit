---
verification:
  risk: high
  default_profile: focused
---

# Eval suite audit verification

Run the focused unit and behavioral-contract tests for changes under this skill:

```text
python -m unittest tests.test_eval_suite_audit tests.test_behavioral_eval tests.test_project_eval
python scripts/behavioral_eval.py check --suite eval-suite-audit
```

Before commit, also run the repository canonical gate from root.
