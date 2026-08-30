#!/usr/bin/env python3
"""Resolve bounded current-filesystem targets and hierarchical REVIEW.md context."""

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
from typing import Any


SCHEMA_VERSION = "1.0"
SKILL_VERSION = "1.0.0"
DEFAULT_MAX_FILES = 5000
MAX_FILES = 10000
MAX_REQUESTED_TARGETS = 1000
MAX_GUIDANCE_SOURCES_PER_CHAIN = 256
MAX_UNIQUE_GUIDANCE_SOURCES = 100000
MAX_LIMITATIONS = 128
DEFAULT_MAX_GUIDANCE_BYTES = 131072
MAX_GUIDANCE_SOURCE_BYTES = 1048576
MAX_INSPECTION_FILE_BYTES = 16777216
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ContextError(ValueError):
    """Raised when target or guidance resolution cannot proceed safely."""


def _filesystem_path(
    value: str, label: str, *, expand_user: bool = False
) -> Path:
    if not isinstance(value, str) or not value:
        raise ContextError(f"{label} must be a non-empty path")
    if CONTROL.search(value):
        raise ContextError(f"{label} must not contain control characters")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ContextError(f"{label} must be valid UTF-8") from exc
    path = Path(value)
    return path.expanduser() if expand_user else path


def _has_link_flag(path: Path) -> bool:
    try:
        value = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(value.st_mode):
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(value, "st_file_attributes", 0)
    return bool(reparse and attributes & reparse)


def _assert_no_link_components(path: Path, *, include_final: bool) -> None:
    absolute = path.absolute()
    parts = absolute.parts[1:] if include_final else absolute.parts[1:-1]
    current = Path(absolute.anchor)
    for part in parts:
        current /= part
        if _has_link_flag(current):
            raise ContextError(f"refusing link-like path component: {current}")


