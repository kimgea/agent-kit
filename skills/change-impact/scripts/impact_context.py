#!/usr/bin/env python3
"""Resolve bounded change-impact targets, context, and trusted guidance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any

from path_safety import (
    SafetyError,
    assert_no_link_components,
    bound_directory_entries,
    canonical_path,
    canonical_text,
    filesystem_snapshot,
    filesystem_path,
    is_link_like,
    read_regular,
    safe_repo_path,
    write_created_output,
)


SCHEMA_VERSION = "1.0.0"
SKILL_VERSION = "1.0.0"
DEFAULT_MAX_TARGETS = 500
DEFAULT_MAX_CONTEXT_FILES = 128
DEFAULT_MAX_FILE_BYTES = 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_GUIDANCE_BYTES = 128 * 1024
DEFAULT_MAX_TRAVERSAL_ENTRIES = 25000
MAX_TARGETS = 5000
MAX_CONTEXT_FILES = 1000
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024
MAX_GUIDANCE_BYTES = 1024 * 1024
MAX_TRAVERSAL_ENTRIES = 250000
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 128
MAX_LIMITATIONS = 256
GIT_TIMEOUT_SECONDS = 30
MAX_GIT_STDOUT_BYTES = 32 * 1024 * 1024
MAX_GIT_STDERR_BYTES = 256 * 1024
HEX_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
STATUS_NAMES = {
    "A": "added",
    "C": "copied",
    "D": "deleted",
    "M": "modified",
    "R": "renamed",
    "T": "type_changed",
    "U": "unmerged",
    "X": "unknown",
    "B": "unknown",
}


class ContextError(ValueError):
    """Raised when an impact context cannot be proven safe and complete."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _machine_json(value: Any) -> bytes:
    """Return the exact canonical machine-readable output, including newline."""
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )


def context_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _git(
    root: Path,
    arguments: list[str],
    *,
    check: bool = True,
    maximum_stdout: int = MAX_GIT_STDOUT_BYTES,
) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    command = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=",
        "-c",
        "diff.external=",
        *arguments,
    ]
    streams: dict[str, list[bytes]] = {"stdout": [], "stderr": []}
    exceeded: dict[str, threading.Event] = {
        "stdout": threading.Event(),
        "stderr": threading.Event(),
    }

    def drain(name: str, stream: Any, maximum: int) -> None:
        total = 0
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            remaining = maximum + 1 - total
            if remaining > 0:
                streams[name].append(chunk[:remaining])
            total += len(chunk)
            if total > maximum:
                exceeded[name].set()

    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ContextError(f"cannot run Git metadata command safely: {exc}") from exc
    assert process.stdout is not None and process.stderr is not None
    threads = [
        threading.Thread(
            target=drain,
            args=("stdout", process.stdout, maximum_stdout),
            daemon=True,
        ),
        threading.Thread(
            target=drain,
            args=("stderr", process.stderr, MAX_GIT_STDERR_BYTES),
            daemon=True,
        ),
    ]
    for worker in threads:
        worker.start()
    deadline = time.monotonic() + GIT_TIMEOUT_SECONDS
    timed_out = False
    while process.poll() is None:
        if exceeded["stdout"].is_set() or exceeded["stderr"].is_set():
            process.kill()
            break
        if time.monotonic() >= deadline:
            timed_out = True
            process.kill()
            break
        time.sleep(0.01)
    process.wait()
    for worker in threads:
        worker.join(timeout=1)
    process.stdout.close()
    process.stderr.close()
    if any(worker.is_alive() for worker in threads):
        raise ContextError("cannot drain Git metadata output safely")
    if timed_out:
        raise ContextError("Git metadata command timed out")
    if exceeded["stdout"].is_set():
        raise ContextError(f"Git metadata output exceeds {maximum_stdout} bytes")
    if exceeded["stderr"].is_set():
        raise ContextError(f"Git metadata error output exceeds {MAX_GIT_STDERR_BYTES} bytes")
    completed = subprocess.CompletedProcess(
        command,
        process.returncode,
        b"".join(streams["stdout"]),
        b"".join(streams["stderr"]),
    )
    if check and completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace").strip()
        raise ContextError(message or f"Git exited with {completed.returncode}")
    return completed


def _repository_root(candidate: Path, *, require_git: bool) -> tuple[Path, bool]:
    try:
        supplied = candidate.absolute()
        assert_no_link_components(supplied, include_final=True)
        supplied = supplied.resolve(strict=True)
    except OSError as exc:
        raise ContextError(f"cannot resolve repository root: {exc}") from exc
    if not supplied.is_dir():
        raise ContextError(f"repository root is not a directory: {supplied}")
    completed = _git(supplied, ["rev-parse", "--show-toplevel"], check=False)
    if completed.returncode == 0:
        try:
            discovered = Path(
                completed.stdout.decode("utf-8", "strict").strip()
            ).resolve(strict=True)
        except (OSError, UnicodeError) as exc:
            raise ContextError(f"Git returned an invalid repository root: {exc}") from exc
        if discovered != supplied:
            raise ContextError(
                f"--repo must name the Git repository root ({discovered}), not {supplied}"
            )
        return supplied, True
    if require_git:
        raise ContextError("this target mode requires a Git repository")
    return supplied, False


