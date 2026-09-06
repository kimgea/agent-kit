from pathlib import Path


heading = Path("docs/help.md").read_text(encoding="utf-8").splitlines()[0]
if heading != "# Setup":
    raise SystemExit("release heading contract still fails")