def _canonical_path(value: str, *, allow_root: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise ContextError("repository paths must be non-empty strings")
    if CONTROL.search(value):
        raise ContextError("repository paths must not contain control characters")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ContextError("repository paths must be valid UTF-8") from exc
    if "\\" in value or value.startswith("/") or value.startswith("//"):
        raise ContextError(f"repository path is not canonical: {value!r}")
    if re.match(r"^[A-Za-z]:", value):
        raise ContextError(f"repository path is not canonical: {value!r}")
    if value == ".":
        if allow_root:
            return value
        raise ContextError("the repository root is not valid in this field")
    if value.endswith("/") or "//" in value:
        raise ContextError(f"repository path is not canonical: {value!r}")
    parts = PurePosixPath(value).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ContextError(f"repository path is not canonical: {value!r}")
    canonical = PurePosixPath(*parts).as_posix()
    if canonical != value:
        raise ContextError(f"repository path is not canonical: {value!r}")
    return canonical


def _safe_repo_path(root: Path, relative: str) -> Path:
    canonical = _canonical_path(relative, allow_root=True)
    current = root
    if canonical == ".":
        return current
    for index, part in enumerate(PurePosixPath(canonical).parts):
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ContextError(f"cannot inspect {canonical}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode) or _has_link_flag(current):
            raise ContextError(f"refusing link-like path: {canonical}")
        if index < len(PurePosixPath(canonical).parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise ContextError(f"non-directory path component in {canonical}")
    return current


def _read_regular_bytes(path: Path, *, maximum: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ContextError(f"cannot open {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ContextError(f"not a regular file: {path}")
        if metadata.st_size > maximum:
            raise ContextError(f"file exceeds {maximum} bytes: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise ContextError(f"file exceeds {maximum} bytes: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _normalized_text(data: bytes, label: str) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContextError(f"{label} is not UTF-8 text") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_root(root: Path) -> bool:
    try:
        process = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if process.returncode != 0:
        return False
    try:
        return Path(process.stdout.strip()).resolve() == root.resolve()
    except OSError:
        return False


def _git_candidates(root: Path, directory: str) -> list[str] | None:
    if not _git_root(root):
        return None
    command = ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"]
    if directory != ".":
        command.extend(["--", directory])
    try:
        process = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if process.returncode != 0:
        return None
    prefix = "" if directory == "." else f"{directory}/"
    values: list[str] = []
    for raw in process.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            value = raw.decode("utf-8")
            canonical = _canonical_path(value)
        except (UnicodeDecodeError, ContextError) as exc:
            raise ContextError(
                "repository contains a non-UTF-8 or non-canonical path"
            ) from exc
        if directory == "." or canonical == directory or canonical.startswith(prefix):
            values.append(canonical)
    return sorted(set(values))


def _walk_candidates(
    root: Path, directory: str
) -> tuple[list[str], list[tuple[str, str]]]:
    base = root if directory == "." else _safe_repo_path(root, directory)
    values: list[str] = []
    skipped: list[tuple[str, str]] = []

    def record_walk_error(error: OSError) -> None:
        relative = directory
        if error.filename:
            try:
                relative = _canonical_path(
                    Path(error.filename).relative_to(root).as_posix(), allow_root=True
                )
            except (OSError, ValueError, ContextError):
                pass
        skipped.append(
            (
                relative,
                f"Safe fallback traversal could not read directory: {relative}",
            )
        )

    for current, directories, files in os.walk(
        base, followlinks=False, onerror=record_walk_error
    ):
        current_path = Path(current)
        kept_directories: list[str] = []
        for name in sorted(directories):
            child = current_path / name
            if name == ".git":
                continue
            if _has_link_flag(child):
                try:
                    relative = child.relative_to(root).as_posix()
                    canonical = _canonical_path(relative)
                except (OSError, ValueError, ContextError) as exc:
                    raise ContextError(
                        "fallback traversal found an unrepresentable directory path"
                    ) from exc
                skipped.append(
                    (
                        canonical,
                        f"Safe fallback traversal skipped link-like directory: {canonical}",
                    )
                )
                continue
            kept_directories.append(name)
        directories[:] = kept_directories
        for name in sorted(files):
            candidate = current_path / name
            try:
                relative = candidate.relative_to(root).as_posix()
                values.append(_canonical_path(relative))
            except (OSError, ValueError, ContextError) as exc:
                raise ContextError(
                    "fallback traversal found an unrepresentable file path"
                ) from exc
    return sorted(set(values)), sorted(set(skipped))


def _enumerate_directory(
    root: Path, relative: str
) -> tuple[list[str], bool, list[tuple[str, str]]]:
    candidates = _git_candidates(root, relative)
    if candidates is not None:
        return candidates, True, []
    discovered, skipped = _walk_candidates(root, relative)
    return discovered, False, skipped


def _file_record(root: Path, relative: str) -> dict[str, Any]:
    path = _safe_repo_path(root, relative)
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ContextError(f"target is not a regular file: {relative}")
    record: dict[str, Any] = {
        "path": relative,
        "bytes": metadata.st_size,
        "sha256": None,
        "inspection_kind": "text",
    }
    if metadata.st_size > MAX_INSPECTION_FILE_BYTES:
        record["inspection_kind"] = "oversized"
        return record
    try:
        data = _read_regular_bytes(path, maximum=MAX_INSPECTION_FILE_BYTES)
    except ContextError:
        record["inspection_kind"] = "unreadable"
        return record
    record["sha256"] = _sha256(data)
    if b"\0" in data:
        record["inspection_kind"] = "binary"
        return record
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        record["inspection_kind"] = "non_utf8"
    return record


def _parse_part(value: str) -> dict[str, Any]:
    try:
        path, start, end = value.rsplit(":", 2)
        start_line = int(start)
        end_line = int(end)
    except (ValueError, TypeError) as exc:
        raise ContextError("parts must use PATH:START_LINE:END_LINE") from exc
    canonical = _canonical_path(path)
    if start_line < 1 or end_line < start_line:
        raise ContextError("part line ranges must be positive and ordered")
    return {
        "kind": "part",
        "path": canonical,
        "start_line": start_line,
        "end_line": end_line,
    }


def _guidance_paths(target: str) -> list[str]:
    parent = PurePosixPath(target).parent
    paths = ["REVIEW.md"]
    current = PurePosixPath()
    if parent.as_posix() == ".":
        return paths
    for part in parent.parts:
        current /= part
        paths.append((current / "REVIEW.md").as_posix())
    return paths


def _source_from_bytes(
    *, source_kind: str, path: str, data: bytes, content_allowed: bool
) -> dict[str, Any]:
    text = _normalized_text(data, path)
    normalized = text.encode("utf-8")
    return {
        "source_kind": source_kind,
        "path": path,
        "revision": None,
        "sha256": _sha256(normalized),
        "bytes": len(normalized),
        "words": len(text.split()),
        "lines": len(text.splitlines()),
        "content": text if content_allowed else None,
        "loaded": content_allowed,
    }


def _read_global_source(path_value: str) -> dict[str, Any]:
    path = _filesystem_path(path_value, "global review file", expand_user=True)
    if not path.is_absolute():
        raise ContextError("global review file must be an absolute path")
    _filesystem_path(str(path), "global review file")
    _assert_no_link_components(path, include_final=True)
    data = _read_regular_bytes(path, maximum=MAX_GUIDANCE_SOURCE_BYTES)
    return _source_from_bytes(
        source_kind="user_global",
        path=str(path),
        data=data,
        content_allowed=True,
    )


def _read_repository_source(root: Path, relative: str) -> dict[str, Any] | None:
    candidate = root / PurePosixPath(relative)
    try:
        candidate.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ContextError(f"cannot inspect guidance {relative}: {exc}") from exc
    path = _safe_repo_path(root, relative)
    data = _read_regular_bytes(path, maximum=MAX_GUIDANCE_SOURCE_BYTES)
    return _source_from_bytes(
        source_kind="repository",
        path=relative,
        data=data,
        content_allowed=True,
    )


def _skill_source() -> dict[str, Any]:
    skill_file = Path(__file__).resolve().parents[1] / "SKILL.md"
    data = _read_regular_bytes(skill_file, maximum=MAX_GUIDANCE_SOURCE_BYTES)
    source = _source_from_bytes(
        source_kind="skill", path="SKILL.md", data=data, content_allowed=False
    )
    source["revision"] = f"review-guidance-audit@{SKILL_VERSION}"
    return source


def _limitation(code: str, message: str, paths: list[str], material: bool) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "affected_paths": sorted(set(paths)),
        "material": material,
    }


def _dedupe_limitations(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        key = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            result.append(value)
    if len(result) <= MAX_LIMITATIONS:
        return result
    omitted = len(result) - (MAX_LIMITATIONS - 1)
    return [
        *result[: MAX_LIMITATIONS - 1],
        _limitation(
            "scope_truncated",
            f"Resolver omitted {omitted} additional limitation records to stay within the canonical result ceiling.",
            [],
            True,
        ),
    ]


def resolve(args: argparse.Namespace) -> dict[str, Any]:
    root_input = _filesystem_path(args.repo, "repository root", expand_user=True)
    _assert_no_link_components(root_input, include_final=True)
    root = root_input.resolve()
    _filesystem_path(str(root), "repository root")
    if not root.is_dir():
        raise ContextError("repository root must be a non-link directory")
    if args.max_files < 1 or args.max_files > MAX_FILES:
        raise ContextError(f"max-files must be between 1 and {MAX_FILES}")
    if args.max_guidance_bytes < 1024 or args.max_guidance_bytes > MAX_GUIDANCE_SOURCE_BYTES:
        raise ContextError(
            f"max-guidance-bytes must be between 1024 and {MAX_GUIDANCE_SOURCE_BYTES}"
        )

    requested: list[dict[str, Any]] = []
    paths = list(args.paths or [])
    if not paths and not args.parts:
        raise ContextError("select at least one --path or --part")
    for value in paths:
        canonical = _canonical_path(value, allow_root=True)
        path = _safe_repo_path(root, canonical)
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            requested.append(
                {"kind": "project" if canonical == "." else "directory", "path": canonical,
                 "start_line": None, "end_line": None}
            )
        elif stat.S_ISREG(metadata.st_mode):
            requested.append(
                {"kind": "file", "path": canonical, "start_line": None, "end_line": None}
            )
        else:
            raise ContextError(f"target is not a regular file or directory: {canonical}")
    for raw in args.parts or []:
        part = _parse_part(raw)
        target_file = _safe_repo_path(root, part["path"])
        if not stat.S_ISREG(target_file.lstat().st_mode):
            raise ContextError(f"part target is not a regular file: {part['path']}")
        requested.append(part)

    unique_requested: list[dict[str, Any]] = []
    seen_requested: set[str] = set()
    for item in requested:
        key = json.dumps(item, sort_keys=True, separators=(",", ":"))
        if key not in seen_requested:
            seen_requested.add(key)
            unique_requested.append(item)
    if len(unique_requested) > MAX_REQUESTED_TARGETS:
        raise ContextError(
            f"requested target selection exceeds {MAX_REQUESTED_TARGETS} entries"
        )
    requested = [
        {"target_id": f"T{index:03d}", **item}
        for index, item in enumerate(unique_requested, 1)
    ]

    candidates: set[str] = set()
    limitations: list[dict[str, Any]] = []
    used_git = True
    for item in requested:
        if item["kind"] in {"file", "part"}:
            candidates.add(item["path"])
            continue
        discovered, git_used, skipped = _enumerate_directory(root, item["path"])
        used_git = used_git and git_used
        candidates.update(discovered)
        for skipped_path, message in skipped:
            limitations.append(
                _limitation(
                    "target_unreadable",
                    message,
                    [] if skipped_path == "." else [skipped_path],
                    True,
                )
            )
    ordered_candidates = sorted(candidates)
    if len(ordered_candidates) > args.max_files:
        omitted = len(ordered_candidates) - args.max_files
        ordered_candidates = ordered_candidates[: args.max_files]
        limitations.append(
            _limitation(
                "scope_truncated",
                f"Target discovery exceeded the technical ceiling by {omitted} files.",
                [],
                True,
            )
        )
    files: list[dict[str, Any]] = []
    for relative in ordered_candidates:
        try:
            files.append(_file_record(root, relative))
        except ContextError as exc:
            limitations.append(_limitation("target_unreadable", str(exc), [relative], True))
    for record in files:
        if record["inspection_kind"] != "text":
            limitations.append(
                _limitation(
                    "target_unreadable",
                    f"Target cannot be inspected as UTF-8 text ({record['inspection_kind']}): {record['path']}",
                    [record["path"]],
                    True,
                )
            )
    file_paths = {item["path"] for item in files}
    for item in requested:
        if item["kind"] == "part" and item["path"] in file_paths:
            record = next(value for value in files if value["path"] == item["path"])
            if record["inspection_kind"] != "text":
                limitations.append(
                    _limitation(
                        "part_unreadable",
                        f"Part target is not readable UTF-8 text: {item['path']}",
                        [item["path"]],
                        True,
                    )
                )
            else:
                data = _read_regular_bytes(root / item["path"], maximum=MAX_INSPECTION_FILE_BYTES)
                line_count = len(_normalized_text(data, item["path"]).splitlines())
                if item["end_line"] > max(1, line_count):
                    raise ContextError(
                        f"part range exceeds the file length for {item['path']}"
                    )

    global_source = _read_global_source(args.global_review_file) if args.global_review_file else None
    skill_source = _skill_source()
    known_source_identities = {
        (skill_source["source_kind"], skill_source["path"], skill_source["sha256"])
    }
    if global_source:
        known_source_identities.add(
            (
                global_source["source_kind"],
                global_source["path"],
                global_source["sha256"],
            )
        )
    repository_cache: dict[str, dict[str, Any] | None] = {}
    chains: list[dict[str, Any]] = []
    chain_index: dict[str, dict[str, Any]] = {}
    per_source: dict[tuple[str, str, str], dict[str, Any]] = {}
    for relative in sorted(file_paths):
        sources = [dict(skill_source)]
        if global_source:
            sources.append(dict(global_source))
        guidance_omitted = False
        for guidance_path in _guidance_paths(relative):
            if len(sources) >= MAX_GUIDANCE_SOURCES_PER_CHAIN:
                guidance_omitted = True
                continue
            if guidance_path not in repository_cache:
                try:
                    repository_cache[guidance_path] = _read_repository_source(root, guidance_path)
                except ContextError as exc:
                    repository_cache[guidance_path] = None
                    limitations.append(
                        _limitation("guidance_unreadable", str(exc), [relative], True)
                    )
            source = repository_cache[guidance_path]
            if source:
                identity = (
                    source["source_kind"],
                    source["path"],
                    source["sha256"],
                )
                if (
                    identity not in known_source_identities
                    and len(known_source_identities) >= MAX_UNIQUE_GUIDANCE_SOURCES
                ):
                    guidance_omitted = True
                    continue
                sources.append(dict(source))
                known_source_identities.add(identity)
        if guidance_omitted:
            limitations.append(
                _limitation(
                    "guidance_budget",
                    f"Applicable guidance for {relative} exceeds the canonical provenance ceiling.",
                    [relative],
                    True,
                )
            )
        loaded_bytes = 0
        chain_complete = not any(
            limitation["material"]
            and limitation["code"] == "guidance_unreadable"
            and relative in limitation["affected_paths"]
            for limitation in limitations
        ) and not guidance_omitted
        for source in sources:
            if source["source_kind"] == "skill":
                continue
            if loaded_bytes + source["bytes"] > args.max_guidance_bytes:
                source["content"] = None
                source["loaded"] = False
                chain_complete = False
                limitations.append(
                    _limitation(
                        "guidance_budget",
                        f"Effective guidance for {relative} exceeds the technical loading ceiling; {source['path']} was not loaded.",
                        [relative],
                        True,
                    )
                )
            else:
                loaded_bytes += source["bytes"]
        identity = json.dumps(
            [
                chain_complete,
                *[
                    (item["source_kind"], item["path"], item["sha256"], item["loaded"])
                    for item in sources
                ],
            ],
            separators=(",", ":"),
        )
        if identity not in chain_index:
            chain = {
                "chain_id": f"G{len(chains) + 1:03d}",
                "applies_to": [],
                "sources": sources,
                "effective_bytes": sum(item["bytes"] for item in sources if item["source_kind"] != "skill"),
                "effective_words": sum(item["words"] for item in sources if item["source_kind"] != "skill"),
                "complete": chain_complete,
            }
            chain_index[identity] = chain
            chains.append(chain)
        chain_index[identity]["applies_to"].append(relative)
        for source in sources:
            key = (source["source_kind"], source["path"], source["sha256"])
            if key not in per_source:
                per_source[key] = {
                    "source_kind": source["source_kind"],
                    "path": source["path"],
                    "sha256": source["sha256"],
                    "bytes": source["bytes"],
                    "words": source["words"],
                    "lines": source["lines"],
                    "fanout": 0,
                }
            per_source[key]["fanout"] += 1
    effective_words = sorted(chain["effective_words"] for chain in chains)
    median_words = 0
    if effective_words:
        middle = len(effective_words) // 2
        median_words = (
            effective_words[middle]
            if len(effective_words) % 2
            else (effective_words[middle - 1] + effective_words[middle]) // 2
        )
    context = {
        "schema_version": SCHEMA_VERSION,
        "target": {
            "kind": "current_filesystem",
            "repository_root": str(root),
            "requested": requested,
            "files": files,
        },
        "guidance": chains,
        "context_metrics": {
            "source_count": len(per_source),
            "chain_count": len(chains),
            "maximum_effective_words": max(effective_words, default=0),
            "median_effective_words": median_words,
            "per_source": sorted(per_source.values(), key=lambda value: (value["source_kind"], value["path"])),
        },
        "discovery": {
            "git_ignore_rules_used": used_git if any(item["kind"] in {"directory", "project"} for item in requested) else None,
            "max_files": args.max_files,
            "max_guidance_bytes": args.max_guidance_bytes,
        },
        "limitations": _dedupe_limitations(limitations),
    }
    return context


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="repository root")
    parser.add_argument("--path", dest="paths", action="append", help="file, directory, or .")
    parser.add_argument("--part", dest="parts", action="append", help="PATH:START_LINE:END_LINE")
    parser.add_argument("--global-review-file", help="absolute active-agent REVIEW.md")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-guidance-bytes", type=int, default=DEFAULT_MAX_GUIDANCE_BYTES)
    parser.add_argument("--output", help="create a new context JSON file instead of stdout")
    return parser


def _write_context(result: dict[str, Any], destination: str | None) -> None:
    text = json.dumps(result, indent=2, ensure_ascii=True, sort_keys=True) + "\n"
    if destination is None:
        sys.stdout.write(text)
        return
    path = _filesystem_path(destination, "output path")
    _assert_no_link_components(path, include_final=False)
    if not path.parent.exists() or not path.parent.is_dir():
        raise ContextError(f"output parent does not exist: {path.parent}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ContextError(f"cannot create output {path}: {exc}") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(text.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = resolve(args)
        _write_context(result, args.output)
        return 0
    except ContextError as exc:
        print(f"review-guidance context: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
