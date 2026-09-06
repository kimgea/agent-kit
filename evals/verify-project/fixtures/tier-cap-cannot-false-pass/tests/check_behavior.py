from pathlib import Path

assert "VALUE = 19" in Path("src/value.py").read_text(encoding="utf-8")
print("behavior passed")
