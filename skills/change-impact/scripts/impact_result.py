#!/usr/bin/env python3
"""Finalize, validate, and render canonical change-impact results."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import unicodedata
from typing import Any

from impact_context import (
    ContextError,
    MAX_JSON_BYTES,
    MAX_JSON_DEPTH,
    context_digest,
    validate_context,
)
from path_safety import SafetyError, canonical_path, filesystem_path, read_regular, write_created_output


SCHEMA_VERSION = "1.0.0"
SKILL_VERSION = "1.0.0"
STATUSES = {"COMPLETE", "INCOMPLETE"}
RELATIONSHIPS = {
    "runtime_dependency",
    "public_api",
    "data_or_wire_contract",
    "configuration",
    "generated_artifact",
    "test_or_fixture",
    "verification_requirement",
    "review_policy",
    "documentation",
    "platform_or_packaging",
    "security_or_privacy",
    "operational_behavior",
    "other",
}
REACH = {"direct", "indirect", "possible"}
CONFIDENCE = {"high", "medium", "low"}
PURPOSES = {
    "review_context",
    "review_target_candidate",
    "verification_context",
    "verification_claim_candidate",
    "remediation_risk_context",
    "documentation_candidate",
    "user_decision",
}
EVIDENCE_KINDS = {
    "source",
    "contract",
    "guidance",
    "test",
    "configuration",
    "history",
    "reasoning",
}
RESOLVER_LIMITATIONS = {
    "empty_target",
    "scope_limit",
    "traversal_limit",
    "unsafe_path",
    "file_unreadable",
    "file_non_text",
    "file_oversized",
    "guidance_unavailable",
    "context_unavailable",
    "target_drift",
    "other",
}
ANALYSIS_LIMITATIONS = {
    "target_unreadable",
    "context_missing",
    "context_unreadable",
    "evidence_ambiguous",
    "dynamic_resolution",
    "analysis_limit",
    "other",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ResultError(ValueError):
    """Raised when a change-impact result is malformed or unbound."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _machine_json_text(value: Any) -> str:
    """Return the exact canonical machine-readable JSON text."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2)


def _object(
    value: Any,
    label: str,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ResultError(f"{label} must be an object")
    optional = optional or set()
    missing = required - value.keys()
    unknown = value.keys() - required - optional
    if missing:
        raise ResultError(f"{label} is missing {sorted(missing)}")
    if unknown:
        raise ResultError(f"{label} has unknown fields {sorted(unknown)}")
    return value


def _array(value: Any, label: str, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        raise ResultError(f"{label} must be an array")
    if len(value) > maximum:
        raise ResultError(f"{label} exceeds {maximum} items")
    return value


def _string(
    value: Any, label: str, maximum: int, *, allow_empty: bool = False
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ResultError(f"{label} must be a non-empty string")
    if len(value) > maximum:
        raise ResultError(f"{label} exceeds {maximum} characters")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ResultError(f"{label} contains unsupported control characters")
    return value


def _path(value: Any, label: str) -> str:
    try:
        return canonical_path(value)
    except SafetyError as exc:
        raise ResultError(f"{label}: {exc}") from exc


def _unique_paths(value: Any, label: str, maximum: int) -> list[str]:
    paths = [
        _path(item, f"{label}[{index}]")
        for index, item in enumerate(_array(value, label, maximum))
    ]
    if len(paths) != len(set(paths)):
        raise ResultError(f"{label} contains duplicate paths")
    return paths


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ResultError(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ResultError(f"{label} must be a boolean")
    return value


def _enum(value: Any, label: str, choices: set[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ResultError(f"{label} must be one of {sorted(choices)}")
    return value


def _line_cap(context: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in context["files"]:
        if item["state"] == "text" and item["line_count"] is not None:
            result[item["path"]] = max(result.get(item["path"], 0), item["line_count"])
    for item in context["guidance"]:
        content = item["content"]
        count = 0 if not content else content.count("\n") + (0 if content.endswith("\n") else 1)
        result[item["path"]] = max(result.get(item["path"], 0), count)
    return result


def _location(
    value: Any,
    label: str,
    *,
    allowed_paths: set[str],
    line_caps: dict[str, int],
) -> dict[str, Any]:
    item = _object(value, label, {"path", "start_line", "end_line"})
    path = _path(item["path"], f"{label}.path")
    if path not in allowed_paths:
        raise ResultError(f"{label}.path is outside frozen target/context evidence: {path}")
    start = item["start_line"]
    end = item["end_line"]
    if (start is None) != (end is None):
        raise ResultError(f"{label} must supply both line bounds or neither")
    if start is not None:
        start = _integer(start, f"{label}.start_line", 1, 5_000_000)
        end = _integer(end, f"{label}.end_line", start, 5_000_000)
        cap = line_caps.get(path)
        if cap is None or end > cap:
            raise ResultError(f"{label} line range exceeds inspected text for {path}")
    return {"path": path, "start_line": start, "end_line": end}


def _target_result(context: dict[str, Any]) -> dict[str, Any]:
    request = context["request"]
    files = [
        {
            "path": item["path"],
            "role": item["role"],
            "revision": item["revision"],
            "state": item["state"],
            "size": item["size"],
            "sha256": item["sha256"],
            "line_count": item["line_count"],
        }
        for item in context["files"]
        if item["role"] in {"target_before", "target_after"}
    ]
    return {
        "kind": request["kind"],
        "repository_root": request["repository_root"],
        "base_revision": request["base_revision"],
        "head_revision": request["head_revision"],
        "working_tree_mode": request["working_tree_mode"],
        "requested_paths": copy.deepcopy(request["requested_paths"]),
        "paths": copy.deepcopy(context["target"]["paths"]),
        "changes": copy.deepcopy(context["target"]["changes"]),
        "files": files,
    }


def _context_provenance(context: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in context["files"]:
        if item["role"] != "context":
            continue
        result.append(
            {
                "path": item["path"],
                "state": item["state"],
                "size": item["size"],
                "sha256": item["sha256"],
                "line_count": item["line_count"],
            }
        )
    return sorted(result, key=lambda item: item["path"])


def _guidance_provenance(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "kind": item["kind"],
            "path": item["path"],
            "revision": item["revision"],
            "applies_to": copy.deepcopy(item["applies_to"]),
            "size": item["size"],
            "sha256": item["sha256"],
            "line_count": _line_count(item["content"]),
        }
        for item in context["guidance"]
    ]


def _line_count(content: str) -> int:
    if not content:
        return 0
    return content.count("\n") + (0 if content.endswith("\n") else 1)


def _text_paths(context: dict[str, Any], role: str) -> set[str]:
    return {
        item["path"]
        for item in context["files"]
        if item["role"] == role and item["state"] == "text"
    }


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def impact_fingerprint(impact: dict[str, Any]) -> str:
    stable = {
        "source_target_paths": impact["source_target_paths"],
        "affected_paths": sorted({item["path"] for item in impact["affected_locations"]}),
        "relationship": impact["relationship"],
        "reach": impact["reach"],
        "title": _normalize(impact["title"]),
        "consequence": _normalize(impact["consequence"]),
    }
    return hashlib.sha256(_canonical_json(stable)).hexdigest()


def _analysis_limitation(
    value: Any,
    label: str,
    known_paths: set[str],
) -> dict[str, Any]:
    item = _object(value, label, {"code", "message", "paths", "material"})
    code = _enum(item["code"], f"{label}.code", ANALYSIS_LIMITATIONS)
    paths = _unique_paths(item["paths"], f"{label}.paths", 5000)
    unknown = set(paths) - known_paths
    if unknown:
        raise ResultError(f"{label}.paths contains unfrozen paths: {sorted(unknown)[:8]}")
    return {
        "code": code,
        "message": _string(item["message"], f"{label}.message", 4096),
        "paths": paths,
        "material": _boolean(item["material"], f"{label}.material"),
        "source": "analysis",
    }


def _impact(
    value: Any,
    label: str,
    *,
    target_paths: set[str],
    affected_paths: set[str],
    evidence_paths: set[str],
    inspected_targets: set[str],
    inspected_context: set[str],
    context_paths: set[str],
    line_caps: dict[str, int],
) -> dict[str, Any]:
    item = _object(
        value,
        label,
        {
            "source_target_paths",
            "affected_locations",
            "relationship",
            "reach",
            "confidence",
            "title",
            "consequence",
            "reason",
            "evidence",
            "safe_direction",
            "consumer_purposes",
        },
    )
    source_paths = _unique_paths(item["source_target_paths"], f"{label}.source_target_paths", 128)
    if not source_paths:
        raise ResultError(f"{label}.source_target_paths must not be empty")
    if set(source_paths) - target_paths:
        raise ResultError(f"{label} cites a source outside the selected target")
    if set(source_paths) - inspected_targets:
        raise ResultError(f"{label} cites an uninspected source target")
    locations = [
        _location(
            entry,
            f"{label}.affected_locations[{index}]",
            allowed_paths=affected_paths,
            line_caps=line_caps,
        )
        for index, entry in enumerate(_array(item["affected_locations"], f"{label}.affected_locations", 128))
    ]
    if not locations:
        raise ResultError(f"{label}.affected_locations must not be empty")
    for location in locations:
        if location["path"] in context_paths and location["path"] not in inspected_context:
            raise ResultError(f"{label} cites uninspected context {location['path']}")
    evidence = []
    for index, entry in enumerate(_array(item["evidence"], f"{label}.evidence", 64)):
        evidence_item = _object(
            entry,
            f"{label}.evidence[{index}]",
            {"kind", "description", "location"},
        )
        evidence.append(
            {
                "kind": _enum(
                    evidence_item["kind"],
                    f"{label}.evidence[{index}].kind",
                    EVIDENCE_KINDS,
                ),
                "description": _string(
                    evidence_item["description"],
                    f"{label}.evidence[{index}].description",
                    4096,
                ),
                "location": _location(
                    evidence_item["location"],
                    f"{label}.evidence[{index}].location",
                    allowed_paths=evidence_paths,
                    line_caps=line_caps,
                ),
            }
        )
    if not evidence or not any(entry["kind"] != "reasoning" for entry in evidence):
        raise ResultError(f"{label} requires at least one non-reasoning evidence record")
    purposes = [
        _enum(entry, f"{label}.consumer_purposes[{index}]", PURPOSES)
        for index, entry in enumerate(_array(item["consumer_purposes"], f"{label}.consumer_purposes", 7))
    ]
    if not purposes or len(purposes) != len(set(purposes)):
        raise ResultError(f"{label}.consumer_purposes must be non-empty and unique")
    return {
        "source_target_paths": sorted(source_paths),
        "affected_locations": sorted(
            locations,
            key=lambda entry: (entry["path"], entry["start_line"] or 0, entry["end_line"] or 0),
        ),
        "relationship": _enum(item["relationship"], f"{label}.relationship", RELATIONSHIPS),
        "reach": _enum(item["reach"], f"{label}.reach", REACH),
        "confidence": _enum(item["confidence"], f"{label}.confidence", CONFIDENCE),
        "title": _string(item["title"], f"{label}.title", 512),
        "consequence": _string(item["consequence"], f"{label}.consequence", 4096),
        "reason": _string(item["reason"], f"{label}.reason", 4096),
        "evidence": evidence,
        "safe_direction": _string(item["safe_direction"], f"{label}.safe_direction", 4096),
        "consumer_purposes": sorted(purposes),
    }


def finalize_draft(context_value: Any, draft_value: Any) -> dict[str, Any]:
    try:
        context = validate_context(context_value, revalidate_current=True)
    except ContextError as exc:
        raise ResultError(str(exc)) from exc
    draft = _object(
        draft_value,
        "draft",
        {"conclusion", "inspected_target_paths", "inspected_context_paths", "impacts", "limitations"},
    )
    target_paths_list = context["target"]["paths"]
    target_paths = set(target_paths_list)
    context_records = _context_provenance(context)
    context_paths = {item["path"] for item in context_records}
    guidance_paths = {item["path"] for item in context["guidance"]}
    target_text = _text_paths(context, "target_before") | _text_paths(context, "target_after")
    context_text = _text_paths(context, "context")
    inspected_targets = set(
        _unique_paths(draft["inspected_target_paths"], "draft.inspected_target_paths", 5000)
    )
    inspected_context = set(
        _unique_paths(draft["inspected_context_paths"], "draft.inspected_context_paths", 1000)
    )
    if inspected_targets - target_paths:
        raise ResultError("draft.inspected_target_paths contains paths outside the target")
    if inspected_targets - target_text:
        raise ResultError("draft claims inspection of target content that is not inspectable text")
    if inspected_context - context_paths:
        raise ResultError("draft.inspected_context_paths contains unfrozen context")
    if inspected_context - context_text:
        raise ResultError("draft claims inspection of context that is not inspectable text")
    line_caps = _line_cap(context)
    impacts = [
        _impact(
            item,
            f"draft.impacts[{index}]",
            target_paths=target_paths,
            affected_paths=target_paths | context_paths,
            evidence_paths=target_paths | context_paths | guidance_paths,
            inspected_targets=inspected_targets,
            inspected_context=inspected_context,
            context_paths=context_paths,
            line_caps=line_caps,
        )
        for index, item in enumerate(_array(draft["impacts"], "draft.impacts", 2000))
    ]
    impacts.sort(
        key=lambda item: (
            item["relationship"],
            item["affected_locations"][0]["path"],
            item["title"].casefold(),
            item["source_target_paths"],
        )
    )
    fingerprints: set[str] = set()
    for index, item in enumerate(impacts, 1):
        fingerprint = impact_fingerprint(item)
        if fingerprint in fingerprints:
            raise ResultError("draft contains duplicate semantic impacts")
        fingerprints.add(fingerprint)
        item["impact_id"] = f"I{index:03d}"
        item["fingerprint"] = fingerprint

    known_paths = target_paths | context_paths
    limitations = [
        {**copy.deepcopy(item), "source": "resolver"}
        for item in context["limitations"]
    ]
    limitations.extend(
        _analysis_limitation(item, f"draft.limitations[{index}]", known_paths)
        for index, item in enumerate(_array(draft["limitations"], "draft.limitations", 256))
    )
    uninspected = sorted(target_paths - inspected_targets)
    if uninspected and not any(
        item["source"] == "analysis" and item["code"] == "target_unreadable"
        for item in limitations
    ):
        limitations.append(
            {
                "code": "target_unreadable",
                "message": "selected target paths were not inspected",
                "paths": uninspected,
                "material": True,
                "source": "analysis",
            }
        )
    limitations.sort(
        key=lambda item: (item["source"], item["code"], item["message"], item["paths"])
    )
    relationship_counts = {name: 0 for name in sorted(RELATIONSHIPS)}
    purpose_counts = {name: 0 for name in sorted(PURPOSES)}
    for item in impacts:
        relationship_counts[item["relationship"]] += 1
        for purpose in item["consumer_purposes"]:
            purpose_counts[purpose] += 1
    relationship_counts = {key: value for key, value in relationship_counts.items() if value}
    purpose_counts = {key: value for key, value in purpose_counts.items() if value}
    status = "INCOMPLETE" if uninspected or any(item["material"] for item in limitations) else "COMPLETE"
    result = {
        "schema_version": SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "context_sha256": context_digest(context),
        "status": status,
        "target": _target_result(context),
        "context": context_records,
        "guidance": _guidance_provenance(context),
        "coverage": {
            "inspected_target_paths": sorted(inspected_targets),
            "uninspected_target_paths": uninspected,
            "inspected_context_paths": sorted(inspected_context),
        },
        "summary": {
            "conclusion": _string(draft["conclusion"], "draft.conclusion", 8192),
            "target_paths": len(target_paths),
            "context_paths": len(context_paths),
            "impacts": len(impacts),
            "by_relationship": relationship_counts,
            "by_consumer_purpose": purpose_counts,
        },
        "impacts": impacts,
        "limitations": limitations,
    }
    return validate_result(result, context=context)


def _validate_target(value: Any) -> dict[str, Any]:
    target = _object(
        value,
        "target",
        {
            "kind",
            "repository_root",
            "base_revision",
            "head_revision",
            "working_tree_mode",
            "requested_paths",
            "paths",
            "changes",
            "files",
        },
    )
    kind = _enum(target["kind"], "target.kind", {"ref_range", "working_tree", "paths"})
    _string(target["repository_root"], "target.repository_root", 8192)
    for key in ("base_revision", "head_revision"):
        value_revision = target[key]
        if value_revision is not None and (
            not isinstance(value_revision, str) or not re.fullmatch(r"[0-9a-f]{40,64}", value_revision)
        ):
            raise ResultError(f"target.{key} must be a canonical commit or null")
    if target["working_tree_mode"] not in {None, "combined"}:
        raise ResultError("target.working_tree_mode must be combined or null")
    requested_raw = _array(target["requested_paths"], "target.requested_paths", 5000)
    requested: list[str] = []
    for index, requested_path in enumerate(requested_raw):
        try:
            requested.append(
                canonical_path(requested_path, allow_root=kind == "paths")
            )
        except SafetyError as exc:
            raise ResultError(f"target.requested_paths[{index}]: {exc}") from exc
    if len(requested) != len(set(requested)):
        raise ResultError("target.requested_paths contains duplicate paths")
    if kind == "paths" and not requested:
        raise ResultError("path targets require requested paths")
    if kind == "paths":
        if (
            target["base_revision"] is not None
            or target["head_revision"] is not None
            or target["working_tree_mode"] is not None
        ):
            raise ResultError("path target fields are inconsistent")
    elif target["base_revision"] is None:
        raise ResultError("Git targets require a base revision")
    elif kind == "ref_range" and (
        target["head_revision"] is None or target["working_tree_mode"] is not None
    ):
        raise ResultError("ref-range target fields are inconsistent")
    elif kind == "working_tree" and (
        target["head_revision"] is not None
        or target["working_tree_mode"] != "combined"
    ):
        raise ResultError("working-tree target fields are inconsistent")
    paths = _unique_paths(target["paths"], "target.paths", 5000)
    if paths != sorted(paths):
        raise ResultError("target.paths must be canonically ordered")
    if kind != "paths" and requested != paths:
        raise ResultError("Git requested paths must match target.paths")
    changes = _array(target["changes"], "target.changes", 5000)
    normalized_changes: list[dict[str, Any]] = []
    for index, change in enumerate(changes):
        item = _object(change, f"target.changes[{index}]", {"path", "source_path", "status"})
        path = _path(item["path"], f"target.changes[{index}].path")
        source_path = None
        if item["source_path"] is not None:
            source_path = _path(
                item["source_path"], f"target.changes[{index}].source_path"
            )
        status = _enum(
            item["status"],
            f"target.changes[{index}].status",
            {"added", "deleted", "modified", "renamed", "copied", "type_changed", "unmerged", "untracked", "snapshot", "unknown"},
        )
        if (status in {"renamed", "copied"}) != (source_path is not None):
            raise ResultError(f"target.changes[{index}] source path is inconsistent")
        normalized_changes.append(
            {"path": path, "source_path": source_path, "status": status}
        )
    if normalized_changes != sorted(
        normalized_changes,
        key=lambda item: (item["path"], item["source_path"] or "", item["status"]),
    ):
        raise ResultError("target.changes must be canonically ordered")
    derived_paths = sorted(
        {
            candidate
            for item in normalized_changes
            for candidate in (item["path"], item["source_path"])
            if candidate is not None
        }
    )
    if derived_paths != paths:
        raise ResultError("target.paths do not match target.changes")
    files = _array(target["files"], "target.files", 10000)
    file_keys: list[tuple[str, str, str | None]] = []
    for index, value_item in enumerate(files):
        item = _object(
            value_item,
            f"target.files[{index}]",
            {"path", "role", "revision", "state", "size", "sha256", "line_count"},
        )
        file_path = _path(item["path"], f"target.files[{index}].path")
        if file_path not in set(paths):
            raise ResultError(f"target.files[{index}] lies outside target.paths")
        role = _enum(
            item["role"],
            f"target.files[{index}].role",
            {"target_before", "target_after"},
        )
        if item["revision"] is not None and (
            not isinstance(item["revision"], str)
            or not re.fullmatch(r"[0-9a-f]{40,64}", item["revision"])
        ):
            raise ResultError(f"target.files[{index}].revision is invalid")
        state = _enum(
            item["state"],
            f"target.files[{index}].state",
            {"text", "binary", "oversized", "unreadable", "absent"},
        )
        if item["size"] is not None:
            _integer(item["size"], f"target.files[{index}].size", 0, 4 * 1024 * 1024)
        if item["sha256"] is not None and (
            not isinstance(item["sha256"], str) or not HEX64.fullmatch(item["sha256"])
        ):
            raise ResultError(f"target.files[{index}].sha256 is invalid")
        if item["line_count"] is not None:
            _integer(item["line_count"], f"target.files[{index}].line_count", 0, 5_000_000)
        if state == "text":
            if item["size"] is None or item["sha256"] is None or item["line_count"] is None:
                raise ResultError(f"target.files[{index}] text provenance is incomplete")
        elif state == "binary":
            if item["size"] is None or item["sha256"] is None or item["line_count"] is not None:
                raise ResultError(f"target.files[{index}] binary provenance is inconsistent")
        elif any(item[key] is not None for key in ("size", "sha256", "line_count")):
            raise ResultError(f"target.files[{index}] unavailable provenance is inconsistent")
        file_keys.append((file_path, role, item["revision"]))
    if file_keys != sorted(set(file_keys)):
        raise ResultError("target.files must be canonically ordered and unique")
    expected_keys: set[tuple[str, str, str | None]] = set()
    content_revision = target["head_revision"] if kind == "ref_range" else None
    for change in normalized_changes:
        source = change["source_path"] or change["path"]
        if change["status"] not in {"added", "untracked", "snapshot"}:
            expected_keys.add((source, "target_before", target["base_revision"]))
        if change["status"] != "deleted":
            expected_keys.add((change["path"], "target_after", content_revision))
    if set(file_keys) != expected_keys:
        raise ResultError("target.files do not match target.changes")
    return target


def validate_result(value: Any, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    result = _object(
        value,
        "result",
        {"schema_version", "skill_version", "context_sha256", "status", "target", "context", "guidance", "coverage", "summary", "impacts", "limitations"},
    )
    if result["schema_version"] != SCHEMA_VERSION or result["skill_version"] != SKILL_VERSION:
        raise ResultError("unsupported result schema or skill version")
    digest = _string(result["context_sha256"], "context_sha256", 64)
    if not HEX64.fullmatch(digest):
        raise ResultError("context_sha256 must be lowercase SHA-256")
    status = _enum(result["status"], "status", STATUSES)
    target = _validate_target(result["target"])
    target_paths = set(target["paths"])

    context_items = _array(result["context"], "context", 1000)
    context_paths: set[str] = set()
    context_order: list[str] = []
    for index, value_item in enumerate(context_items):
        item = _object(value_item, f"context[{index}]", {"path", "state", "size", "sha256", "line_count"})
        path = _path(item["path"], f"context[{index}].path")
        if path in context_paths or path in target_paths:
            raise ResultError("context paths must be unique and outside target paths")
        context_paths.add(path)
        context_order.append(path)
        state = _enum(item["state"], f"context[{index}].state", {"text", "binary", "oversized", "unreadable", "absent"})
        if item["size"] is not None:
            _integer(item["size"], f"context[{index}].size", 0, 4 * 1024 * 1024)
        if item["sha256"] is not None and (not isinstance(item["sha256"], str) or not HEX64.fullmatch(item["sha256"])):
            raise ResultError(f"context[{index}].sha256 is invalid")
        if item["line_count"] is not None:
            _integer(item["line_count"], f"context[{index}].line_count", 0, 5_000_000)
        if state == "text":
            if item["size"] is None or item["sha256"] is None or item["line_count"] is None:
                raise ResultError(f"context[{index}] text provenance is incomplete")
        elif state == "binary":
            if item["size"] is None or item["sha256"] is None or item["line_count"] is not None:
                raise ResultError(f"context[{index}] binary provenance is inconsistent")
        elif any(item[key] is not None for key in ("size", "sha256", "line_count")):
            raise ResultError(f"context[{index}] unavailable provenance is inconsistent")
    if context_order != sorted(context_order):
        raise ResultError("context must be canonically ordered")

    guidance_paths: set[str] = set()
    guidance_keys: list[tuple[str, str]] = []
    for index, value_item in enumerate(_array(result["guidance"], "guidance", 10000)):
        item = _object(value_item, f"guidance[{index}]", {"kind", "path", "revision", "applies_to", "size", "sha256", "line_count"})
        _enum(item["kind"], f"guidance[{index}].kind", {"review", "verification"})
        path = _path(item["path"], f"guidance[{index}].path")
        guidance_paths.add(path)
        guidance_keys.append((item["kind"], path))
        if item["revision"] is not None and (
            not isinstance(item["revision"], str) or not re.fullmatch(r"[0-9a-f]{40,64}", item["revision"])
        ):
            raise ResultError(f"guidance[{index}].revision is invalid")
        applies = _unique_paths(item["applies_to"], f"guidance[{index}].applies_to", 5000)
        if not applies or set(applies) - target_paths:
            raise ResultError(f"guidance[{index}] has invalid applicability")
        _integer(item["size"], f"guidance[{index}].size", 0, 1024 * 1024)
        if not isinstance(item["sha256"], str) or not HEX64.fullmatch(item["sha256"]):
            raise ResultError(f"guidance[{index}].sha256 is invalid")
        _integer(item["line_count"], f"guidance[{index}].line_count", 0, 5_000_000)
    if guidance_keys != sorted(set(guidance_keys)):
        raise ResultError("guidance must be canonically ordered and unique")

    coverage = _object(result["coverage"], "coverage", {"inspected_target_paths", "uninspected_target_paths", "inspected_context_paths"})
    inspected_targets = set(_unique_paths(coverage["inspected_target_paths"], "coverage.inspected_target_paths", 5000))
    uninspected_targets = set(_unique_paths(coverage["uninspected_target_paths"], "coverage.uninspected_target_paths", 5000))
    inspected_context = set(_unique_paths(coverage["inspected_context_paths"], "coverage.inspected_context_paths", 1000))
    if inspected_targets & uninspected_targets or inspected_targets | uninspected_targets != target_paths:
        raise ResultError("coverage must partition every selected target path")
    if inspected_context - context_paths:
        raise ResultError("coverage cites unfrozen context")

    allowed_affected = target_paths | context_paths
    allowed_evidence = allowed_affected | guidance_paths
    line_caps: dict[str, int] = {}
    for item in [*target["files"], *context_items, *result["guidance"]]:
        if item["line_count"] is not None:
            line_caps[item["path"]] = max(
                line_caps.get(item["path"], 0), item["line_count"]
            )
    if context is not None:
        line_caps.update(_line_cap(context))
    impacts = _array(result["impacts"], "impacts", 2000)
    fingerprints: set[str] = set()
    for index, value_item in enumerate(impacts, 1):
        item = _object(
            value_item,
            f"impacts[{index - 1}]",
            {"impact_id", "fingerprint", "source_target_paths", "affected_locations", "relationship", "reach", "confidence", "title", "consequence", "reason", "evidence", "safe_direction", "consumer_purposes"},
        )
        if item["impact_id"] != f"I{index:03d}":
            raise ResultError("impact IDs must be canonical and sequential")
        expected_fingerprint = impact_fingerprint(item)
        if item["fingerprint"] != expected_fingerprint or expected_fingerprint in fingerprints:
            raise ResultError("impact fingerprint is invalid or duplicated")
        fingerprints.add(expected_fingerprint)
        normalized = _impact(
            {key: copy.deepcopy(value_field) for key, value_field in item.items() if key not in {"impact_id", "fingerprint"}},
            f"impacts[{index - 1}]",
            target_paths=target_paths,
            affected_paths=allowed_affected,
            evidence_paths=allowed_evidence,
            inspected_targets=inspected_targets,
            inspected_context=inspected_context,
            context_paths=context_paths,
            line_caps=line_caps,
        )
        if _canonical_json(normalized) != _canonical_json({key: value_field for key, value_field in item.items() if key not in {"impact_id", "fingerprint"}}):
            raise ResultError("impact fields are not canonically ordered")

    limitations = _array(result["limitations"], "limitations", 512)
    material = bool(uninspected_targets)
    for index, value_item in enumerate(limitations):
        item = _object(value_item, f"limitations[{index}]", {"code", "message", "paths", "material", "source"})
        source = _enum(item["source"], f"limitations[{index}].source", {"resolver", "analysis"})
        choices = RESOLVER_LIMITATIONS if source == "resolver" else ANALYSIS_LIMITATIONS
        _enum(item["code"], f"limitations[{index}].code", choices)
        _string(item["message"], f"limitations[{index}].message", 4096)
        _unique_paths(item["paths"], f"limitations[{index}].paths", 5000)
        material = _boolean(item["material"], f"limitations[{index}].material") or material
    expected_status = "INCOMPLETE" if material else "COMPLETE"
    if status != expected_status:
        raise ResultError(f"status must be {expected_status}")

    summary = _object(result["summary"], "summary", {"conclusion", "target_paths", "context_paths", "impacts", "by_relationship", "by_consumer_purpose"})
    _string(summary["conclusion"], "summary.conclusion", 8192)
    if summary["target_paths"] != len(target_paths) or summary["context_paths"] != len(context_paths) or summary["impacts"] != len(impacts):
        raise ResultError("summary counts do not match canonical records")
    expected_relationships: dict[str, int] = {}
    expected_purposes: dict[str, int] = {}
    for item in impacts:
        expected_relationships[item["relationship"]] = expected_relationships.get(item["relationship"], 0) + 1
        for purpose in item["consumer_purposes"]:
            expected_purposes[purpose] = expected_purposes.get(purpose, 0) + 1
    if summary["by_relationship"] != dict(sorted(expected_relationships.items())):
        raise ResultError("summary.by_relationship is not derived from impacts")
    if summary["by_consumer_purpose"] != dict(sorted(expected_purposes.items())):
        raise ResultError("summary.by_consumer_purpose is not derived from impacts")

    if context is not None:
        try:
            validate_context(context)
        except ContextError as exc:
            raise ResultError(str(exc)) from exc
        if digest != context_digest(context):
            raise ResultError("result is not bound to the supplied context")
        if _canonical_json(target) != _canonical_json(_target_result(context)):
            raise ResultError("result target differs from the supplied context")
        if _canonical_json(context_items) != _canonical_json(_context_provenance(context)):
            raise ResultError("result context provenance differs from the supplied context")
        if _canonical_json(result["guidance"]) != _canonical_json(_guidance_provenance(context)):
            raise ResultError("result guidance provenance differs from the supplied context")

    if len((_machine_json_text(result) + "\n").encode("utf-8")) > MAX_JSON_BYTES:
        raise ResultError("canonical result exceeds the 16 MiB output limit")
    return result


def _display(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_location(value: dict[str, Any]) -> str:
    path = _display(value["path"])
    if value["start_line"] is None:
        return path
    if value["start_line"] == value["end_line"]:
        return f"{path}:{value['start_line']}"
    return f"{path}:{value['start_line']}-{value['end_line']}"


def render_human(result: dict[str, Any]) -> str:
    validate_result(result)
    summary = result["summary"]
    lines = [
        f"Change impact: {result['status']}",
        f"Target: {summary['target_paths']} path(s); context: {summary['context_paths']} path(s); impacts: {summary['impacts']}",
        f"Conclusion: {_display(summary['conclusion'])}",
    ]
    if result["impacts"]:
        lines.append("")
        lines.append("Impacts:")
        for impact in result["impacts"]:
            affected = ", ".join(_format_location(item) for item in impact["affected_locations"])
            source = ", ".join(_display(path) for path in impact["source_target_paths"])
            purposes = ", ".join(impact["consumer_purposes"])
            lines.extend(
                [
                    f"- {impact['impact_id']} [{impact['relationship']}; {impact['reach']}; {impact['confidence']}] {_display(impact['title'])}",
                    f"  Source: {source}",
                    f"  Affected: {affected}",
                    f"  Consequence: {_display(impact['consequence'])}",
                    f"  Why: {_display(impact['reason'])}",
                    f"  Suggested use: {purposes}",
                    f"  Safe direction: {_display(impact['safe_direction'])}",
                ]
            )
            for evidence in impact["evidence"]:
                lines.append(
                    f"  Evidence ({evidence['kind']}, {_format_location(evidence['location'])}): {_display(evidence['description'])}"
                )
    else:
        lines.extend(["", "Impacts: none"])
    if result["coverage"]["uninspected_target_paths"]:
        lines.extend(
            [
                "",
                "Uninspected targets: "
                + ", ".join(
                    _display(path)
                    for path in result["coverage"]["uninspected_target_paths"]
                ),
            ]
        )
    if result["limitations"]:
        lines.append("")
        lines.append("Limitations:")
        for item in result["limitations"]:
            paths = (
                f" ({', '.join(_display(path) for path in item['paths'])})"
                if item["paths"]
                else ""
            )
            material = "material" if item["material"] else "non-material"
            lines.append(
                f"- [{material}; {item['source']}; {item['code']}] {_display(item['message'])}{paths}"
            )
    return "\n".join(lines)


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _parse_json(data: bytes, label: str) -> Any:
    if len(data) > MAX_JSON_BYTES:
        raise ResultError(f"{label} exceeds the 16 MiB input limit")
    try:
        value = json.loads(
            data.decode("utf-8", "strict"),
            object_pairs_hook=_reject_duplicate_members,
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ResultError(f"cannot parse {label}: {exc}") from exc
    pending = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise ResultError(f"cannot parse {label}: JSON nesting exceeds {MAX_JSON_DEPTH}")
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
        raise ResultError(f"cannot read JSON input: {exc}") from exc


def _format(result: dict[str, Any], output_format: str) -> str:
    human = render_human(result)
    encoded = _machine_json_text(result)
    if output_format == "human":
        return human
    if output_format == "json":
        return encoded
    return f"{human}\n\n--- JSON ---\n{encoded}"


def _emit(text: str, output: str | None) -> None:
    data = text.encode("utf-8") + (b"" if text.endswith("\n") else b"\n")
    if len(data) > MAX_JSON_BYTES:
        raise ResultError("formatted output exceeds the 16 MiB limit")
    if output is None:
        sys.stdout.buffer.write(data)
        return
    try:
        write_created_output(filesystem_path(output, "output path"), data)
    except SafetyError as exc:
        raise ResultError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("finalize")
    command.add_argument("--context", required=True)
    command.add_argument("--input", default="-")
    command.add_argument("--format", choices=("human", "json", "both"), default="human")
    command.add_argument("--output")
    command = commands.add_parser("validate")
    command.add_argument("--input", default="-")
    command.add_argument("--context")
    command = commands.add_parser("render")
    command.add_argument("--input", default="-")
    command.add_argument("--format", choices=("human", "json", "both"), default="human")
    command.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "finalize":
            context = _read_json(args.context)
            result = finalize_draft(context, _read_json(args.input))
            _emit(_format(result, args.format), args.output)
        elif args.command == "validate":
            context = _read_json(args.context) if args.context else None
            result = validate_result(_read_json(args.input), context=context)
            _emit(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2), None)
        else:
            result = validate_result(_read_json(args.input))
            _emit(_format(result, args.format), args.output)
        return 0
    except (ResultError, SafetyError) as exc:
        print(f"change-impact result: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