def _commit(root: Path, revision: str) -> str:
    if not isinstance(revision, str) or not revision or len(revision) > 512:
        raise ContextError("revision must contain 1 to 512 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in revision):
        raise ContextError("revision must not contain control characters")
    completed = _git(
        root,
        ["rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"],
    )
    value = completed.stdout.decode("ascii", "strict").strip().lower()
    if not HEX_REVISION.fullmatch(value):
        raise ContextError("Git returned a non-canonical commit identifier")
    return value


def _decode_git_path(value: bytes) -> str:
    try:
        return canonical_path(value.decode("utf-8", "strict"))
    except (UnicodeDecodeError, SafetyError) as exc:
        raise ContextError(f"Git returned an unsafe repository path: {exc}") from exc


def _parse_name_status(payload: bytes) -> list[dict[str, Any]]:
    tokens = payload.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    changes: list[dict[str, Any]] = []
    index = 0
    while index < len(tokens):
        status_token = tokens[index].decode("ascii", "replace")
        index += 1
        code = status_token[:1]
        if code not in STATUS_NAMES:
            raise ContextError(f"unsupported Git status {status_token!r}")
        source_path: str | None = None
        if code in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise ContextError("malformed Git rename or copy record")
            source_path = _decode_git_path(tokens[index])
            path = _decode_git_path(tokens[index + 1])
            index += 2
        else:
            if index >= len(tokens):
                raise ContextError("malformed Git change record")
            path = _decode_git_path(tokens[index])
            index += 1
        changes.append(
            {
                "path": path,
                "source_path": source_path,
                "status": STATUS_NAMES[code],
            }
        )
    return changes


def _merge_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str | None], dict[str, Any]] = {}
    precedence = {
        "unknown": 0,
        "modified": 1,
        "type_changed": 2,
        "copied": 3,
        "renamed": 4,
        "added": 5,
        "untracked": 6,
        "deleted": 7,
        "unmerged": 8,
        "snapshot": 9,
    }
    for change in changes:
        key = (change["path"], change["source_path"])
        current = merged.get(key)
        if current is None or precedence[change["status"]] > precedence[current["status"]]:
            merged[key] = change
    return sorted(
        merged.values(),
        key=lambda item: (item["path"], item["source_path"] or "", item["status"]),
    )


def _ref_changes(root: Path, base: str, head: str) -> list[dict[str, Any]]:
    completed = _git(
        root,
        [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--find-renames",
            "--name-status",
            "-z",
            base,
            head,
            "--",
        ],
    )
    return _merge_changes(_parse_name_status(completed.stdout))


def _working_changes(root: Path, base: str) -> list[dict[str, Any]]:
    tracked = _git(
        root,
        [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--find-renames",
            "--name-status",
            "-z",
            base,
            "--",
        ],
    )
    untracked = _git(
        root,
        ["ls-files", "--others", "--exclude-standard", "-z", "--"],
    )
    additions = [
        {"path": _decode_git_path(value), "source_path": None, "status": "untracked"}
        for value in untracked.stdout.split(b"\0")
        if value
    ]
    return _merge_changes([*_parse_name_status(tracked.stdout), *additions])


def _target_paths(changes: list[dict[str, Any]]) -> list[str]:
    paths: set[str] = set()
    for change in changes:
        paths.add(change["path"])
        if change["source_path"] is not None:
            paths.add(change["source_path"])
    return sorted(paths)


def _limitation(
    code: str, message: str, paths: list[str] | None = None, *, material: bool = True
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "paths": sorted(set(paths or [])),
        "material": material,
    }


def _line_count(content: str) -> int:
    if not content:
        return 0
    return content.count("\n") + (0 if content.endswith("\n") else 1)


def _content_record(
    path: str,
    role: str,
    revision: str | None,
    data: bytes | None,
    *,
    maximum: int,
    error_state: str | None = None,
) -> dict[str, Any]:
    if data is None:
        return {
            "path": path,
            "role": role,
            "revision": revision,
            "state": error_state or "absent",
            "size": None,
            "sha256": None,
            "line_count": None,
            "content": None,
        }
    if len(data) > maximum:
        return {
            "path": path,
            "role": role,
            "revision": revision,
            "state": "oversized",
            "size": None,
            "sha256": None,
            "line_count": None,
            "content": None,
        }
    if b"\0" in data:
        return {
            "path": path,
            "role": role,
            "revision": revision,
            "state": "binary",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "line_count": None,
            "content": None,
        }
    try:
        content, normalized = canonical_text(data, path)
    except SafetyError:
        return {
            "path": path,
            "role": role,
            "revision": revision,
            "state": "binary",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "line_count": None,
            "content": None,
        }
    return {
        "path": path,
        "role": role,
        "revision": revision,
        "state": "text",
        "size": len(normalized),
        "sha256": hashlib.sha256(normalized).hexdigest(),
        "line_count": _line_count(content),
        "content": content,
    }


