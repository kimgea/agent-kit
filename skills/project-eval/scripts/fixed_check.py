#!/usr/bin/env python3
"""Evaluator-owned fixed project checks; manifests select names, never argv."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import hashlib
from pathlib import Path
import sys


def _load_safety():
    path = Path(__file__).with_name("path_safety.py")
    name = f"_project_eval_check_safety_{hashlib.sha256(str(path).encode()).hexdigest()[:12]}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load path safety helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SAFETY = _load_safety()
MAX_ENTRIES = 10_000
MAX_BYTES = 64 * 1024 * 1024


def python_compile(workspace: Path) -> bool:
    pending = [workspace]
    count = 0
    total = 0
    while pending:
        directory = pending.pop()
        entries, _, complete = _SAFETY.bound_directory_entries(directory, MAX_ENTRIES - count)
        if not complete:
            return False
        for entry in entries:
            count += 1
            if entry.link_like:
                return False
            if entry.is_directory:
                if entry.name != ".git":
                    pending.append(entry.path)
            elif entry.is_regular and entry.name.endswith(".py"):
                _, raw = _SAFETY.read_regular(entry.path, MAX_BYTES - total, require_single_link=True)
                total += len(raw)
                if total > MAX_BYTES:
                    return False
                try:
                    ast.parse(raw, filename=str(entry.path))
                except (SyntaxError, ValueError):
                    return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("python-compile",))
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)
    workspace = Path(args.workspace).absolute()
    try:
        _SAFETY.assert_no_link_components(workspace, include_final=True)
        passed = python_compile(workspace)
    except (OSError, _SAFETY.SafetyError):
        return 2
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
