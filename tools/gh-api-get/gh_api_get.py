#!/usr/bin/env python3
"""Portable GET-only wrapper around GitHub CLI's REST API command."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence


USAGE = """Usage: gh-api-get ENDPOINT [READ-ONLY FLAGS]

Perform a GitHub REST API request using GET against github.com.
GraphQL, method overrides, request bodies, caching, typed fields, custom
hostnames, verbose output, and unsafe headers are rejected.
"""

VALUE_FLAGS = {
    "-q",
    "--jq",
    "-t",
    "--template",
    "-p",
    "--preview",
    "-H",
    "--header",
    "-f",
    "--raw-field",
}
EQUAL_FLAGS = ("--jq=", "--template=", "--preview=", "--raw-field=")
SWITCH_FLAGS = {"-i", "--include", "--paginate", "--silent", "--slurp"}
BLOCKED_FLAGS = {
    "-X",
    "--method",
    "-F",
    "--field",
    "--input",
    "--cache",
    "--hostname",
    "--verbose",
}
BLOCKED_PREFIXES = (
    "-X",
    "--method=",
    "-F",
    "--field=",
    "--input=",
    "--cache=",
    "--hostname=",
)
SAFE_HEADERS = {
    "accept",
    "if-none-match",
    "if-modified-since",
    "x-github-api-version",
}


class UsageError(ValueError):
    pass


def validate_endpoint(endpoint: str) -> None:
    normalized = endpoint.split("?", 1)[0].strip("/").casefold()
    if not endpoint or endpoint.startswith("-"):
        raise UsageError("the endpoint must be the first argument")
    if "://" in endpoint:
        raise UsageError("full URLs are blocked; provide a github.com REST endpoint")
    if normalized == "graphql":
        raise UsageError("GraphQL is blocked because it can carry mutations")
    if any(char in endpoint for char in "\r\n\0"):
        raise UsageError("the endpoint contains a forbidden control character")


def validate_header(header: str) -> None:
    if any(char in header for char in "\r\n\0"):
        raise UsageError("headers may not contain control characters")
    if ":" not in header:
        raise UsageError("headers must use NAME:VALUE form")
    name = header.split(":", 1)[0].strip().casefold()
    if name not in SAFE_HEADERS:
        raise UsageError(f"header '{name}' is not on the read-only allowlist")


def build_command(argv: Sequence[str], gh: str = "gh") -> list[str]:
    if not argv:
        raise UsageError("an endpoint is required")
    endpoint = argv[0]
    validate_endpoint(endpoint)
    accepted = [endpoint]
    index = 1
    while index < len(argv):
        option = argv[index]
        if option in VALUE_FLAGS:
            if index + 1 >= len(argv):
                raise UsageError(f"option '{option}' requires a value")
            value = argv[index + 1]
            if option in {"-H", "--header"}:
                validate_header(value)
            accepted.extend((option, value))
            index += 2
            continue
        if option.startswith("--header="):
            validate_header(option.split("=", 1)[1])
            accepted.append(option)
            index += 1
            continue
        if option.startswith(EQUAL_FLAGS) or option in SWITCH_FLAGS:
            accepted.append(option)
            index += 1
            continue
        if option in BLOCKED_FLAGS or option.startswith(BLOCKED_PREFIXES):
            raise UsageError(f"option '{option}' is blocked")
        raise UsageError(f"unsupported argument '{option}'")
    return [gh, "api", "--method", "GET", "--hostname", "github.com", *accepted]


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"-h", "--help"}:
        print(USAGE)
        return 0
    gh = shutil.which("gh")
    if gh is None:
        print("gh-api-get: GitHub CLI `gh` is not on PATH", file=sys.stderr)
        return 69
    try:
        command = build_command(arguments, gh)
    except UsageError as exc:
        print(f"gh-api-get: {exc}", file=sys.stderr)
        return 64
    try:
        return subprocess.run(command, check=False, env=os.environ.copy()).returncode
    except OSError as exc:
        print(f"gh-api-get: failed to execute GitHub CLI: {exc}", file=sys.stderr)
        return 69


if __name__ == "__main__":
    raise SystemExit(main())