def _git_file(root: Path, revision: str, path: str, maximum: int) -> bytes | None:
    object_spec = f"{revision}:{path}"
    size_result = _git(root, ["cat-file", "-s", object_spec], check=False)
    if size_result.returncode != 0:
        return None
    try:
        size = int(size_result.stdout.decode("ascii", "strict").strip())
    except (UnicodeError, ValueError) as exc:
        raise ContextError(f"Git returned an invalid blob size for {path}") from exc
    if size < 0:
        raise ContextError(f"Git returned an invalid blob size for {path}")
    if size > maximum:
        return b"\0" * (maximum + 1)
    completed = _git(
        root,
        ["cat-file", "-p", object_spec],
        check=False,
        maximum_stdout=maximum,
    )
    if completed.returncode != 0 or len(completed.stdout) != size:
        raise ContextError(f"Git blob changed or became unavailable for {path}")
    return completed.stdout


def _current_file(root: Path, path: str, maximum: int) -> tuple[bytes | None, str | None]:
    try:
        candidate = safe_repo_path(root, path)
        metadata = candidate.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            return None, "unreadable"
        if metadata.st_size > maximum:
            return None, "oversized"
        metadata, data = read_regular(
            candidate,
            maximum,
            expected_snapshot=filesystem_snapshot(candidate, metadata),
            require_single_link=True,
        )
        return data, None
    except (OSError, SafetyError) as exc:
        message = str(exc)
        if message.startswith("cannot inspect repository path:"):
            return None, "absent"
        return None, f"unreadable: {message}"


def _read_record(
    root: Path,
    path: str,
    role: str,
    revision: str | None,
    maximum: int,
    limitations: list[dict[str, Any]],
) -> dict[str, Any]:
    if revision is not None:
        data = _git_file(root, revision, path, maximum)
        if data is None:
            return _content_record(path, role, revision, None, maximum=maximum)
    else:
        data, error = _current_file(root, path, maximum)
        if error is not None:
            state = error if error in {"absent", "oversized", "unreadable"} else "unreadable"
            code = "file_oversized" if state == "oversized" else "file_unreadable"
            limitations.append(
                _limitation(code, f"cannot inspect {path}: {error}", [path])
            )
            return _content_record(
                path,
                role,
                revision,
                None,
                maximum=maximum,
                error_state=state,
            )
    record = _content_record(path, role, revision, data, maximum=maximum)
    if record["state"] == "binary":
        limitations.append(
            _limitation("file_non_text", f"{path} is not inspectable UTF-8 text", [path])
        )
    elif record["state"] == "oversized":
        limitations.append(
            _limitation("file_oversized", f"{path} exceeds the per-file read limit", [path])
        )
    return record


def _git_ignored(root: Path, paths: list[str]) -> set[str]:
    ignored: set[str] = set()
    for offset in range(0, len(paths), 256):
        chunk = paths[offset : offset + 256]
        payload = b"\0".join(item.encode("utf-8") for item in chunk) + b"\0"
        environment = dict(os.environ)
        environment.pop("GIT_LITERAL_PATHSPECS", None)
        environment.update(
            {
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            }
        )
        try:
            completed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    f"core.hooksPath={os.devnull}",
                    "check-ignore",
                    "-z",
                    "--stdin",
                ],
                cwd=root,
                env=environment,
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ContextError(f"Git ignore classification failed: {exc}") from exc
        if completed.returncode not in {0, 1}:
            message = completed.stderr.decode("utf-8", "replace").strip()
            raise ContextError(
                f"Git ignore classification failed: {message or completed.returncode}"
            )
        for value in completed.stdout.split(b"\0"):
            if value:
                ignored.add(_decode_git_path(value))
    return ignored


