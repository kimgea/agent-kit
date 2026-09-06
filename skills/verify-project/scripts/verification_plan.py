#!/usr/bin/env python3
"""Finalize, validate, and render canonical verify-project plans."""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any

from path_safety import (
    SafetyError,
    canonical_path,
    canonical_text,
    filesystem_path,
    filesystem_snapshot,
    read_regular,
    safe_repo_path,
    text,
    write_created_output,
)


SCHEMA_VERSION = "1.0.0"
MAX_JSON_BYTES = 16 * 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ID_PATTERNS = {
    "target": re.compile(r"^T[0-9]{3,6}$"),
    "policy": re.compile(r"^P[0-9]{3,6}$"),
    "source": re.compile(r"^S[0-9]{3,6}$"),
    "discovery": re.compile(r"^D[0-9]{3,6}$"),
    "candidate": re.compile(r"^Q[0-9]{3,6}$"),
    "chain": re.compile(r"^G[0-9]{3,6}$"),
}
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
DISCOVERY_KINDS = {
    "manifest", "script", "test_configuration", "build_configuration",
    "lint_configuration", "type_configuration", "local_ci", "related_test",
    "documentation", "contract", "source", "other",
}
DISCOVERY_PROVENANCE = {
    "caller", "agent_policy", "verify_guidance", "project_entry_point",
    "related_context",
}
PLAN_LIMITATION_CODES = {
    "target_unavailable",
    "target_limit",
    "guidance_unavailable",
    "guidance_conflict",
    "guidance_limit",
    "discovery_unavailable",
    "discovery_limit",
    "coverage_gap",
    "authority_unavailable",
    "unsafe_candidate",
    "unsupported_effect",
    "caller_cap",
    "context_drift",
    "semantic_ambiguity",
    "other",
}
NEXT_ACTIONS = {"none", "plan", "decision", "authorization", "rescope", "manual"}


class PlanError(ValueError):
    """Raised when context or plan data violates the canonical contract."""


