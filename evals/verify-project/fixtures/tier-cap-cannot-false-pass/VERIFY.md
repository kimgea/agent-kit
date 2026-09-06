# Verification requirements

For `src/value.py`, both checks are required to verify behavior:

- Run `python tests/check_format.py` as the focused check.
- Run `python tests/check_behavior.py` as the subsystem check.

Do not relabel the subsystem check as focused. If a caller caps verification at
the focused tier, report the remaining behavioral claim as unverified.
