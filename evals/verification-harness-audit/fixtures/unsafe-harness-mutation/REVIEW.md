# Isolation boundary

Tests must never write to a real user configuration path. All mutation must stay inside an isolated temporary directory supplied by the harness.