def _enumerate_explicit(
    root: Path,
    selectors: list[str],
    *,
    git_repository: bool,
    max_targets: int,
    max_traversal: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    limitations: list[dict[str, Any]] = []
    files: set[str] = set()
    traversed = 0
    for selector in selectors:
        try:
            canonical = canonical_path(selector, allow_root=True)
            candidate = safe_repo_path(root, canonical)
        except SafetyError as exc:
            limitations.append(_limitation("unsafe_path", str(exc)))
            continue
        if candidate.is_file():
            files.add(canonical)
            continue
        if not candidate.is_dir():
            limitations.append(
                _limitation("file_unreadable", f"target is not a regular file or directory: {canonical}")
            )
            continue
        stack: list[tuple[Path, str]] = [(candidate, canonical)]
        while stack:
            directory, relative = stack.pop()
            remaining = max_traversal - traversed
            if remaining <= 0:
                limitations.append(
                    _limitation("traversal_limit", "directory traversal limit was exhausted", [canonical])
                )
                break
            try:
                entries, consumed, complete = bound_directory_entries(directory, remaining)
            except (OSError, SafetyError) as exc:
                limitations.append(
                    _limitation("unsafe_path", f"cannot enumerate {relative}: {exc}", [canonical])
                )
                break
            traversed += consumed
            if not complete:
                limitations.append(
                    _limitation("traversal_limit", "directory traversal limit was exhausted", [canonical])
                )
                break
            relative_entries: list[tuple[Any, str]] = []
            for entry in entries:
                child = entry.name if relative == "." else f"{relative}/{entry.name}"
                try:
                    child = canonical_path(child)
                except SafetyError as exc:
                    limitations.append(_limitation("unsafe_path", str(exc), [canonical]))
                    continue
                if child == ".git" or child.startswith(".git/"):
                    continue
                relative_entries.append((entry, child))
            ignored = (
                _git_ignored(root, [child for _, child in relative_entries])
                if git_repository and relative_entries
                else set()
            )
            for entry, child in reversed(relative_entries):
                if child in ignored:
                    continue
                if entry.link_like or (not entry.is_directory and not entry.is_regular):
                    limitations.append(
                        _limitation("unsafe_path", f"target contains link-like or special path: {child}", [child])
                    )
                elif entry.is_directory:
                    stack.append((entry.path, child))
                else:
                    files.add(child)
                if len(files) > max_targets:
                    limitations.append(
                        _limitation("scope_limit", f"target exceeds {max_targets} files", [canonical])
                    )
                    break
            if len(files) > max_targets:
                break
    over_limit = len(files) > max_targets
    selected = [] if over_limit else sorted(files)
    changes = [
        {"path": path, "source_path": None, "status": "snapshot"}
        for path in selected
    ]
    if not selected and not over_limit:
        limitations.append(_limitation("empty_target", "explicit target resolved to no files"))
    return changes, limitations


def _guidance_candidates(path: str, name: str) -> list[str]:
    parent = PurePosixPath(path).parent
    directories = [PurePosixPath(".")]
    current = PurePosixPath()
    if str(parent) not in {"", "."}:
        for part in parent.parts:
            current /= part
            directories.append(current)
    return [name if str(item) == "." else f"{item.as_posix()}/{name}" for item in directories]


def _guidance(
    root: Path,
    target_paths: list[str],
    *,
    revision: str | None,
    maximum: int,
    limitations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for target_path in target_paths:
        for kind, name in (("review", "REVIEW.md"), ("verification", "VERIFY.md")):
            for path in _guidance_candidates(target_path, name):
                if path == target_path:
                    continue
                if revision is not None:
                    data = _git_file(root, revision, path, maximum)
                    read_state = None
                else:
                    data, read_state = _current_file(root, path, maximum)
                if data is None:
                    if read_state not in {None, "absent"}:
                        limitations.append(
                            _limitation(
                                "guidance_unavailable",
                                f"trusted {path} is unavailable: {read_state}",
                                [target_path],
                            )
                        )
                    continue
                if len(data) > maximum:
                    limitations.append(
                        _limitation(
                            "guidance_unavailable",
                            f"trusted {path} exceeds the guidance limit",
                            [target_path],
                        )
                    )
                    continue
                try:
                    content, normalized = canonical_text(data, path)
                except SafetyError:
                    limitations.append(
                        _limitation(
                            "guidance_unavailable",
                            f"trusted {path} is not UTF-8 text",
                            [target_path],
                        )
                    )
                    continue
                key = (kind, path)
                source = found.setdefault(
                    key,
                    {
                        "kind": kind,
                        "path": path,
                        "revision": revision,
                        "applies_to": [],
                        "size": len(normalized),
                        "sha256": hashlib.sha256(normalized).hexdigest(),
                        "content": content,
                    },
                )
                source["applies_to"].append(target_path)
    result = []
    for key in sorted(found):
        source = found[key]
        source["applies_to"] = sorted(set(source["applies_to"]))
        result.append(source)
    return result


def _validate_limits(args: argparse.Namespace) -> dict[str, int]:
    pairs = (
        ("max_targets", args.max_targets, 1, MAX_TARGETS),
        ("max_context_files", args.max_context_files, 0, MAX_CONTEXT_FILES),
        ("max_file_bytes", args.max_file_bytes, 1, MAX_FILE_BYTES),
        ("max_total_bytes", args.max_total_bytes, 1, MAX_TOTAL_BYTES),
        ("max_guidance_bytes", args.max_guidance_bytes, 1, MAX_GUIDANCE_BYTES),
        ("max_traversal_entries", args.max_traversal_entries, 1, MAX_TRAVERSAL_ENTRIES),
    )
    result: dict[str, int] = {}
    for name, value, minimum, maximum in pairs:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ContextError(f"--{name.replace('_', '-')} must be between {minimum} and {maximum}")
        result[name] = value
    return result


def _dedupe_limitations(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[bytes] = set()
    result: list[dict[str, Any]] = []
    for item in value:
        encoded = _canonical_json(item)
        if encoded not in seen:
            seen.add(encoded)
            result.append(item)
    result.sort(key=lambda item: (item["code"], item["message"], item["paths"]))
    if len(result) > MAX_LIMITATIONS:
        raise ContextError(f"context exceeds {MAX_LIMITATIONS} limitations")
    return result


def resolve(args: argparse.Namespace) -> dict[str, Any]:
    limits = _validate_limits(args)
    require_git = args.scope in {"ref-range", "working-tree"}
    try:
        root, is_git = _repository_root(
            filesystem_path(args.repo, "repository path"), require_git=require_git
        )
    except SafetyError as exc:
        raise ContextError(str(exc)) from exc
    context_paths: list[str] = []
    for value in args.context or []:
        try:
            path = canonical_path(value)
        except SafetyError as exc:
            raise ContextError(str(exc)) from exc
        if path not in context_paths:
            context_paths.append(path)
    context_paths.sort()
    if len(context_paths) > limits["max_context_files"]:
        raise ContextError("context path count exceeds the configured limit")

    limitations: list[dict[str, Any]] = []
    if args.scope == "ref-range":
        base = _commit(root, args.base) if args.base else None
        head = _commit(root, args.head)
        if base is None:
            base = _commit(root, f"{head}^")
        changes = _ref_changes(root, base, head)
        request_kind = "ref_range"
        working_mode = None
        content_revision = head
        guidance_revision = base
        selectors: list[str] = []
    elif args.scope == "working-tree":
        base = _commit(root, "HEAD")
        head = None
        changes = _working_changes(root, base)
        request_kind = "working_tree"
        working_mode = "combined"
        content_revision = None
        guidance_revision = base
        selectors = []
    else:
        base = None
        head = None
        selectors = list(dict.fromkeys(args.paths))
        changes, path_limitations = _enumerate_explicit(
            root,
            selectors,
            git_repository=is_git,
            max_targets=limits["max_targets"],
            max_traversal=limits["max_traversal_entries"],
        )
        limitations.extend(path_limitations)
        request_kind = "paths"
        working_mode = None
        content_revision = None
        guidance_revision = None

    paths = _target_paths(changes)
    if len(paths) > limits["max_targets"]:
        limitations.append(
            _limitation("scope_limit", f"target exceeds {limits['max_targets']} paths")
        )
        changes = []
        paths = []
    if not paths:
        limitations.append(_limitation("empty_target", "selected target contains no changes or files"))
    overlap = sorted(set(paths) & set(context_paths))
    if overlap:
        raise ContextError(f"context paths overlap selected targets: {', '.join(overlap[:8])}")

    files: list[dict[str, Any]] = []
    for change in changes:
        source = change["source_path"] or change["path"]
        if change["status"] not in {"added", "untracked", "snapshot"}:
            files.append(
                _read_record(
                    root,
                    source,
                    "target_before",
                    base,
                    limits["max_file_bytes"],
                    limitations,
                )
            )
        if change["status"] != "deleted":
            files.append(
                _read_record(
                    root,
                    change["path"],
                    "target_after",
                    content_revision,
                    limits["max_file_bytes"],
                    limitations,
                )
            )
    for path in context_paths:
        record = _read_record(
            root,
            path,
            "context",
            content_revision,
            limits["max_file_bytes"],
            limitations,
        )
        if record["state"] != "text":
            limitations.append(
                _limitation(
                    "context_unavailable",
                    f"context path is not inspectable text: {path}",
                    [path],
                )
            )
        files.append(record)

    guidance = _guidance(
        root,
        paths,
        revision=guidance_revision,
        maximum=limits["max_guidance_bytes"],
        limitations=limitations,
    )
    total_bytes = sum(
        item["size"] or 0 for item in files if item["content"] is not None
    ) + sum(item["size"] for item in guidance)
    if total_bytes > limits["max_total_bytes"]:
        limitations.append(
            _limitation(
                "scope_limit",
                f"embedded content uses {total_bytes} bytes, above the {limits['max_total_bytes']} byte limit",
                paths,
            )
        )

    request_paths = selectors if request_kind == "paths" else paths
    result = {
        "schema_version": SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "request": {
            "kind": request_kind,
            "repository_root": str(root),
            "base_revision": base,
            "head_revision": head,
            "working_tree_mode": working_mode,
            "requested_paths": request_paths,
            "context_paths": context_paths,
        },
        "target": {"paths": paths, "changes": changes},
        "files": sorted(files, key=lambda item: (item["path"], item["role"], item["revision"] or "")),
        "guidance": guidance,
        "limits": limits,
        "limitations": _dedupe_limitations(limitations),
    }
    encoded = _canonical_json(result)
    if len(encoded) > MAX_JSON_BYTES:
        raise ContextError("canonical context exceeds the 16 MiB output limit")
    return validate_context(result)


def _args_from_context(context: dict[str, Any]) -> argparse.Namespace:
    request = context["request"]
    limits = context["limits"]
    common = {
        "repo": request["repository_root"],
        "context": request["context_paths"],
        **limits,
    }
    if request["kind"] == "ref_range":
        return SimpleNamespace(
            **common,
            scope="ref-range",
            base=request["base_revision"],
            head=request["head_revision"],
        )
    if request["kind"] == "working_tree":
        return SimpleNamespace(**common, scope="working-tree")
    return SimpleNamespace(**common, scope="paths", paths=request["requested_paths"])


def _shape_object(value: Any, label: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContextError(f"{label} has invalid fields or type")
    return value


def _shape_array(value: Any, label: str, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ContextError(f"{label} must be an array of at most {maximum} items")
    return value


def _shape_text(value: Any, label: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value) or len(value) > maximum:
        raise ContextError(f"{label} has invalid text")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ContextError(f"{label} contains unsupported control characters")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ContextError(f"{label} is not valid UTF-8") from exc
    return value


def _shape_path(value: Any, label: str, *, allow_root: bool = False) -> str:
    try:
        return canonical_path(value, allow_root=allow_root)
    except SafetyError as exc:
        raise ContextError(f"{label}: {exc}") from exc


def _shape_integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ContextError(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def _shape_revision(value: Any, label: str) -> str | None:
    if value is not None and (not isinstance(value, str) or not HEX_REVISION.fullmatch(value)):
        raise ContextError(f"{label} must be a canonical commit or null")
    return value


def validate_context(value: Any, *, revalidate_current: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContextError("context must be a JSON object")
    expected = {
        "schema_version",
        "skill_version",
        "request",
        "target",
        "files",
        "guidance",
        "limits",
        "limitations",
    }
    if set(value) != expected:
        raise ContextError("context has missing or unknown top-level fields")
    if value["schema_version"] != SCHEMA_VERSION or value["skill_version"] != SKILL_VERSION:
        raise ContextError("unsupported context schema or skill version")
    request = _shape_object(
        value["request"],
        "request",
        {"kind", "repository_root", "base_revision", "head_revision", "working_tree_mode", "requested_paths", "context_paths"},
    )
    if request["kind"] not in {"ref_range", "working_tree", "paths"}:
        raise ContextError("request.kind is invalid")
    _shape_text(request["repository_root"], "request.repository_root", 8192)
    base = _shape_revision(request["base_revision"], "request.base_revision")
    head = _shape_revision(request["head_revision"], "request.head_revision")
    if request["working_tree_mode"] not in {None, "combined"}:
        raise ContextError("request.working_tree_mode is invalid")
    requested = _shape_array(request["requested_paths"], "request.requested_paths", 5000)
    if len(requested) != len(set(requested)):
        raise ContextError("request.requested_paths must be unique")
    if request["kind"] == "paths":
        if not requested:
            raise ContextError("path snapshots require at least one requested path")
        for index, item in enumerate(requested):
            _shape_path(item, f"request.requested_paths[{index}]", allow_root=True)
        if base is not None or head is not None or request["working_tree_mode"] is not None:
            raise ContextError("path snapshots cannot carry Git target fields")
    else:
        for index, item in enumerate(requested):
            _shape_path(item, f"request.requested_paths[{index}]")
        if base is None:
            raise ContextError("Git targets require a base revision")
        if request["kind"] == "ref_range" and (head is None or request["working_tree_mode"] is not None):
            raise ContextError("ref-range target fields are inconsistent")
        if request["kind"] == "working_tree" and (head is not None or request["working_tree_mode"] != "combined"):
            raise ContextError("working-tree target fields are inconsistent")
    context_paths = [
        _shape_path(item, f"request.context_paths[{index}]")
        for index, item in enumerate(_shape_array(request["context_paths"], "request.context_paths", 1000))
    ]
    if context_paths != sorted(set(context_paths)):
        raise ContextError("request.context_paths must be sorted and unique")

    limits = _shape_object(
        value["limits"],
        "limits",
        {"max_targets", "max_context_files", "max_file_bytes", "max_total_bytes", "max_guidance_bytes", "max_traversal_entries"},
    )
    maxima = {
        "max_targets": (1, MAX_TARGETS),
        "max_context_files": (0, MAX_CONTEXT_FILES),
        "max_file_bytes": (1, MAX_FILE_BYTES),
        "max_total_bytes": (1, MAX_TOTAL_BYTES),
        "max_guidance_bytes": (1, MAX_GUIDANCE_BYTES),
        "max_traversal_entries": (1, MAX_TRAVERSAL_ENTRIES),
    }
    for key, (minimum, maximum) in maxima.items():
        _shape_integer(limits[key], f"limits.{key}", minimum, maximum)

    target = _shape_object(value["target"], "target", {"paths", "changes"})
    target_paths = [
        _shape_path(item, f"target.paths[{index}]")
        for index, item in enumerate(_shape_array(target["paths"], "target.paths", MAX_TARGETS))
    ]
    if target_paths != sorted(set(target_paths)):
        raise ContextError("target.paths must be sorted and unique")
    changes = _shape_array(target["changes"], "target.changes", MAX_TARGETS)
    normalized_changes = []
    for index, change_value in enumerate(changes):
        change = _shape_object(
            change_value,
            f"target.changes[{index}]",
            {"path", "source_path", "status"},
        )
        path = _shape_path(change["path"], f"target.changes[{index}].path")
        source_path = (
            None
            if change["source_path"] is None
            else _shape_path(change["source_path"], f"target.changes[{index}].source_path")
        )
        if change["status"] not in {
            "added", "deleted", "modified", "renamed", "copied", "type_changed", "unmerged", "untracked", "snapshot", "unknown"
        }:
            raise ContextError(f"target.changes[{index}].status is invalid")
        if (change["status"] in {"renamed", "copied"}) != (source_path is not None):
            raise ContextError(f"target.changes[{index}] source path is inconsistent")
        normalized_changes.append({"path": path, "source_path": source_path, "status": change["status"]})
    if normalized_changes != sorted(
        normalized_changes,
        key=lambda item: (item["path"], item["source_path"] or "", item["status"]),
    ):
        raise ContextError("target.changes are not canonically ordered")
    if _target_paths(normalized_changes) != target_paths:
        raise ContextError("target.paths do not match target.changes")
    if request["kind"] != "paths" and requested != target_paths:
        raise ContextError("Git request paths must match resolved target paths")
    if set(context_paths) & set(target_paths):
        raise ContextError("context paths overlap target paths")

    files = _shape_array(value["files"], "files", 11000)
    file_keys: set[tuple[str, str, str | None]] = set()
    embedded_total = 0
    for index, file_value in enumerate(files):
        item = _shape_object(
            file_value,
            f"files[{index}]",
            {"path", "role", "revision", "state", "size", "sha256", "line_count", "content"},
        )
        path = _shape_path(item["path"], f"files[{index}].path")
        if item["role"] not in {"target_before", "target_after", "context"}:
            raise ContextError(f"files[{index}].role is invalid")
        revision = _shape_revision(item["revision"], f"files[{index}].revision")
        key = (path, item["role"], revision)
        if key in file_keys:
            raise ContextError("files contain duplicate role/path/revision records")
        file_keys.add(key)
        if item["role"] == "context" and path not in context_paths:
            raise ContextError(f"files[{index}] context path was not requested")
        if item["role"] != "context" and path not in target_paths:
            raise ContextError(f"files[{index}] target path is outside target.paths")
        state = item["state"]
        if state not in {"text", "binary", "oversized", "unreadable", "absent"}:
            raise ContextError(f"files[{index}].state is invalid")
        size = item["size"]
        digest = item["sha256"]
        line_count = item["line_count"]
        content = item["content"]
        if state == "text":
            content = _shape_text(content, f"files[{index}].content", MAX_FILE_BYTES, empty=True)
            normalized = content.encode("utf-8")
            if size != len(normalized) or digest != hashlib.sha256(normalized).hexdigest():
                raise ContextError(f"files[{index}] text size or digest is invalid")
            if line_count != _line_count(content):
                raise ContextError(f"files[{index}].line_count is invalid")
            embedded_total += size
        elif state == "binary":
            _shape_integer(size, f"files[{index}].size", 0, MAX_FILE_BYTES)
            if not isinstance(digest, str) or not HEX64.fullmatch(digest):
                raise ContextError(f"files[{index}].sha256 is invalid")
            if line_count is not None or content is not None:
                raise ContextError(f"files[{index}] binary fields are inconsistent")
        else:
            if size is not None:
                raise ContextError(f"files[{index}].size must be null")
            if digest is not None or line_count is not None or content is not None:
                raise ContextError(f"files[{index}] unavailable fields must be null")
    if sorted(file_keys) != [(item["path"], item["role"], item["revision"]) for item in files]:
        raise ContextError("files are not canonically ordered")
    if {key[0] for key in file_keys if key[1] == "context"} != set(context_paths):
        raise ContextError("context path inventory is incomplete")
    expected_target_keys: set[tuple[str, str, str | None]] = set()
    content_revision = head if request["kind"] == "ref_range" else None
    for change in normalized_changes:
        source = change["source_path"] or change["path"]
        if change["status"] not in {"added", "untracked", "snapshot"}:
            expected_target_keys.add((source, "target_before", base))
        if change["status"] != "deleted":
            expected_target_keys.add((change["path"], "target_after", content_revision))
    actual_target_keys = {key for key in file_keys if key[1] != "context"}
    if actual_target_keys != expected_target_keys:
        raise ContextError("target file inventory does not match target.changes")

    guidance = _shape_array(value["guidance"], "guidance", 10000)
    guidance_keys: list[tuple[str, str]] = []
    for index, source_value in enumerate(guidance):
        source = _shape_object(
            source_value,
            f"guidance[{index}]",
            {"kind", "path", "revision", "applies_to", "size", "sha256", "content"},
        )
        if source["kind"] not in {"review", "verification"}:
            raise ContextError(f"guidance[{index}].kind is invalid")
        path = _shape_path(source["path"], f"guidance[{index}].path")
        guidance_keys.append((source["kind"], path))
        _shape_revision(source["revision"], f"guidance[{index}].revision")
        applies = [
            _shape_path(item, f"guidance[{index}].applies_to[{item_index}]")
            for item_index, item in enumerate(_shape_array(source["applies_to"], f"guidance[{index}].applies_to", MAX_TARGETS))
        ]
        if not applies or applies != sorted(set(applies)) or set(applies) - set(target_paths):
            raise ContextError(f"guidance[{index}].applies_to is invalid")
        content = _shape_text(source["content"], f"guidance[{index}].content", MAX_GUIDANCE_BYTES, empty=True)
        normalized = content.encode("utf-8")
        if source["size"] != len(normalized) or source["sha256"] != hashlib.sha256(normalized).hexdigest():
            raise ContextError(f"guidance[{index}] size or digest is invalid")
        embedded_total += source["size"]
    if guidance_keys != sorted(set(guidance_keys)):
        raise ContextError("guidance is not canonically ordered and unique")
    if embedded_total > limits["max_total_bytes"] and not any(
        isinstance(item, dict) and item.get("code") == "scope_limit"
        for item in value["limitations"]
    ):
        raise ContextError("embedded content exceeds max_total_bytes without a limitation")

    limitations = _shape_array(value["limitations"], "limitations", MAX_LIMITATIONS)
    for index, limitation_value in enumerate(limitations):
        item = _shape_object(
            limitation_value,
            f"limitations[{index}]",
            {"code", "message", "paths", "material"},
        )
        if item["code"] not in {
            "empty_target", "scope_limit", "traversal_limit", "unsafe_path", "file_unreadable", "file_non_text", "file_oversized", "guidance_unavailable", "context_unavailable", "target_drift", "other"
        }:
            raise ContextError(f"limitations[{index}].code is invalid")
        _shape_text(item["message"], f"limitations[{index}].message", 4096)
        paths_value = [
            _shape_path(path, f"limitations[{index}].paths[{path_index}]")
            for path_index, path in enumerate(_shape_array(item["paths"], f"limitations[{index}].paths", MAX_TARGETS))
        ]
        if paths_value != sorted(set(paths_value)):
            raise ContextError(f"limitations[{index}].paths must be sorted and unique")
        if not isinstance(item["material"], bool):
            raise ContextError(f"limitations[{index}].material must be boolean")
    encoded = _canonical_json(value)
    if len(_machine_json(value)) > MAX_JSON_BYTES:
        raise ContextError("canonical context exceeds the 16 MiB output limit")
    if revalidate_current:
        try:
            refreshed = resolve(_args_from_context(value))
        except (KeyError, TypeError, SafetyError) as exc:
            raise ContextError(f"cannot revalidate malformed context: {exc}") from exc
        if _canonical_json(refreshed) != encoded:
            raise ContextError("target or context changed after impact resolution")
    return value


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _parse_json(data: bytes, label: str) -> Any:
    if len(data) > MAX_JSON_BYTES:
        raise ContextError(f"{label} exceeds the 16 MiB input limit")
    try:
        value = json.loads(
            data.decode("utf-8", "strict"),
            object_pairs_hook=_reject_duplicate_members,
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ContextError(f"cannot parse {label}: {exc}") from exc
    pending = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise ContextError(f"cannot parse {label}: JSON nesting exceeds {MAX_JSON_DEPTH}")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def _read_json(path: str) -> Any:
    if path == "-":
        return _parse_json(sys.stdin.buffer.read(MAX_JSON_BYTES + 1), "JSON input")
    candidate = filesystem_path(path, "JSON input path")
    try:
        _, data = read_regular(candidate, MAX_JSON_BYTES, require_single_link=True)
        return _parse_json(data, "JSON input")
    except (OSError, SafetyError) as exc:
        raise ContextError(f"cannot read JSON input: {exc}") from exc


def _emit(value: Any, output: str | None) -> None:
    data = _machine_json(value)
    if len(data) > MAX_JSON_BYTES:
        raise ContextError("formatted context exceeds the 16 MiB output limit")
    if output is None:
        sys.stdout.buffer.write(data)
        return
    try:
        write_created_output(filesystem_path(output, "output path"), data)
    except SafetyError as exc:
        raise ContextError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--context", action="append", default=[])
    parser.add_argument("--output")
    parser.add_argument("--max-targets", type=int, default=DEFAULT_MAX_TARGETS)
    parser.add_argument("--max-context-files", type=int, default=DEFAULT_MAX_CONTEXT_FILES)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    parser.add_argument("--max-guidance-bytes", type=int, default=DEFAULT_MAX_GUIDANCE_BYTES)
    parser.add_argument("--max-traversal-entries", type=int, default=DEFAULT_MAX_TRAVERSAL_ENTRIES)
    commands = parser.add_subparsers(dest="scope", required=True)
    command = commands.add_parser("ref-range")
    command.add_argument("--base")
    command.add_argument("--head", required=True)
    commands.add_parser("working-tree")
    command = commands.add_parser("paths")
    command.add_argument("paths", nargs="+")
    command = commands.add_parser("validate")
    command.add_argument("--input", default="-")
    command.add_argument("--current", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.scope == "validate":
            value = validate_context(_read_json(args.input), revalidate_current=args.current)
        else:
            value = resolve(args)
        _emit(value, args.output)
        return 0
    except (ContextError, SafetyError) as exc:
        print(f"change-impact context: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
