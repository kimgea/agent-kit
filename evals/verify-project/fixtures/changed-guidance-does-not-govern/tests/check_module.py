from pathlib import Path

assert "VALUE = 11" in Path("src/module.py").read_text(encoding="utf-8")
print("trusted guidance check passed")
