#!/usr/bin/env python3
"""Block direct `gh api` shell commands in a Claude-style pre-tool hook.

Read one JSON object from stdin or accept `--command`. Exit 2 when a visible shell
segment invokes `gh api`; otherwise exit 0. This is defense in depth and does not
replace harness permission policy or the validated gh-api-get wrapper.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any


DIRECT_GH_API = re.compile(
    r"(?:^|[;&|()]\s*)(?:[^\s;&|()]*/)?gh(?:\.exe)?\s+api(?:\s|$)",
    re.IGNORECASE,
)


def command_from_payload(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in ("command", "cmd"):
        command = value.get(key)
        if isinstance(command, str):
            return command
    for key in ("tool_input", "input"):
        command = command_from_payload(value.get(key))
        if command:
            return command
    return ""


def blocked(command: str) -> bool:
    return bool(DIRECT_GH_API.search(command))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command")
    args = parser.parse_args(argv)

    if args.command is not None:
        command = args.command
    else:
        try:
            command = command_from_payload(json.load(sys.stdin))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"github-api-guard: invalid hook input: {exc}", file=sys.stderr)
            return 2

    if blocked(command):
        print(
            "Direct `gh api` is blocked. Use the reviewed GET-only gh-api-get "
            "wrapper for REST reads and a purpose-specific command for mutations.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
