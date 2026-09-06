import sys
from pathlib import Path

assert sys.argv[1] in {"focused", "contract"}
assert "VALUE = 42" in Path("src/deep/module.py").read_text(encoding="utf-8")
print(f"{sys.argv[1]} check passed")
