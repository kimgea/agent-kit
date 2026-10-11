#!/usr/bin/env python3
"""Route todo-capture through a Git project's declared store.

This entry point is deliberately excluded from generated automatic permission
rules. A repository can select a write destination, so its configuration is
never treated as permission to run this command.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import data_root, ensure_private_dir  # noqa: E402
from todo import build_parser, main as todo_main  # noqa: E402


CONFIG_NAME = ".todo-capture.toml"
STORE_NAME = ".todo"
MARKER_NAME = ".todo-capture-store"
MARKER_TEXT = "todo-capture repository store v1\n"
IGNORE_NAME = ".gitignore"
IGNORE_LINE = ".todo-capture.lock"
MAX_CONFIG_BYTES = 16384
MUTATING = ("new", "domain-add", "done")


def git_root():
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=os.getcwd(), text=True, capture_output=True, check=False,
    )
    if result.returncode != 0:
        if any((parent / ".git").exists() for parent in
               (Path.cwd(), *Path.cwd().parents)):
            raise ValueError("cannot resolve the Git project root")
        return None
    root = result.stdout.strip()
    if not root or not os.path.isdir(root):
        raise ValueError("Git did not return a usable project root")
    return Path(root)


def read_route():
    root = git_root()
    if root is None:
        return {"backend": "private", "project_root": None,
                "store": data_root(), "config": None}
    config = root / CONFIG_NAME
    if config.is_symlink():
        raise ValueError(f"refusing symlinked project configuration: {config}")
    if not config.exists():
        return {"backend": "private", "project_root": str(root),
                "store": data_root(), "config": None}
    if not config.is_file():
        raise ValueError(f"expected a regular project configuration file: {config}")
    with config.open("rb") as handle:
        content = handle.read(MAX_CONFIG_BYTES + 1)
    if len(content) > MAX_CONFIG_BYTES:
        raise ValueError(f"project configuration exceeds {MAX_CONFIG_BYTES} bytes: {config}")
    payload = tomllib.loads(content.decode("utf-8"))
    if (set(payload) != {"version", "backend"} or
            type(payload.get("version")) is not int or payload["version"] != 1):
        raise ValueError("project configuration must contain only version = 1 and backend")
    backend = payload["backend"]
    if backend not in ("private", "repository"):
        raise ValueError(f"unsupported todo-capture backend: {backend!r}")
    store = root / STORE_NAME if backend == "repository" else Path(data_root())
    if backend == "repository":
        inspect_store(store)
    return {"backend": backend, "project_root": str(root),
            "store": str(store),
            "config": str(config)}


def inspect_store(store):
    if store.is_symlink():
        raise ValueError(f"refusing symlinked project todo store: {store}")
    if not store.exists():
        return
    if not store.is_dir():
        raise ValueError(f"expected a project todo directory: {store}")
    marker = store / MARKER_NAME
    if marker.is_symlink():
        raise ValueError(f"refusing symlinked project todo marker: {marker}")
    if not marker.exists() and not any(store.iterdir()):
        return
    if not marker.is_file() or marker.read_text(encoding="utf-8") != MARKER_TEXT:
        raise ValueError(f"existing .todo is not an owned todo-capture store: {store}")
    ignore = store / IGNORE_NAME
    if ignore.is_symlink():
        raise ValueError(f"refusing symlinked project todo ignore file: {ignore}")
    if ignore.exists() and (not ignore.is_file() or
                            ignore.read_text(encoding="utf-8") != IGNORE_LINE + "\n"):
        raise ValueError(f"{ignore} must contain only {IGNORE_LINE!r}")


def prepare_store(store, allow_create):
    inspect_store(store)
    if not store.exists():
        if not allow_create:
            raise ValueError(f"project todo store does not exist: {store}")
        ensure_private_dir(store)
    marker = store / MARKER_NAME
    if not marker.exists():
        create_owned_file(store / MARKER_NAME, MARKER_TEXT)
    ignore = store / IGNORE_NAME
    if not ignore.exists():
        create_owned_file(ignore, IGNORE_LINE + "\n")


def create_owned_file(path, content):
    """Create a project-store control file without replacing another path."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if any(arg == "--dir" or arg.startswith("--dir=") for arg in args):
        print("error: todo_project.py does not accept --dir", file=sys.stderr)
        return 2
    try:
        route = read_route()
        if args == ["route"]:
            print(json.dumps(route, indent=2))
            return 0
        if not args:
            print("error: select route, list, new, show, done, check, or domain-add",
                  file=sys.stderr)
            return 2
        if route["backend"] == "repository":
            store = Path(route["store"])
            if args[0] in MUTATING:
                build_parser(allow_custom_dir=False).parse_args(args)
                prepare_store(store, allow_create=args[0] != "done")
            return todo_main(args, allow_custom_dir=False, selected_dir=str(store))
        return todo_main(args, allow_custom_dir=False)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
