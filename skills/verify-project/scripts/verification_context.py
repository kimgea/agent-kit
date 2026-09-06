#!/usr/bin/env python3
"""Resolve a bounded lead-owned context for verify-project."""

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

from path_safety import (
    BoundDirectoryEntry,
    SafetyError,
    assert_no_link_components,
    bound_directory_entries,
    canonical_path,
    canonical_text,
    filesystem_alias_identity,
    filesystem_identity,
    filesystem_path,
    filesystem_snapshot,
    is_link_like,
    read_regular,
    safe_repo_path,
    text,
    write_created_output,
)


SCHEMA_VERSION = "1.0.0"
SKILL_VERSION = "1.0.0"
DEFAULT_MAX_TARGETS = 5000
DEFAULT_MAX_TARGET_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_TOTAL_TARGET_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_TRAVERSAL_ENTRIES = 50000
DEFAULT_MAX_DISCOVERY = 256
DEFAULT_MAX_DISCOVERY_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_GUIDANCE_BYTES = 128 * 1024
DEFAULT_COMMAND_CAP = 16
DEFAULT_TIME_CAP_SECONDS = 1800
MAX_TARGETS = 20000
MAX_TARGET_BYTES = 16 * 1024 * 1024
MAX_TOTAL_TARGET_BYTES = 256 * 1024 * 1024
MAX_TRAVERSAL_ENTRIES = 1000000
MAX_PROTECTED_PATHS = 100000
MAX_DISCOVERY = 5000
MAX_DISCOVERY_BYTES = 64 * 1024 * 1024
MAX_GUIDANCE_BYTES = 1024 * 1024
MAX_GUIDANCE_SOURCE_BYTES = 1024 * 1024
MAX_GUIDANCE_SOURCES_PER_CHAIN = 256
MAX_POLICY_BYTES = 1024 * 1024
MAX_POLICY_SOURCES = 64
MAX_CANDIDATE_INPUT_BYTES = 1024 * 1024
MAX_CANDIDATES = 128
MAX_CONTEXT_BYTES = 16 * 1024 * 1024
MAX_PATH_BYTES = 4 * 1024 * 1024
MAX_LIMITATIONS = 256
ORDINARY_EFFECTS = {
    "repository_read",
    "local_process",
    "disposable_repository_write",
    "bounded_temporary_write",
}
ALL_EFFECTS = ORDINARY_EFFECTS | {
    "source_mutation",
    "configuration_mutation",
    "dependency_installation",
    "network_access",
    "external_service",
    "persistent_process",
    "destructive_action",
    "permission_change",
    "remote_mutation",
    "outside_bounded_roots",
}
DISCOVERY_NAMES = {
    "pyproject.toml": "manifest",
    "setup.cfg": "manifest",
    "tox.ini": "test_configuration",
    "pytest.ini": "test_configuration",
    "package.json": "manifest",
    "deno.json": "manifest",
    "deno.jsonc": "manifest",
    "Cargo.toml": "manifest",
    "go.mod": "manifest",
    "Makefile": "script",
    "Justfile": "script",
    "Taskfile.yml": "script",
    "Taskfile.yaml": "script",
    "CMakeLists.txt": "build_configuration",
    "meson.build": "build_configuration",
    "build.gradle": "build_configuration",
    "build.gradle.kts": "build_configuration",
    "pom.xml": "build_configuration",
    "README.md": "documentation",
}
DISCOVERY_PREFIXES = (
    ".github/workflows/",
    ".gitlab-ci",
    "tests/",
    "test/",
    "scripts/",
    "docs/",
)


