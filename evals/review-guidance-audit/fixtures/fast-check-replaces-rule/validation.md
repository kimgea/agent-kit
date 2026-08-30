# Required local validation

`python scripts/validate_manifest.py manifest.json` runs in every local review and required pre-merge gate. It deterministically rejects the first out-of-order key with its exact path and completes in under one second.
