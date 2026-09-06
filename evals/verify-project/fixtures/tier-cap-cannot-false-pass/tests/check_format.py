from pathlib import Path

assert Path("src/value.py").read_text(encoding="utf-8").endswith("\n")
print("format passed")
