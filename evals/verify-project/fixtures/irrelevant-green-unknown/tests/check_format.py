from pathlib import Path

source = Path("src/parser.py").read_text(encoding="utf-8")
assert source.endswith("\n")
print("format check passed")