def _fail_closed(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except PlanError:
            raise
        except (SafetyError, TypeError, KeyError, IndexError) as exc:
            raise PlanError(f"malformed {function.__name__.replace('_', ' ')} input: {exc}") from exc
    return wrapped


def _canonical_json(value: Any, *, pretty: bool = False) -> bytes:
    if pretty:
        payload = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True)
    else:
        payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return (payload + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError(f"{label} must be an object")
    actual = set(value)
    if actual != keys:
        raise PlanError(f"{label} fields differ: expected {sorted(keys)}, got {sorted(actual)}")
    return value


def _array(value: Any, label: str, maximum: int, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise PlanError(f"{label} must contain between {minimum} and {maximum} items")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise PlanError(f"{label} must be a boolean")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise PlanError(f"{label} must be an integer from {minimum} through {maximum}")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise PlanError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _identifier(value: Any, kind: str, label: str) -> str:
    if not isinstance(value, str) or not ID_PATTERNS[kind].fullmatch(value):
        raise PlanError(f"{label} has an invalid identifier")
    return value


def _unique(values: list[str], label: str) -> None:
    if any(not isinstance(value, str) for value in values):
        raise PlanError(f"{label} must contain only strings")
    if len(values) != len(set(values)):
        raise PlanError(f"{label} contains duplicates")


def _read_json(path_value: str) -> dict[str, Any]:
    if path_value == "-":
        data = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            raise PlanError("JSON input is too large")
    else:
        path = filesystem_path(path_value, "JSON input", expand_user=True).absolute()
        _, data = read_regular(path, MAX_JSON_BYTES, require_single_link=True)
    try:
        result = json.loads(data.decode("utf-8", "strict"), object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"invalid JSON input: {exc}") from exc
    if not isinstance(result, dict):
        raise PlanError("JSON input root must be an object")
    return result


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _validate_target(target: Any) -> dict[str, Any]:
    item = _exact(target, {"kind", "repository_root", "base_revision", "requested_paths"}, "target")
    if item["kind"] not in {"working_tree", "paths"}:
        raise PlanError("target kind is invalid")
    root = filesystem_path(item["repository_root"], "repository root")
    if not root.is_absolute():
        raise PlanError("repository root must be absolute")
    if item["base_revision"] is not None:
        text(item["base_revision"], "base revision", maximum=512)
    paths = _array(item["requested_paths"], "requested paths", 20000, minimum=1)
    canonical = [canonical_path(value, allow_root=True) for value in paths]
    _unique(canonical, "requested paths")
    return item


def _validate_target_record(value: Any) -> dict[str, Any]:
    keys = {
        "target_id", "path", "old_path", "change_kind", "presence", "file_kind",
        "inspection_kind", "size_bytes", "mode", "sha256", "guidance_chain_id",
        "old_guidance_chain_id",
    }
    item = _exact(value, keys, "target record")
    _identifier(item["target_id"], "target", "target id")
    canonical_path(item["path"], allow_root=True)
    if item["old_path"] is not None:
        canonical_path(item["old_path"])
    if item["change_kind"] not in {"added", "modified", "deleted", "renamed", "type_changed", "mode_changed", "untracked", "snapshot", "unknown"}:
        raise PlanError("target change kind is invalid")
    if item["presence"] not in {"present", "absent"} or item["file_kind"] not in {"regular", "directory", "absent", "other"}:
        raise PlanError("target presence or file kind is invalid")
    if item["inspection_kind"] not in {"text", "binary", "metadata_only", "absent", "unreadable", "oversized", "unsupported"}:
        raise PlanError("target inspection kind is invalid")
    if item["size_bytes"] is not None:
        _integer(item["size_bytes"], "target size", 0, 268435456)
    if item["mode"] is not None:
        _integer(item["mode"], "target mode", 0, 65535)
    if item["sha256"] is not None:
        _digest(item["sha256"], "target digest")
    _identifier(item["guidance_chain_id"], "chain", "guidance chain id")
    if item["old_guidance_chain_id"] is not None:
        _identifier(item["old_guidance_chain_id"], "chain", "old guidance chain id")
    if item["presence"] == "absent":
        if item["file_kind"] != "absent" or item["inspection_kind"] != "absent" or any(
            item[field] is not None for field in ("size_bytes", "mode", "sha256")
        ):
            raise PlanError("absent target metadata is inconsistent")
    elif item["file_kind"] == "directory":
        if item["inspection_kind"] != "metadata_only" or item["size_bytes"] != 0 or item["mode"] is None or item["sha256"] is None:
            raise PlanError("directory target metadata is inconsistent")
    elif item["file_kind"] == "regular":
        if item["inspection_kind"] not in {"text", "binary", "unreadable", "oversized", "unsupported"} or item["size_bytes"] is None or item["mode"] is None:
            raise PlanError("regular target metadata is inconsistent")
        if item["inspection_kind"] in {"text", "binary"} and item["sha256"] is None:
            raise PlanError("inspected regular target requires a digest")
        if item["inspection_kind"] in {"unreadable", "oversized", "unsupported"} and item["sha256"] is not None:
            raise PlanError("uninspected regular target must not claim a digest")
    elif item["presence"] == "present":
        raise PlanError("present target file kind is inconsistent")
    if item["change_kind"] == "renamed" and item["old_path"] is None:
        raise PlanError("renamed target requires an old path")
    if item["change_kind"] != "renamed" and item["old_path"] is not None:
        raise PlanError("only renamed targets may carry an old path")
    return item


def _validate_guidance_bindings(
    targets: list[dict[str, Any]],
    chains: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
) -> None:
    records = {value["target_id"]: value for value in targets}
    for record in targets:
        for field, governed_path in (
            ("guidance_chain_id", record["path"]),
            ("old_guidance_chain_id", record["old_path"]),
        ):
            chain_id = record[field]
            if chain_id is None:
                continue
            if chain_id not in chains or record["target_id"] not in chains[chain_id]["target_ids"]:
                raise PlanError("target guidance binding is invalid")
            expected_paths = ["VERIFY.md"]
            if governed_path != ".":
                parent = PurePosixPath(governed_path).parent
                current = PurePosixPath()
                for part in ([] if str(parent) == "." else parent.parts):
                    current /= part
                    expected_paths.append((current / "VERIFY.md").as_posix())
            actual_paths = [sources[value]["path"] for value in chains[chain_id]["source_ids"][1:]]
            if any(value not in expected_paths for value in actual_paths):
                raise PlanError("guidance chain contains a non-ancestor source")
            positions = [expected_paths.index(value) for value in actual_paths]
            if positions != sorted(set(positions)):
                raise PlanError("guidance chain is not ordered root to nearest")
    for chain_id, chain in chains.items():
        for target_id in chain["target_ids"]:
            record = records[target_id]
            if chain_id not in {record["guidance_chain_id"], record["old_guidance_chain_id"]}:
                raise PlanError("guidance chain contains an unbound target")


def _revalidate_target(root: Path, item: dict[str, Any]) -> None:
    path = safe_repo_path(root, item["path"], allow_absent_final=True)
    if item["presence"] == "absent":
        if path.exists() or path.is_symlink():
            raise PlanError(f"target changed after context resolution: {item['path']}")
        return
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise PlanError(f"target changed after context resolution: {item['path']}") from exc
    if stat.S_ISDIR(metadata.st_mode):
        if item["file_kind"] != "directory" or item["mode"] != stat.S_IMODE(metadata.st_mode):
            raise PlanError(f"target changed after context resolution: {item['path']}")
        return
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise PlanError(f"target changed after context resolution: {item['path']}")
    if item["inspection_kind"] in {"unreadable", "oversized", "unsupported"}:
        if item["size_bytes"] != int(metadata.st_size) or item["mode"] != stat.S_IMODE(metadata.st_mode):
            raise PlanError(f"target changed after context resolution: {item['path']}")
        return
    snapshot = filesystem_snapshot(path, metadata)
    _, raw = read_regular(path, 16 * 1024 * 1024, expected_snapshot=snapshot, require_single_link=True)
    if item["inspection_kind"] == "text":
        _, canonical = canonical_text(raw, item["path"])
        digest = _sha256(canonical)
    else:
        digest = _sha256(raw)
    if item["sha256"] != digest or item["size_bytes"] != len(raw) or item["mode"] != stat.S_IMODE(metadata.st_mode):
        raise PlanError(f"target changed after context resolution: {item['path']}")


@_fail_closed
def validate_context(context: Any, *, revalidate: bool) -> dict[str, Any]:
    keys = {
        "schema_version", "target", "target_sha256", "repository_state", "invocation",
        "authority", "policy", "limits", "targets", "guidance", "discovery",
        "command_candidates", "limitations",
    }
    item = _exact(context, keys, "context")
    if item["schema_version"] != SCHEMA_VERSION:
        raise PlanError("unsupported context schema version")
    target = _validate_target(item["target"])
    root = Path(target["repository_root"])
    targets = [_validate_target_record(value) for value in _array(item["targets"], "targets", 20000, minimum=1)]
    target_ids = [value["target_id"] for value in targets]
    _unique(target_ids, "target ids")
    expected_ids = [f"T{index:03d}" for index in range(1, len(targets) + 1)]
    if target_ids != expected_ids:
        raise PlanError("target ids are not canonical and sequential")
    target_payload = [
        {key: value for key, value in record.items() if key not in {"guidance_chain_id", "old_guidance_chain_id"}}
        for record in targets
    ]
    if _digest(item["target_sha256"], "target digest") != _sha256(_canonical_json(target_payload)):
        raise PlanError("target digest does not match the target inventory")
    repository = _exact(item["repository_state"], {"repository_identity_sha256", "git_repository", "head_revision", "protected_state_sha256", "protected_path_hashes"}, "repository state")
    repository_identity = _digest(repository["repository_identity_sha256"], "repository identity")
    _boolean(repository["git_repository"], "git repository")
    if repository["head_revision"] is not None:
        text(repository["head_revision"], "head revision", maximum=512)
    _digest(repository["protected_state_sha256"], "protected state digest")
    protected_path_hashes = _array(repository["protected_path_hashes"], "protected path hashes", 100000)
    for value in protected_path_hashes:
        _digest(value, "protected path hash")
    if protected_path_hashes != sorted(set(protected_path_hashes)):
        raise PlanError("protected path hashes are not canonical")
    if repository_identity != _sha256(os.path.normcase(str(root)).encode("utf-8")):
        raise PlanError("repository identity does not match repository root")
    if target["base_revision"] != repository["head_revision"]:
        raise PlanError("target base revision does not match repository state")
    invocation = _exact(item["invocation"], {"mode", "request", "freshness", "tier_cap", "command_cap", "time_cap_seconds"}, "invocation")
    if invocation["mode"] not in {"plan", "execute"}:
        raise PlanError("invocation mode is invalid")
    text(invocation["request"], "request", maximum=4000)
    freshness = _exact(invocation["freshness"], {"context_kind", "producer", "producer_version", "consumer"}, "freshness")
    if freshness["context_kind"] not in {"fresh", "existing"}:
        raise PlanError("freshness context kind is invalid")
    text(freshness["producer"], "freshness producer", maximum=128)
    if freshness["producer_version"] is not None:
        text(freshness["producer_version"], "freshness producer version", maximum=128)
    if freshness["consumer"] is not None:
        text(freshness["consumer"], "freshness consumer", maximum=128)
    if invocation["tier_cap"] not in {None, "focused", "subsystem", "project"}:
        raise PlanError("tier cap is invalid")
    if invocation["command_cap"] is not None:
        _integer(invocation["command_cap"], "command cap", 0, 128)
    if invocation["time_cap_seconds"] is not None:
        _integer(invocation["time_cap_seconds"], "time cap", 0, 86400)
    authority = _exact(item["authority"], {"source_kind", "source", "direct_execution_intent", "authorized_effects"}, "authority")
    if authority["source_kind"] not in {"caller", "user_global", "none"}:
        raise PlanError("authority source kind is invalid")
    text(authority["source"], "authority source", maximum=4000)
    _boolean(authority["direct_execution_intent"], "direct execution intent")
    effects = _array(authority["authorized_effects"], "authorized effects", 14)
    _unique(effects, "authorized effects")
    if any(value not in ORDINARY_EFFECTS for value in effects):
        raise PlanError("invocation authority contains an excluded effect")
    policy_ids: list[str] = []
    policy_labels: list[str] = []
    for value in _array(item["policy"], "policy", 64, minimum=1):
        policy = _exact(value, {"policy_id", "kind", "label", "sha256", "content"}, "policy source")
        policy_ids.append(_identifier(policy["policy_id"], "policy", "policy id"))
        if policy["kind"] not in {"caller", "user_global", "project"}:
            raise PlanError("policy kind is invalid")
        policy_labels.append(text(policy["label"], "policy label", maximum=512))
        content = text(policy["content"], "policy content", maximum=1048576).replace("\r\n", "\n").replace("\r", "\n")
        if _digest(policy["sha256"], "policy digest") != _sha256(content.encode("utf-8")):
            raise PlanError("policy digest does not match content")
    _unique(policy_ids, "policy ids")
    _unique(policy_labels, "policy labels")
    if policy_ids != [f"P{index:03d}" for index in range(1, len(policy_ids) + 1)] or item["policy"][0]["kind"] != "caller":
        raise PlanError("policy identities are not canonical")
    guidance = _exact(item["guidance"], {"sources", "chains"}, "guidance")
    source_ids: list[str] = []
    source_map: dict[str, dict[str, Any]] = {}
    for value in _array(guidance["sources"], "guidance sources", 5000, minimum=1):
        source = _exact(value, {"source_id", "kind", "path", "provenance", "revision", "sha256", "content"}, "guidance source")
        source_id = _identifier(source["source_id"], "source", "source id")
        source_ids.append(source_id)
        source_map[source_id] = source
        canonical_path(source["path"])
        if source["kind"] not in {"skill", "repository"} or source["provenance"] not in {"locked_skill", "git_head", "current_filesystem"}:
            raise PlanError("guidance source kind or provenance is invalid")
        if source["revision"] is not None:
            text(source["revision"], "guidance revision", maximum=512)
        content = source["content"]
        if not isinstance(content, str) or len(content) > 16777216:
            raise PlanError("guidance content is invalid")
        if _digest(source["sha256"], "guidance digest") != _sha256(content.encode("utf-8")):
            raise PlanError("guidance digest does not match content")
        if source["kind"] == "skill":
            if source_id != "S001" or source["provenance"] != "locked_skill" or source["revision"] is None:
                raise PlanError("locked skill guidance provenance is invalid")
        elif repository["git_repository"]:
            if source["provenance"] != "git_head" or source["revision"] != repository["head_revision"]:
                raise PlanError("repository guidance is not bound to Git HEAD")
        elif source["provenance"] != "current_filesystem" or source["revision"] is not None:
            raise PlanError("non-Git repository guidance provenance is invalid")
    _unique(source_ids, "guidance source ids")
    if source_ids != [f"S{index:03d}" for index in range(1, len(source_ids) + 1)] or guidance["sources"][0]["kind"] != "skill":
        raise PlanError("guidance source identities are not canonical")
    chain_ids: list[str] = []
    chain_map: dict[str, dict[str, Any]] = {}
    for value in _array(guidance["chains"], "guidance chains", 20000, minimum=1):
        chain = _exact(value, {"chain_id", "target_ids", "source_ids", "complete"}, "guidance chain")
        chain_id = _identifier(chain["chain_id"], "chain", "chain id")
        chain_ids.append(chain_id)
        chain_map[chain_id] = chain
        chain_targets = [_identifier(value, "target", "chain target") for value in _array(chain["target_ids"], "chain targets", 20000, minimum=1)]
        chain_sources = [_identifier(value, "source", "chain source") for value in _array(chain["source_ids"], "chain sources", 256, minimum=1)]
        _unique(chain_targets, "chain targets")
        _unique(chain_sources, "chain sources")
        if any(value not in target_ids for value in chain_targets) or any(value not in source_ids for value in chain_sources):
            raise PlanError("guidance chain cites an unknown target or source")
        _boolean(chain["complete"], "guidance chain completeness")
        if chain_sources[0] != source_ids[0]:
            raise PlanError("guidance chain does not begin with locked skill guidance")
    _unique(chain_ids, "guidance chain ids")
    if chain_ids != [f"G{index:03d}" for index in range(1, len(chain_ids) + 1)]:
        raise PlanError("guidance chain identities are not canonical")
    for record in targets:
        if record["guidance_chain_id"] not in chain_map or record["target_id"] not in chain_map[record["guidance_chain_id"]]["target_ids"]:
            raise PlanError("target guidance binding is invalid")
        old_chain = record["old_guidance_chain_id"]
        if old_chain is not None and (old_chain not in chain_map or record["target_id"] not in chain_map[old_chain]["target_ids"]):
            raise PlanError("old target guidance binding is invalid")
        for field, governed_path in (
            ("guidance_chain_id", record["path"]),
            ("old_guidance_chain_id", record["old_path"]),
        ):
            chain_id = record[field]
            if chain_id is None:
                continue
            expected_paths = ["VERIFY.md"]
            if governed_path != ".":
                parent = PurePosixPath(governed_path).parent
                current = PurePosixPath()
                for part in ([] if str(parent) == "." else parent.parts):
                    current /= part
                    expected_paths.append((current / "VERIFY.md").as_posix())
            actual_paths = [source_map[value]["path"] for value in chain_map[chain_id]["source_ids"][1:]]
            if any(value not in expected_paths for value in actual_paths):
                raise PlanError("guidance chain contains a non-ancestor source")
            positions = [expected_paths.index(value) for value in actual_paths]
            if positions != sorted(set(positions)):
                raise PlanError("guidance chain is not ordered root to nearest")
    for chain_id, chain in chain_map.items():
        for target_id in chain["target_ids"]:
            record = next(value for value in targets if value["target_id"] == target_id)
            if chain_id not in {record["guidance_chain_id"], record["old_guidance_chain_id"]}:
                raise PlanError("guidance chain contains an unbound target")
    discovery_ids: list[str] = []
    discovery_paths: dict[str, str] = {}
    for value in _array(item["discovery"], "discovery", 5000):
        source = _exact(value, {"discovery_id", "kind", "path", "sha256", "inspection_kind", "provenance"}, "discovery source")
        source_id = _identifier(source["discovery_id"], "discovery", "discovery id")
        discovery_ids.append(source_id)
        discovery_paths[source_id] = canonical_path(source["path"])
        if source["kind"] not in DISCOVERY_KINDS or source["provenance"] not in DISCOVERY_PROVENANCE:
            raise PlanError("discovery source kind or provenance is invalid")
        if source["inspection_kind"] not in {"text", "binary", "metadata_only", "unreadable", "oversized", "unsupported"}:
            raise PlanError("discovery inspection kind is invalid")
        if source["sha256"] is not None:
            _digest(source["sha256"], "discovery digest")
        if (source["inspection_kind"] in {"text", "binary"}) != (source["sha256"] is not None):
            raise PlanError("discovery digest and inspection state are inconsistent")
    _unique(discovery_ids, "discovery ids")
    if discovery_ids != [f"D{index:03d}" for index in range(1, len(discovery_ids) + 1)]:
        raise PlanError("discovery identities are not canonical")
    candidate_ids: list[str] = []
    known_provenance = set(policy_ids) | set(source_ids) | set(discovery_ids)
    for value in _array(item["command_candidates"], "command candidates", 128):
        candidate = _exact(value, {"candidate_id", "argv", "cwd", "provenance_ids", "timeout_seconds", "repetitions", "expected_effects", "artifact_boundaries", "authority"}, "command candidate")
        candidate_ids.append(_identifier(candidate["candidate_id"], "candidate", "candidate id"))
        argv = _array(candidate["argv"], "candidate argv", 128, minimum=1)
        for argument in argv:
            text(argument, "candidate argument", maximum=4096)
        canonical_path(candidate["cwd"], allow_root=True)
        provenance_ids = _array(candidate["provenance_ids"], "candidate provenance", 64, minimum=1)
        _unique(provenance_ids, "candidate provenance")
        if any(value not in known_provenance for value in provenance_ids):
            raise PlanError("candidate cites unknown provenance")
        _integer(candidate["timeout_seconds"], "candidate timeout", 1, 3600)
        _integer(candidate["repetitions"], "candidate repetitions", 1, 32)
        expected_effects = _array(candidate["expected_effects"], "candidate effects", 14, minimum=1)
        _unique(expected_effects, "candidate effects")
        boundary_kinds: set[str] = set()
        for boundary in _array(candidate["artifact_boundaries"], "artifact boundaries", 64):
            boundary = _exact(boundary, {"root_kind", "path"}, "artifact boundary")
            if boundary["root_kind"] not in {"repository", "run_temp"}:
                raise PlanError("artifact boundary root kind is invalid")
            canonical_path(boundary["path"])
            boundary_kinds.add(boundary["root_kind"])
        if any(value not in ALL_EFFECTS for value in expected_effects):
            raise PlanError("candidate effect is invalid")
        if "disposable_repository_write" in expected_effects and "repository" not in boundary_kinds:
            raise PlanError("repository write candidate has no repository artifact boundary")
        if "bounded_temporary_write" in expected_effects and "run_temp" not in boundary_kinds:
            raise PlanError("temporary write candidate has no run-temp artifact boundary")
        candidate_authority = _exact(candidate["authority"], {"source_kind", "source", "authorized"}, "candidate authority")
        if candidate_authority["source_kind"] not in {"caller", "user_global", "none"}:
            raise PlanError("candidate authority source kind is invalid")
        text(candidate_authority["source"], "candidate authority source", maximum=4000)
        _boolean(candidate_authority["authorized"], "candidate authorized")
        if candidate_authority["authorized"] and (candidate_authority["source_kind"] == "none" or not set(expected_effects).issubset(ORDINARY_EFFECTS)):
            raise PlanError("candidate authority expands the ordinary effect boundary")
        if not candidate_authority["authorized"] and candidate_authority["source_kind"] != "none":
            raise PlanError("unauthorized candidate must not retain an authority kind")
    _unique(candidate_ids, "candidate ids")
    if candidate_ids != [f"Q{index:03d}" for index in range(1, len(candidate_ids) + 1)]:
        raise PlanError("candidate identities are not canonical")
    known_context_sources = set(policy_ids) | set(source_ids) | set(discovery_ids) | set(candidate_ids)
    for value in _array(item["limitations"], "context limitations", 256):
        limitation = _exact(value, {"code", "message", "source_ids", "affected_target_ids", "material"}, "context limitation")
        if limitation["code"] not in {"target_unavailable", "target_limit", "guidance_unavailable", "guidance_conflict", "guidance_limit", "discovery_unavailable", "discovery_limit", "authority_unavailable", "unsafe_candidate", "unsupported_effect", "context_drift", "other"}:
            raise PlanError("context limitation code is invalid")
        text(limitation["message"], "context limitation message", maximum=4000)
        limitation_sources = _array(limitation["source_ids"], "context limitation sources", 5000)
        limitation_targets = _array(limitation["affected_target_ids"], "context limitation targets", 20000)
        _unique(limitation_sources, "context limitation sources")
        _unique(limitation_targets, "context limitation targets")
        if any(value not in known_context_sources for value in limitation_sources) or any(value not in target_ids for value in limitation_targets):
            raise PlanError("context limitation cites an unknown record")
        _boolean(limitation["material"], "context limitation material")
    limits = _exact(item["limits"], {"target_records", "target_bytes", "discovery_records", "discovery_bytes", "effective_guidance_bytes_per_target", "planned_checks", "argv_entries_per_check", "timeout_seconds_per_check", "total_execution_seconds", "repetitions_per_check", "capture_bytes_per_stream", "diagnostic_excerpt_bytes_per_stream", "canonical_json_bytes"}, "limits")
    ranges = {
        "target_records": (1, 20000), "target_bytes": (1, 268435456),
        "discovery_records": (0, 5000), "discovery_bytes": (0, 67108864),
        "effective_guidance_bytes_per_target": (0, 1048576),
        "planned_checks": (0, 128), "argv_entries_per_check": (1, 128),
        "timeout_seconds_per_check": (1, 3600), "total_execution_seconds": (0, 86400),
        "repetitions_per_check": (1, 32), "capture_bytes_per_stream": (0, 16777216),
        "diagnostic_excerpt_bytes_per_stream": (0, 16384), "canonical_json_bytes": (1, MAX_JSON_BYTES),
    }
    for field, (minimum, maximum) in ranges.items():
        _integer(limits[field], field.replace("_", " "), minimum, maximum)
    if len(targets) > limits["target_records"] or len(item["discovery"]) > limits["discovery_records"] or len(item["command_candidates"]) > limits["planned_checks"]:
        raise PlanError("context inventory exceeds its declared limits")
    if any(len(value["argv"]) > limits["argv_entries_per_check"] or value["timeout_seconds"] > limits["timeout_seconds_per_check"] or value["repetitions"] > limits["repetitions_per_check"] for value in item["command_candidates"]):
        raise PlanError("command candidate exceeds its declared limits")
    if len(_canonical_json(item)) > limits["canonical_json_bytes"]:
        raise PlanError("canonical context exceeds its declared JSON ceiling")
    if revalidate:
        for record in targets:
            _revalidate_target(root, record)
        for source_id, relative in discovery_paths.items():
            source = next(value for value in item["discovery"] if value["discovery_id"] == source_id)
            path = safe_repo_path(root, relative)
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > 16 * 1024 * 1024:
                raise PlanError(f"discovery source changed after context resolution: {relative}")
            snapshot = filesystem_snapshot(path, metadata)
            _, raw = read_regular(path, 16 * 1024 * 1024, expected_snapshot=snapshot, require_single_link=True)
            try:
                _, canonical = canonical_text(raw, relative)
                digest = _sha256(canonical)
            except SafetyError:
                digest = _sha256(raw)
            if source["sha256"] != digest:
                raise PlanError(f"discovery source changed after context resolution: {relative}")
        from verification_context import _git, _protected_digest

        protected, protected_paths, protected_limits = _protected_digest(
            root,
            repository["git_repository"],
            int(item["limits"]["target_bytes"]),
        )
        if protected_limits or protected != repository["protected_state_sha256"] or protected_paths != repository["protected_path_hashes"]:
            raise PlanError("protected repository state changed after context resolution")
        if repository["git_repository"]:
            current_head = _git(root, ["rev-parse", "--verify", "HEAD^{commit}"], timeout=10).decode("ascii").strip()
            if current_head != repository["head_revision"]:
                raise PlanError("Git HEAD changed after context resolution")
    return item


def _location(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    item = _exact(value, {"path", "start_line", "end_line"}, "location")
    canonical_path(item["path"], allow_root=True)
    for field in ("start_line", "end_line"):
        if item[field] is not None:
            _integer(item[field], field.replace("_", " "), 1, 2147483647)
    if item["start_line"] is None and item["end_line"] is not None:
        raise PlanError("location end line requires a start line")
    if item["start_line"] is not None and item["end_line"] is not None and item["end_line"] < item["start_line"]:
        raise PlanError("location end line precedes start line")
    return item


def _semantic_limitation(value: Any, known_sources: set[str], claim_map: dict[str, str], target_ids: set[str]) -> dict[str, Any]:
    item = _exact(value, {"code", "message", "source_ids", "target_ids", "claim_keys", "material", "next_action"}, "semantic limitation")
    if item["code"] not in PLAN_LIMITATION_CODES:
        raise PlanError("semantic limitation code is invalid")
    message = text(item["message"], "limitation message", maximum=4000)
    sources = _array(item["source_ids"], "limitation source ids", 5000)
    targets = _array(item["target_ids"], "limitation target ids", 20000)
    claim_keys = _array(item["claim_keys"], "limitation claim keys", 20000)
    _unique(sources, "limitation source ids")
    _unique(targets, "limitation target ids")
    _unique(claim_keys, "limitation claim keys")
    if any(value not in known_sources for value in sources) or any(value not in target_ids for value in targets) or any(value not in claim_map for value in claim_keys):
        raise PlanError("semantic limitation cites an unknown record")
    if item["next_action"] not in NEXT_ACTIONS:
        raise PlanError("semantic limitation next action is invalid")
    return {"code": item["code"], "message": message, "source_ids": sorted(set(sources)), "target_ids": sorted(set(targets)), "claim_ids": sorted({claim_map[value] for value in claim_keys}), "material": _boolean(item["material"], "limitation material"), "next_action": item["next_action"]}


@_fail_closed
def finalize(context: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    context = validate_context(context, revalidate=True)
    context_sha = _sha256(_canonical_json(context))
    draft = _exact(draft, {"claims", "guidance_interpretations", "checks", "limitations"}, "plan draft")
    target_ids = {item["target_id"] for item in context["targets"]}
    policy_ids = {item["policy_id"] for item in context["policy"]}
    guidance_ids = {item["source_id"] for item in context["guidance"]["sources"]}
    discovery_ids = {item["discovery_id"] for item in context["discovery"]}
    known_sources = policy_ids | guidance_ids | discovery_ids
    claim_drafts: list[tuple[str, dict[str, Any], str]] = []
    claim_keys_seen: set[str] = set()
    for value in _array(draft["claims"], "draft claims", 20000):
        claim = _exact(value, {"key", "statement", "material", "target_ids", "basis", "evidence_requirement"}, "draft claim")
        key = text(claim["key"], "claim key", maximum=128)
        if key in claim_keys_seen:
            raise PlanError(f"duplicate claim key: {key}")
        claim_keys_seen.add(key)
        statement = text(claim["statement"], "claim statement", maximum=4000)
        selected_targets = _array(claim["target_ids"], "claim targets", 20000, minimum=1)
        _unique(selected_targets, "claim targets")
        if any(value not in target_ids for value in selected_targets):
            raise PlanError("claim cites an unknown target")
        bases = []
        for basis_value in _array(claim["basis"], "claim basis", 64, minimum=1):
            basis = _exact(basis_value, {"kind", "description", "source_id", "location"}, "claim basis")
            if basis["kind"] not in {"caller", "agent_policy", "verify_guidance", "target_content", "project_contract", "related_test", "reasoning"}:
                raise PlanError("claim basis kind is invalid")
            if basis["source_id"] is not None and basis["source_id"] not in known_sources:
                raise PlanError("claim basis cites an unknown source")
            bases.append({"kind": basis["kind"], "description": text(basis["description"], "basis description", maximum=4000), "source_id": basis["source_id"], "location": _location(basis["location"])})
        if claim["evidence_requirement"] not in {"static", "command", "either"}:
            raise PlanError("claim evidence requirement is invalid")
        semantic = {"statement": statement, "material": _boolean(claim["material"], "claim material"), "target_ids": sorted(selected_targets), "basis": bases, "evidence_requirement": claim["evidence_requirement"]}
        fingerprint = _sha256(_canonical_json(semantic))
        claim_drafts.append((key, semantic, fingerprint))
    claim_drafts.sort(key=lambda value: (value[2], value[1]["statement"]))
    claims: list[dict[str, Any]] = []
    claim_map: dict[str, str] = {}
    for index, (key, semantic, fingerprint) in enumerate(claim_drafts, start=1):
        claim_id = f"C{index:03d}"
        claim_map[key] = claim_id
        claims.append({"claim_id": claim_id, "fingerprint": fingerprint, **semantic})
    interpretation_drafts = []
    interpretation_keys: set[str] = set()
    for value in _array(draft["guidance_interpretations"], "guidance interpretations", 5000):
        interpretation = _exact(value, {"key", "source_id", "target_ids", "claim_keys", "kind", "requirement", "replaces_key", "replacement_reason"}, "guidance interpretation")
        key = text(interpretation["key"], "interpretation key", maximum=128)
        if key in interpretation_keys:
            raise PlanError(f"duplicate interpretation key: {key}")
        interpretation_keys.add(key)
        if interpretation["source_id"] not in guidance_ids:
            raise PlanError("guidance interpretation cites a non-guidance source")
        selected_targets = _array(interpretation["target_ids"], "interpretation targets", 20000, minimum=1)
        claim_keys = _array(interpretation["claim_keys"], "interpretation claim keys", 20000)
        _unique(selected_targets, "interpretation targets")
        _unique(claim_keys, "interpretation claim keys")
        if any(value not in target_ids for value in selected_targets) or any(value not in claim_map for value in claim_keys):
            raise PlanError("guidance interpretation cites an unknown target or claim")
        if interpretation["kind"] not in {"required", "conditional", "recommended", "replacement", "artifact"}:
            raise PlanError("guidance interpretation kind is invalid")
        if interpretation["kind"] in {"required", "conditional", "replacement"} and not claim_keys:
            raise PlanError("required, conditional, and replacement guidance must map to a claim")
        replaces_key = interpretation["replaces_key"]
        replacement_reason = interpretation["replacement_reason"]
        if interpretation["kind"] == "replacement":
            text(replaces_key, "replaced interpretation key", maximum=128)
            text(replacement_reason, "replacement reason", maximum=4000)
        elif replaces_key is not None or replacement_reason is not None:
            raise PlanError("only replacement guidance may set replacement fields")
        semantic = {
            "source_id": interpretation["source_id"],
            "target_ids": sorted(set(selected_targets)),
            "claim_ids": sorted({claim_map[value] for value in claim_keys}),
            "kind": interpretation["kind"],
            "requirement": text(interpretation["requirement"], "guidance requirement", maximum=4000),
            "replaces_key": replaces_key,
            "replacement_reason": replacement_reason,
        }
        interpretation_drafts.append((key, semantic, _sha256(_canonical_json(semantic))))
    interpretation_drafts.sort(key=lambda value: (value[2], value[1]["source_id"]))
    interpretation_map = {key: f"I{index:03d}" for index, (key, _, _) in enumerate(interpretation_drafts, start=1)}
    interpretations = []
    source_order_by_chain = {
        chain["chain_id"]: {source_id: index for index, source_id in enumerate(chain["source_ids"])}
        for chain in context["guidance"]["chains"]
    }
    target_chain_ids = {
        target["target_id"]: [target["guidance_chain_id"]] + ([target["old_guidance_chain_id"]] if target["old_guidance_chain_id"] else [])
        for target in context["targets"]
    }
    semantic_by_key = {key: semantic for key, semantic, _ in interpretation_drafts}
    for index, (key, semantic, _) in enumerate(interpretation_drafts, start=1):
        replaces_id = None
        if semantic["kind"] == "replacement":
            replaced_key = semantic["replaces_key"]
            if replaced_key not in interpretation_map or replaced_key == key:
                raise PlanError("replacement cites an unknown or identical interpretation")
            replaced = semantic_by_key[replaced_key]
            if replaced["kind"] == "replacement" or not set(semantic["target_ids"]).issubset(replaced["target_ids"]):
                raise PlanError("replacement scope does not identify a broader requirement")
            for target_id in semantic["target_ids"]:
                if not any(
                    semantic["source_id"] in source_order_by_chain[chain_id]
                    and replaced["source_id"] in source_order_by_chain[chain_id]
                    and source_order_by_chain[chain_id][semantic["source_id"]] > source_order_by_chain[chain_id][replaced["source_id"]]
                    for chain_id in target_chain_ids[target_id]
                ):
                    raise PlanError("replacement source is not closer than the replaced source")
            replaces_id = interpretation_map[replaced_key]
        interpretations.append({
            "interpretation_id": f"I{index:03d}",
            "source_id": semantic["source_id"],
            "target_ids": semantic["target_ids"],
            "claim_ids": semantic["claim_ids"],
            "kind": semantic["kind"],
            "requirement": semantic["requirement"],
            "replaces_interpretation_id": replaces_id,
            "replacement_reason": semantic["replacement_reason"],
        })
    candidate_map = {item["candidate_id"]: item for item in context["command_candidates"]}
    checks: list[dict[str, Any]] = []
    check_keys: dict[str, str] = {}
    selected_candidates: set[str] = set()
    for index, value in enumerate(_array(draft["checks"], "draft checks", 128), start=1):
        check = _exact(value, {"key", "candidate_id", "tier", "reason", "claim_keys", "depends_on_keys", "useful_after_failure"}, "draft check")
        key = text(check["key"], "check key", maximum=128)
        if key in check_keys:
            raise PlanError(f"duplicate check key: {key}")
        candidate_id = _identifier(check["candidate_id"], "candidate", "candidate id")
        if candidate_id not in candidate_map or candidate_id in selected_candidates:
            raise PlanError("check selects an unknown or duplicate candidate")
        selected_candidates.add(candidate_id)
        if check["tier"] not in {"focused", "subsystem", "project"}:
            raise PlanError("check tier is invalid")
        claim_keys = _array(check["claim_keys"], "check claim keys", 20000, minimum=1)
        dependencies = _array(check["depends_on_keys"], "check dependencies", 127)
        _unique(claim_keys, "check claim keys")
        _unique(dependencies, "check dependencies")
        if any(value not in claim_map for value in claim_keys) or any(value not in check_keys for value in dependencies):
            raise PlanError("check cites an unknown claim or forward dependency")
        candidate = candidate_map[candidate_id]
        if not set(candidate["expected_effects"]).issubset(ORDINARY_EFFECTS):
            decision = "unsupported"
        elif context["invocation"]["mode"] == "plan":
            decision = "plan_only"
        elif candidate["authority"]["authorized"]:
            decision = "run"
        else:
            decision = "authorization_required"
        semantic = {"candidate_id": candidate_id, "tier": check["tier"], "reason": text(check["reason"], "check reason", maximum=4000), "claim_ids": sorted({claim_map[value] for value in claim_keys}), "depends_on": [check_keys[value] for value in dependencies], "useful_after_failure": _boolean(check["useful_after_failure"], "useful after failure")}
        fingerprint = _sha256(_canonical_json({**semantic, "argv": candidate["argv"], "cwd": candidate["cwd"], "expected_effects": candidate["expected_effects"], "artifact_boundaries": candidate["artifact_boundaries"]}))
        check_id = f"K{index:03d}"
        check_keys[key] = check_id
        checks.append({
            "check_id": check_id,
            "fingerprint": fingerprint,
            "candidate_id": candidate_id,
            "argv": candidate["argv"],
            "cwd": candidate["cwd"],
            "tier": semantic["tier"],
            "reason": semantic["reason"],
            "claim_ids": semantic["claim_ids"],
            "timeout_seconds": candidate["timeout_seconds"],
            "repetitions": candidate["repetitions"],
            "depends_on": semantic["depends_on"],
            "useful_after_failure": semantic["useful_after_failure"],
            "expected_effects": candidate["expected_effects"],
            "artifact_boundaries": candidate["artifact_boundaries"],
            "authority": candidate["authority"],
            "decision": decision,
        })
    tier_order = {"focused": 0, "subsystem": 1, "project": 2}
    tier_cap = context["invocation"]["tier_cap"]
    if tier_cap is not None and any(tier_order[value["tier"]] > tier_order[tier_cap] for value in checks):
        raise PlanError("semantic plan selects a check above the caller tier cap")
    time_cap = context["invocation"]["time_cap_seconds"]
    planned_seconds = sum(value["timeout_seconds"] * value["repetitions"] for value in checks)
    if time_cap is not None and planned_seconds > time_cap:
        raise PlanError("semantic plan exceeds the caller total-time cap")
    context_limitations = []
    for value in context["limitations"]:
        limitation = _exact(value, {"code", "message", "source_ids", "affected_target_ids", "material"}, "context limitation")
        code = limitation["code"] if limitation["code"] in PLAN_LIMITATION_CODES else "other"
        if code in {"authority_unavailable", "unsafe_candidate", "unsupported_effect"}:
            next_action = "authorization" if code == "authority_unavailable" else "manual"
        elif code.startswith("target"):
            next_action = "rescope"
        elif code == "guidance_conflict":
            next_action = "decision"
        else:
            next_action = "plan"
        context_limitations.append({"code": code, "message": limitation["message"], "source_ids": limitation["source_ids"], "target_ids": limitation["affected_target_ids"], "claim_ids": [], "material": limitation["material"], "next_action": next_action})
    semantic_limitations = [
        _semantic_limitation(value, known_sources | set(interpretation_map.values()) | set(candidate_map), claim_map, target_ids)
        for value in _array(draft["limitations"], "draft limitations", 256)
    ]
    material_claim_ids = sorted(item["claim_id"] for item in claims if item["material"])
    checked_claim_ids = {claim_id for check in checks for claim_id in check["claim_ids"]}
    planned_claim_ids = sorted({item["claim_id"] for item in claims if item["evidence_requirement"] in {"static", "either"}} | checked_claim_ids)
    uncovered = sorted(set(material_claim_ids) - set(planned_claim_ids))
    limitations = context_limitations + semantic_limitations
    if uncovered:
        limitations.append({"code": "coverage_gap", "message": "One or more material claims have no planned evidence.", "source_ids": [], "target_ids": [], "claim_ids": uncovered, "material": True, "next_action": "plan"})
    for check in checks:
        if check["decision"] == "authorization_required":
            limitations.append({"code": "authority_unavailable", "message": f"{check['check_id']} requires separate execution authority.", "source_ids": [check["candidate_id"]], "target_ids": [], "claim_ids": check["claim_ids"], "material": True, "next_action": "authorization"})
        elif check["decision"] == "unsupported":
            limitations.append({"code": "unsupported_effect", "message": f"{check['check_id']} requires an effect excluded from verify-project v1.", "source_ids": [check["candidate_id"]], "target_ids": [], "claim_ids": check["claim_ids"], "material": True, "next_action": "manual"})
    unique_limitations = { _canonical_json(value): value for value in limitations }
    limitations = [unique_limitations[key] for key in sorted(unique_limitations)]
    if len(limitations) > 256:
        raise PlanError("plan limitations exceed the canonical ceiling")
    material_limits = sum(1 for value in limitations if value["material"])
    if material_limits:
        execution_state = "blocked"
    elif context["invocation"]["mode"] == "plan":
        execution_state = "plan_only"
    elif all(item["decision"] == "run" for item in checks):
        execution_state = "ready"
    else:
        execution_state = "blocked"
    highest_tier = max((item["tier"] for item in checks), key=lambda value: tier_order[value], default=None)
    policy = [{key: value for key, value in item.items() if key != "content"} for item in context["policy"]]
    guidance = {
        "sources": [{key: value for key, value in item.items() if key != "content"} for item in context["guidance"]["sources"]],
        "chains": context["guidance"]["chains"],
    }
    plan = {
        "schema_version": SCHEMA_VERSION,
        "context_sha256": context_sha,
        "target": context["target"],
        "target_sha256": context["target_sha256"],
        "targets": context["targets"],
        "repository_state": context["repository_state"],
        "invocation": {key: value for key, value in context["invocation"].items() if key != "request"},
        "policy": policy,
        "guidance": guidance,
        "discovery": context["discovery"],
        "claims": claims,
        "guidance_interpretations": interpretations,
        "checks": checks,
        "coverage": {"material_claim_ids": material_claim_ids, "planned_claim_ids": planned_claim_ids, "uncovered_claim_ids": uncovered, "highest_tier": highest_tier},
        "limitations": limitations,
        "execution_state": execution_state,
        "summary": {
            "conclusion": "Verification plan is ready for bounded execution." if execution_state == "ready" else ("Verification plan is complete and non-executing." if execution_state == "plan_only" else "Verification plan is blocked by material limitations."),
            "claim_count": len(claims),
            "material_claim_count": len(material_claim_ids),
            "check_count": len(checks),
            "runnable_check_count": sum(1 for item in checks if item["decision"] == "run"),
            "material_limitation_count": material_limits,
        },
    }
    validate_plan(plan)
    return plan


@_fail_closed
def validate_plan(plan: Any) -> dict[str, Any]:
    keys = {"schema_version", "context_sha256", "target", "target_sha256", "targets", "repository_state", "invocation", "policy", "guidance", "discovery", "claims", "guidance_interpretations", "checks", "coverage", "limitations", "execution_state", "summary"}
    item = _exact(plan, keys, "plan")
    if item["schema_version"] != SCHEMA_VERSION:
        raise PlanError("unsupported plan schema version")
    _digest(item["context_sha256"], "context digest")
    target = _validate_target(item["target"])
    target_digest = _digest(item["target_sha256"], "target digest")
    target_records = [_validate_target_record(value) for value in _array(item["targets"], "targets", 20000, minimum=1)]
    target_id_list = [value["target_id"] for value in target_records]
    if target_id_list != [f"T{index:03d}" for index in range(1, len(target_records) + 1)]:
        raise PlanError("target ids are not canonical and sequential")
    target_ids = set(target_id_list)
    target_payload = [
        {key: value for key, value in record.items() if key not in {"guidance_chain_id", "old_guidance_chain_id"}}
        for record in target_records
    ]
    if target_digest != _sha256(_canonical_json(target_payload)):
        raise PlanError("target digest does not match target inventory")
    repository = _exact(item["repository_state"], {"repository_identity_sha256", "git_repository", "head_revision", "protected_state_sha256", "protected_path_hashes"}, "repository state")
    repository_identity = _digest(repository["repository_identity_sha256"], "repository identity")
    _boolean(repository["git_repository"], "git repository")
    if repository["head_revision"] is not None:
        text(repository["head_revision"], "head revision", maximum=512)
    _digest(repository["protected_state_sha256"], "protected state digest")
    protected_path_hashes = _array(repository["protected_path_hashes"], "protected path hashes", 100000)
    for value in protected_path_hashes:
        _digest(value, "protected path hash")
    if protected_path_hashes != sorted(set(protected_path_hashes)):
        raise PlanError("protected path hashes are not canonical")
    if repository_identity != _sha256(os.path.normcase(target["repository_root"]).encode("utf-8")) or target["base_revision"] != repository["head_revision"]:
        raise PlanError("repository state does not match target")
    invocation = _exact(item["invocation"], {"mode", "freshness", "tier_cap", "command_cap", "time_cap_seconds"}, "invocation")
    if invocation["mode"] not in {"plan", "execute"} or invocation["tier_cap"] not in {None, "focused", "subsystem", "project"}:
        raise PlanError("plan invocation is invalid")
    freshness = _exact(invocation["freshness"], {"context_kind", "producer", "producer_version", "consumer"}, "freshness")
    if freshness["context_kind"] not in {"fresh", "existing"}:
        raise PlanError("freshness context kind is invalid")
    text(freshness["producer"], "freshness producer", maximum=128)
    for field in ("producer_version", "consumer"):
        if freshness[field] is not None:
            text(freshness[field], f"freshness {field.replace('_', ' ')}", maximum=128)
    if invocation["command_cap"] is not None:
        _integer(invocation["command_cap"], "command cap", 0, 128)
    if invocation["time_cap_seconds"] is not None:
        _integer(invocation["time_cap_seconds"], "time cap", 0, 86400)

    policy_ids: list[str] = []
    policy_labels: list[str] = []
    for value in _array(item["policy"], "policy", 64, minimum=1):
        policy = _exact(value, {"policy_id", "kind", "label", "sha256"}, "policy source")
        policy_ids.append(_identifier(policy["policy_id"], "policy", "policy id"))
        if policy["kind"] not in {"caller", "user_global", "project"}:
            raise PlanError("policy kind is invalid")
        policy_labels.append(text(policy["label"], "policy label", maximum=512))
        _digest(policy["sha256"], "policy digest")
    if policy_ids != [f"P{index:03d}" for index in range(1, len(policy_ids) + 1)] or item["policy"][0]["kind"] != "caller":
        raise PlanError("policy identities are not canonical")
    _unique(policy_labels, "policy labels")

    guidance = _exact(item["guidance"], {"sources", "chains"}, "guidance")
    source_ids: list[str] = []
    source_map: dict[str, dict[str, Any]] = {}
    for value in _array(guidance["sources"], "guidance sources", 5000, minimum=1):
        source = _exact(value, {"source_id", "kind", "path", "provenance", "revision", "sha256"}, "guidance source")
        source_id = _identifier(source["source_id"], "source", "source id")
        source_ids.append(source_id)
        source_map[source_id] = source
        canonical_path(source["path"])
        if source["kind"] not in {"skill", "repository"} or source["provenance"] not in {"locked_skill", "git_head", "current_filesystem"}:
            raise PlanError("guidance source kind or provenance is invalid")
        if source["revision"] is not None:
            text(source["revision"], "guidance revision", maximum=512)
        _digest(source["sha256"], "guidance digest")
        if source["kind"] == "skill":
            if source_id != "S001" or source["provenance"] != "locked_skill" or source["revision"] is None:
                raise PlanError("locked skill guidance provenance is invalid")
        elif repository["git_repository"]:
            if source["provenance"] != "git_head" or source["revision"] != repository["head_revision"]:
                raise PlanError("repository guidance is not bound to Git HEAD")
        elif source["provenance"] != "current_filesystem" or source["revision"] is not None:
            raise PlanError("non-Git repository guidance provenance is invalid")
    if source_ids != [f"S{index:03d}" for index in range(1, len(source_ids) + 1)]:
        raise PlanError("guidance source identities are not canonical")
    chain_ids: list[str] = []
    chain_map: dict[str, dict[str, Any]] = {}
    for value in _array(guidance["chains"], "guidance chains", 20000, minimum=1):
        chain = _exact(value, {"chain_id", "target_ids", "source_ids", "complete"}, "guidance chain")
        chain_id = _identifier(chain["chain_id"], "chain", "chain id")
        chain_ids.append(chain_id)
        chain_map[chain_id] = chain
        chain_targets = _array(chain["target_ids"], "chain targets", 20000, minimum=1)
        chain_sources = _array(chain["source_ids"], "chain sources", 256, minimum=1)
        _unique(chain_targets, "chain targets")
        _unique(chain_sources, "chain sources")
        if any(value not in target_ids for value in chain_targets) or any(value not in source_map for value in chain_sources) or chain_sources[0] != "S001":
            raise PlanError("guidance chain cites an unknown or invalid record")
        _boolean(chain["complete"], "guidance chain completeness")
    if chain_ids != [f"G{index:03d}" for index in range(1, len(chain_ids) + 1)]:
        raise PlanError("guidance chain identities are not canonical")
    for record in target_records:
        for field in ("guidance_chain_id", "old_guidance_chain_id"):
            chain_id = record[field]
            if chain_id is not None and (chain_id not in chain_map or record["target_id"] not in chain_map[chain_id]["target_ids"]):
                raise PlanError("target guidance binding is invalid")
    for chain_id, chain in chain_map.items():
        if any(chain_id not in {next(record for record in target_records if record["target_id"] == target_id)["guidance_chain_id"], next(record for record in target_records if record["target_id"] == target_id)["old_guidance_chain_id"]} for target_id in chain["target_ids"]):
            raise PlanError("guidance chain contains an unbound target")
    _validate_guidance_bindings(target_records, chain_map, source_map)

    discovery_ids: list[str] = []
    for value in _array(item["discovery"], "discovery", 5000):
        source = _exact(value, {"discovery_id", "kind", "path", "sha256", "inspection_kind", "provenance"}, "discovery source")
        discovery_ids.append(_identifier(source["discovery_id"], "discovery", "discovery id"))
        canonical_path(source["path"])
        if source["kind"] not in DISCOVERY_KINDS or source["provenance"] not in DISCOVERY_PROVENANCE or source["inspection_kind"] not in {"text", "binary", "metadata_only", "unreadable", "oversized", "unsupported"}:
            raise PlanError("discovery source classification is invalid")
        if source["sha256"] is not None:
            _digest(source["sha256"], "discovery digest")
        if (source["inspection_kind"] in {"text", "binary"}) != (source["sha256"] is not None):
            raise PlanError("discovery digest and inspection state are inconsistent")
    if discovery_ids != [f"D{index:03d}" for index in range(1, len(discovery_ids) + 1)]:
        raise PlanError("discovery identities are not canonical")
    known_sources = set(policy_ids) | set(source_ids) | set(discovery_ids)

    claims = _array(item["claims"], "claims", 20000)
    claim_ids: list[str] = []
    claim_map: dict[str, dict[str, Any]] = {}
    for claim in claims:
        claim = _exact(claim, {"claim_id", "fingerprint", "statement", "material", "target_ids", "basis", "evidence_requirement"}, "claim")
        claim_id = text(claim["claim_id"], "claim id", maximum=16)
        claim_ids.append(claim_id)
        statement = text(claim["statement"], "claim statement", maximum=4000)
        selected_targets = _array(claim["target_ids"], "claim targets", 20000, minimum=1)
        _unique(selected_targets, "claim targets")
        if any(value not in target_ids for value in selected_targets):
            raise PlanError("claim cites an unknown target")
        bases = []
        for basis_value in _array(claim["basis"], "claim basis", 64, minimum=1):
            basis = _exact(basis_value, {"kind", "description", "source_id", "location"}, "claim basis")
            if basis["kind"] not in {"caller", "agent_policy", "verify_guidance", "target_content", "project_contract", "related_test", "reasoning"}:
                raise PlanError("claim basis kind is invalid")
            if basis["source_id"] is not None and basis["source_id"] not in known_sources:
                raise PlanError("claim basis cites an unknown source")
            bases.append({"kind": basis["kind"], "description": text(basis["description"], "basis description", maximum=4000), "source_id": basis["source_id"], "location": _location(basis["location"])})
        if claim["evidence_requirement"] not in {"static", "command", "either"}:
            raise PlanError("claim evidence requirement is invalid")
        semantic = {"statement": statement, "material": _boolean(claim["material"], "claim material"), "target_ids": selected_targets, "basis": bases, "evidence_requirement": claim["evidence_requirement"]}
        if _digest(claim["fingerprint"], "claim fingerprint") != _sha256(_canonical_json(semantic)):
            raise PlanError("claim fingerprint is not derived")
        claim_map[claim_id] = claim
    if claim_ids != [f"C{index:03d}" for index in range(1, len(claim_ids) + 1)]:
        raise PlanError("claim ids are not canonical and sequential")

    interpretation_ids: list[str] = []
    interpretation_map: dict[str, dict[str, Any]] = {}
    for value in _array(item["guidance_interpretations"], "guidance interpretations", 5000):
        interpretation = _exact(value, {"interpretation_id", "source_id", "target_ids", "claim_ids", "kind", "requirement", "replaces_interpretation_id", "replacement_reason"}, "guidance interpretation")
        interpretation_id = text(interpretation["interpretation_id"], "interpretation id", maximum=16)
        interpretation_ids.append(interpretation_id)
        interpretation_map[interpretation_id] = interpretation
        if interpretation["source_id"] not in source_map or interpretation["source_id"] == "S001" and source_map["S001"]["kind"] != "skill":
            raise PlanError("guidance interpretation cites an unknown source")
        selected_targets = _array(interpretation["target_ids"], "interpretation targets", 20000, minimum=1)
        selected_claims = _array(interpretation["claim_ids"], "interpretation claims", 20000)
        _unique(selected_targets, "interpretation targets")
        _unique(selected_claims, "interpretation claims")
        if any(value not in target_ids for value in selected_targets) or any(value not in claim_map for value in selected_claims):
            raise PlanError("guidance interpretation cites an unknown target or claim")
        if interpretation["kind"] not in {"required", "conditional", "recommended", "replacement", "artifact"}:
            raise PlanError("guidance interpretation kind is invalid")
        if interpretation["kind"] in {"required", "conditional", "replacement"} and not selected_claims:
            raise PlanError("required, conditional, and replacement guidance must map to a claim")
        text(interpretation["requirement"], "guidance requirement", maximum=4000)
        if interpretation["kind"] == "replacement":
            text(interpretation["replaces_interpretation_id"], "replaced interpretation id", maximum=16)
            text(interpretation["replacement_reason"], "replacement reason", maximum=4000)
        elif interpretation["replaces_interpretation_id"] is not None or interpretation["replacement_reason"] is not None:
            raise PlanError("only replacement guidance may set replacement fields")
        for target_id in selected_targets:
            record = next(value for value in target_records if value["target_id"] == target_id)
            applicable = {record["guidance_chain_id"], record["old_guidance_chain_id"]}
            if not any(interpretation["source_id"] in chain_map[chain_id]["source_ids"] for chain_id in applicable if chain_id is not None):
                raise PlanError("guidance interpretation source is not applicable to its target")
    if interpretation_ids != [f"I{index:03d}" for index in range(1, len(interpretation_ids) + 1)]:
        raise PlanError("interpretation ids are not canonical and sequential")
    for interpretation in item["guidance_interpretations"]:
        replaced_id = interpretation["replaces_interpretation_id"]
        if replaced_id is None:
            continue
        if replaced_id not in interpretation_map or replaced_id == interpretation["interpretation_id"]:
            raise PlanError("replacement cites an unknown or identical interpretation")
        replaced = interpretation_map[replaced_id]
        if replaced["kind"] == "replacement" or not set(interpretation["target_ids"]).issubset(replaced["target_ids"]):
            raise PlanError("replacement scope is invalid")
        for target_id in interpretation["target_ids"]:
            record = next(value for value in target_records if value["target_id"] == target_id)
            if not any(
                interpretation["source_id"] in chain_map[chain_id]["source_ids"]
                and replaced["source_id"] in chain_map[chain_id]["source_ids"]
                and chain_map[chain_id]["source_ids"].index(interpretation["source_id"]) > chain_map[chain_id]["source_ids"].index(replaced["source_id"])
                for chain_id in {record["guidance_chain_id"], record["old_guidance_chain_id"]} if chain_id is not None
            ):
                raise PlanError("replacement source is not closer than the replaced source")

    checks = _array(item["checks"], "checks", 128)
    check_ids: list[str] = []
    candidate_ids: set[str] = set()
    tier_order = {"focused": 0, "subsystem": 1, "project": 2}
    total_seconds = 0
    for check in checks:
        required = {"check_id", "fingerprint", "candidate_id", "argv", "cwd", "tier", "reason", "claim_ids", "timeout_seconds", "repetitions", "depends_on", "useful_after_failure", "expected_effects", "artifact_boundaries", "authority", "decision"}
        check = _exact(check, required, "check")
        check_id = text(check["check_id"], "check id", maximum=16)
        check_ids.append(check_id)
        candidate_id = _identifier(check["candidate_id"], "candidate", "candidate id")
        if candidate_id in candidate_ids:
            raise PlanError("plan selects a candidate more than once")
        candidate_ids.add(candidate_id)
        argv = _array(check["argv"], "check argv", 128, minimum=1)
        for argument in argv:
            text(argument, "check argument", maximum=4096)
        cwd = canonical_path(check["cwd"], allow_root=True)
        if check["tier"] not in tier_order:
            raise PlanError("check tier is invalid")
        reason = text(check["reason"], "check reason", maximum=4000)
        selected_claims = _array(check["claim_ids"], "check claims", 20000, minimum=1)
        dependencies = _array(check["depends_on"], "check dependencies", 127)
        _unique(selected_claims, "check claims")
        _unique(dependencies, "check dependencies")
        if any(value not in check_ids[:-1] for value in dependencies):
            raise PlanError("check dependency is forward or unknown")
        if any(value not in claim_map for value in selected_claims):
            raise PlanError("check cites an unknown claim")
        timeout = _integer(check["timeout_seconds"], "check timeout", 1, 3600)
        repetitions = _integer(check["repetitions"], "check repetitions", 1, 32)
        total_seconds += timeout * repetitions
        useful = _boolean(check["useful_after_failure"], "useful after failure")
        effects = _array(check["expected_effects"], "check effects", 14, minimum=1)
        _unique(effects, "check effects")
        if any(value not in ALL_EFFECTS for value in effects):
            raise PlanError("check effect is invalid")
        boundaries = []
        for value in _array(check["artifact_boundaries"], "artifact boundaries", 64):
            boundary = _exact(value, {"root_kind", "path"}, "artifact boundary")
            if boundary["root_kind"] not in {"repository", "run_temp"}:
                raise PlanError("artifact boundary root kind is invalid")
            boundaries.append({"root_kind": boundary["root_kind"], "path": canonical_path(boundary["path"])})
        boundary_kinds = {value["root_kind"] for value in boundaries}
        if "disposable_repository_write" in effects and "repository" not in boundary_kinds or "bounded_temporary_write" in effects and "run_temp" not in boundary_kinds:
            raise PlanError("check write effect lacks a matching artifact boundary")
        authority = _exact(check["authority"], {"source_kind", "source", "authorized"}, "check authority")
        if authority["source_kind"] not in {"caller", "user_global", "none"}:
            raise PlanError("check authority kind is invalid")
        text(authority["source"], "check authority source", maximum=4000)
        authorized = _boolean(authority["authorized"], "check authorized")
        if authorized != (authority["source_kind"] != "none") or authorized and not set(effects).issubset(ORDINARY_EFFECTS):
            raise PlanError("check authority is inconsistent")
        expected_decision = "unsupported" if not set(effects).issubset(ORDINARY_EFFECTS) else ("plan_only" if invocation["mode"] == "plan" else ("run" if authorized else "authorization_required"))
        if check["decision"] != expected_decision:
            raise PlanError("check decision is not derived")
        semantic = {"candidate_id": candidate_id, "tier": check["tier"], "reason": reason, "claim_ids": selected_claims, "depends_on": dependencies, "useful_after_failure": useful}
        fingerprint_payload = {**semantic, "argv": argv, "cwd": cwd, "expected_effects": effects, "artifact_boundaries": boundaries}
        if _digest(check["fingerprint"], "check fingerprint") != _sha256(_canonical_json(fingerprint_payload)):
            raise PlanError("check fingerprint is not derived")
    if check_ids != [f"K{index:03d}" for index in range(1, len(check_ids) + 1)]:
        raise PlanError("check ids are not canonical and sequential")
    if invocation["command_cap"] is not None and len(checks) > invocation["command_cap"]:
        raise PlanError("plan exceeds the caller command cap")
    if invocation["time_cap_seconds"] is not None and total_seconds > invocation["time_cap_seconds"]:
        raise PlanError("plan exceeds the caller total-time cap")
    if invocation["tier_cap"] is not None and any(tier_order[value["tier"]] > tier_order[invocation["tier_cap"]] for value in checks):
        raise PlanError("plan exceeds the caller tier cap")

    known_limit_sources = known_sources | set(interpretation_ids) | candidate_ids
    limitations = _array(item["limitations"], "limitations", 256)
    for limitation in limitations:
        limitation = _exact(limitation, {"code", "message", "source_ids", "target_ids", "claim_ids", "material", "next_action"}, "limitation")
        if limitation["code"] not in PLAN_LIMITATION_CODES or limitation["next_action"] not in NEXT_ACTIONS:
            raise PlanError("plan limitation classification is invalid")
        text(limitation["message"], "limitation message", maximum=4000)
        source_values = _array(limitation["source_ids"], "limitation sources", 5000)
        target_values = _array(limitation["target_ids"], "limitation targets", 20000)
        claim_values = _array(limitation["claim_ids"], "limitation claims", 20000)
        for values, label in ((source_values, "limitation sources"), (target_values, "limitation targets"), (claim_values, "limitation claims")):
            _unique(values, label)
        if any(value not in known_limit_sources for value in source_values) or any(value not in target_ids for value in target_values) or any(value not in claim_map for value in claim_values):
            raise PlanError("plan limitation cites an unknown record")
        _boolean(limitation["material"], "limitation material")

    material_claim_ids = sorted(value["claim_id"] for value in claims if value["material"])
    checked_claim_ids = {claim_id for check in checks for claim_id in check["claim_ids"]}
    planned_claim_ids = sorted({value["claim_id"] for value in claims if value["evidence_requirement"] in {"static", "either"}} | checked_claim_ids)
    uncovered_claim_ids = sorted(set(material_claim_ids) - set(planned_claim_ids))
    highest_tier = max((value["tier"] for value in checks), key=lambda value: tier_order[value], default=None)
    coverage = _exact(item["coverage"], {"material_claim_ids", "planned_claim_ids", "uncovered_claim_ids", "highest_tier"}, "coverage")
    expected_coverage = {"material_claim_ids": material_claim_ids, "planned_claim_ids": planned_claim_ids, "uncovered_claim_ids": uncovered_claim_ids, "highest_tier": highest_tier}
    if coverage != expected_coverage:
        raise PlanError("plan coverage is not derived")
    if uncovered_claim_ids and not any(value["code"] == "coverage_gap" and set(uncovered_claim_ids).issubset(value["claim_ids"]) and value["material"] for value in limitations):
        raise PlanError("uncovered material claims lack a coverage limitation")
    material_limits = sum(1 for value in limitations if value["material"])
    expected_execution_state = "blocked" if material_limits else ("plan_only" if invocation["mode"] == "plan" else ("ready" if all(value["decision"] == "run" for value in checks) else "blocked"))
    if item["execution_state"] != expected_execution_state:
        raise PlanError("plan execution state is not derived")
    summary = _exact(item["summary"], {"conclusion", "claim_count", "material_claim_count", "check_count", "runnable_check_count", "material_limitation_count"}, "summary")
    expected_conclusion = "Verification plan is ready for bounded execution." if expected_execution_state == "ready" else ("Verification plan is complete and non-executing." if expected_execution_state == "plan_only" else "Verification plan is blocked by material limitations.")
    if summary != {
        "conclusion": expected_conclusion,
        "claim_count": len(claims),
        "material_claim_count": len(material_claim_ids),
        "check_count": len(checks),
        "runnable_check_count": sum(1 for value in checks if value["decision"] == "run"),
        "material_limitation_count": material_limits,
    }:
        raise PlanError("plan summary is not derived")
    encoded = _canonical_json(item)
    if len(encoded) > MAX_JSON_BYTES:
        raise PlanError("canonical plan exceeds the JSON ceiling")
    return item


def render(plan: dict[str, Any]) -> str:
    plan = validate_plan(plan)
    lines = [
        f"Verification plan: {plan['execution_state']}",
        plan["summary"]["conclusion"],
        f"Target: {plan['target']['kind']} ({len(plan['targets'])} records, {plan['target_sha256'][:12]})",
        f"Claims: {plan['summary']['material_claim_count']} material / {plan['summary']['claim_count']} total",
        f"Checks: {plan['summary']['runnable_check_count']} runnable / {plan['summary']['check_count']} planned",
    ]
    for check in plan["checks"]:
        command = " ".join(json.dumps(value, ensure_ascii=True) for value in check["argv"])
        lines.append(f"- {check['check_id']} [{check['tier']}; {check['decision']}]: {command}")
        lines.append(f"  Reason: {check['reason']}")
    if plan["limitations"]:
        lines.append("Limitations:")
        for limitation in plan["limitations"]:
            marker = "material" if limitation["material"] else "non-material"
            lines.append(f"- [{marker}; next {limitation['next_action']}] {limitation['message']}")
    return "\n".join(lines) + "\n"


def _emit(value: dict[str, Any], output_format: str, destination: str | None) -> None:
    if output_format == "human":
        data = render(value).encode("utf-8")
    elif output_format == "json":
        data = _canonical_json(value, pretty=True)
    else:
        data = (render(value) + _canonical_json(value, pretty=True).decode("utf-8")).encode("utf-8")
    if len(data) > MAX_JSON_BYTES:
        raise PlanError("rendered plan exceeds the output ceiling")
    if destination is None:
        sys.stdout.buffer.write(data)
    else:
        write_created_output(filesystem_path(destination, "output path", expand_user=True).absolute(), data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    finalize_command = commands.add_parser("finalize")
    finalize_command.add_argument("--context", required=True)
    finalize_command.add_argument("--input", required=True)
    finalize_command.add_argument("--format", choices=("human", "json", "both"), default="human")
    finalize_command.add_argument("--output")
    validate_command = commands.add_parser("validate")
    validate_command.add_argument("--input", required=True)
    validate_context_command = commands.add_parser("validate-context")
    validate_context_command.add_argument("--input", required=True)
    validate_context_command.add_argument(
        "--revalidate",
        action="store_true",
        help="also require the original target and protected repository snapshot",
    )
    render_command = commands.add_parser("render")
    render_command.add_argument("--input", required=True)
    render_command.add_argument("--format", choices=("human", "json", "both"), default="human")
    render_command.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "finalize":
            value = finalize(_read_json(args.context), _read_json(args.input))
            _emit(value, args.format, args.output)
        elif args.command == "validate":
            validate_plan(_read_json(args.input))
        elif args.command == "validate-context":
            validate_context(_read_json(args.input), revalidate=args.revalidate)
        else:
            _emit(validate_plan(_read_json(args.input)), args.format, args.output)
        return 0
    except (PlanError, SafetyError, OSError, UnicodeError, ValueError) as exc:
        print(f"verify-project plan: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
