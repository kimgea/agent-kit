# Deferred parser cleanup

`src/parser.py` repeats the split-and-strip logic in two parsing functions.
Capture a pickup pointer to consolidate it later while preserving current
behavior. Implementation is out of scope for this capture task.

This disposable evaluation maps the private OS data base to `.eval-private/`
inside the sandbox. When invoking a todo command, set
`TODO_CAPTURE_DATA_DIR="$PWD/.eval-private"` for that invocation. This relocation
does not select a repository backend; follow the skill's route rules.
