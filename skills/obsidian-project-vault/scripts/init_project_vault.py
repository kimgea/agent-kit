from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys


PLACEHOLDERS = ("{{project_name}}", "{{date}}")
EXTRA_DIRS = [
    "05 Intake/To Process",
    "05 Intake/In Review",
    "05 Intake/Processed",
    "05 Intake/Rejected",
    "10 Ideas",
    "20 Explorations",
    "30 Designs",
    "40 Requirements",
    "60 Reference",
    "90 Archive",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize a shared Obsidian project vault scaffold."
    )
    parser.add_argument("target", help="Target directory for the vault scaffold")
    parser.add_argument(
        "--project-name",
        required=True,
        help="Project name to insert into starter files",
    )
    parser.add_argument(
        "--date",
        default="YYYY-MM-DD",
        help="Date value to insert into starter files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in the target path",
    )
    return parser.parse_args()


def render_text(text: str, project_name: str, date: str) -> str:
    return text.replace("{{project_name}}", project_name).replace("{{date}}", date)


def write_file(source: Path, destination: Path, project_name: str, date: str, force: bool) -> None:
    if destination.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing file: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    if source.suffix.lower() == ".md":
        text = source.read_text(encoding="utf-8")
        destination.write_text(render_text(text, project_name, date), encoding="utf-8")
        return

    shutil.copy2(source, destination)


def main() -> int:
    args = parse_args()

    script_dir = Path(__file__).resolve().parent
    skill_dir = script_dir.parent
    scaffold_dir = skill_dir / "assets" / "scaffold"
    target_dir = Path(args.target).resolve()

    if not scaffold_dir.exists():
        print(f"Scaffold directory not found: {scaffold_dir}", file=sys.stderr)
        return 1

    target_dir.mkdir(parents=True, exist_ok=True)

    for rel_dir in EXTRA_DIRS:
        (target_dir / rel_dir).mkdir(parents=True, exist_ok=True)

    for source in scaffold_dir.rglob("*"):
        if source.is_dir():
            continue
        relative = source.relative_to(scaffold_dir)
        destination = target_dir / relative
        write_file(source, destination, args.project_name, args.date, args.force)

    print(f"Initialized project vault scaffold at {target_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
