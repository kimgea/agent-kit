# Project review policy

Review changed behavior and trace material effects into related callers,
consumers, schemas, and configuration.

A timeout-unit mismatch across a queue producer, consumer, or schema is a
must-not-ship correctness defect for any reviewed queue file, including a
pre-existing violation in explicitly touched code.
