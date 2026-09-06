from pathlib import Path

assert "VALUE = 3" in Path("src/value.py").read_text(encoding="utf-8"), "expected VALUE = 3"
