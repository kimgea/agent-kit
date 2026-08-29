#!/usr/bin/env python3
"""Resolve bounded review targets and trusted hierarchical REVIEW.md guidance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "1.0.0"
SKILL_VERSION = "1.0.0"
DEFAULT_MAX_GUIDANCE_BYTES = 32768
DEFAULT_MAX_TARGETS = 250
GIT_TIMEOUT_SECONDS = 30
MAX_GUIDANCE_SOURCE_BYTES = 1048576
MAX_GUIDANCE_CHAINS = 512
MAX_GUIDANCE_SOURCES_PER_CHAIN = 128
MAX_LIMITATIONS = 256
STATUS_NAMES = {
    "A": "added",
    "C": "copied",
    "D": "deleted",
    "M": "modified",
    "R": "renamed",
    "T": "type_changed",
    "U": "unmerged",
    "X": "unknown",
    "B": "broken_pairing",
}
SAFE_PATH = re.compile(
    r"^(?!/)(?![A-Za-z]:)(?!.*\\)(?!.*[\x00-\x1f\x7f])"
    r"(?!.*(?:^|/)\.\.(?:/|$)).+$"
)


class ContextError(RuntimeError):
    """Raised when a review context cannot be resolved safely."""


def _git(root: Path, arguments: list[str], check: bool = True) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment.update({"GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContextError(f"cannot run Git safely: {exc}") from exc
    if check and completed.returncode != 0:
        error = completed.stderr.decode("utf-8", "replace").strip()
        raise ContextError(error or f"Git command failed with exit code {completed.returncode}")
    return completed


def _repository_root(candidate: Path, require_git: bool) -> tuple[Path, bool]:
    root = candidate.resolve()
    if not root.is_dir():
        raise ContextError(f"repository path is not a directory: {root}")
    completed = _git(root, ["rev-parse", "--show-toplevel"], check=False)
    if completed.returncode == 0:
        discovered = Path(completed.stdout.decode("utf-8", "replace").strip()).resolve()
        if not discovered.is_dir():
            raise ContextError("Git returned an invalid repository root")
        return discovered, True
    if require_git:
        raise ContextError("this review scope requires a Git repository")
    return root, False


def _commit(root: Path, revision: str) -> str:
    if not revision or "\x00" in revision or len(revision) > 512:
        raise ContextError("revision must be a non-empty value of at most 512 characters")
    completed = _git(root, ["rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"])
    value = completed.stdout.decode("ascii", "strict").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", value):
        raise ContextError(f"Git returned an invalid commit for {revision!r}")
    return value.lower()


def _canonical_git_path(value: str) -> str:
    if not SAFE_PATH.fullmatch(value):
        raise ContextError(f"unsafe or non-portable repository path: {value!r}")
    normalized = PurePosixPath(value).as_posix()
    if normalized in {"", "."} or normalized.startswith("../"):
        raise ContextError(f"unsafe repository path: {value!r}")
    return normalized


def _canonical_snapshot_path(root: Path, path: Path) -> str:
    value = path.relative_to(root).as_posix()
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ContextError(f"snapshot path is not valid UTF-8: {value!r}") from exc
    return _canonical_git_path(value)


def _decode_path(value: bytes) -> str:
    try:
        return _canonical_git_path(value.decode("utf-8", "strict"))
    except UnicodeDecodeError as exc:
        raise ContextError("repository contains a non-UTF-8 path") from exc


def _parse_name_status(payload: bytes) -> list[dict[str, Any]]:
    tokens = payload.split(b"\0")
    if tokens and not tokens[-1]:
        tokens.pop()
    changes: list[dict[str, Any]] = []
    index = 0
    while index < len(tokens):
        status_token = tokens[index].decode("ascii", "replace")
        index += 1
        code = status_token[:1]
        if code not in STATUS_NAMES:
            raise ContextError(f"unsupported Git change status: {status_token!r}")
        if code in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise ContextError("malformed Git rename/copy record")
            old_path = _decode_path(tokens[index])
            path = _decode_path(tokens[index + 1])
            index += 2
        else:
            if index >= len(tokens):
                raise ContextError("malformed Git change record")
            old_path = None
            path = _decode_path(tokens[index])
            index += 1
        changes.append(
            {
                "path": path,
                "old_path": old_path,
                "status": STATUS_NAMES[code],
                "similarity": int(status_token[1:]) if status_token[1:].isdigit() else None,
            }
        )
    return changes


def _diff_changes(root: Path, arguments: list[str]) -> list[dict[str, Any]]:
    completed = _git(root, ["diff", "--name-status", "-z", "--find-renames", *arguments, "--"])
    return _parse_name_status(completed.stdout)


def _untracked_changes(root: Path) -> list[dict[str, Any]]:
    completed = _git(root, ["ls-files", "--others", "--exclude-standard", "-z"])
    paths = completed.stdout.split(b"\0")
    return [
        {"path": _decode_path(path), "old_path": None, "status": "untracked", "similarity": None}
        for path in paths
        if path
    ]


def _merge_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str | None, str], dict[str, Any]] = {}
    for change in changes:
        key = (change["old_path"], change["path"])
        existing = merged.get(key)
        if existing is None or existing["status"] == change["status"]:
            merged[key] = change
        elif {existing["status"], change["status"]} == {"deleted", "untracked"}:
            merged[key] = {
                "path": change["path"],
                "old_path": None,
                "status": "replaced",
                "similarity": None,
            }
        else:
            raise ContextError(
                f"cannot represent layered change statuses for {change['path']}: "
                f"{existing['status']} and {change['status']}"
            )
    return sorted(merged.values(), key=lambda item: (item["path"], item["old_path"] or ""))


def _is_link_like(metadata: os.stat_result) -> bool:
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _has_symlink_component(root: Path, candidate: Path) -> bool:
    relative = candidate.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ContextError(f"cannot inspect explicit path component {current}: {exc}") from exc
        if _is_link_like(metadata):
            return True
    return False


def _current_relative_path(root: Path, value: str) -> Path:
    supplied = Path(value)
    candidate = supplied if supplied.is_absolute() else root / supplied
    candidate = Path(os.path.abspath(candidate))
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ContextError(f"explicit path escapes the project root: {value}") from exc
    if _has_symlink_component(root, candidate):
        raise ContextError(f"explicit path contains a symlink: {value}")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ContextError(f"explicit path escapes the project root: {value}") from exc
    return resolved


def _snapshot_changes(
    root: Path,
    values: list[str],
    max_targets: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paths: set[str] = set()
    limitations: list[dict[str, Any]] = []
    truncated = False
    first_omitted: str | None = None
    for value in sorted(set(values)):
        try:
            candidate = _current_relative_path(root, value)
        except ContextError as exc:
            limitations.append(_limitation("scope_unavailable", str(exc), [], True))
            continue
        if not candidate.exists():
            limitations.append(
                _limitation("scope_unavailable", f"explicit path does not exist: {value}", [], True)
            )
            continue
        if candidate != root:
            try:
                candidate_relative = _canonical_snapshot_path(root, candidate)
            except ContextError as exc:
                limitations.append(_limitation("scope_unavailable", str(exc), [], True))
                continue
        else:
            candidate_relative = None
        if candidate.is_file():
            paths.add(candidate_relative)
            continue
        if not candidate.is_dir():
            limitations.append(
                _limitation("scope_unavailable", f"explicit path is not a regular file or directory: {value}", [], True)
            )
            continue
        pending: list[tuple[Path, os.stat_result]] = []
        try:
            with os.scandir(candidate) as entries:
                initial = sorted(entries, key=lambda entry: entry.name)
        except OSError as exc:
            limitations.append(
                _limitation(
                    "scope_unavailable",
                    f"cannot enumerate directory {candidate_relative or '.'}: {exc}",
                    [candidate_relative] if candidate_relative is not None else [],
                    True,
                )
            )
            continue
        for entry in reversed(initial):
            child = Path(entry.path)
            try:
                pending.append((child, entry.stat(follow_symlinks=False)))
            except OSError as exc:
                try:
                    child_text = _canonical_snapshot_path(root, child)
                except ContextError as path_exc:
                    limitations.append(_limitation("scope_unavailable", str(path_exc), [], True))
                    continue
                limitations.append(
                    _limitation(
                        "file_unreadable",
                        f"cannot inspect target {child_text}: {exc}",
                        [child_text],
                        True,
                    )
                )
        while pending:
            child, metadata = pending.pop()
            relative = child.relative_to(root)
            try:
                relative_text = _canonical_snapshot_path(root, child)
            except ContextError as exc:
                limitations.append(_limitation("scope_unavailable", str(exc), [], True))
                continue
            if ".git" in relative.parts:
                continue
            if _is_link_like(metadata):
                limitations.append(
                    _limitation(
                        "file_unreadable",
                        f"skipped symlinked or reparse-point target: {relative_text}",
                        [relative_text],
                        True,
                    )
                )
                continue
            if stat.S_ISREG(metadata.st_mode):
                paths.add(relative_text)
                if len(paths) > max_targets:
                    first_omitted = relative_text
                    truncated = True
                    break
                continue
            if not stat.S_ISDIR(metadata.st_mode):
                limitations.append(
                    _limitation(
                        "file_unreadable",
                        f"skipped non-regular target: {relative_text}",
                        [relative_text],
                        True,
                    )
                )
                continue
            try:
                with os.scandir(child) as entries:
                    descendants = sorted(entries, key=lambda entry: entry.name)
            except OSError as exc:
                limitations.append(
                    _limitation(
                        "scope_unavailable",
                        f"cannot enumerate directory {relative_text}: {exc}",
                        [relative_text],
                        True,
                    )
                )
                continue
            for entry in reversed(descendants):
                descendant = Path(entry.path)
                try:
                    pending.append((descendant, entry.stat(follow_symlinks=False)))
                except OSError as exc:
                    try:
                        descendant_text = _canonical_snapshot_path(root, descendant)
                    except ContextError as path_exc:
                        limitations.append(_limitation("scope_unavailable", str(path_exc), [], True))
                        continue
                    limitations.append(
                        _limitation(
                            "file_unreadable",
                            f"cannot inspect target {descendant_text}: {exc}",
                            [descendant_text],
                            True,
                        )
                    )
        if truncated:
            break
    ordered = sorted(paths)
    if truncated or len(ordered) > max_targets:
        omitted = ordered[max_targets:]
        if first_omitted and first_omitted not in omitted:
            omitted.append(first_omitted)
        limitations.append(
            _limitation(
                "scope_truncated",
                f"explicit scope exceeds {max_targets} files; enumeration stopped at the limit",
                omitted[:5000],
                True,
            )
        )
        ordered = ordered[:max_targets]
    return (
        [{"path": path, "old_path": None, "status": "snapshot", "similarity": None} for path in ordered],
        limitations,
    )


def _limitation(code: str, message: str, paths: list[str], material: bool) -> dict[str, Any]:
    return {"code": code, "message": message, "affected_paths": sorted(set(paths)), "material": material}


def _read_current_file(path: Path) -> tuple[bytes | None, str | None]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"cannot inspect guidance file: {exc}"
    if _is_link_like(metadata):
        return None, "guidance file is a symlink or reparse point"
    if not stat.S_ISREG(metadata.st_mode):
        return None, "guidance path is not a regular file"
    if metadata.st_size > MAX_GUIDANCE_SOURCE_BYTES:
        return None, f"guidance file exceeds {MAX_GUIDANCE_SOURCE_BYTES} bytes"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            content = handle.read(MAX_GUIDANCE_SOURCE_BYTES + 1)
    except OSError as exc:
        return None, f"cannot read guidance file: {exc}"
    if len(content) > MAX_GUIDANCE_SOURCE_BYTES:
        return None, f"guidance file exceeds {MAX_GUIDANCE_SOURCE_BYTES} bytes"
    return content, None


def _read_git_file(root: Path, revision: str, relative: str) -> tuple[bytes | None, str | None]:
    completed = _git(root, ["ls-tree", "-z", revision, "--", relative], check=False)
    if completed.returncode != 0:
        return None, completed.stderr.decode("utf-8", "replace").strip() or "cannot inspect guidance"
    entries = [entry for entry in completed.stdout.split(b"\0") if entry]
    if not entries:
        return None, None
    if len(entries) != 1:
        return None, "guidance path resolved to multiple Git entries"
    metadata, _, encoded_path = entries[0].partition(b"\t")
    parts = metadata.split()
    if len(parts) != 3 or _decode_path(encoded_path) != relative:
        return None, "malformed Git tree entry for guidance"
    mode, kind, object_id = parts
    if mode == b"120000":
        return None, "guidance file is a symlink in the trusted revision"
    if kind != b"blob" or mode not in {b"100644", b"100755"}:
        return None, "guidance path is not a regular file in the trusted revision"
    size = _git(root, ["cat-file", "-s", object_id.decode("ascii")], check=False)
    if size.returncode != 0:
        return None, size.stderr.decode("utf-8", "replace").strip() or "cannot size guidance blob"
    try:
        blob_size = int(size.stdout.decode("ascii", "strict").strip())
    except (UnicodeDecodeError, ValueError):
        return None, "Git returned an invalid guidance blob size"
    if blob_size > MAX_GUIDANCE_SOURCE_BYTES:
        return None, f"guidance blob exceeds {MAX_GUIDANCE_SOURCE_BYTES} bytes"
    blob = _git(root, ["cat-file", "blob", object_id.decode("ascii")], check=False)
    if blob.returncode != 0:
        return None, blob.stderr.decode("utf-8", "replace").strip() or "cannot read guidance blob"
    return blob.stdout, None


def _source(kind: str, path: str, revision: str | None, content: bytes, include_content: bool = True) -> dict[str, Any]:
    if len(content) > MAX_GUIDANCE_SOURCE_BYTES:
        raise ContextError(f"guidance exceeds {MAX_GUIDANCE_SOURCE_BYTES} bytes: {path}")
    try:
        decoded = content.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ContextError(f"guidance is not valid UTF-8: {path}") from exc
    return {
        "source_kind": kind,
        "path": path,
        "revision": revision,
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "content": decoded if include_content else None,
    }


def _review_paths(target: str) -> list[str]:
    parent = PurePosixPath(target).parent
    paths = ["REVIEW.md"]
    current = PurePosixPath()
    if parent.as_posix() != ".":
        for part in parent.parts:
            current = current / part
            paths.append((current / "REVIEW.md").as_posix())
    return paths


def _repository_sources(
    root: Path,
    target: str,
    trusted_revision: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = []
    limitations: list[dict[str, Any]] = []
    for relative in _review_paths(target):
        if trusted_revision is None:
            content, error = _read_current_file(root / relative)
            revision = None
        else:
            content, error = _read_git_file(root, trusted_revision, relative)
            revision = trusted_revision
        if error:
            limitations.append(
                _limitation(
                    "file_unreadable",
                    f"cannot use {relative}: {error}",
                    [target],
                    True,
                )
            )
        elif content is not None:
            try:
                sources.append(_source("repository", relative, revision, content))
            except ContextError as exc:
                limitations.append(_limitation("file_unreadable", str(exc), [target], True))
    return sources, limitations


def _global_source(path_value: str | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if path_value is None:
        return None, []
    path = Path(path_value)
    if not path.is_absolute():
        return None, [_limitation("file_unreadable", "global review file must be an absolute path", [], True)]
    content, error = _read_current_file(path)
    if error:
        return None, [_limitation("file_unreadable", f"cannot use global guidance {path}: {error}", [], True)]
    if content is None:
        return None, []
    try:
        return _source("user_global", str(path), None, content), []
    except ContextError as exc:
        return None, [_limitation("file_unreadable", str(exc), [], True)]


def _skill_source() -> dict[str, Any]:
    path = Path(__file__).resolve().parent.parent / "SKILL.md"
    content = path.read_bytes()
    return _source("skill", "SKILL.md", f"project-review@{SKILL_VERSION}", content, include_content=False)


def _dedupe_limitations(limitations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in limitations:
        key = (item["code"], item["message"], tuple(item["affected_paths"]), item["material"])
        unique[key] = item
    ordered = sorted(unique.values(), key=lambda item: (item["code"], item["message"], item["affected_paths"]))
    if len(ordered) <= MAX_LIMITATIONS:
        return ordered
    retained = ordered[: MAX_LIMITATIONS - 1]
    omitted = ordered[MAX_LIMITATIONS - 1 :]
    affected = sorted({path for item in omitted for path in item["affected_paths"]})[:5000]
    retained.append(
        _limitation(
            "other",
            f"{len(omitted)} additional resolver limitations were collapsed at the canonical limit",
            affected,
            any(item["material"] for item in omitted),
        )
    )
    return retained


def _build_guidance(
    root: Path,
    changes: list[dict[str, Any]],
    trusted_revision: str | None,
    global_review_file: str | None,
    max_guidance_bytes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    skill = _skill_source()
    global_guidance, global_limitations = _global_source(global_review_file)
    limitations = list(global_limitations)
    global_incomplete = any(item["material"] for item in global_limitations)
    chains_by_signature: dict[tuple[Any, ...], dict[str, Any]] = {}
    chain_order: list[dict[str, Any]] = []

    def chain_for(path: str) -> str:
        repository, repo_limitations = _repository_sources(root, path, trusted_revision)
        limitations.extend(repo_limitations)
        candidates = ([global_guidance] if global_guidance is not None else []) + repository
        selected = [skill]
        consumed = 0
        skipped: list[str] = []
        for source in candidates:
            if len(selected) >= MAX_GUIDANCE_SOURCES_PER_CHAIN:
                skipped.append(source["path"])
                limitations.append(
                    _limitation(
                        "guidance_truncated",
                        f"guidance source limit omitted {source['path']} for {path}",
                        [path],
                        True,
                    )
                )
                continue
            if consumed + source["bytes"] > max_guidance_bytes:
                skipped.append(source["path"])
                limitations.append(
                    _limitation(
                        "guidance_truncated",
                        f"guidance budget omitted {source['path']} for {path}",
                        [path],
                        True,
                    )
                )
                continue
            selected.append(source)
            consumed += source["bytes"]
        complete = not global_incomplete and not skipped and not any(
            item["material"] and path in item["affected_paths"] for item in repo_limitations
        )
        signature = (
            tuple((item["source_kind"], item["path"], item["revision"], item["sha256"]) for item in selected),
            tuple(skipped),
            complete,
        )
        chain = chains_by_signature.get(signature)
        if chain is None:
            chain = {
                "chain_id": f"G{len(chain_order) + 1:03d}",
                "applies_to": [],
                "sources": selected,
                "complete": complete,
            }
            chains_by_signature[signature] = chain
            chain_order.append(chain)
        if path not in chain["applies_to"]:
            chain["applies_to"].append(path)
        return chain["chain_id"]

    enriched: list[dict[str, Any]] = []
    for change in changes:
        item = dict(change)
        item["guidance_chain_id"] = chain_for(item["path"])
        item["old_guidance_chain_id"] = (
            chain_for(item["old_path"]) if item["old_path"] is not None else None
        )
        enriched.append(item)
    for chain in chain_order:
        chain["applies_to"].sort()
    return enriched, chain_order, _dedupe_limitations(limitations)


def resolve(args: argparse.Namespace) -> dict[str, Any]:
    if args.max_guidance_bytes < 1024 or args.max_guidance_bytes > 1048576:
        raise ContextError("--max-guidance-bytes must be between 1024 and 1048576")
    if args.max_targets < 1 or args.max_targets > 250:
        raise ContextError("--max-targets must be between 1 and 250")
    require_git = args.scope in {"ref-range", "working-tree"}
    root, has_git = _repository_root(Path(args.repo), require_git)
    limitations: list[dict[str, Any]] = []
    trusted_revision: str | None
    if args.scope == "ref-range":
        head = _commit(root, args.head)
        base = _commit(root, args.base) if args.base else _commit(root, f"{head}^")
        changes = _diff_changes(root, [base, head])
        target_kind = "ref_range"
        mode = None
        trusted_revision = base
    elif args.scope == "working-tree":
        base = _commit(root, "HEAD")
        head = None
        if args.mode == "staged":
            changes = _diff_changes(root, ["--cached", base])
        elif args.mode == "unstaged":
            changes = [*_diff_changes(root, []), *_untracked_changes(root)]
        else:
            changes = [*_diff_changes(root, [base]), *_untracked_changes(root)]
        changes = _merge_changes(changes)
        target_kind = "working_tree"
        mode = args.mode
        trusted_revision = base
    else:
        base = None
        head = None
        mode = None
        target_kind = "paths"
        trusted_revision = None
        changes, limitations = _snapshot_changes(root, args.paths, args.max_targets)
    if len(changes) > args.max_targets:
        omitted = [item["path"] for item in changes[args.max_targets:]]
        limitations.append(
            _limitation(
                "scope_truncated",
                f"change scope contains {len(changes)} paths; limited to {args.max_targets}",
                omitted[:5000],
                True,
            )
        )
        changes = changes[: args.max_targets]
    changes, guidance, guidance_limitations = _build_guidance(
        root,
        changes,
        trusted_revision,
        args.global_review_file,
        args.max_guidance_bytes,
    )
    limitations.extend(guidance_limitations)
    if len(guidance) > MAX_GUIDANCE_CHAINS:
        raise ContextError(
            f"resolved {len(guidance)} guidance chains, exceeding canonical limit {MAX_GUIDANCE_CHAINS}"
        )
    requested_paths = sorted({item["path"] for item in changes})
    return {
        "schema_version": SCHEMA_VERSION,
        "target": {
            "kind": target_kind,
            "repository_root": str(root),
            "base_revision": base,
            "head_revision": head,
            "working_tree_mode": mode,
            "requested_paths": requested_paths,
        },
        "changes": changes,
        "guidance": guidance,
        "limitations": _dedupe_limitations(limitations),
        "git_repository": has_git,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="project path; defaults to current directory")
    parser.add_argument("--global-review-file", help="absolute active-agent user REVIEW.md")
    parser.add_argument("--max-guidance-bytes", type=int, default=DEFAULT_MAX_GUIDANCE_BYTES)
    parser.add_argument("--max-targets", type=int, default=DEFAULT_MAX_TARGETS)
    subparsers = parser.add_subparsers(dest="scope", required=True)

    command = subparsers.add_parser("ref-range", help="review changes between two Git commits")
    command.add_argument("--base", help="base revision; defaults to the parent of --head")
    command.add_argument("--head", required=True)

    command = subparsers.add_parser("working-tree", help="review local working-tree changes")
    command.add_argument("--mode", choices=("staged", "unstaged", "combined"), default="combined")

    command = subparsers.add_parser("paths", help="review current files or bounded directories")
    command.add_argument("paths", nargs="+")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        result = resolve(build_parser().parse_args(argv))
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    except ContextError as exc:
        print(f"project-review context: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
