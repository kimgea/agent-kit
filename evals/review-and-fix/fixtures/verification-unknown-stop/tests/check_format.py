from pathlib import Path


text = Path("docs/help.md").read_text(encoding="utf-8")
if not text.startswith("# "):
    raise SystemExit("missing Markdown heading")
