#!/usr/bin/env python3
"""Finalize, validate, and render canonical project-review results."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0.0"
VERDICTS = {"PASS", "BLOCK", "INCOMPLETE"}
DISPOSITIONS = ("blocker", "suggestion", "nit")
SEVERITIES = {"critical", "high", "medium", "low"}
CONFIDENCES = {"high", "medium", "low"}
CATEGORIES = {
    "correctness",
    "security",
    "privacy",
    "data_integrity",
    "reliability",
    "concurrency",
    "compatibility",
    "performance",
    "testing",
    "maintainability",
    "documentation",
    "policy",
    "other",
}
CHANGE_STATUSES = {
    "added",
    "broken_pairing",
    "copied",
    "deleted",
    "modified",
    "renamed",
    "replaced",
    "snapshot",
    "type_changed",
    "unmerged",
    "unknown",
    "untracked",
}
SCOPE_RELATIONS = {"introduced", "worsened", "pre_existing", "uncertain"}
BLOCKING_BASES = {"change", "touched_code_policy", None}
SOURCE_KINDS = {"skill", "user_global", "repository"}
LIMITATION_CODES = {
    "guidance_truncated",
    "scope_truncated",
    "scope_unavailable",
    "file_unreadable",
    "verification_not_authorized",
    "verification_unavailable",
    "verification_failed",
    "evidence_inconclusive",
    "delegation_unavailable",
    "budget_exhausted",
    "other",
}
PATH_PATTERN = re.compile(
    r"^(?!/)(?![A-Za-z]:)(?!.*\\)(?!.*[\x00-\x1f\x7f])"
    r"(?!.*(?:^|/)\.\.(?:/|$)).+$"
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ResultError(ValueError):
    """Raised when a review result is not canonical."""


def _read_json(path: str) -> Any:
    try:
        if path == "-":
            return json.load(sys.stdin)
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ResultError(f"cannot read review JSON: {exc}") from exc


def _is_link_like(metadata: os.stat_result) -> bool:
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _write_output(text: str, path: str | None, overwrite: bool) -> None:
    if path is None:
        print(text)
        return
    destination = Path(path)
    try:
        metadata = destination.lstat()
    except FileNotFoundError:
        metadata = None
    except OSError as exc:
        raise ResultError(f"cannot inspect output path {destination}: {exc}") from exc
    if metadata is not None and _is_link_like(metadata):
        raise ResultError(f"output may not be a symlink or reparse point: {destination}")
    if not destination.parent.is_dir():
        raise ResultError(f"output parent does not exist: {destination.parent}")
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= os.O_TRUNC if overwrite else os.O_EXCL
    try:
        descriptor = os.open(destination, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text + ("" if text.endswith("\n") else "\n"))
    except FileExistsError as exc:
        raise ResultError(f"output already exists: {destination}; use --overwrite") from exc
    except OSError as exc:
        raise ResultError(f"cannot write output {destination}: {exc}") from exc


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


def _array(value: Any, label: str, maximum: int = 5000) -> list[Any]:
    if not isinstance(value, list):
        raise ResultError(f"{label} must be an array")
    if len(value) > maximum:
        raise ResultError(f"{label} exceeds {maximum} items")
    return value


def _string(value: Any, label: str, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ResultError(f"{label} must be a non-empty string")
    if len(value) > maximum:
        raise ResultError(f"{label} exceeds {maximum} characters")
    return value


def _path(value: Any, label: str) -> str:
    path = _string(value, label, 4096)
    if not PATH_PATTERN.fullmatch(path):
        raise ResultError(f"{label} must be a contained POSIX-style relative path")
    return path


def _unique_paths(value: Any, label: str, maximum: int = 5000) -> list[str]:
    paths = [_path(item, f"{label}[{index}]") for index, item in enumerate(_array(value, label, maximum))]
    if len(paths) != len(set(paths)):
        raise ResultError(f"{label} contains duplicate paths")
    return paths


def _nullable_string(value: Any, label: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _string(value, label, maximum)


def _integer(value: Any, label: str, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ResultError(f"{label} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ResultError(f"{label} exceeds {maximum}")
    return value


def _enum(value: Any, label: str, choices: set[Any]) -> Any:
    if value not in choices:
        raise ResultError(f"{label} must be one of {sorted(str(item) for item in choices)}")
    return value


def _validate_location(value: Any, label: str) -> dict[str, Any]:
    location = _object(value, label, {"path", "start_line", "end_line"})
    _path(location["path"], f"{label}.path")
    start = location["start_line"]
    end = location["end_line"]
    if start is not None:
        _integer(start, f"{label}.start_line", 1)
    if end is not None:
        _integer(end, f"{label}.end_line", 1)
    if (start is None) != (end is None):
        raise ResultError(f"{label} line bounds must both be null or integers")
    if start is not None and end < start:
        raise ResultError(f"{label}.end_line must be >= start_line")
    return location


def _validate_rule(value: Any, label: str) -> dict[str, Any]:
    rule = _object(value, label, {"source_kind", "path", "section", "revision"})
    _enum(rule["source_kind"], f"{label}.source_kind", SOURCE_KINDS)
    _string(rule["path"], f"{label}.path", 4096)
    _nullable_string(rule["section"], f"{label}.section", 500)
    _nullable_string(rule["revision"], f"{label}.revision", 512)
    return rule


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
        },
    )
    kind = _enum(target["kind"], "target.kind", {"ref_range", "working_tree", "paths"})
    _string(target["repository_root"], "target.repository_root", 4096)
    base = _nullable_string(target["base_revision"], "target.base_revision", 512)
    head = _nullable_string(target["head_revision"], "target.head_revision", 512)
    mode = target["working_tree_mode"]
    if mode is not None:
        _enum(mode, "target.working_tree_mode", {"staged", "unstaged", "combined"})
    _unique_paths(target["requested_paths"], "target.requested_paths")
    if kind == "ref_range" and (base is None or head is None or mode is not None):
        raise ResultError("ref_range target requires base/head and no working_tree_mode")
    if kind == "working_tree" and (base is None or head is not None or mode is None):
        raise ResultError("working_tree target requires base, mode, and null head")
    if kind == "paths" and (base is not None or head is not None or mode is not None):
        raise ResultError("paths target requires null base/head and working_tree_mode")
    return target


def _validate_guidance(value: Any) -> list[dict[str, Any]]:
    chains = _array(value, "guidance", 512)
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, item in enumerate(chains):
        label = f"guidance[{index}]"
        chain = _object(item, label, {"chain_id", "applies_to", "sources", "complete"})
        chain_id = _string(chain["chain_id"], f"{label}.chain_id", 16)
        if not re.fullmatch(r"G[0-9]{3,6}", chain_id) or chain_id in seen_ids:
            raise ResultError(f"{label}.chain_id is invalid or duplicated")
        seen_ids.add(chain_id)
        paths = _unique_paths(chain["applies_to"], f"{label}.applies_to")
        if not paths:
            raise ResultError(f"{label}.applies_to must not be empty")
        overlap = seen_paths.intersection(paths)
        if overlap:
            raise ResultError(f"{label}.applies_to overlaps another chain at {sorted(overlap)}")
        seen_paths.update(paths)
        sources = _array(chain["sources"], f"{label}.sources", 128)
        if not sources:
            raise ResultError(f"{label}.sources must not be empty")
        source_kinds: list[str] = []
        for source_index, source_value in enumerate(sources):
            source_label = f"{label}.sources[{source_index}]"
            source = _object(source_value, source_label, {"source_kind", "path", "revision", "sha256", "bytes"})
            _enum(source["source_kind"], f"{source_label}.source_kind", SOURCE_KINDS)
            source_kinds.append(source["source_kind"])
            _string(source["path"], f"{source_label}.path", 4096)
            _nullable_string(source["revision"], f"{source_label}.revision", 512)
            digest = _string(source["sha256"], f"{source_label}.sha256", 64)
            if not HEX64.fullmatch(digest):
                raise ResultError(f"{source_label}.sha256 must be lowercase SHA-256")
            _integer(source["bytes"], f"{source_label}.bytes", 0, 1048576)
        if source_kinds[0] != "skill" or source_kinds.count("skill") != 1:
            raise ResultError(f"{label}.sources must start with exactly one skill source")
        if source_kinds.count("user_global") > 1:
            raise ResultError(f"{label}.sources may contain at most one user_global source")
        if "user_global" in source_kinds and source_kinds.index("user_global") != 1:
            raise ResultError(f"{label}.user_global source must follow the skill source")
        first_repository = next((i for i, kind in enumerate(source_kinds) if kind == "repository"), len(source_kinds))
        if any(kind != "repository" for kind in source_kinds[first_repository:]):
            raise ResultError(f"{label}.repository sources must come last")
        if not isinstance(chain["complete"], bool):
            raise ResultError(f"{label}.complete must be boolean")
    return chains


def _validate_changes(
    value: Any,
    guidance: list[dict[str, Any]],
    requested_paths: set[str],
) -> tuple[list[dict[str, Any]], dict[str, tuple[str, ...]]]:
    changes = _array(value, "changes", 5000)
    chain_paths = {chain["chain_id"]: set(chain["applies_to"]) for chain in guidance}
    seen_paths: set[str] = set()
    path_chains: dict[str, tuple[str, ...]] = {}
    for index, item in enumerate(changes):
        label = f"changes[{index}]"
        change = _object(
            item,
            label,
            {
                "path",
                "old_path",
                "status",
                "similarity",
                "guidance_chain_id",
                "old_guidance_chain_id",
            },
        )
        path = _path(change["path"], f"{label}.path")
        if path in seen_paths:
            raise ResultError(f"{label}.path is duplicated")
        seen_paths.add(path)
        status = _enum(change["status"], f"{label}.status", CHANGE_STATUSES)
        old_path = change["old_path"]
        if old_path is not None:
            old_path = _path(old_path, f"{label}.old_path")
        similarity = change["similarity"]
        if similarity is not None:
            _integer(similarity, f"{label}.similarity", 0, 100)
        chain_id = _string(change["guidance_chain_id"], f"{label}.guidance_chain_id", 16)
        if chain_id not in chain_paths or path not in chain_paths[chain_id]:
            raise ResultError(f"{label}.guidance_chain_id does not govern its path")
        old_chain_id = change["old_guidance_chain_id"]
        if old_path is None:
            if old_chain_id is not None:
                raise ResultError(f"{label}.old_guidance_chain_id requires old_path")
            if status in {"renamed", "copied"}:
                raise ResultError(f"{label}.{status} status requires old_path")
            path_chains[path] = (chain_id,)
            continue
        if status not in {"renamed", "copied"}:
            raise ResultError(f"{label}.old_path is valid only for renamed or copied status")
        old_chain_id = _string(old_chain_id, f"{label}.old_guidance_chain_id", 16)
        if old_chain_id not in chain_paths or old_path not in chain_paths[old_chain_id]:
            raise ResultError(f"{label}.old_guidance_chain_id does not govern old_path")
        path_chains[path] = tuple(dict.fromkeys((chain_id, old_chain_id)))
    if seen_paths != requested_paths:
        raise ResultError("changes must describe every requested path exactly once")
    return changes, path_chains


def _validate_coverage(
    value: Any,
    guidance_ids: set[str],
    path_chains: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    coverage = _object(
        value,
        "coverage",
        {"complete", "requested_paths", "reviewed_paths", "context_paths", "groups", "residual_risk"},
    )
    if not isinstance(coverage["complete"], bool):
        raise ResultError("coverage.complete must be boolean")
    requested = _unique_paths(coverage["requested_paths"], "coverage.requested_paths")
    reviewed = _unique_paths(coverage["reviewed_paths"], "coverage.reviewed_paths")
    _unique_paths(coverage["context_paths"], "coverage.context_paths")
    if not set(reviewed) <= set(requested):
        raise ResultError("coverage.reviewed_paths must be a subset of requested_paths")
    groups = _array(coverage["groups"], "coverage.groups", 512)
    group_paths: list[str] = []
    seen_groups: set[str] = set()
    for index, value_group in enumerate(groups):
        label = f"coverage.groups[{index}]"
        group = _object(value_group, label, {"group_id", "paths", "guidance_chain_ids", "reviewer_mode"})
        group_id = _string(group["group_id"], f"{label}.group_id", 16)
        if not re.fullmatch(r"R[0-9]{3,6}", group_id) or group_id in seen_groups:
            raise ResultError(f"{label}.group_id is invalid or duplicated")
        seen_groups.add(group_id)
        paths = _unique_paths(group["paths"], f"{label}.paths")
        if not paths:
            raise ResultError(f"{label}.paths must not be empty")
        group_paths.extend(paths)
        chain_ids = [
            _string(chain_id, f"{label}.guidance_chain_ids[{chain_index}]", 16)
            for chain_index, chain_id in enumerate(
                _array(group["guidance_chain_ids"], f"{label}.guidance_chain_ids", 2)
            )
        ]
        if not chain_ids or len(chain_ids) != len(set(chain_ids)):
            raise ResultError(f"{label}.guidance_chain_ids must be non-empty and unique")
        if any(chain_id not in guidance_ids for chain_id in chain_ids):
            raise ResultError(f"{label}.guidance_chain_ids contains an unknown chain")
        expected = tuple(chain_ids)
        for path in paths:
            if path_chains.get(path) != expected:
                raise ResultError(f"{label}.guidance_chain_ids do not match {path}")
        _enum(group["reviewer_mode"], f"{label}.reviewer_mode", {"lead", "delegated"})
    if len(group_paths) != len(set(group_paths)):
        raise ResultError("coverage groups overlap")
    if set(group_paths) != set(reviewed):
        raise ResultError("coverage groups must cover reviewed_paths exactly")
    for index, risk in enumerate(_array(coverage["residual_risk"], "coverage.residual_risk", 256)):
        _string(risk, f"coverage.residual_risk[{index}]", 2000)
    return coverage


def _validate_verification(value: Any) -> list[dict[str, Any]]:
    records = _array(value, "verification", 128)
    seen: set[str] = set()
    for index, item in enumerate(records):
        label = f"verification[{index}]"
        record = _object(
            item,
            label,
            {
                "verification_id",
                "command",
                "cwd",
                "authorization",
                "status",
                "exit_code",
                "duration_ms",
                "output_summary",
            },
        )
        record_id = _string(record["verification_id"], f"{label}.verification_id", 16)
        if not re.fullmatch(r"V[0-9]{3,6}", record_id) or record_id in seen:
            raise ResultError(f"{label}.verification_id is invalid or duplicated")
        seen.add(record_id)
        _string(record["command"], f"{label}.command", 4096)
        _path(record["cwd"], f"{label}.cwd")
        authorization = _object(record["authorization"], f"{label}.authorization", {"source_kind", "source"})
        _enum(authorization["source_kind"], f"{label}.authorization.source_kind", {"caller", "user_global"})
        _string(authorization["source"], f"{label}.authorization.source", 1000)
        status = _enum(record["status"], f"{label}.status", {"passed", "failed", "timed_out", "unavailable"})
        exit_code = record["exit_code"]
        if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
            raise ResultError(f"{label}.exit_code must be an integer or null")
        if status in {"passed", "failed"} and exit_code is None:
            raise ResultError(f"{label}.exit_code is required for completed commands")
        if status in {"timed_out", "unavailable"} and exit_code is not None:
            raise ResultError(f"{label}.exit_code must be null for {status}")
        if status == "passed" and exit_code != 0:
            raise ResultError(f"{label} passed status requires exit_code 0")
        if status == "failed" and exit_code == 0:
            raise ResultError(f"{label} failed status requires nonzero exit_code")
        _integer(record["duration_ms"], f"{label}.duration_ms", 0, 86400000)
        _string(record["output_summary"], f"{label}.output_summary", 4000)
    return records


def _validate_findings(value: Any) -> list[dict[str, Any]]:
    findings = _array(value, "findings", 1000)
    seen_ids: set[str] = set()
    seen_fingerprints: set[str] = set()
    for index, item in enumerate(findings):
        label = f"findings[{index}]"
        finding = _object(
            item,
            label,
            {
                "finding_id", "fingerprint", "disposition", "severity", "confidence",
                "category", "scope_relation", "blocking_basis", "title", "explanation",
                "impact", "evidence", "primary_location", "related_locations",
                "governing_rule", "safe_direction",
            },
        )
        finding_id = _string(finding["finding_id"], f"{label}.finding_id", 16)
        if not re.fullmatch(r"F[0-9]{3,6}", finding_id) or finding_id in seen_ids:
            raise ResultError(f"{label}.finding_id is invalid or duplicated")
        seen_ids.add(finding_id)
        fingerprint = _string(finding["fingerprint"], f"{label}.fingerprint", 64)
        if not HEX64.fullmatch(fingerprint) or fingerprint in seen_fingerprints:
            raise ResultError(f"{label}.fingerprint is invalid or duplicated")
        seen_fingerprints.add(fingerprint)
        disposition = _enum(finding["disposition"], f"{label}.disposition", set(DISPOSITIONS))
        severity = _enum(finding["severity"], f"{label}.severity", SEVERITIES)
        confidence = _enum(finding["confidence"], f"{label}.confidence", CONFIDENCES)
        _enum(finding["category"], f"{label}.category", CATEGORIES)
        relation = _enum(finding["scope_relation"], f"{label}.scope_relation", SCOPE_RELATIONS)
        basis = _enum(finding["blocking_basis"], f"{label}.blocking_basis", BLOCKING_BASES)
        _string(finding["title"], f"{label}.title", 300)
        _string(finding["explanation"], f"{label}.explanation", 8000)
        _string(finding["impact"], f"{label}.impact", 4000)
        evidence = _array(finding["evidence"], f"{label}.evidence", 32)
        if not evidence:
            raise ResultError(f"{label}.evidence must not be empty")
        for evidence_index, evidence_value in enumerate(evidence):
            evidence_label = f"{label}.evidence[{evidence_index}]"
            item_evidence = _object(evidence_value, evidence_label, {"kind", "description", "location"})
            _enum(
                item_evidence["kind"],
                f"{evidence_label}.kind",
                {"code", "test", "rule", "history", "command", "reasoning"},
            )
            _string(item_evidence["description"], f"{evidence_label}.description", 4000)
            if item_evidence["location"] is not None:
                _validate_location(item_evidence["location"], f"{evidence_label}.location")
        _validate_location(finding["primary_location"], f"{label}.primary_location")
        for related_index, related in enumerate(_array(finding["related_locations"], f"{label}.related_locations", 32)):
            _validate_location(related, f"{label}.related_locations[{related_index}]")
        _validate_rule(finding["governing_rule"], f"{label}.governing_rule")
        _string(finding["safe_direction"], f"{label}.safe_direction", 4000)
        if disposition == "blocker":
            if confidence != "high":
                raise ResultError(f"{label}: blockers require high confidence")
            if relation in {"introduced", "worsened"} and basis != "change":
                raise ResultError(f"{label}: introduced/worsened blockers require blocking_basis change")
            if relation == "pre_existing" and basis != "touched_code_policy":
                raise ResultError(f"{label}: pre-existing blockers require touched_code_policy")
            if relation == "uncertain":
                raise ResultError(f"{label}: uncertain findings cannot block")
        elif basis is not None:
            raise ResultError(f"{label}: non-blockers require null blocking_basis")
        if disposition == "nit" and severity != "low":
            raise ResultError(f"{label}: nits require low severity")
        if finding_fingerprint(finding) != fingerprint:
            raise ResultError(f"{label}.fingerprint does not match the finding")
    return findings


def _validate_limitations(value: Any) -> list[dict[str, Any]]:
    limitations = _array(value, "limitations", 256)
    for index, item in enumerate(limitations):
        label = f"limitations[{index}]"
        limitation = _object(item, label, {"code", "message", "affected_paths", "material"})
        _enum(limitation["code"], f"{label}.code", LIMITATION_CODES)
        _string(limitation["message"], f"{label}.message", 4000)
        _unique_paths(limitation["affected_paths"], f"{label}.affected_paths")
        if not isinstance(limitation["material"], bool):
            raise ResultError(f"{label}.material must be boolean")
    return limitations


def validate_result(value: Any) -> dict[str, Any]:
    result = _object(
        value,
        "result",
        {
            "schema_version",
            "target",
            "changes",
            "verdict",
            "summary",
            "guidance",
            "coverage",
            "verification",
            "findings",
            "limitations",
        },
    )
    if result["schema_version"] != SCHEMA_VERSION:
        raise ResultError(f"schema_version must be {SCHEMA_VERSION}")
    target = _validate_target(result["target"])
    _enum(result["verdict"], "verdict", VERDICTS)
    guidance = _validate_guidance(result["guidance"])
    requested = set(target["requested_paths"])
    _, path_chains = _validate_changes(result["changes"], guidance, requested)
    coverage = _validate_coverage(
        result["coverage"],
        {item["chain_id"] for item in guidance},
        path_chains,
    )
    verification = _validate_verification(result["verification"])
    findings = _validate_findings(result["findings"])
    limitations = _validate_limitations(result["limitations"])
    limitation_codes = {item["code"] for item in limitations}
    if any(item["status"] == "failed" for item in verification) and "verification_failed" not in limitation_codes:
        raise ResultError("failed verification requires a verification_failed limitation")
    if any(item["status"] in {"timed_out", "unavailable"} for item in verification) and not (
        {"verification_unavailable", "verification_failed"} & limitation_codes
    ):
        raise ResultError("timed-out or unavailable verification requires a verification limitation")
    summary = _object(result["summary"], "summary", {"conclusion", "finding_counts"})
    _string(summary["conclusion"], "summary.conclusion", 2000)
    counts = _object(summary["finding_counts"], "summary.finding_counts", {"blocker", "suggestion", "nit", "total"})
    actual = {item: sum(finding["disposition"] == item for finding in findings) for item in DISPOSITIONS}
    actual["total"] = len(findings)
    for key, expected in actual.items():
        if _integer(counts[key], f"summary.finding_counts.{key}", 0, 1000) != expected:
            raise ResultError(f"summary.finding_counts.{key} must equal {expected}")
    material = any(item["material"] for item in limitations)
    if coverage["complete"] == material:
        raise ResultError("coverage.complete must be false exactly when a material limitation exists")
    if any(not chain["complete"] for chain in guidance) and coverage["complete"]:
        raise ResultError("coverage cannot be complete while a guidance chain is incomplete")
    expected_verdict = derive_verdict(findings, limitations)
    if result["verdict"] != expected_verdict:
        raise ResultError(f"verdict must be {expected_verdict}")
    if requested != set(coverage["requested_paths"]):
        raise ResultError("target.requested_paths must equal coverage.requested_paths")
    guided = {path for chain in guidance for path in chain["applies_to"]}
    reviewed = set(coverage["reviewed_paths"])
    if coverage["complete"] and reviewed != requested:
        raise ResultError("complete coverage must review every requested path")
    if not requested <= guided:
        raise ResultError("every requested path must have an applicable guidance chain")
    chains_by_id = {chain["chain_id"]: chain for chain in guidance}
    for index, finding in enumerate(findings):
        finding_path = finding["primary_location"]["path"]
        if finding_path not in requested:
            raise ResultError(f"findings[{index}].primary_location must be within the requested scope")
        available_rules = {
            (source["source_kind"], source["path"], source["revision"])
            for chain_id in path_chains[finding_path]
            for source in chains_by_id[chain_id]["sources"]
        }
        rule = finding["governing_rule"]
        if (rule["source_kind"], rule["path"], rule["revision"]) not in available_rules:
            raise ResultError(f"findings[{index}].governing_rule is not present in guidance provenance")
    return result


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def finding_fingerprint(finding: dict[str, Any]) -> str:
    rule = finding.get("governing_rule") or {}
    primary = finding.get("primary_location") or {}
    value = {
        "category": finding.get("category"),
        "rule": {
            "source_kind": rule.get("source_kind"),
            "path": rule.get("path"),
            "section": _normalized(str(rule.get("section") or "")),
        },
        "path": primary.get("path"),
        "scope_relation": finding.get("scope_relation"),
        "claim": _normalized(str(finding.get("title") or "")),
    }
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def derive_verdict(findings: list[dict[str, Any]], limitations: list[dict[str, Any]]) -> str:
    if any(item.get("disposition") == "blocker" for item in findings):
        return "BLOCK"
    if any(item.get("material") is True for item in limitations):
        return "INCOMPLETE"
    return "PASS"


def finalize_draft(value: Any) -> dict[str, Any]:
    draft = copy.deepcopy(value)
    if not isinstance(draft, dict):
        raise ResultError("draft must be an object")
    draft["schema_version"] = SCHEMA_VERSION
    findings = draft.get("findings")
    if not isinstance(findings, list):
        raise ResultError("draft.findings must be an array")
    priority = {"blocker": 0, "suggestion": 1, "nit": 2}
    findings.sort(
        key=lambda item: (
            priority.get(item.get("disposition"), 99) if isinstance(item, dict) else 99,
            str((item.get("primary_location") or {}).get("path", "")) if isinstance(item, dict) else "",
            str(item.get("title", "")) if isinstance(item, dict) else "",
        )
    )
    for index, finding in enumerate(findings, 1):
        if not isinstance(finding, dict):
            raise ResultError(f"draft.findings[{index - 1}] must be an object")
        finding["finding_id"] = f"F{index:03d}"
        finding["fingerprint"] = finding_fingerprint(finding)
    summary = draft.get("summary")
    if not isinstance(summary, dict):
        raise ResultError("draft.summary must be an object")
    summary["finding_counts"] = {
        disposition: sum(item.get("disposition") == disposition for item in findings)
        for disposition in DISPOSITIONS
    }
    summary["finding_counts"]["total"] = len(findings)
    limitations = draft.get("limitations")
    if not isinstance(limitations, list):
        raise ResultError("draft.limitations must be an array")
    draft["verdict"] = derive_verdict(findings, limitations)
    validate_result(draft)
    return draft


def _format_location(location: dict[str, Any]) -> str:
    path = _display_text(location["path"])
    if location["start_line"] is None:
        return path
    if location["start_line"] == location["end_line"]:
        return f"{path}:{location['start_line']}"
    return f"{path}:{location['start_line']}-{location['end_line']}"


def _display_text(value: str) -> str:
    pieces: list[str] = []
    for character in value:
        category = unicodedata.category(character)
        if character == "\\" or category.startswith("C") or category in {"Zl", "Zp"}:
            pieces.append(json.dumps(character, ensure_ascii=True)[1:-1])
        else:
            pieces.append(character)
    escaped = "".join(pieces)
    return escaped.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_human(result: dict[str, Any]) -> str:
    validate_result(result)
    counts = result["summary"]["finding_counts"]
    lines = [
        f"Project review: {result['verdict']}",
        _display_text(result["summary"]["conclusion"]),
        "",
        f"Findings: {counts['blocker']} blocker, {counts['suggestion']} suggestion, {counts['nit']} nit",
    ]
    labels = {"blocker": "Blockers", "suggestion": "Suggestions", "nit": "Nits"}
    for disposition in DISPOSITIONS:
        selected = [item for item in result["findings"] if item["disposition"] == disposition]
        if not selected:
            continue
        lines.extend(["", labels[disposition]])
        for finding in selected:
            rule = finding["governing_rule"]
            rule_text = _display_text(rule["path"])
            if rule["section"]:
                rule_text += f" - {_display_text(rule['section'])}"
            lines.extend(
                [
                    f"- [{finding['finding_id']}] {_display_text(finding['title'])} "
                    f"({finding['severity']}, {finding['confidence']} confidence)",
                    f"  Location: {_format_location(finding['primary_location'])}",
                    f"  Explanation: {_display_text(finding['explanation'])}",
                    f"  Impact: {_display_text(finding['impact'])}",
                    "  Evidence:",
                    *[
                        "  - "
                        + _display_text(item["description"])
                        + (f" ({_format_location(item['location'])})" if item["location"] else "")
                        for item in finding["evidence"]
                    ],
                    f"  Rule: {rule_text}",
                    f"  Safe direction: {_display_text(finding['safe_direction'])}",
                ]
            )
            if finding["related_locations"]:
                lines.append(
                    "  Related: "
                    + ", ".join(_format_location(location) for location in finding["related_locations"])
                )
    lines.extend(
        [
            "",
            "Coverage",
            f"- Reviewed {len(result['coverage']['reviewed_paths'])} of "
            f"{len(result['coverage']['requested_paths'])} requested paths.",
            f"- Coverage complete: {'yes' if result['coverage']['complete'] else 'no'}.",
        ]
    )
    if result["verification"]:
        lines.extend(["", "Verification"])
        for record in result["verification"]:
            lines.append(
                f"- [{record['status']}] {_display_text(record['command'])} - "
                f"{_display_text(record['output_summary'])}"
            )
    if result["limitations"]:
        lines.extend(["", "Limitations"])
        for limitation in result["limitations"]:
            marker = "material" if limitation["material"] else "non-material"
            lines.append(f"- [{marker}] {_display_text(limitation['message'])}")
    source_names = []
    for chain in result["guidance"]:
        for source in chain["sources"]:
            name = f"{source['source_kind']}:{_display_text(source['path'])}"
            if name not in source_names:
                source_names.append(name)
    lines.extend(["", "Guidance", *[f"- {name}" for name in source_names]])
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("finalize", "validate", "render"):
        command = subparsers.add_parser(name)
        command.add_argument("--input", default="-", help="JSON file or - for stdin")
        if name != "validate":
            command.add_argument("--format", choices=("human", "json", "both"), default="human")
            command.add_argument("--output")
            command.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        value = _read_json(args.input)
        if args.command == "finalize":
            result = finalize_draft(value)
            _write_output(_format_result(result, args.format), args.output, args.overwrite)
        elif args.command == "validate":
            validate_result(value)
            print("valid project-review result")
        else:
            result = validate_result(value)
            _write_output(_format_result(result, args.format), args.output, args.overwrite)
        return 0
    except ResultError as exc:
        print(f"project-review result: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
