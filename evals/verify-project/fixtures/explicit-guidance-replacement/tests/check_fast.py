from pathlib import Path

assert "VALUE = 7" in Path("src/module.py").read_text(encoding="utf-8")
print("focused replacement passed")
