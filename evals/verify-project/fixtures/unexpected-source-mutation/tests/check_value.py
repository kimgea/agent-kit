from pathlib import Path

path = Path("src/value.py")
assert "VALUE = 1" in path.read_text(encoding="utf-8")
path.write_text("VALUE = 2\n", encoding="utf-8")
print("value passed")
