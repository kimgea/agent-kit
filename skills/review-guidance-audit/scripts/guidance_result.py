#!/usr/bin/env python3
"""Finalize, validate, and render canonical review-guidance audit results."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import unicodedata
from typing import Any


SCHEMA_VERSION = "1.0"
MAX_JSON_BYTES = 16777216
HEX64 = re.compile(r"[0-9a-f]{64}")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
ACTIONS = ("keep", "rewrite", "move", "merge", "remove", "create")
STRENGTHS = ("essential", "strong", "moderate", "optional")
DECISIONS = ("ready", "decision_required")
INTENT_EFFECTS = ("preserved", "narrowed", "changed")
HARNESS_RELATIONSHIPS = ("replace", "partially_cover", "support")
LIMITATION_CODES = {
    "scope_truncated",
    "target_unreadable",
    "part_unreadable",
    "guidance_unreadable",
    "guidance_budget",
    "coverage_incomplete",
    "context_unavailable",
    "evidence_missing",
    "conflicting_evidence",
    "other",
}


class ResultError(ValueError):
    """Raised when an audit context, draft, or canonical result is invalid."""


def _filesystem_path(value: str, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ResultError(f"{label} must be a non-empty path")
    if CONTROL.search(value):
        raise ResultError(f"{label} must not contain control characters")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ResultError(f"{label} must be valid UTF-8") from exc
    return Path(value)


def _absolute_authority_path(value: Any, label: str) -> str:
    text = _string(value, label, 8192)
    path = _filesystem_path(text, label)
    if not path.is_absolute():
        raise ResultError(f"{label} must be absolute")
    return text


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ResultError(f"duplicate JSON member: {key}")
        value[key] = item
    return value


def _is_link_like(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(reparse and attributes & reparse)


def _assert_no_link_components(path: Path, *, include_final: bool) -> None:
    absolute = path.absolute()
    parts = absolute.parts[1:] if include_final else absolute.parts[1:-1]
    current = Path(absolute.anchor)
    for part in parts:
        current /= part
        if _is_link_like(current):
            raise ResultError(f"refusing link-like path component: {current}")


def _read_json(source: str) -> Any:
    if source == "-":
        raw = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ResultError("JSON input is too large: stdin")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResultError("JSON input is not UTF-8: stdin") from exc
    else:
        path = _filesystem_path(source, "JSON input path")
        _assert_no_link_components(path, include_final=True)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ResultError(f"cannot open JSON input {source}: {exc}") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ResultError(f"JSON input must be a regular file: {source}")
            if metadata.st_size > MAX_JSON_BYTES:
                raise ResultError(f"JSON input is too large: {source}")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(
                    descriptor, min(65536, MAX_JSON_BYTES + 1 - total)
                )
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_JSON_BYTES:
                    raise ResultError(f"JSON input is too large: {source}")
            try:
                text = b"".join(chunks).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ResultError(f"JSON input is not UTF-8: {source}") from exc
        finally:
            os.close(descriptor)
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicates)
    except json.JSONDecodeError as exc:
        raise ResultError(f"invalid JSON: {exc}") from exc


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _object(value: Any, label: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ResultError(f"{label} must be an object")
    missing = keys - set(value)
    extra = set(value) - keys
    if missing:
        raise ResultError(f"{label} is missing fields: {sorted(missing)}")
    if extra:
        raise ResultError(f"{label} has unknown fields: {sorted(extra)}")
    return value


def _array(value: Any, label: str, maximum: int = 10000) -> list[Any]:
    if not isinstance(value, list):
        raise ResultError(f"{label} must be an array")
    if len(value) > maximum:
        raise ResultError(f"{label} exceeds {maximum} entries")
    return value


def _string(value: Any, label: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ResultError(f"{label} must be a non-empty string")
    if len(value) > maximum:
        raise ResultError(f"{label} exceeds {maximum} characters")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ResultError(f"{label} must be valid UTF-8") from exc
    return value


def _nullable_string(value: Any, label: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _string(value, label, maximum)


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ResultError(f"{label} must be an integer from {minimum} through {maximum}")
    return value


def _enum(value: Any, label: str, choices: set[str] | tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ResultError(f"{label} must be one of {sorted(choices)}")
    return value


def _path(value: Any, label: str, *, allow_root: bool = False) -> str:
    text = _string(value, label, 4096)
    if CONTROL.search(text) or "\\" in text or text.startswith("/") or text.startswith("//"):
        raise ResultError(f"{label} must be a canonical repository-relative path")
    if re.match(r"^[A-Za-z]:", text) or text.endswith("/") or "//" in text:
        raise ResultError(f"{label} must be a canonical repository-relative path")
    if text == ".":
        if allow_root:
            return text
        raise ResultError(f"{label} cannot be the repository root")
    parts = PurePosixPath(text).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ResultError(f"{label} must be a canonical repository-relative path")
    if PurePosixPath(*parts).as_posix() != text:
        raise ResultError(f"{label} must be a canonical repository-relative path")
    return text


def _unique_paths(value: Any, label: str, *, allow_empty: bool = True) -> list[str]:
    paths = [_path(item, f"{label}[{index}]") for index, item in enumerate(_array(value, label))]
    if not allow_empty and not paths:
        raise ResultError(f"{label} must not be empty")
    if len(paths) != len(set(paths)):
        raise ResultError(f"{label} contains duplicate paths")
    return paths


def _validate_location(value: Any, label: str) -> dict[str, Any]:
    location = _object(value, label, {"path", "start_line", "end_line"})
    _path(location["path"], f"{label}.path")
    start = location["start_line"]
    end = location["end_line"]
    if start is None or end is None:
        if start is not None or end is not None:
            raise ResultError(f"{label} line range must be fully null or fully specified")
    else:
        _integer(start, f"{label}.start_line", 1, 100000000)
        _integer(end, f"{label}.end_line", start, 100000000)
    return location


def _validate_limitation(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label, {"code", "message", "affected_paths", "material"})
    _enum(item["code"], f"{label}.code", LIMITATION_CODES)
    _string(item["message"], f"{label}.message", 4000)
    _unique_paths(item["affected_paths"], f"{label}.affected_paths")
    if not isinstance(item["material"], bool):
        raise ResultError(f"{label}.material must be boolean")
    return item


def _applicable_repository_guidance(path: str) -> list[str]:
    parent = PurePosixPath(path).parent
    result = ["REVIEW.md"]
    current = PurePosixPath()
    if parent.as_posix() == ".":
        return result
    for part in parent.parts:
        current /= part
        result.append((current / "REVIEW.md").as_posix())
    return result


def _validate_context(value: Any) -> dict[str, Any]:
    context = _object(
        value,
        "context",
        {"schema_version", "target", "guidance", "context_metrics", "discovery", "limitations"},
    )
    if context["schema_version"] != SCHEMA_VERSION:
        raise ResultError(f"context.schema_version must be {SCHEMA_VERSION}")
    target = _object(
        context["target"],
        "context.target",
        {"kind", "repository_root", "requested", "files"},
    )
    if target["kind"] != "current_filesystem":
        raise ResultError("context.target.kind must be current_filesystem")
    repository_root = _absolute_authority_path(
        target["repository_root"], "context.target.repository_root"
    )
    requested = _array(target["requested"], "context.target.requested", 1000)
    if not requested:
        raise ResultError("context.target.requested must not be empty")
    seen_target_ids: set[str] = set()
    for index, raw in enumerate(requested):
        label = f"context.target.requested[{index}]"
        item = _object(raw, label, {"target_id", "kind", "path", "start_line", "end_line"})
        target_id = _string(item["target_id"], f"{label}.target_id", 16)
        if not re.fullmatch(r"T[0-9]{3,6}", target_id) or target_id in seen_target_ids:
            raise ResultError(f"{label}.target_id is invalid or duplicated")
        seen_target_ids.add(target_id)
        _enum(item["kind"], f"{label}.kind", {"part", "file", "directory", "project"})
        _path(item["path"], f"{label}.path", allow_root=True)
        if item["kind"] == "part":
            start = _integer(item["start_line"], f"{label}.start_line", 1, 100000000)
            _integer(item["end_line"], f"{label}.end_line", start, 100000000)
        elif item["start_line"] is not None or item["end_line"] is not None:
            raise ResultError(f"{label} non-part ranges must be null")
    files = _array(target["files"], "context.target.files", 100000)
    seen_files: set[str] = set()
    for index, raw in enumerate(files):
        label = f"context.target.files[{index}]"
        item = _object(raw, label, {"path", "bytes", "sha256", "inspection_kind"})
        path = _path(item["path"], f"{label}.path")
        if path in seen_files:
            raise ResultError("context.target.files contains duplicate paths")
        seen_files.add(path)
        _integer(item["bytes"], f"{label}.bytes", 0, 1 << 50)
        if item["sha256"] is not None:
            digest = _string(item["sha256"], f"{label}.sha256", 64)
            if not HEX64.fullmatch(digest):
                raise ResultError(
                    f"{label}.sha256 must be a lowercase SHA-256 or null"
                )
        _enum(item["inspection_kind"], f"{label}.inspection_kind", {"text", "binary", "non_utf8", "oversized", "unreadable"})
    for item in requested:
        if item["kind"] in {"file", "part"} and item["path"] not in seen_files:
            raise ResultError(
                f"context.target.requested target is missing from files: {item['path']}"
            )
    for file_path in seen_files:
        governed = False
        for item in requested:
            if item["kind"] in {"file", "part"}:
                governed = governed or file_path == item["path"]
            elif item["kind"] == "project":
                governed = True
            else:
                governed = governed or file_path == item["path"] or file_path.startswith(
                    f"{item['path']}/"
                )
        if not governed:
            raise ResultError(
                f"context.target.files contains a path outside requested scope: {file_path}"
            )
    chains = _array(context["guidance"], "context.guidance", 100000)
    seen_chains: set[str] = set()
    guided: set[str] = set()
    for chain_index, raw_chain in enumerate(chains):
        label = f"context.guidance[{chain_index}]"
        chain = _object(raw_chain, label, {"chain_id", "applies_to", "sources", "effective_bytes", "effective_words", "complete"})
        chain_id = _string(chain["chain_id"], f"{label}.chain_id", 16)
        if not re.fullmatch(r"G[0-9]{3,6}", chain_id) or chain_id in seen_chains:
            raise ResultError(f"{label}.chain_id is invalid or duplicated")
        seen_chains.add(chain_id)
        applies = _unique_paths(chain["applies_to"], f"{label}.applies_to", allow_empty=False)
        if not set(applies) <= seen_files:
            raise ResultError(f"{label}.applies_to must stay within target files")
        if guided & set(applies):
            raise ResultError("each target file must have exactly one guidance chain")
        guided.update(applies)
        sources = _array(chain["sources"], f"{label}.sources", 256)
        if (
            not sources
            or not isinstance(sources[0], dict)
            or sources[0].get("source_kind") != "skill"
        ):
            raise ResultError(f"{label}.sources must begin with the skill contract")
        previous_depth = -2
        seen_source_identities: set[tuple[str, str, str]] = set()
        seen_global = False
        seen_repository = False
        for source_index, raw_source in enumerate(sources):
            source_label = f"{label}.sources[{source_index}]"
            source = _object(raw_source, source_label, {"source_kind", "path", "revision", "sha256", "bytes", "words", "lines", "content", "loaded"})
            kind = _enum(source["source_kind"], f"{source_label}.source_kind", {"skill", "user_global", "repository"})
            source_path = _string(source["path"], f"{source_label}.path", 8192)
            if kind in {"skill", "repository"}:
                _path(source_path, f"{source_label}.path")
            else:
                _absolute_authority_path(source_path, f"{source_label}.path")
            _nullable_string(source["revision"], f"{source_label}.revision", 256)
            digest = _string(source["sha256"], f"{source_label}.sha256", 64)
            if not HEX64.fullmatch(digest):
                raise ResultError(f"{source_label}.sha256 must be lowercase SHA-256")
            identity = (kind, source_path, digest)
            if identity in seen_source_identities:
                raise ResultError(f"{label}.sources contains a duplicate source")
            seen_source_identities.add(identity)
            _integer(source["bytes"], f"{source_label}.bytes", 0, 1 << 40)
            _integer(source["words"], f"{source_label}.words", 0, 1 << 40)
            _integer(source["lines"], f"{source_label}.lines", 0, 1 << 40)
            if not isinstance(source["loaded"], bool):
                raise ResultError(f"{source_label}.loaded must be boolean")
            if source["loaded"]:
                content = _string(source["content"], f"{source_label}.content", 1048576, empty=True)
                normalized = content.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
                if hashlib.sha256(normalized).hexdigest() != digest:
                    raise ResultError(f"{source_label}.content digest does not match")
            elif source["content"] is not None:
                raise ResultError(f"{source_label}.content must be null when not loaded")
            depth = -1 if kind == "skill" else 0 if kind == "user_global" else len(PurePosixPath(source_path).parts)
            if depth < previous_depth:
                raise ResultError(f"{label}.sources must be broad-to-specific")
            previous_depth = depth
            if kind == "skill":
                if source_index != 0 or source_path != "SKILL.md":
                    raise ResultError(f"{label}.sources contains an invalid skill source")
            elif kind == "user_global":
                if seen_global or seen_repository:
                    raise ResultError(f"{label}.sources contains misplaced user-global guidance")
                seen_global = True
            else:
                seen_repository = True
                if any(source_path not in _applicable_repository_guidance(path) for path in applies):
                    raise ResultError(f"{label}.sources contains non-applicable repository guidance")
        repository_paths = [
            source["path"] for source in sources if source["source_kind"] == "repository"
        ]
        if repository_paths != sorted(repository_paths, key=lambda path: len(PurePosixPath(path).parts)):
            raise ResultError(f"{label}.repository sources must be broad-to-specific")
        expected_bytes = sum(source["bytes"] for source in sources if source["source_kind"] != "skill")
        expected_words = sum(source["words"] for source in sources if source["source_kind"] != "skill")
        if _integer(chain["effective_bytes"], f"{label}.effective_bytes", 0, 1 << 50) != expected_bytes:
            raise ResultError(f"{label}.effective_bytes is inconsistent")
        if _integer(chain["effective_words"], f"{label}.effective_words", 0, 1 << 50) != expected_words:
            raise ResultError(f"{label}.effective_words is inconsistent")
        if not isinstance(chain["complete"], bool):
            raise ResultError(f"{label}.complete must be boolean")
        expected_complete = all(
            source["loaded"] for source in sources if source["source_kind"] != "skill"
        )
        if chain["complete"] and not expected_complete:
            raise ResultError(f"{label}.complete cannot hide unloaded guidance")
    if guided != seen_files:
        raise ResultError("every target file must have exactly one guidance chain")
    metrics = _object(context["context_metrics"], "context.context_metrics", {"source_count", "chain_count", "maximum_effective_words", "median_effective_words", "per_source"})
    _integer(metrics["source_count"], "context.context_metrics.source_count", 0, 100000)
    if metrics["source_count"] != len(_array(metrics["per_source"], "context.context_metrics.per_source", 100000)):
        raise ResultError("context.context_metrics.source_count is inconsistent")
    if _integer(metrics["chain_count"], "context.context_metrics.chain_count", 0, 100000) != len(chains):
        raise ResultError("context.context_metrics.chain_count is inconsistent")
    _integer(metrics["maximum_effective_words"], "context.context_metrics.maximum_effective_words", 0, 1 << 50)
    _integer(metrics["median_effective_words"], "context.context_metrics.median_effective_words", 0, 1 << 50)
    actual_metrics: dict[tuple[str, str, str], dict[str, Any]] = {}
    for chain in chains:
        for source in chain["sources"]:
            key = (source["source_kind"], source["path"], source["sha256"])
            if key not in actual_metrics:
                actual_metrics[key] = {
                    "source_kind": source["source_kind"],
                    "path": source["path"],
                    "sha256": source["sha256"],
                    "bytes": source["bytes"],
                    "words": source["words"],
                    "lines": source["lines"],
                    "fanout": 0,
                }
            actual_metrics[key]["fanout"] += len(chain["applies_to"])
    if metrics["source_count"] != len(actual_metrics):
        raise ResultError("context.context_metrics.source_count is inconsistent")
    effective_words = sorted(chain["effective_words"] for chain in chains)
    expected_maximum = max(effective_words, default=0)
    if metrics["maximum_effective_words"] != expected_maximum:
        raise ResultError("context.context_metrics.maximum_effective_words is inconsistent")
    if effective_words:
        middle = len(effective_words) // 2
        expected_median = effective_words[middle] if len(effective_words) % 2 else (effective_words[middle - 1] + effective_words[middle]) // 2
    else:
        expected_median = 0
    if metrics["median_effective_words"] != expected_median:
        raise ResultError("context.context_metrics.median_effective_words is inconsistent")
    validated_metrics: list[dict[str, Any]] = []
    for index, raw in enumerate(metrics["per_source"]):
        label = f"context.context_metrics.per_source[{index}]"
        item = _object(raw, label, {"source_kind", "path", "sha256", "bytes", "words", "lines", "fanout"})
        _enum(item["source_kind"], f"{label}.source_kind", {"skill", "user_global", "repository"})
        _string(item["path"], f"{label}.path", 8192)
        digest = _string(item["sha256"], f"{label}.sha256", 64)
        if not HEX64.fullmatch(digest):
            raise ResultError(f"{label}.sha256 must be lowercase SHA-256")
        for key in ("bytes", "words", "lines", "fanout"):
            _integer(item[key], f"{label}.{key}", 0, 1 << 50)
        validated_metrics.append(item)
    expected_metric_values = sorted(actual_metrics.values(), key=lambda value: (value["source_kind"], value["path"]))
    if validated_metrics != expected_metric_values:
        raise ResultError("context.context_metrics.per_source is inconsistent")
    discovery = _object(context["discovery"], "context.discovery", {"git_ignore_rules_used", "max_files", "max_guidance_bytes"})
    if discovery["git_ignore_rules_used"] is not None and not isinstance(discovery["git_ignore_rules_used"], bool):
        raise ResultError("context.discovery.git_ignore_rules_used must be boolean or null")
    _integer(discovery["max_files"], "context.discovery.max_files", 1, 100000)
    _integer(discovery["max_guidance_bytes"], "context.discovery.max_guidance_bytes", 1024, 1048576)
    for index, limitation in enumerate(_array(context["limitations"], "context.limitations", 1000)):
        _validate_limitation(limitation, f"context.limitations[{index}]")
    return context


def _context_result_guidance(context: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for chain in context["guidance"]:
        result.append(
            {
                "chain_id": chain["chain_id"],
                "applies_to": list(chain["applies_to"]),
                "sources": [
                    {key: source[key] for key in ("source_kind", "path", "revision", "sha256", "bytes", "words", "lines", "loaded")}
                    for source in chain["sources"]
                ],
                "effective_bytes": chain["effective_bytes"],
                "effective_words": chain["effective_words"],
                "complete": chain["complete"],
            }
        )
    return result


def _verify_context_fresh(context: dict[str, Any]) -> None:
    resolver_path = Path(__file__).resolve().with_name("guidance_context.py")
    specification = importlib.util.spec_from_file_location(
        "review_guidance_context_fresh", resolver_path
    )
    if specification is None or specification.loader is None:
        raise ResultError("cannot load the bundled context resolver")
    resolver = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(resolver)
    paths = [
        item["path"]
        for item in context["target"]["requested"]
        if item["kind"] != "part"
    ]
    parts = [
        f"{item['path']}:{item['start_line']}:{item['end_line']}"
        for item in context["target"]["requested"]
        if item["kind"] == "part"
    ]
    global_paths = {
        source["path"]
        for chain in context["guidance"]
        for source in chain["sources"]
        if source["source_kind"] == "user_global"
    }
    if len(global_paths) > 1:
        raise ResultError("context contains multiple user-global guidance files")
    arguments = argparse.Namespace(
        repo=context["target"]["repository_root"],
        paths=paths,
        parts=parts,
        global_review_file=next(iter(global_paths), None),
        max_files=context["discovery"]["max_files"],
        max_guidance_bytes=context["discovery"]["max_guidance_bytes"],
        output=None,
    )
    try:
        fresh = resolver.resolve(arguments)
    except Exception as exc:
        raise ResultError(f"cannot refresh the resolver-owned context: {exc}") from exc
    if _sha256_json(fresh) != _sha256_json(context):
        raise ResultError(
            "resolver-owned context is stale; resolve the unchanged target again"
        )


def _source_map(guidance: list[dict[str, Any]]) -> dict[str, set[tuple[str, str, str]]]:
    result: dict[str, set[tuple[str, str, str]]] = {}
    for chain in guidance:
        sources = {
            (item["source_kind"], item["path"], item["sha256"])
            for item in chain["sources"]
            if item["source_kind"] in {"user_global", "repository"}
        }
        for path in chain["applies_to"]:
            result[path] = sources
    return result


def _valid_destination(destination: dict[str, Any], affected: list[str], guidance: list[dict[str, Any]], label: str) -> None:
    kind = _enum(destination["source_kind"], f"{label}.source_kind", {"user_global", "repository"})
    path = _string(destination["path"], f"{label}.path", 8192)
    if kind == "user_global":
        _absolute_authority_path(path, f"{label}.path")
        known = {
            item["path"]
            for chain in guidance
            for item in chain["sources"]
            if item["source_kind"] == "user_global"
        }
        if path not in known:
            raise ResultError(f"{label} must name the resolved user-global REVIEW.md")
        return
    canonical = _path(path, f"{label}.path")
    if PurePosixPath(canonical).name != "REVIEW.md":
        raise ResultError(f"{label}.path must name REVIEW.md")
    parent = PurePosixPath(canonical).parent
    parent_text = parent.as_posix()
    for affected_path in affected:
        if parent_text != "." and not affected_path.startswith(f"{parent_text}/"):
            raise ResultError(f"{label}.path is not an ancestor of every affected path")


def _validate_guidance_ref(value: Any, label: str) -> dict[str, Any]:
    reference = _object(value, label, {"source_kind", "path", "sha256", "start_line", "end_line"})
    kind = _enum(reference["source_kind"], f"{label}.source_kind", {"user_global", "repository"})
    path = _string(reference["path"], f"{label}.path", 8192)
    if kind == "repository":
        _path(path, f"{label}.path")
    else:
        _absolute_authority_path(path, f"{label}.path")
    digest = _string(reference["sha256"], f"{label}.sha256", 64)
    if not HEX64.fullmatch(digest):
        raise ResultError(f"{label}.sha256 must be lowercase SHA-256")
    start = reference["start_line"]
    end = reference["end_line"]
    if start is None or end is None:
        if start is not None or end is not None:
            raise ResultError(f"{label} line range must be fully null or fully specified")
    else:
        _integer(start, f"{label}.start_line", 1, 100000000)
        _integer(end, f"{label}.end_line", start, 100000000)
    return reference


def _validate_harness(value: Any, label: str) -> dict[str, Any]:
    item = _object(
        value,
        label,
        {
            "relationship", "kind", "summary", "reason", "coverage", "timing",
            "speed", "enforcement", "determinism", "availability", "diagnostics",
            "paths",
        },
    )
    relationship = _enum(item["relationship"], f"{label}.relationship", HARNESS_RELATIONSHIPS)
    _enum(item["kind"], f"{label}.kind", {"test", "lint", "formatter", "schema", "static_analysis", "validator", "other"})
    _string(item["summary"], f"{label}.summary", 1000)
    _string(item["reason"], f"{label}.reason", 4000)
    coverage = _enum(item["coverage"], f"{label}.coverage", {"complete", "partial", "unknown"})
    timing = _enum(item["timing"], f"{label}.timing", {"review_loop", "pre_merge", "pre_deploy", "manual", "unknown"})
    speed = _enum(item["speed"], f"{label}.speed", {"fast", "slow", "unknown"})
    enforcement = _enum(item["enforcement"], f"{label}.enforcement", {"required", "optional", "unknown"})
    determinism = _enum(item["determinism"], f"{label}.determinism", {"deterministic", "nondeterministic", "unknown"})
    availability = _enum(item["availability"], f"{label}.availability", {"ordinary", "restricted", "unknown"})
    diagnostics = _enum(item["diagnostics"], f"{label}.diagnostics", {"actionable", "weak", "unknown"})
    _unique_paths(item["paths"], f"{label}.paths")
    if relationship == "replace" and (
        coverage != "complete"
        or timing != "review_loop"
        or speed != "fast"
        or enforcement != "required"
        or determinism != "deterministic"
        or availability != "ordinary"
        or diagnostics != "actionable"
    ):
        raise ResultError(
            f"{label}: replacement requires complete deterministic coverage enforced in the review loop"
        )
    return item


def _validate_recommendations(
    value: Any,
    *,
    target_paths: set[str],
    requested_targets: list[dict[str, Any]],
    context_paths: set[str],
    guidance: list[dict[str, Any]],
    finalized: bool,
) -> list[dict[str, Any]]:
    recommendations = _array(value, "recommendations", 2000)
    source_map = _source_map(guidance)
    source_lines = {
        (source["source_kind"], source["path"], source["sha256"]): source["lines"]
        for chain in guidance
        for source in chain["sources"]
        if source["source_kind"] in {"user_global", "repository"}
    }
    source_loaded = {
        (source["source_kind"], source["path"], source["sha256"]): source["loaded"]
        for chain in guidance
        for source in chain["sources"]
        if source["source_kind"] in {"user_global", "repository"}
    }
    targets_by_id = {item["target_id"]: item for item in requested_targets}
    if len(targets_by_id) != len(requested_targets):
        raise ResultError("target.requested contains duplicate target_id values")
    seen_ids: set[str] = set()
    seen_fingerprints: set[str] = set()
    for index, raw in enumerate(recommendations):
        label = f"recommendations[{index}]"
        keys = {
            "action", "strength", "decision", "intent_effect", "title", "reason",
            "current_guidance", "destination", "affected_targets", "affected_paths", "evidence",
            "estimated_savings", "proposed_text", "harness_changes",
        }
        if finalized:
            keys |= {"recommendation_id", "fingerprint"}
        item = _object(raw, label, keys)
        if finalized:
            identifier = _string(item["recommendation_id"], f"{label}.recommendation_id", 16)
            if not re.fullmatch(r"R[0-9]{3,6}", identifier) or identifier in seen_ids:
                raise ResultError(f"{label}.recommendation_id is invalid or duplicated")
            seen_ids.add(identifier)
            fingerprint = _string(item["fingerprint"], f"{label}.fingerprint", 64)
            if not HEX64.fullmatch(fingerprint) or fingerprint in seen_fingerprints:
                raise ResultError(f"{label}.fingerprint is invalid or duplicated")
            seen_fingerprints.add(fingerprint)
        action = _enum(item["action"], f"{label}.action", ACTIONS)
        _enum(item["strength"], f"{label}.strength", STRENGTHS)
        decision = _enum(item["decision"], f"{label}.decision", DECISIONS)
        intent_effect = _enum(item["intent_effect"], f"{label}.intent_effect", INTENT_EFFECTS)
        if intent_effect == "changed" and decision != "decision_required":
            raise ResultError(f"{label}: changed intent requires decision_required")
        _string(item["title"], f"{label}.title", 300)
        _string(item["reason"], f"{label}.reason", 6000)
        affected = _unique_paths(item["affected_paths"], f"{label}.affected_paths", allow_empty=False)
        if not set(affected) <= target_paths:
            raise ResultError(f"{label}.affected_paths must stay within the resolved target")
        affected_targets = [
            _string(value, f"{label}.affected_targets[{target_index}]", 16)
            for target_index, value in enumerate(
                _array(item["affected_targets"], f"{label}.affected_targets", 1000)
            )
        ]
        if not affected_targets or len(affected_targets) != len(set(affected_targets)):
            raise ResultError(f"{label}.affected_targets must be non-empty and unique")
        if not set(affected_targets) <= set(targets_by_id):
            raise ResultError(f"{label}.affected_targets contains an unknown target")
        governed_union: set[str] = set()
        for target_id in affected_targets:
            selected = targets_by_id[target_id]
            selected_path = selected["path"]
            if selected["kind"] in {"part", "file"}:
                governed = {selected_path}
            elif selected["kind"] == "project":
                governed = set(target_paths)
            else:
                governed = {
                    path
                    for path in target_paths
                    if path == selected_path or path.startswith(f"{selected_path}/")
                }
            if not set(affected) & governed:
                raise ResultError(
                    f"{label}.affected_targets includes a target with no affected path"
                )
            governed_union.update(governed)
        if not set(affected) <= governed_union:
            raise ResultError(
                f"{label}.affected_paths are not covered by affected_targets"
            )
        references = [
            _validate_guidance_ref(raw_reference, f"{label}.current_guidance[{ref_index}]")
            for ref_index, raw_reference in enumerate(_array(item["current_guidance"], f"{label}.current_guidance", 64))
        ]
        if action != "create" and not references:
            raise ResultError(f"{label}.current_guidance must not be empty for {action}")
        for reference in references:
            identity = (reference["source_kind"], reference["path"], reference["sha256"])
            if any(identity not in source_map[path] for path in affected):
                raise ResultError(f"{label}.current_guidance is not applicable to every affected path")
            if not source_loaded[identity]:
                raise ResultError(
                    f"{label}.current_guidance cannot cite an unloaded source"
                )
            if (
                reference["end_line"] is not None
                and reference["end_line"] > source_lines[identity]
            ):
                raise ResultError(
                    f"{label}.current_guidance line range exceeds the resolved source"
                )
        destination = item["destination"]
        if destination is not None:
            destination = _object(destination, f"{label}.destination", {"source_kind", "path"})
            _valid_destination(destination, affected, guidance, f"{label}.destination")
        if action in {"move", "merge", "create", "rewrite"} and destination is None:
            raise ResultError(f"{label}.destination is required for {action}")
        if action in {"keep", "remove"} and destination is not None:
            raise ResultError(f"{label}.destination must be null for {action}")
        proposed = _nullable_string(item["proposed_text"], f"{label}.proposed_text", 16000)
        if action in {"rewrite", "move", "merge", "create"} and proposed is None:
            raise ResultError(f"{label}.proposed_text is required for {action}")
        if action in {"keep", "remove"} and proposed is not None:
            raise ResultError(f"{label}.proposed_text must be null for {action}")
        evidence = _array(item["evidence"], f"{label}.evidence", 64)
        if not evidence:
            raise ResultError(f"{label}.evidence must not be empty")
        allowed_evidence_paths = target_paths | context_paths | {
            source["path"]
            for chain in guidance
            for source in chain["sources"]
            if source["source_kind"] == "repository"
        }
        for evidence_index, raw_evidence in enumerate(evidence):
            evidence_label = f"{label}.evidence[{evidence_index}]"
            evidence_item = _object(raw_evidence, evidence_label, {"kind", "description", "location"})
            _enum(evidence_item["kind"], f"{evidence_label}.kind", {"guidance", "code", "test", "specification", "documentation", "configuration", "history", "reasoning"})
            _string(evidence_item["description"], f"{evidence_label}.description", 4000)
            if evidence_item["location"] is not None:
                location = _validate_location(evidence_item["location"], f"{evidence_label}.location")
                if location["path"] not in allowed_evidence_paths:
                    raise ResultError(f"{evidence_label}.location must be a target, context, or repository guidance path")
        for target_id in affected_targets:
            selected = targets_by_id[target_id]
            if selected["kind"] != "part":
                continue
            focused_evidence = False
            for evidence_item in evidence:
                location = evidence_item["location"]
                if location is None or location["path"] != selected["path"]:
                    continue
                if location["start_line"] is None:
                    continue
                if (
                    location["start_line"] >= selected["start_line"]
                    and location["end_line"] <= selected["end_line"]
                ):
                    focused_evidence = True
                    break
            if not focused_evidence:
                raise ResultError(
                    f"{label} must cite evidence inside affected part {target_id}"
                )
        savings = _object(item["estimated_savings"], f"{label}.estimated_savings", {"words", "bytes", "basis"})
        for key in ("words", "bytes"):
            if savings[key] is not None:
                _integer(savings[key], f"{label}.estimated_savings.{key}", 0, 1 << 40)
        _string(savings["basis"], f"{label}.estimated_savings.basis", 2000)
        harness = [
            _validate_harness(raw_harness, f"{label}.harness_changes[{harness_index}]")
            for harness_index, raw_harness in enumerate(_array(item["harness_changes"], f"{label}.harness_changes", 32))
        ]
        if any(change["relationship"] == "replace" for change in harness) and action not in {"remove", "rewrite"}:
            raise ResultError(f"{label}: replacement harness changes require remove or rewrite guidance action")
        if finalized and recommendation_fingerprint(item) != item["fingerprint"]:
            raise ResultError(f"{label}.fingerprint does not match the recommendation")
    return recommendations


def _validate_coverage(value: Any, target_files: list[dict[str, Any]]) -> dict[str, Any]:
    target_paths = {item["path"] for item in target_files}
    non_text_paths = {
        item["path"]
        for item in target_files
        if item["inspection_kind"] != "text"
    }
    coverage = _object(value, "coverage", {"complete", "inspected_paths", "excluded", "context_paths"})
    inspected = set(_unique_paths(coverage["inspected_paths"], "coverage.inspected_paths"))
    if not inspected <= target_paths:
        raise ResultError("coverage.inspected_paths must stay within target files")
    if inspected & non_text_paths:
        raise ResultError(
            "coverage.inspected_paths cannot claim non-text or unavailable target files"
        )
    excluded_paths: set[str] = set()
    for index, raw in enumerate(_array(coverage["excluded"], "coverage.excluded", 100000)):
        label = f"coverage.excluded[{index}]"
        item = _object(raw, label, {"path", "reason", "material"})
        path = _path(item["path"], f"{label}.path")
        if path in excluded_paths or path in inspected or path not in target_paths:
            raise ResultError(f"{label}.path is duplicate, inspected, or outside target")
        excluded_paths.add(path)
        _string(item["reason"], f"{label}.reason", 2000)
        if not isinstance(item["material"], bool):
            raise ResultError(f"{label}.material must be boolean")
        if path in non_text_paths and not item["material"]:
            raise ResultError(f"{label}.material must be true for an unavailable target")
    if inspected | excluded_paths != target_paths:
        raise ResultError("coverage must account for every resolved target file")
    _unique_paths(coverage["context_paths"], "coverage.context_paths")
    if not isinstance(coverage["complete"], bool):
        raise ResultError("coverage.complete must be boolean")
    expected = not any(item["material"] for item in coverage["excluded"])
    if coverage["complete"] != expected:
        raise ResultError("coverage.complete must reflect material exclusions")
    return coverage


def recommendation_fingerprint(item: dict[str, Any]) -> str:
    value = {
        "action": item.get("action"),
        "title": " ".join(str(item.get("title", "")).casefold().split()),
        "affected_targets": sorted(item.get("affected_targets") or []),
        "affected_paths": sorted(item.get("affected_paths") or []),
        "current_guidance": sorted(
            (reference.get("source_kind"), reference.get("path"), reference.get("sha256"))
            for reference in item.get("current_guidance") or []
        ),
        "destination": item.get("destination"),
    }
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _validate_result(value: Any) -> dict[str, Any]:
    result = _object(
        value,
        "result",
        {"schema_version", "context_sha256", "status", "target", "guidance", "context_metrics", "summary", "coverage", "recommendations", "limitations"},
    )
    if result["schema_version"] != SCHEMA_VERSION:
        raise ResultError(f"schema_version must be {SCHEMA_VERSION}")
    context_digest = _string(result["context_sha256"], "context_sha256", 64)
    if not HEX64.fullmatch(context_digest):
        raise ResultError("context_sha256 must be a lowercase SHA-256")
    _enum(result["status"], "status", {"COMPLETE", "INCOMPLETE"})
    result_guidance = _array(result["guidance"], "result.guidance", 100000)
    for chain_index, chain in enumerate(result_guidance):
        if not isinstance(chain, dict):
            raise ResultError(f"result.guidance[{chain_index}] must be an object")
        complete = chain.get("complete")
        if not isinstance(complete, bool):
            raise ResultError(
                f"result.guidance[{chain_index}].complete must be boolean"
            )
        sources = chain.get("sources")
        if not isinstance(sources, list):
            raise ResultError(
                f"result.guidance[{chain_index}].sources must be an array"
            )
        if any(not isinstance(source, dict) for source in sources):
            raise ResultError(
                f"result.guidance[{chain_index}].sources must contain objects"
            )
        for source_index, raw_source in enumerate(sources):
            source_label = f"result.guidance[{chain_index}].sources[{source_index}]"
            source = _object(
                raw_source,
                source_label,
                {
                    "source_kind",
                    "path",
                    "revision",
                    "sha256",
                    "bytes",
                    "words",
                    "lines",
                    "loaded",
                },
            )
            _enum(
                source["source_kind"],
                f"{source_label}.source_kind",
                {"skill", "user_global", "repository"},
            )
            if not isinstance(source["loaded"], bool):
                raise ResultError(
                    f"{source_label}.loaded must be boolean"
                )
        if complete and any(
            source.get("source_kind") != "skill" and not source["loaded"]
            for source in sources
        ):
            raise ResultError(
                f"result.guidance[{chain_index}].complete cannot hide unloaded guidance"
            )
    synthetic_context = {
        "schema_version": SCHEMA_VERSION,
        "target": result["target"],
        "guidance": [
            {
                **chain,
                "sources": [{**source, "content": None} for source in chain["sources"]],
            }
            for chain in result["guidance"]
        ],
        "context_metrics": result["context_metrics"],
        "discovery": {"git_ignore_rules_used": None, "max_files": 1, "max_guidance_bytes": 1024},
        "limitations": [],
    }
    # Result provenance intentionally omits guidance bodies. Validate its shape directly below
    # using a context-shaped object with loaded flags temporarily disabled.
    for chain in synthetic_context["guidance"]:
        has_non_skill_source = False
        for source in chain["sources"]:
            if source["source_kind"] != "skill":
                has_non_skill_source = True
            source["loaded"] = False
        if has_non_skill_source:
            chain["complete"] = False
    _validate_context(synthetic_context)
    target_paths = {item["path"] for item in result["target"]["files"]}
    coverage = _validate_coverage(result["coverage"], result["target"]["files"])
    context_paths = set(result["coverage"]["context_paths"])
    recommendations = _validate_recommendations(
        result["recommendations"],
        target_paths=target_paths,
        requested_targets=result["target"]["requested"],
        context_paths=context_paths,
        guidance=result["guidance"],
        finalized=True,
    )
    limitations = [
        _validate_limitation(item, f"limitations[{index}]")
        for index, item in enumerate(_array(result["limitations"], "limitations", 2000))
    ]
    expected_status = "INCOMPLETE" if (
        not coverage["complete"]
        or any(item["material"] for item in limitations)
        or any(not chain["complete"] for chain in result["guidance"])
    ) else "COMPLETE"
    if result["status"] != expected_status:
        raise ResultError(f"status must be {expected_status}")
    summary = _object(result["summary"], "summary", {"conclusion", "recommendation_counts", "ready", "decision_required", "harness_changes"})
    _string(summary["conclusion"], "summary.conclusion", 3000)
    counts = _object(summary["recommendation_counts"], "summary.recommendation_counts", set(ACTIONS))
    for action in ACTIONS:
        actual = sum(item["action"] == action for item in recommendations)
        if _integer(counts[action], f"summary.recommendation_counts.{action}", 0, 2000) != actual:
            raise ResultError(f"summary.recommendation_counts.{action} must equal {actual}")
    ready = sum(item["decision"] == "ready" for item in recommendations)
    decisions = sum(item["decision"] == "decision_required" for item in recommendations)
    harness_count = sum(len(item["harness_changes"]) for item in recommendations)
    ready_value = _integer(summary["ready"], "summary.ready", 0, 2000)
    decision_value = _integer(
        summary["decision_required"], "summary.decision_required", 0, 2000
    )
    harness_value = _integer(
        summary["harness_changes"], "summary.harness_changes", 0, 2000
    )
    if (
        ready_value != ready
        or decision_value != decisions
        or harness_value != harness_count
    ):
        raise ResultError("summary totals do not match recommendations")
    return result


def finalize(context_value: Any, draft_value: Any) -> dict[str, Any]:
    context = _validate_context(context_value)
    _verify_context_fresh(context)
    draft = _object(draft_value, "draft", {"summary", "coverage", "recommendations", "limitations"})
    summary_draft = _object(draft["summary"], "draft.summary", {"conclusion"})
    _string(summary_draft["conclusion"], "draft.summary.conclusion", 3000)
    target_paths = {item["path"] for item in context["target"]["files"]}
    coverage = _validate_coverage(draft["coverage"], context["target"]["files"])
    context_paths = set(coverage["context_paths"])
    recommendations = copy.deepcopy(
        _validate_recommendations(
            draft["recommendations"],
            target_paths=target_paths,
            requested_targets=context["target"]["requested"],
            context_paths=context_paths,
            guidance=context["guidance"],
            finalized=False,
        )
    )
    strength_order = {value: index for index, value in enumerate(STRENGTHS)}
    action_order = {value: index for index, value in enumerate(ACTIONS)}
    recommendations.sort(
        key=lambda item: (
            strength_order[item["strength"]],
            action_order[item["action"]],
            item["affected_paths"],
            item["title"].casefold(),
        )
    )
    for index, item in enumerate(recommendations, 1):
        item["recommendation_id"] = f"R{index:03d}"
        item["fingerprint"] = recommendation_fingerprint(item)
    draft_limitations = [
        _validate_limitation(item, f"draft.limitations[{index}]")
        for index, item in enumerate(_array(draft["limitations"], "draft.limitations", 1000))
    ]
    limitations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*context["limitations"], *draft_limitations]:
        key = json.dumps(item, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            limitations.append(copy.deepcopy(item))
    guidance = _context_result_guidance(context)
    status = "INCOMPLETE" if (
        not coverage["complete"]
        or any(item["material"] for item in limitations)
        or any(not chain["complete"] for chain in guidance)
    ) else "COMPLETE"
    result = {
        "schema_version": SCHEMA_VERSION,
        "context_sha256": _sha256_json(context),
        "status": status,
        "target": copy.deepcopy(context["target"]),
        "guidance": guidance,
        "context_metrics": copy.deepcopy(context["context_metrics"]),
        "summary": {
            "conclusion": summary_draft["conclusion"],
            "recommendation_counts": {
                action: sum(item["action"] == action for item in recommendations)
                for action in ACTIONS
            },
            "ready": sum(item["decision"] == "ready" for item in recommendations),
            "decision_required": sum(item["decision"] == "decision_required" for item in recommendations),
            "harness_changes": sum(len(item["harness_changes"]) for item in recommendations),
        },
        "coverage": copy.deepcopy(coverage),
        "recommendations": recommendations,
        "limitations": limitations,
    }
    return _validate_result(result)


def _display(value: str) -> str:
    pieces: list[str] = []
    for character in value:
        category = unicodedata.category(character)
        if character == "\\" or category.startswith("C") or category in {"Zl", "Zp"}:
            pieces.append(json.dumps(character, ensure_ascii=True)[1:-1])
        else:
            pieces.append(character)
    return "".join(pieces).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _location_text(location: dict[str, Any]) -> str:
    path = _display(location["path"])
    if location["start_line"] is None:
        return path
    if location["start_line"] == location["end_line"]:
        return f"{path}:{location['start_line']}"
    return f"{path}:{location['start_line']}-{location['end_line']}"


def render_human(result: dict[str, Any]) -> str:
    result = _validate_result(result)
    metrics = result["context_metrics"]
    summary = result["summary"]
    lines = [
        f"Review guidance audit: {result['status']}",
        _display(summary["conclusion"]),
        "",
        f"Recommendations: {len(result['recommendations'])} total; {summary['ready']} ready; "
        f"{summary['decision_required']} require a decision; {summary['harness_changes']} linked harness change(s).",
        f"Context: {metrics['source_count']} source(s), {metrics['chain_count']} effective chain(s), "
        f"maximum {metrics['maximum_effective_words']} words, median {metrics['median_effective_words']} words.",
    ]
    for item in result["recommendations"]:
        lines.extend(
            [
                "",
                f"[{item['recommendation_id']}] {item['action'].upper()}: {_display(item['title'])}",
                f"Strength: {item['strength']}; decision: {item['decision']}; intent: {item['intent_effect']}.",
                f"Targets: {', '.join(item['affected_targets'])}",
                f"Affects: {', '.join(_display(path) for path in item['affected_paths'])}",
                f"Reason: {_display(item['reason'])}",
            ]
        )
        if item["current_guidance"]:
            guidance_refs = ", ".join(
                f"{reference['source_kind']}:{_location_text(reference)}"
                for reference in item["current_guidance"]
            )
            lines.append(f"Guidance: {guidance_refs}")
        if item["destination"]:
            lines.append(
                f"Destination: {item['destination']['source_kind']}:{_display(item['destination']['path'])}"
            )
        savings = item["estimated_savings"]
        words = "unknown" if savings["words"] is None else str(savings["words"])
        bytes_saved = "unknown" if savings["bytes"] is None else str(savings["bytes"])
        lines.append(
            f"Estimated savings: {words} words / {bytes_saved} bytes. "
            f"{_display(savings['basis'])}"
        )
        lines.append("Evidence:")
        for evidence in item["evidence"]:
            suffix = f" ({_location_text(evidence['location'])})" if evidence["location"] else ""
            lines.append(f"- {_display(evidence['description'])}{suffix}")
        if item["proposed_text"]:
            lines.extend(["Proposed guidance:", _display(item["proposed_text"])])
        if item["harness_changes"]:
            lines.append("Linked harness changes:")
            for change in item["harness_changes"]:
                lines.append(
                    f"- [{change['relationship']}] {_display(change['summary'])} "
                    f"({change['coverage']}, {change['timing']}, {change['speed']}, "
                    f"{change['enforcement']}, {change['determinism']}, "
                    f"{change['availability']}, {change['diagnostics']})"
                )
                lines.append(f"  Reason: {_display(change['reason'])}")
    lines.extend(
        [
            "",
            "Coverage",
            f"- Inspected {len(result['coverage']['inspected_paths'])} of {len(result['target']['files'])} resolved files.",
            f"- Complete: {'yes' if result['coverage']['complete'] else 'no'}.",
        ]
    )
    for excluded in result["coverage"]["excluded"]:
        marker = "material" if excluded["material"] else "non-material"
        lines.append(f"- Excluded {_display(excluded['path'])} [{marker}]: {_display(excluded['reason'])}")
    if result["limitations"]:
        lines.extend(["", "Limitations"])
        for item in result["limitations"]:
            marker = "material" if item["material"] else "non-material"
            lines.append(f"- [{marker}] {_display(item['message'])}")
    return "\n".join(lines)


def _format_result(result: dict[str, Any], output_format: str) -> str:
    json_text = json.dumps(result, indent=2, ensure_ascii=True, sort_keys=True)
    json_text = json_text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    if output_format == "json":
        return json_text
    human = render_human(result)
    if output_format == "human":
        return human
    return f"{human}\n\nCanonical JSON\n```json\n{json_text}\n```"


def _write_output(text: str, destination: str | None, overwrite: bool) -> None:
    if destination is None:
        print(text)
        return
    path = _filesystem_path(destination, "output path")
    _assert_no_link_components(path, include_final=False)
    data = (text + "\n").encode("utf-8")
    if not path.parent.exists() or not path.parent.is_dir():
        raise ResultError(f"output parent does not exist: {path.parent}")
    if path.exists() or _is_link_like(path):
        if not overwrite:
            raise ResultError(f"output already exists: {path}")
        if _is_link_like(path):
            raise ResultError(f"refusing link-like output: {path}")
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ResultError(f"refusing unsafe output replacement: {path}")
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    finalize_parser = commands.add_parser("finalize")
    finalize_parser.add_argument("--context", required=True)
    finalize_parser.add_argument("--draft", required=True)
    finalize_parser.add_argument("--format", choices=("human", "json", "both"), default="human")
    finalize_parser.add_argument("--output")
    finalize_parser.add_argument("--overwrite", action="store_true")
    for name in ("validate", "render"):
        command = commands.add_parser(name)
        command.add_argument("--input", default="-")
        if name == "render":
            command.add_argument("--format", choices=("human", "json", "both"), default="human")
            command.add_argument("--output")
            command.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "finalize":
            result = finalize(_read_json(args.context), _read_json(args.draft))
            _write_output(_format_result(result, args.format), args.output, args.overwrite)
        elif args.command == "validate":
            _validate_result(_read_json(args.input))
            print("valid review-guidance-audit result")
        else:
            result = _validate_result(_read_json(args.input))
            _write_output(_format_result(result, args.format), args.output, args.overwrite)
        return 0
    except (ResultError, OSError) as exc:
        print(f"review-guidance result: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
