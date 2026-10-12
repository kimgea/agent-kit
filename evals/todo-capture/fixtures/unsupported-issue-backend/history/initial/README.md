# Deferred parser cleanup

`src/parser.py` repeats the split-and-strip logic in two parsing functions.
Capture a pickup pointer to consolidate it later while preserving current
behavior. Implementation is out of scope for this capture task.