class ContextError(ValueError):
    """Raised when a canonical context cannot be built safely."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _git(root: Path, arguments: list[str], *, timeout: int = 30, check: bool = True) -> bytes:
    environment = dict(os.environ)
    environment["GIT_LITERAL_PATHSPECS"] = "1"
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContextError(f"Git command unavailable: {exc}") from exc
    if check and completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise ContextError(f"Git command failed: {detail or completed.returncode}")
    return completed.stdout if completed.returncode == 0 else b""


def _repository_root(value: str) -> tuple[Path, bool, str | None]:
    supplied = filesystem_path(value, "repository root").absolute()
    assert_no_link_components(supplied, include_final=True)
    if not supplied.exists() or not supplied.is_dir() or is_link_like(supplied):
        raise ContextError(f"repository root is not a safe directory: {supplied}")
    git_marker = supplied / ".git"
    try:
        output = _git(supplied, ["rev-parse", "--show-toplevel"], timeout=10)
    except ContextError:
        if git_marker.exists():
            raise
        return supplied, False, None
    try:
        discovered = Path(output.decode("utf-8", "strict").strip()).absolute()
    except UnicodeDecodeError as exc:
        raise ContextError("Git returned a non-UTF-8 worktree root") from exc
    assert_no_link_components(discovered, include_final=True)
    if not discovered.is_dir() or is_link_like(discovered):
        raise ContextError(f"Git worktree root is not a safe directory: {discovered}")
    if not _repository_roots_match(supplied, discovered):
        raise ContextError(f"--repo must name the Git worktree root: {discovered}")
    # Preserve the lead-owned spelling after proving it identifies the Git root.
    # This keeps target binding stable across Windows short/long path aliases.
    root = supplied
    head = _git(root, ["rev-parse", "--verify", "HEAD^{commit}"], timeout=10).decode("ascii").strip()
    return root, True, head


def _repository_roots_match(supplied: Path, discovered: Path) -> bool:
    if os.name == "nt":
        return filesystem_alias_identity(
            discovered, discovered.lstat()
        ) == filesystem_alias_identity(supplied, supplied.lstat())
    return os.path.normcase(str(discovered)) == os.path.normcase(str(supplied))


def _decode_paths(payload: bytes) -> list[str]:
    result: list[str] = []
    for raw in payload.split(b"\0"):
        if not raw:
            continue
        try:
            result.append(canonical_path(raw.decode("utf-8", "strict")))
        except (UnicodeDecodeError, SafetyError) as exc:
            raise ContextError("Git returned a non-UTF-8 or non-canonical path") from exc
    return result


def _working_tree_changes(root: Path) -> list[dict[str, Any]]:
    payload = _git(root, ["diff", "--raw", "--no-abbrev", "-z", "--find-renames", "HEAD", "--"])
    parts = payload.split(b"\0")
    changes: list[dict[str, Any]] = []
    index = 0
    while index < len(parts) and parts[index]:
        header = parts[index]
        index += 1
        if not header.startswith(b":"):
            raise ContextError("Git returned malformed raw change metadata")
        fields = header[1:].split()
        if len(fields) != 5:
            raise ContextError("Git returned malformed raw change fields")
        old_mode, new_mode, old_oid, new_oid, status_raw = fields
        status_text = status_raw.decode("ascii", "strict")
        status = status_text[:1]
        if index >= len(parts) or not parts[index]:
            raise ContextError("Git omitted a changed path")
        first = canonical_path(parts[index].decode("utf-8", "strict"))
        index += 1
        old_path: str | None = None
        path = first
        if status in {"R", "C"}:
            if index >= len(parts) or not parts[index]:
                raise ContextError("Git omitted a rename destination")
            old_path = first
            path = canonical_path(parts[index].decode("utf-8", "strict"))
            index += 1
        if status == "A":
            kind = "added"
        elif status == "D":
            kind = "deleted"
        elif status == "R":
            kind = "renamed"
        elif status == "T":
            kind = "type_changed"
        elif status == "M" and old_mode != new_mode:
            try:
                committed = _git_blob(root, "HEAD", path)
                current_path = safe_repo_path(root, path)
                _, current = read_regular(current_path, MAX_TARGET_BYTES)
                kind = "mode_changed" if committed == current else "modified"
            except (ContextError, SafetyError, OSError):
                kind = "modified"
        elif status == "M":
            kind = "modified"
        else:
            kind = "unknown"
        changes.append({"path": path, "old_path": old_path, "change_kind": kind, "_old_oid": old_oid.decode("ascii")})
    untracked = _decode_paths(_git(root, ["ls-files", "--others", "--exclude-standard", "-z"]))
    deletions_by_oid: dict[str, list[dict[str, Any]]] = {}
    for change in changes:
        if change["change_kind"] == "deleted":
            deletions_by_oid.setdefault(change["_old_oid"], []).append(change)
    consumed_deletions: set[str] = set()
    for path in untracked:
        try:
            object_id = _git(root, ["hash-object", f"--path={path}", "--", path]).decode("ascii").strip()
        except (ContextError, UnicodeDecodeError):
            object_id = ""
        matches = deletions_by_oid.get(object_id, [])
        if len(matches) == 1 and matches[0]["path"] not in consumed_deletions:
            deleted = matches[0]
            consumed_deletions.add(deleted["path"])
            changes.append({"path": path, "old_path": deleted["path"], "change_kind": "renamed", "_old_oid": object_id})
        else:
            changes.append({"path": path, "old_path": None, "change_kind": "untracked", "_old_oid": ""})
    changes = [item for item in changes if not (item["change_kind"] == "deleted" and item["path"] in consumed_deletions)]
    merged: dict[str, dict[str, Any]] = {}
    for change in changes:
        prior = merged.get(change["path"])
        if prior is None or prior["change_kind"] == "unknown":
            merged[change["path"]] = change
    return [
        {key: value for key, value in merged[path].items() if not key.startswith("_")}
        for path in sorted(merged)
    ]


def _git_visible_paths(root: Path) -> list[str]:
    return sorted(set(_decode_paths(_git(root, ["ls-files", "-co", "--exclude-standard", "-z"]))))


def _git_ignored(root: Path, paths: list[str]) -> set[str]:
    ignored: set[str] = set()
    for offset in range(0, len(paths), 256):
        chunk = paths[offset : offset + 256]
        payload = b"\0".join(item.encode("utf-8") for item in chunk) + b"\0"
        environment = dict(os.environ)
        environment.pop("GIT_LITERAL_PATHSPECS", None)
        try:
            completed = subprocess.run(
                ["git", "-C", str(root), "check-ignore", "-z", "--stdin"],
                input=payload,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ContextError(f"Git ignore classification failed: {exc}") from exc
        if completed.returncode not in {0, 1}:
            detail = completed.stderr.decode("utf-8", "replace").strip()
            raise ContextError(f"Git ignore classification failed: {detail or completed.returncode}")
        ignored.update(_decode_paths(completed.stdout))
    return ignored


def _bounded_directory_entries(
    directory: Path, remaining: int
) -> tuple[list[BoundDirectoryEntry], int, bool]:
    try:
        return bound_directory_entries(directory, remaining)
    except (SafetyError, OSError, UnicodeError) as exc:
        raise ContextError(f"cannot enumerate directory {directory}: {exc}") from exc


def _relative(root: Path, candidate: Path) -> str:
    try:
        value = candidate.absolute().relative_to(root).as_posix()
    except ValueError as exc:
        raise ContextError(f"path escaped repository root: {candidate}") from exc
    return canonical_path(value, allow_root=True)


def _enumerate_directories(
    root: Path,
    selectors: list[str],
    *,
    git_repository: bool,
    max_entries: int,
    max_targets: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    pending = sorted(set(selectors))
    paths: list[str] = []
    limitations: list[dict[str, Any]] = []
    traversed = 0
    complete = True
    seen_identities: dict[tuple[Any, ...], str] = {}
    while pending and complete:
        relative = pending.pop(0)
        directory = safe_repo_path(root, relative)
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise ContextError(f"selected directory is not a directory: {relative}")
        entries, consumed, exhausted = _bounded_directory_entries(
            directory, max_entries - traversed
        )
        traversed += consumed
        if not exhausted:
            complete = False
            break
        relative_entries = [(entry, _relative(root, Path(entry.path))) for entry in entries]
        ignored = _git_ignored(root, [item[1] for item in relative_entries]) if git_repository and relative_entries else set()
        for entry, child in relative_entries:
            if entry.name == ".git" or child in ignored:
                continue
            if entry.link_like:
                limitations.append(_limitation("target_unavailable", f"Skipped link-like target {child}.", [], True))
                continue
            if entry.is_directory:
                pending.append(child)
                pending.sort()
            elif entry.is_regular:
                if entry.identity in seen_identities:
                    limitations.append(_limitation("target_unavailable", f"Filesystem aliases identify both {seen_identities[entry.identity]} and {child}.", [], True))
                    continue
                seen_identities[entry.identity] = child
                paths.append(child)
                if len(paths) > max_targets:
                    complete = False
                    break
            else:
                limitations.append(_limitation("target_unavailable", f"Skipped special target {child}.", [], True))
    if not complete:
        limitations.append(_limitation("target_limit", "Directory enumeration reached a target or traversal limit before proving complete coverage.", [], True))
        return [], limitations
    return sorted(set(paths)), limitations


def _limitation(
    code: str,
    message: str,
    source_ids: list[str],
    material: bool,
    affected_target_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "source_ids": sorted(set(source_ids)),
        "affected_target_ids": sorted(set(affected_target_ids or [])),
        "material": material,
    }


def _dedupe_limitations(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[bytes, dict[str, Any]] = {}
    for value in values:
        unique[_canonical_json(value)] = value
    ordered = [unique[key] for key in sorted(unique)]
    if len(ordered) <= MAX_LIMITATIONS:
        return ordered
    retained = ordered[: MAX_LIMITATIONS - 1]
    retained.append(_limitation("other", f"Collapsed {len(ordered) - len(retained)} additional limitations at the canonical ceiling.", [], True))
    return retained


def _file_record(
    root: Path,
    relative: str,
    change_kind: str,
    old_path: str | None,
    max_bytes: int,
) -> tuple[dict[str, Any], int, tuple[Any, ...] | None, str | None]:
    path = safe_repo_path(root, relative, allow_absent_final=True)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return ({
            "path": relative,
            "old_path": old_path,
            "change_kind": change_kind,
            "presence": "absent",
            "file_kind": "absent",
            "inspection_kind": "absent",
            "size_bytes": None,
            "mode": None,
            "sha256": None,
            "guidance_chain_id": "G000",
            "old_guidance_chain_id": None,
        }, 0, None, None)
    if stat.S_ISLNK(metadata.st_mode) or is_link_like(path):
        raise ContextError(f"refusing link-like target: {relative}")
    if stat.S_ISDIR(metadata.st_mode):
        digest = _sha256(relative.encode("utf-8"))
        return ({
            "path": relative,
            "old_path": old_path,
            "change_kind": change_kind,
            "presence": "present",
            "file_kind": "directory",
            "inspection_kind": "metadata_only",
            "size_bytes": 0,
            "mode": stat.S_IMODE(metadata.st_mode),
            "sha256": digest,
            "guidance_chain_id": "G000",
            "old_guidance_chain_id": None,
        }, 0, filesystem_identity(path, metadata), None)
    if not stat.S_ISREG(metadata.st_mode):
        raise ContextError(f"target is not a regular file or directory: {relative}")
    snapshot = filesystem_snapshot(path, metadata)
    if metadata.st_nlink != 1:
        raise ContextError(f"target is hard-linked and has ambiguous ownership: {relative}")
    mode = stat.S_IMODE(metadata.st_mode)
    identity = filesystem_alias_identity(path, metadata)
    if metadata.st_size > max_bytes:
        return ({
            "path": relative,
            "old_path": old_path,
            "change_kind": change_kind,
            "presence": "present",
            "file_kind": "regular",
            "inspection_kind": "oversized",
            "size_bytes": int(metadata.st_size),
            "mode": mode,
            "sha256": None,
            "guidance_chain_id": "G000",
            "old_guidance_chain_id": None,
        }, int(metadata.st_size), identity, "target exceeds the per-file inspection limit")
    final, data = read_regular(path, max_bytes, expected_snapshot=snapshot, require_single_link=True)
    try:
        _, canonical = canonical_text(data, relative)
        inspection = "text"
        digest_data = canonical
    except SafetyError:
        inspection = "binary"
        digest_data = data
    return ({
        "path": relative,
        "old_path": old_path,
        "change_kind": change_kind,
        "presence": "present",
        "file_kind": "regular",
        "inspection_kind": inspection,
        "size_bytes": int(final.st_size),
        "mode": stat.S_IMODE(final.st_mode),
        "sha256": _sha256(digest_data),
        "guidance_chain_id": "G000",
        "old_guidance_chain_id": None,
    }, len(data), identity, None)


def _git_blob(root: Path, revision: str, relative: str) -> bytes | None:
    tree = _git(root, ["ls-tree", "-z", revision, "--", relative])
    records = [item for item in tree.split(b"\0") if item]
    if not records:
        return None
    if len(records) != 1:
        raise ContextError(f"ambiguous Git guidance path: {relative}")
    try:
        metadata, returned_path = records[0].split(b"\t", 1)
        mode, kind, object_id = metadata.split(b" ")
    except ValueError as exc:
        raise ContextError(f"malformed Git guidance metadata: {relative}") from exc
    if returned_path.decode("utf-8", "strict") != relative or kind != b"blob" or mode == b"120000":
        raise ContextError(f"guidance is not a regular committed file: {relative}")
    size = int(_git(root, ["cat-file", "-s", object_id.decode("ascii")]).decode("ascii"))
    if size > MAX_GUIDANCE_SOURCE_BYTES:
        raise ContextError(f"guidance exceeds {MAX_GUIDANCE_SOURCE_BYTES} bytes: {relative}")
    return _git(root, ["cat-file", "blob", object_id.decode("ascii")])


def _guidance_paths(relative: str) -> list[str]:
    if relative == ".":
        return ["VERIFY.md"]
    parent = PurePosixPath(relative).parent
    parts = [] if str(parent) == "." else list(parent.parts)
    result = ["VERIFY.md"]
    current = PurePosixPath()
    for part in parts:
        current /= part
        result.append((current / "VERIFY.md").as_posix())
    return result


def _guidance_source(
    kind: str,
    path: str,
    provenance: str,
    revision: str | None,
    raw: bytes,
) -> dict[str, Any]:
    content, canonical = canonical_text(raw, path)
    return {
        "kind": kind,
        "path": path,
        "provenance": provenance,
        "revision": revision,
        "sha256": _sha256(canonical),
        "content": content,
    }


def _resolve_guidance(
    root: Path,
    git_repository: bool,
    head: str | None,
    targets: list[dict[str, Any]],
    max_effective_bytes: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    skill_file = Path(__file__).resolve().parents[1] / "SKILL.md"
    _, skill_raw = read_regular(skill_file, MAX_GUIDANCE_SOURCE_BYTES, require_single_link=True)
    base_source = _guidance_source("skill", "SKILL.md", "locked_skill", f"verify-project@{SKILL_VERSION}", skill_raw)
    sources_by_key: dict[tuple[str, str, str | None, str], dict[str, Any]] = {
        (base_source["kind"], base_source["path"], base_source["revision"], base_source["sha256"]): base_source
    }
    chains_by_signature: dict[
        tuple[tuple[tuple[str, str, str | None, str], ...], bool],
        list[tuple[int, str]],
    ] = {}
    limitations: list[dict[str, Any]] = []
    target_roles: list[tuple[int, str, str]] = []
    for index, target in enumerate(targets):
        target_roles.append((index, "guidance_chain_id", target["path"]))
        if target["old_path"] is not None and target["old_path"] != target["path"]:
            target_roles.append((index, "old_guidance_chain_id", target["old_path"]))
    for index, field, governed_path in target_roles:
        target = targets[index]
        selected = [base_source]
        chain_complete = True
        for relative in _guidance_paths(governed_path):
            try:
                if git_repository:
                    assert head is not None
                    raw = _git_blob(root, head, relative)
                    if raw is None:
                        continue
                    source = _guidance_source("repository", relative, "git_head", head, raw)
                else:
                    path = safe_repo_path(root, relative, allow_absent_final=True)
                    if not path.exists():
                        continue
                    _, raw = read_regular(path, MAX_GUIDANCE_SOURCE_BYTES, require_single_link=True)
                    source = _guidance_source("repository", relative, "current_filesystem", None, raw)
                selected.append(source)
                key = (source["kind"], source["path"], source["revision"], source["sha256"])
                sources_by_key[key] = source
            except (ContextError, SafetyError, OSError, UnicodeError, ValueError) as exc:
                chain_complete = False
                limitations.append(_limitation("guidance_unavailable", f"Cannot load guidance {relative}: {exc}", [], True, [target["target_id"]]))
        if len(selected) > MAX_GUIDANCE_SOURCES_PER_CHAIN:
            chain_complete = False
            limitations.append(_limitation("guidance_limit", f"Guidance chain for {governed_path} exceeds {MAX_GUIDANCE_SOURCES_PER_CHAIN} sources.", [], True, [target["target_id"]]))
            selected = selected[:MAX_GUIDANCE_SOURCES_PER_CHAIN]
        total = sum(len(item["content"].encode("utf-8")) for item in selected)
        if total > max_effective_bytes:
            chain_complete = False
            limitations.append(_limitation("guidance_limit", f"Effective guidance for {governed_path} exceeds {max_effective_bytes} bytes.", [], True, [target["target_id"]]))
        signature = tuple((item["kind"], item["path"], item["revision"], item["sha256"]) for item in selected)
        chains_by_signature.setdefault((signature, chain_complete), []).append((index, field))
    ordered_sources = sorted(sources_by_key.values(), key=lambda item: (item["kind"] != "skill", item["path"], item["revision"] or "", item["sha256"]))
    for source_index, source in enumerate(ordered_sources, start=1):
        source["source_id"] = f"S{source_index:03d}"
    source_id_by_key = {(item["kind"], item["path"], item["revision"], item["sha256"]): item["source_id"] for item in ordered_sources}
    chains: list[dict[str, Any]] = []
    for chain_index, chain_key in enumerate(sorted(chains_by_signature), start=1):
        signature, complete = chain_key
        target_roles_for_chain = chains_by_signature[chain_key]
        chain_id = f"G{chain_index:03d}"
        source_ids = [source_id_by_key[key] for key in signature]
        target_ids = sorted({targets[item]["target_id"] for item, _ in target_roles_for_chain})
        chains.append({"chain_id": chain_id, "target_ids": target_ids, "source_ids": source_ids, "complete": complete})
        for item, field in target_roles_for_chain:
            targets[item][field] = chain_id
    for target in targets:
        if target["old_guidance_chain_id"] == target["guidance_chain_id"]:
            target["old_guidance_chain_id"] = None
    return {"sources": ordered_sources, "chains": chains}, limitations


def _discovery_kind(relative: str) -> str | None:
    name = PurePosixPath(relative).name
    if name in DISCOVERY_NAMES:
        return DISCOVERY_NAMES[name]
    if relative.startswith(".github/workflows/") or relative.startswith(".gitlab-ci"):
        return "local_ci"
    if relative.startswith(("tests/", "test/")):
        return "related_test"
    if relative.startswith("scripts/"):
        return "script"
    if relative.startswith("docs/"):
        return "documentation"
    return None


def _discover(
    root: Path,
    git_repository: bool,
    target_paths: set[str],
    max_records: int,
    max_bytes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if git_repository:
        candidates = _git_visible_paths(root)
    else:
        candidates, walk_limits = _enumerate_directories(root, ["."], git_repository=False, max_entries=MAX_TRAVERSAL_ENTRIES, max_targets=MAX_TARGETS)
        if any(item["material"] for item in walk_limits):
            return [], [_limitation("discovery_unavailable", item["message"], [], True) for item in walk_limits]
    target_stems = {PurePosixPath(path).stem.lower() for path in target_paths if path != "."}
    selected: list[tuple[str, str]] = []
    for relative in candidates:
        if relative in target_paths or PurePosixPath(relative).name == "VERIFY.md":
            continue
        kind = _discovery_kind(relative)
        if kind is None:
            continue
        if kind == "related_test" and target_stems and not any(stem and stem in relative.lower() for stem in target_stems):
            continue
        selected.append((relative, kind))
    records: list[dict[str, Any]] = []
    limitations: list[dict[str, Any]] = []
    consumed = 0
    for relative, kind in sorted(selected):
        if len(records) >= max_records:
            limitations.append(_limitation("discovery_limit", "Discovery reached its record limit before exhausting relevant project entry points.", [], True))
            break
        try:
            path = safe_repo_path(root, relative)
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ContextError("discovery source is not a singly linked regular file")
            if metadata.st_size > MAX_TARGET_BYTES or consumed + metadata.st_size > max_bytes:
                limitations.append(_limitation("discovery_limit", f"Discovery byte budget prevents inspecting {relative}.", [], True))
                break
            snapshot = filesystem_snapshot(path, metadata)
            final, raw = read_regular(path, MAX_TARGET_BYTES, expected_snapshot=snapshot, require_single_link=True)
            try:
                _, canonical = canonical_text(raw, relative)
                inspection = "text"
                digest = _sha256(canonical)
            except SafetyError:
                inspection = "binary"
                digest = _sha256(raw)
            records.append({
                "kind": kind,
                "path": relative,
                "sha256": digest,
                "inspection_kind": inspection,
                "provenance": "project_entry_point" if kind != "related_test" else "related_context",
            })
            consumed += int(final.st_size)
        except (ContextError, SafetyError, OSError) as exc:
            limitations.append(_limitation("discovery_unavailable", f"Cannot inspect discovery source {relative}: {exc}", [], True))
    for index, record in enumerate(records, start=1):
        record["discovery_id"] = f"D{index:03d}"
    return records, limitations


def _load_policy(args: argparse.Namespace, root: Path) -> list[dict[str, Any]]:
    records = [{"kind": "caller", "label": "caller request", "content": text(args.request, "request", maximum=4000)}]
    if args.policy_input:
        path = filesystem_path(args.policy_input, "policy input", expand_user=True).absolute()
        try:
            if os.path.commonpath([os.path.normcase(str(path)), os.path.normcase(str(root))]) == os.path.normcase(str(root)):
                raise ContextError("policy input must be lead-owned outside the repository")
        except ValueError as exc:
            raise ContextError("cannot compare policy input with repository root") from exc
        _, raw = read_regular(path, MAX_POLICY_BYTES, require_single_link=True)
        try:
            loaded = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_reject_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContextError(f"invalid policy input: {exc}") from exc
        if not isinstance(loaded, list) or len(loaded) > MAX_POLICY_SOURCES - 1:
            raise ContextError("policy input must be a bounded array")
        for index, item in enumerate(loaded):
            if not isinstance(item, dict) or set(item) != {"kind", "label", "content"}:
                raise ContextError(f"policy input item {index} has invalid fields")
            if item["kind"] not in {"user_global", "project"}:
                raise ContextError(f"policy input item {index} has invalid kind")
            records.append({"kind": item["kind"], "label": text(item["label"], "policy label", maximum=512), "content": text(item["content"], "policy content", maximum=MAX_POLICY_BYTES)})
    result = []
    labels: set[str] = set()
    for index, item in enumerate(records, start=1):
        if item["label"] in labels:
            raise ContextError(f"duplicate policy label: {item['label']!r}")
        labels.add(item["label"])
        canonical = item["content"].replace("\r\n", "\n").replace("\r", "\n")
        result.append({"policy_id": f"P{index:03d}", "kind": item["kind"], "label": item["label"], "sha256": _sha256(canonical.encode("utf-8")), "content": canonical})
    return result


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContextError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _executable_family(executable: str) -> str:
    value = executable.casefold()
    if value.endswith(".exe"):
        value = value[:-4]
    families = (
        (r"pythonw?(?:\d+(?:\.\d+)*)?", "python"),
        (r"pypy(?:\d+(?:\.\d+)*)?", "python"),
        (r"node(?:js)?(?:\d+(?:\.\d+)*)?", "node"),
        (r"ruby(?:\d+(?:\.\d+)*)?", "ruby"),
        (r"perl(?:\d+(?:\.\d+)*)?", "perl"),
        (r"(?:ba|da|z|fi)?sh(?:\d+(?:\.\d+)*)?", None),
    )
    for pattern, family in families:
        if re.fullmatch(pattern, value):
            return value.rstrip("0123456789.") if family is None else family
    return value


def _unsafe_dispatch_reason(argv: list[str]) -> str | None:
    executable = Path(argv[0]).name.casefold()
    executable = _executable_family(executable)
    lowered = [value.casefold() for value in argv[1:]]
    if executable in {"env", "xargs", "sudo", "doas", "su", "busybox", "toybox"}:
        return f"generic or privilege-changing dispatcher {executable!r}"
    inline_flags = {
        "sh": {"-c"},
        "bash": {"-c"},
        "dash": {"-c"},
        "zsh": {"-c"},
        "fish": {"-c"},
        "cmd": {"/c", "/k"},
        "powershell": {"-command", "-encodedcommand", "-c", "-enc"},
        "pwsh": {"-command", "-encodedcommand", "-c", "-enc"},
        "python": {"-c", "-"},
        "python3": {"-c", "-"},
        "py": {"-c", "-"},
        "node": {"-e", "--eval", "-p", "--print"},
        "ruby": {"-e"},
        "perl": {"-e"},
    }
    forbidden = inline_flags.get(executable, set())
    if any(value in forbidden for value in lowered):
        return f"inline evaluation through {executable!r}"
    return None


def _load_candidates(
    args: argparse.Namespace,
    root: Path,
    policy: list[dict[str, Any]],
    guidance: dict[str, Any],
    discovery: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not args.candidate_input:
        return [], []
    path = filesystem_path(args.candidate_input, "candidate input", expand_user=True).absolute()
    try:
        if os.path.commonpath([os.path.normcase(str(path)), os.path.normcase(str(root))]) == os.path.normcase(str(root)):
            raise ContextError("candidate input must be lead-owned outside the repository")
    except ValueError as exc:
        raise ContextError("cannot compare candidate input with repository root") from exc
    _, raw = read_regular(path, MAX_CANDIDATE_INPUT_BYTES, require_single_link=True)
    try:
        loaded = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContextError(f"invalid candidate input: {exc}") from exc
    if not isinstance(loaded, list) or len(loaded) > MAX_CANDIDATES:
        raise ContextError("candidate input must be a bounded array")
    source_by_label: dict[str, str] = {}
    for label, source_id in (
        [("caller", policy[0]["policy_id"])]
        + [(item["label"], item["policy_id"]) for item in policy]
        + [(item["path"], item["source_id"]) for item in guidance["sources"]]
        + [(item["path"], item["discovery_id"]) for item in discovery]
    ):
        if label in source_by_label and source_by_label[label] != source_id:
            raise ContextError(f"ambiguous provenance label: {label!r}")
        source_by_label[label] = source_id
    records: list[dict[str, Any]] = []
    limitations: list[dict[str, Any]] = []
    expected_keys = {"argv", "cwd", "provenance", "timeout_seconds", "repetitions", "expected_effects", "artifact_boundaries"}
    for index, item in enumerate(loaded, start=1):
        item_keys = frozenset(item) if isinstance(item, dict) else frozenset()
        if not isinstance(item, dict) or item_keys not in {frozenset(expected_keys), frozenset(expected_keys | {"authority_policy"})}:
            raise ContextError(f"candidate {index} has invalid fields")
        argv = item["argv"]
        if not isinstance(argv, list) or not 1 <= len(argv) <= 128:
            raise ContextError(f"candidate {index} argv is invalid")
        argv = [text(value, f"candidate {index} argv", maximum=4096) for value in argv]
        cwd = canonical_path(item["cwd"], allow_root=True)
        safe_repo_path(root, cwd)
        provenance = item["provenance"]
        if not isinstance(provenance, list) or not provenance or len(provenance) > 64:
            raise ContextError(f"candidate {index} provenance is invalid")
        try:
            provenance_ids = sorted({source_by_label[text(value, "candidate provenance", maximum=4096)] for value in provenance})
        except KeyError as exc:
            raise ContextError(f"candidate {index} cites unknown provenance {exc.args[0]!r}") from exc
        effects = item["expected_effects"]
        if not isinstance(effects, list) or not effects or len(effects) > len(ALL_EFFECTS):
            raise ContextError(f"candidate {index} effects are invalid")
        effects = [text(value, f"candidate {index} effect", maximum=64) for value in effects]
        if any(value not in ALL_EFFECTS for value in effects):
            raise ContextError(f"candidate {index} effects are invalid")
        boundaries = item["artifact_boundaries"]
        if not isinstance(boundaries, list) or len(boundaries) > 64:
            raise ContextError(f"candidate {index} artifact boundaries are invalid")
        normalized_boundaries = []
        for boundary in boundaries:
            if not isinstance(boundary, dict) or set(boundary) != {"root_kind", "path"} or boundary["root_kind"] not in {"repository", "run_temp"}:
                raise ContextError(f"candidate {index} artifact boundary is invalid")
            relative = canonical_path(boundary["path"])
            normalized_boundaries.append({"root_kind": boundary["root_kind"], "path": relative})
        boundary_kinds = {value["root_kind"] for value in normalized_boundaries}
        if "disposable_repository_write" in effects and "repository" not in boundary_kinds:
            raise ContextError(f"candidate {index} repository write has no repository artifact boundary")
        if "bounded_temporary_write" in effects and "run_temp" not in boundary_kinds:
            raise ContextError(f"candidate {index} temporary write has no run-temp artifact boundary")
        timeout_seconds = item["timeout_seconds"]
        repetitions = item["repetitions"]
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 3600:
            raise ContextError(f"candidate {index} timeout is invalid")
        if isinstance(repetitions, bool) or not isinstance(repetitions, int) or not 1 <= repetitions <= 32:
            raise ContextError(f"candidate {index} repetitions are invalid")
        authority_label = text(item.get("authority_policy", "caller"), "candidate authority policy", maximum=512)
        policy_by_label = {value["label"]: value for value in policy}
        if authority_label == "caller":
            authority_kind = "caller"
            authority_id = policy[0]["policy_id"]
            intent_authorized = bool(args.direct_execution_intent)
        elif authority_label in policy_by_label and policy_by_label[authority_label]["kind"] == "user_global":
            authority_kind = "user_global"
            authority_id = policy_by_label[authority_label]["policy_id"]
            intent_authorized = True
        elif authority_label in policy_by_label:
            authority_kind = "none"
            authority_id = policy_by_label[authority_label]["policy_id"]
            intent_authorized = False
        else:
            raise ContextError(f"candidate {index} cites unknown authority policy {authority_label!r}")
        unsafe_dispatch = _unsafe_dispatch_reason(argv)
        authorized = (
            args.mode == "execute"
            and intent_authorized
            and set(effects).issubset(ORDINARY_EFFECTS)
            and unsafe_dispatch is None
        )
        candidate_id = f"Q{index:03d}"
        if unsafe_dispatch is not None:
            limitations.append(_limitation(
                "unsafe_candidate",
                f"Candidate {candidate_id} uses {unsafe_dispatch}; inline evaluation and generic dispatch are outside verify-project v1.",
                [],
                False,
            ))
        records.append({
            "candidate_id": candidate_id,
            "argv": argv,
            "cwd": cwd,
            "provenance_ids": provenance_ids,
            "timeout_seconds": timeout_seconds,
            "repetitions": repetitions,
            "expected_effects": sorted(set(effects)),
            "artifact_boundaries": sorted(normalized_boundaries, key=lambda value: (value["root_kind"], value["path"])),
            "authority": {
                "source_kind": authority_kind if authorized else "none",
                "source": f"{authority_id}: {authority_label}" if authorized else f"{authority_id}: no active authority covers this candidate",
                "authorized": authorized,
            },
        })
    return records, limitations


def _protected_digest(
    root: Path,
    git_repository: bool,
    max_bytes: int,
    *,
    excluded_paths: set[str] | None = None,
) -> tuple[str, list[str], list[dict[str, Any]]]:
    directory_records: list[dict[str, Any]] = []
    # Protected state is the bounded filesystem tree, not merely Git's visible
    # tracked/untracked set. Ignored paths are not implicitly disposable, and
    # empty-directory creation is still an observable local mutation.
    paths, limitations = _enumerate_directories(
        root,
        ["."],
        git_repository=False,
        max_entries=MAX_TRAVERSAL_ENTRIES,
        max_targets=MAX_PROTECTED_PATHS,
    )
    if any(item["material"] for item in limitations):
        return _sha256(_canonical_json({"incomplete": True})), [], [_limitation("target_unavailable", "Protected-state inventory is incomplete.", [], True)]
    pending = ["."]
    traversed = 0
    while pending:
        relative = pending.pop(0)
        directory = root if relative == "." else safe_repo_path(root, relative)
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or is_link_like(directory):
            return _sha256(_canonical_json({"incomplete": True})), [], [_limitation("target_unavailable", f"Protected directory is unsafe: {relative}.", [], True)]
        directory_records.append({"path": relative, "kind": "directory", "mode": stat.S_IMODE(metadata.st_mode)})
        entries, consumed, exhausted = _bounded_directory_entries(directory, MAX_TRAVERSAL_ENTRIES - traversed)
        traversed += consumed
        if not exhausted:
            return _sha256(_canonical_json({"incomplete": True})), [], [_limitation("target_limit", "Protected-state directory inventory reached its traversal limit.", [], True)]
        for entry in entries:
            child = _relative(root, Path(entry.path))
            if entry.is_directory and entry.name != ".git" and not entry.link_like:
                pending.append(child)
        pending.sort()
    excluded = excluded_paths or set()
    paths = [path for path in paths if path not in excluded]
    records: list[dict[str, Any]] = [
        record for record in directory_records if record["path"] not in excluded
    ]
    protected_paths = sorted({record["path"] for record in records} | set(paths))
    if len(protected_paths) > MAX_PROTECTED_PATHS:
        return _sha256(_canonical_json({"incomplete": True})), [], [_limitation("target_limit", f"Protected-state inventory exceeds {MAX_PROTECTED_PATHS} paths.", [], True)]
    limitations: list[dict[str, Any]] = []
    total = 0
    identities: dict[tuple[Any, ...], str] = {}
    for relative in paths:
        try:
            path = safe_repo_path(root, relative, allow_absent_final=True)
            if not path.exists():
                records.append({"path": relative, "presence": "absent"})
                continue
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ContextError("protected entry is not a singly linked regular file")
            identity = filesystem_alias_identity(path, metadata)
            if identity in identities:
                raise ContextError(f"protected aliases identify {identities[identity]} and {relative}")
            identities[identity] = relative
            if metadata.st_size > MAX_TARGET_BYTES or total + metadata.st_size > max_bytes:
                raise ContextError("protected-state byte budget is exhausted")
            snapshot = filesystem_snapshot(path, metadata)
            final, raw = read_regular(path, MAX_TARGET_BYTES, expected_snapshot=snapshot, require_single_link=True)
            records.append({"path": relative, "mode": stat.S_IMODE(final.st_mode), "size": len(raw), "sha256": _sha256(raw)})
            total += len(raw)
        except (ContextError, SafetyError, OSError) as exc:
            limitations.append(_limitation("target_unavailable", f"Cannot bind protected state at {relative}: {exc}", [], True))
            records.append({"path": relative, "unavailable": True})
    path_hashes = sorted(_sha256(value.encode("utf-8")) for value in protected_paths)
    return _sha256(_canonical_json(records)), path_hashes, limitations


def _target_snapshot_digest(
    root: Path,
    targets: list[dict[str, Any]],
    *,
    max_file_bytes: int = MAX_TARGET_BYTES,
    max_total_bytes: int = MAX_TOTAL_TARGET_BYTES,
) -> tuple[str, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    identities: dict[tuple[Any, ...], str] = {}
    total = 0
    limitations: list[dict[str, Any]] = []
    for target in targets:
        try:
            record, consumed, identity, record_limit = _file_record(
                root,
                target["path"],
                target["change_kind"],
                target["old_path"],
                max_file_bytes,
            )
            record["target_id"] = target["target_id"]
            if identity is not None:
                if identity in identities:
                    raise ContextError(
                        f"target aliases identify {identities[identity]} and {record['path']}"
                    )
                identities[identity] = record["path"]
            total += consumed
            if total > max_total_bytes:
                raise ContextError("aggregate target byte budget is exhausted")
            if record_limit:
                limitations.append(
                    _limitation(
                        "target_limit",
                        f"Cannot inspect {record['path']}: {record_limit}.",
                        [],
                        True,
                        [record["target_id"]],
                    )
                )
            records.append(record)
        except (ContextError, SafetyError, OSError) as exc:
            limitations.append(
                _limitation(
                    "target_unavailable",
                    f"Cannot snapshot target {target['path']}: {exc}",
                    [],
                    True,
                    [target["target_id"]],
                )
            )
    if limitations:
        return _sha256(_canonical_json({"incomplete": True})), _dedupe_limitations(limitations)
    payload = [
        {
            key: value
            for key, value in record.items()
            if key not in {"guidance_chain_id", "old_guidance_chain_id"}
        }
        for record in records
    ]
    return _sha256(_canonical_json(payload)), []


def _validate_limits(args: argparse.Namespace) -> None:
    values = [
        ("max-targets", args.max_targets, 1, MAX_TARGETS),
        ("max-target-bytes", args.max_target_bytes, 1, MAX_TARGET_BYTES),
        ("max-total-target-bytes", args.max_total_target_bytes, 1, MAX_TOTAL_TARGET_BYTES),
        ("max-traversal-entries", args.max_traversal_entries, 1, MAX_TRAVERSAL_ENTRIES),
        ("max-discovery", args.max_discovery, 0, MAX_DISCOVERY),
        ("max-discovery-bytes", args.max_discovery_bytes, 0, MAX_DISCOVERY_BYTES),
        ("max-guidance-bytes", args.max_guidance_bytes, 0, MAX_GUIDANCE_BYTES),
        ("command-cap", args.command_cap, 0, MAX_CANDIDATES),
        ("time-cap-seconds", args.time_cap_seconds, 0, 86400),
    ]
    for label, value, minimum, maximum in values:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ContextError(f"{label} must be between {minimum} and {maximum}")


def _resolve(args: argparse.Namespace) -> dict[str, Any]:
    _validate_limits(args)
    try:
        root, git_repository, head = _repository_root(args.repo)
    except SafetyError as exc:
        raise ContextError(str(exc)) from exc
    if args.scope == "working-tree" and not git_repository:
        raise ContextError("working-tree mode requires a Git repository")
    limitations: list[dict[str, Any]] = []
    if args.scope == "working-tree":
        changes = _working_tree_changes(root)
        requested_paths = [item["path"] for item in changes]
    else:
        requested_paths = []
        explicit_files: list[str] = []
        directories: list[str] = []
        for raw in args.paths:
            relative = canonical_path(raw, allow_root=True)
            if relative in requested_paths:
                raise ContextError(f"duplicate requested path: {relative}")
            requested_paths.append(relative)
            path = safe_repo_path(root, relative, allow_absent_final=True)
            if not path.exists():
                explicit_files.append(relative)
            elif path.is_dir():
                directories.append(relative)
            else:
                explicit_files.append(relative)
        discovered, directory_limits = _enumerate_directories(
            root,
            directories,
            git_repository=git_repository,
            max_entries=args.max_traversal_entries,
            max_targets=args.max_targets,
        ) if directories else ([], [])
        limitations.extend(directory_limits)
        selected = sorted(set(explicit_files) | set(discovered))
        if not selected and directories:
            selected = sorted(set(directories))
        changes = [{"path": path, "old_path": None, "change_kind": "snapshot"} for path in selected]
    if not changes:
        raise ContextError("selected target contains no current changes or files")
    if len(changes) > args.max_targets:
        raise ContextError(f"target contains {len(changes)} records, above the limit {args.max_targets}")
    if sum(len(item["path"].encode("utf-8")) for item in changes) > MAX_PATH_BYTES:
        raise ContextError("target paths exceed the canonical path budget")
    targets: list[dict[str, Any]] = []
    identities: dict[tuple[Any, ...], str] = {}
    total_target_bytes = 0
    for index, change in enumerate(changes, start=1):
        try:
            record, consumed, identity, record_limit = _file_record(
                root,
                change["path"],
                change["change_kind"],
                change["old_path"],
                args.max_target_bytes,
            )
            record["target_id"] = f"T{index:03d}"
            if identity is not None:
                if identity in identities:
                    raise ContextError(f"target aliases identify {identities[identity]} and {record['path']}")
                identities[identity] = record["path"]
            total_target_bytes += consumed
            if total_target_bytes > args.max_total_target_bytes:
                raise ContextError("aggregate target byte budget is exhausted")
            targets.append(record)
            if record_limit:
                limitations.append(_limitation("target_limit", f"Cannot inspect {record['path']}: {record_limit}.", [], True, [record["target_id"]]))
        except (ContextError, SafetyError, OSError) as exc:
            raise ContextError(f"cannot bind target {change['path']}: {exc}") from exc
    guidance, guidance_limits = _resolve_guidance(root, git_repository, head, targets, args.max_guidance_bytes)
    limitations.extend(guidance_limits)
    target_paths = {item["path"] for item in targets}
    discovery, discovery_limits = _discover(root, git_repository, target_paths, args.max_discovery, args.max_discovery_bytes)
    limitations.extend(discovery_limits)
    policy = _load_policy(args, root)
    candidates, candidate_limits = _load_candidates(
        args, root, policy, guidance, discovery
    )
    limitations.extend(candidate_limits)
    if len(candidates) > args.command_cap:
        limitations.append(_limitation("target_limit", f"Caller command cap {args.command_cap} excludes {len(candidates) - args.command_cap} frozen candidates.", [], True))
        candidates = candidates[: args.command_cap]
    protected_sha, protected_path_hashes, protected_limits = _protected_digest(root, git_repository, args.max_total_target_bytes)
    limitations.extend(protected_limits)
    target_payload = [
        {
            key: value
            for key, value in item.items()
            if key not in {"guidance_chain_id", "old_guidance_chain_id"}
        }
        for item in targets
    ]
    target_sha = _sha256(_canonical_json(target_payload))
    authority_kind = "caller" if args.mode == "execute" and args.direct_execution_intent else "none"
    authority_effects = sorted(ORDINARY_EFFECTS) if authority_kind == "caller" else []
    context = {
        "schema_version": SCHEMA_VERSION,
        "target": {
            "kind": "working_tree" if args.scope == "working-tree" else "paths",
            "repository_root": str(root),
            "base_revision": head,
            "requested_paths": requested_paths,
        },
        "target_sha256": target_sha,
        "repository_state": {
            "repository_identity_sha256": _sha256(os.path.normcase(str(root)).encode("utf-8")),
            "git_repository": git_repository,
            "head_revision": head,
            "protected_state_sha256": protected_sha,
            "protected_path_hashes": protected_path_hashes,
        },
        "invocation": {
            "mode": args.mode,
            "request": args.request,
            "freshness": {
                "context_kind": "fresh" if args.fresh_context else "existing",
                "producer": "verify-project",
                "producer_version": SKILL_VERSION,
                "consumer": args.consumer,
            },
            "tier_cap": args.tier_cap,
            "command_cap": args.command_cap,
            "time_cap_seconds": args.time_cap_seconds,
        },
        "authority": {
            "source_kind": authority_kind,
            "source": "Caller requested direct bounded local verification." if authority_kind == "caller" else "Planning or non-executing intent does not grant command authority.",
            "direct_execution_intent": bool(args.direct_execution_intent),
            "authorized_effects": authority_effects,
        },
        "policy": policy,
        "limits": {
            "target_records": args.max_targets,
            "target_bytes": args.max_total_target_bytes,
            "discovery_records": args.max_discovery,
            "discovery_bytes": args.max_discovery_bytes,
            "effective_guidance_bytes_per_target": args.max_guidance_bytes,
            "planned_checks": args.command_cap,
            "argv_entries_per_check": 128,
            "timeout_seconds_per_check": 3600,
            "total_execution_seconds": args.time_cap_seconds,
            "repetitions_per_check": 32,
            "capture_bytes_per_stream": 1024 * 1024,
            "diagnostic_excerpt_bytes_per_stream": 4096,
            "canonical_json_bytes": MAX_CONTEXT_BYTES,
        },
        "targets": targets,
        "guidance": guidance,
        "discovery": discovery,
        "command_candidates": candidates,
        "limitations": _dedupe_limitations(limitations),
    }
    data = _canonical_json(context)
    if len(data) > MAX_CONTEXT_BYTES:
        raise ContextError(f"canonical context exceeds {MAX_CONTEXT_BYTES} bytes")
    return context


def resolve(args: argparse.Namespace) -> dict[str, Any]:
    try:
        return _resolve(args)
    except (SafetyError, TypeError, KeyError, IndexError) as exc:
        raise ContextError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="project root")
    parser.add_argument("--request", default="Verify the selected local changes.")
    parser.add_argument("--mode", choices=("plan", "execute"), default="execute")
    parser.add_argument("--direct-execution-intent", action="store_true")
    parser.add_argument("--fresh-context", action="store_true")
    parser.add_argument("--consumer")
    parser.add_argument("--tier-cap", choices=("focused", "subsystem", "project"))
    parser.add_argument("--command-cap", type=int, default=DEFAULT_COMMAND_CAP)
    parser.add_argument("--time-cap-seconds", type=int, default=DEFAULT_TIME_CAP_SECONDS)
    parser.add_argument("--policy-input", help="lead-owned JSON outside the repository")
    parser.add_argument("--candidate-input", help="lead-owned JSON outside the repository")
    parser.add_argument("--output", help="create a lead-owned context file instead of writing stdout")
    parser.add_argument("--max-targets", type=int, default=DEFAULT_MAX_TARGETS)
    parser.add_argument("--max-target-bytes", type=int, default=DEFAULT_MAX_TARGET_BYTES)
    parser.add_argument("--max-total-target-bytes", type=int, default=DEFAULT_MAX_TOTAL_TARGET_BYTES)
    parser.add_argument("--max-traversal-entries", type=int, default=DEFAULT_MAX_TRAVERSAL_ENTRIES)
    parser.add_argument("--max-discovery", type=int, default=DEFAULT_MAX_DISCOVERY)
    parser.add_argument("--max-discovery-bytes", type=int, default=DEFAULT_MAX_DISCOVERY_BYTES)
    parser.add_argument("--max-guidance-bytes", type=int, default=DEFAULT_MAX_GUIDANCE_BYTES)
    commands = parser.add_subparsers(dest="scope", required=True)
    commands.add_parser("working-tree", help="combined current Git working tree")
    paths = commands.add_parser("paths", help="explicit current files, directories, or .")
    paths.add_argument("paths", nargs="+")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        result = resolve(args)
        data = _canonical_json(result)
        if args.output:
            write_created_output(filesystem_path(args.output, "output path", expand_user=True).absolute(), data)
        else:
            sys.stdout.buffer.write(data)
        return 0
    except (ContextError, SafetyError, OSError, UnicodeError, ValueError) as exc:
        print(f"verify-project: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
