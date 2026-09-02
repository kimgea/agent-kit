from pathlib import Path


def main():
    paths = sorted(Path("src").rglob("*.py"))
    failures = [str(path) for path in paths if "\t" in path.read_text()]
    if failures:
        print("tab indentation: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
