#!/usr/bin/env python3
"""Finalize and validate neutral review batches and conservative fix plans."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any


BATCH_SCHEMA_VERSION = "1.0.0"
PLAN_SCHEMA_VERSION = "1.0.0"
RUN_SCHEMA_VERSION = "1.0.0"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 100
HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
FINDING_ID = re.compile(r"^RF[0-9]{3,6}$")

TARGET_KINDS = {"ref_range", "working_tree", "paths"}
WORKING_TREE_MODES = {"staged", "unstaged", "combined", None}
OUTPUT_FORMATS = {"project_review_json", "neutral_json", "structured", "prose"}
SOURCE_OUTCOMES = {"pass", "changes_requested", "incomplete", "unknown"}
NORMALIZATION_MODES = {"deterministic", "native", "independent_agent"}
LEVELS = {"high", "medium", "low"}
PROVENANCE = {"explicit", "inferred", "missing"}
DISPOSITIONS = {"blocker", "suggestion", "nit", "unknown"}
SEVERITIES = {"critical", "high", "medium", "low", "unknown"}
CONFIDENCES = {"high", "medium", "low", "unknown"}
SCOPE_RELATIONS = {"introduced", "worsened", "pre_existing", "uncertain", "unknown"}
ACTIONABILITIES = {"actionable", "needs_triage", "informational"}
EVIDENCE_KINDS = {
    "code",
    "test",
    "rule",
    "history",
    "command",
    "reasoning",
    "reviewer_statement",
}
LIMITATION_CODES = {
    "source_incomplete",
    "source_limitation",
    "target_mismatch",
    "output_ambiguous",
    "missing_evidence",
    "missing_location",
    "contradictory_output",
    "normalizer_unavailable",
    "other",
}
INTENT_STATUSES = {"explicit", "inferred", "uncertain"}
INTENT_SOURCES = {
    "user",
    "test",
    "specification",
    "review_rule",
    "public_contract",
    "existing_behavior",
    "none",
}
BEHAVIOR_EFFECTS = {"none", "restorative", "new_or_changed", "uncertain"}
CHANGE_KINDS = {"text_only", "mechanical", "code", "configuration", "other"}
REMEDY_SHAPES = {"singular", "multiple", "unknown"}
SCOPE_SIZES = {"small", "medium", "large", "unknown"}
VALIDATION_STATES = {"available", "static_sufficient", "unavailable", "uncertain"}
RISK_FACTORS = {
    "product_behavior",
    "public_api",
    "schema_or_format",
    "compatibility",
    "security",
    "privacy",
    "durable_data",
    "concurrency",
    "failure_policy",
    "dependency",
    "external_service",
    "architecture",
    "broad_scope",
    "difficult_rollback",
    "user_change_overlap",
    "uncertain_intent",
    "validation_gap",
    "destructive_action",
    "remote_state",
    "permission_change",
    "dependency_installation",
    "persistent_service",
    "other",
}
AUTHORIZATION_RISKS = {
    "destructive_action",
    "remote_state",
    "permission_change",
    "dependency_installation",
    "persistent_service",
}
DECISIONS = {"auto", "user_decision_required", "authorization_required"}
RUN_STATUSES = {
    "completed",
    "decision_required",
    "authorization_required",
    "incomplete",
    "stopped",
}
RUN_STOP_REASONS = {
    "reviewer_pass",
    "user_decision_required",
    "authorization_required",
    "reviewer_incomplete",
    "reviewer_not_passed",
    "reviewer_set_drift",
    "target_drift",
    "ref_range_review_only",
    "no_material_progress",
    "maximum_rounds_reached",
    "validation_failed",
    "workflow_incomplete",
}
SEMANTIC_FIELDS = (
    "disposition",
    "severity",
    "confidence",
    "scope_relation",
    "actionability",
    "safe_direction",
)
UNKNOWN_VALUES = {
    "disposition": "unknown",
    "severity": "unknown",
    "confidence": "unknown",
    "scope_relation": "unknown",
    "actionability": "needs_triage",
    "safe_direction": None,
}
DISPOSITION_ORDER = {"blocker": 0, "suggestion": 1, "nit": 2, "unknown": 3}


class WorkflowError(ValueError):
    """Raised when review workflow data violates its locked contract."""


def _object(
    value: Any,
    label: str,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkflowError(f"{label} must be an object")
    optional = set() if optional is None else optional
    keys = set(value)
    missing = required - keys
    extra = keys - required - optional
    if missing:
        raise WorkflowError(f"{label} is missing: {', '.join(sorted(missing))}")
    if extra:
        raise WorkflowError(f"{label} has unexpected fields: {', '.join(sorted(extra))}")
    return value


def _sequence(value: Any, label: str, maximum: int, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list):
        raise WorkflowError(f"{label} must be an array")
    if not minimum <= len(value) <= maximum:
        raise WorkflowError(f"{label} must contain between {minimum} and {maximum} items")
    return value


def _has_unsafe_control(value: str) -> bool:
    return any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in value)


def _text(
    value: Any,
    label: str,
    maximum: int,
    *,
    nullable: bool = False,
    single_line: bool = False,
) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value or len(value) > maximum:
        suffix = " or null" if nullable else ""
        raise WorkflowError(f"{label} must be a non-empty string up to {maximum} characters{suffix}")
    if _has_unsafe_control(value):
        raise WorkflowError(f"{label} contains unsafe control characters")
    if single_line and any(char in value for char in "\r\n"):
        raise WorkflowError(f"{label} must be one line")
    return value


def _enum(value: Any, allowed: set[Any], label: str) -> Any:
    try:
        accepted = value in allowed
    except TypeError:
        accepted = False
    if not accepted:
        rendered = ", ".join(repr(item) for item in sorted(allowed, key=lambda item: str(item)))
        raise WorkflowError(f"{label} must be one of: {rendered}")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise WorkflowError(f"{label} must be a boolean")
    return value


def _unique_strings(
    value: Any,
    label: str,
    maximum: int,
    *,
    item_maximum: int,
    paths: bool = False,
) -> list[str]:
    items = _sequence(value, label, maximum)
    result: list[str] = []
    for index, item in enumerate(items):
        if paths:
            result.append(_repo_path(item, f"{label}[{index}]"))
        else:
            result.append(_text(item, f"{label}[{index}]", item_maximum) or "")
    if len(result) != len(set(result)):
        raise WorkflowError(f"{label} must not contain duplicates")
    return result


def _repo_path(value: Any, label: str) -> str:
    path = _text(value, label, 4096, single_line=True)
    assert path is not None
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise WorkflowError(f"{label} contains unsafe control characters")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path) or "\\" in path:
        raise WorkflowError(f"{label} must be a portable repository-relative path")
    parts = path.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise WorkflowError(f"{label} is not canonical")
    return path


def _revision(value: Any, label: str) -> str | None:
    return _text(value, label, 512, nullable=True, single_line=True)


def _target(value: Any, label: str = "target") -> dict[str, Any]:
    item = _object(
        value,
        label,
        {
            "kind",
            "repository_root",
            "base_revision",
            "head_revision",
            "working_tree_mode",
            "requested_paths",
        },
    )
    kind = _enum(item["kind"], TARGET_KINDS, f"{label}.kind")
    root = _text(item["repository_root"], f"{label}.repository_root", 4096, single_line=True)
    base = _revision(item["base_revision"], f"{label}.base_revision")
    head = _revision(item["head_revision"], f"{label}.head_revision")
    mode = _enum(item["working_tree_mode"], WORKING_TREE_MODES, f"{label}.working_tree_mode")
    requested = _unique_strings(
        item["requested_paths"], f"{label}.requested_paths", 5000, item_maximum=4096, paths=True
    )
    if not requested:
        raise WorkflowError(f"{label}.requested_paths must identify at least one exact target path")
    if kind == "working_tree" and mode is None:
        raise WorkflowError(f"{label}.working_tree_mode is required for a working tree target")
    if kind != "working_tree" and mode is not None:
        raise WorkflowError(f"{label}.working_tree_mode is valid only for a working tree target")
    if kind == "paths" and (base is not None or head is not None):
        raise WorkflowError(f"{label} path snapshots cannot claim Git revisions")
    if kind == "ref_range" and (base is None or head is None):
        raise WorkflowError(f"{label} ref ranges require base_revision and head_revision")
    return {
        "kind": kind,
        "repository_root": root,
        "base_revision": base,
        "head_revision": head,
        "working_tree_mode": mode,
        "requested_paths": requested,
    }


def _source(value: Any) -> dict[str, Any]:
    item = _object(
        value,
        "source",
        {
            "reviewer",
            "reviewer_version",
            "output_format",
            "output_sha256",
            "completed",
            "verdict",
            "outcome",
        },
    )
    digest = _text(item["output_sha256"], "source.output_sha256", 64, single_line=True)
    if digest is None or not HEX_DIGEST.fullmatch(digest):
        raise WorkflowError("source.output_sha256 must be a lowercase SHA-256 digest")
    result = {
        "reviewer": _text(item["reviewer"], "source.reviewer", 128, single_line=True),
        "reviewer_version": _text(
            item["reviewer_version"], "source.reviewer_version", 128, nullable=True, single_line=True
        ),
        "output_format": _enum(item["output_format"], OUTPUT_FORMATS, "source.output_format"),
        "output_sha256": digest,
        "completed": _boolean(item["completed"], "source.completed"),
        "verdict": _text(item["verdict"], "source.verdict", 128, nullable=True, single_line=True),
        "outcome": _enum(item["outcome"], SOURCE_OUTCOMES, "source.outcome"),
    }
    if result["outcome"] in {"pass", "changes_requested"} and result["verdict"] is None:
        raise WorkflowError("pass and changes_requested outcomes require an explicit source verdict")
    return result


def _normalization(value: Any) -> dict[str, Any]:
    item = _object(value, "normalization", {"mode", "confidence", "notes"})
    notes = [
        _text(note, f"normalization.notes[{index}]", 2000) or ""
        for index, note in enumerate(_sequence(item["notes"], "normalization.notes", 256))
    ]
    return {
        "mode": _enum(item["mode"], NORMALIZATION_MODES, "normalization.mode"),
        "confidence": _enum(item["confidence"], LEVELS, "normalization.confidence"),
        "notes": notes,
    }


def _line(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise WorkflowError(f"{label} must be a positive integer or null")
    return value


def _location(value: Any, label: str, *, nullable: bool = False) -> dict[str, Any] | None:
    if value is None and nullable:
        return None
    item = _object(value, label, {"path", "start_line", "end_line"})
    start = _line(item["start_line"], f"{label}.start_line")
    end = _line(item["end_line"], f"{label}.end_line")
    if (start is None) != (end is None):
        raise WorkflowError(f"{label} line bounds must both be set or both be null")
    if start is not None and end is not None and end < start:
        raise WorkflowError(f"{label}.end_line cannot precede start_line")
    return {"path": _repo_path(item["path"], f"{label}.path"), "start_line": start, "end_line": end}


def _evidence(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label, {"kind", "description", "location"})
    return {
        "kind": _enum(item["kind"], EVIDENCE_KINDS, f"{label}.kind"),
        "description": _text(item["description"], f"{label}.description", 4000),
        "location": _location(item["location"], f"{label}.location", nullable=True),
    }


def _field_provenance(value: Any, finding: dict[str, Any], label: str) -> dict[str, str]:
    item = _object(value, label, set(SEMANTIC_FIELDS))
    result: dict[str, str] = {}
    errors: list[str] = []
    for field in SEMANTIC_FIELDS:
        provenance = _enum(item[field], PROVENANCE, f"{label}.{field}")
        expected_missing = finding[field] == UNKNOWN_VALUES[field]
        if provenance == "missing" and not expected_missing:
            errors.append(f"{label}.{field} cannot be missing when the value is known")
        if provenance != "missing" and expected_missing:
            errors.append(f"{label}.{field} must be missing when the value is unknown")
        result[field] = provenance
    if errors:
        raise WorkflowError("; ".join(errors))
    return result


def _finding_draft(value: Any, index: int) -> dict[str, Any]:
    label = f"findings[{index}]"
    item = _object(
        value,
        label,
        {
            "source_id",
            "source_fingerprint",
            "disposition",
            "severity",
            "confidence",
            "scope_relation",
            "actionability",
            "title",
            "problem",
            "impact",
            "evidence",
            "primary_location",
            "related_locations",
            "safe_direction",
            "field_provenance",
            "normalization_confidence",
            "normalization_notes",
        },
    )
    result: dict[str, Any] = {
        "source_id": _text(item["source_id"], f"{label}.source_id", 256, nullable=True, single_line=True),
        "source_fingerprint": _text(
            item["source_fingerprint"],
            f"{label}.source_fingerprint",
            64,
            nullable=True,
            single_line=True,
        ),
        "disposition": _enum(item["disposition"], DISPOSITIONS, f"{label}.disposition"),
        "severity": _enum(item["severity"], SEVERITIES, f"{label}.severity"),
        "confidence": _enum(item["confidence"], CONFIDENCES, f"{label}.confidence"),
        "scope_relation": _enum(item["scope_relation"], SCOPE_RELATIONS, f"{label}.scope_relation"),
        "actionability": _enum(item["actionability"], ACTIONABILITIES, f"{label}.actionability"),
        "title": _text(item["title"], f"{label}.title", 300),
        "problem": _text(item["problem"], f"{label}.problem", 8000),
        "impact": _text(item["impact"], f"{label}.impact", 4000),
        "evidence": [
            _evidence(evidence, f"{label}.evidence[{evidence_index}]")
            for evidence_index, evidence in enumerate(
                _sequence(item["evidence"], f"{label}.evidence", 32)
            )
        ],
        "primary_location": _location(
            item["primary_location"], f"{label}.primary_location", nullable=True
        ),
        "related_locations": [
            _location(location, f"{label}.related_locations[{location_index}]")
            for location_index, location in enumerate(
                _sequence(item["related_locations"], f"{label}.related_locations", 32)
            )
        ],
        "safe_direction": _text(
            item["safe_direction"], f"{label}.safe_direction", 4000, nullable=True
        ),
        "normalization_confidence": _enum(
            item["normalization_confidence"], LEVELS, f"{label}.normalization_confidence"
        ),
        "normalization_notes": [
            _text(note, f"{label}.normalization_notes[{note_index}]", 2000) or ""
            for note_index, note in enumerate(
                _sequence(item["normalization_notes"], f"{label}.normalization_notes", 64)
            )
        ],
    }
    result["field_provenance"] = _field_provenance(
        item["field_provenance"], result, f"{label}.field_provenance"
    )
    if result["source_fingerprint"] is not None and not HEX_DIGEST.fullmatch(
        result["source_fingerprint"]
    ):
        raise WorkflowError(f"{label}.source_fingerprint must be a lowercase SHA-256 digest or null")
    if "inferred" in result["field_provenance"].values() and not result["normalization_notes"]:
        raise WorkflowError(f"{label} inferred fields require a normalization note")
    if result["actionability"] == "actionable":
        if not result["evidence"] or result["primary_location"] is None or result["safe_direction"] is None:
            raise WorkflowError(
                f"{label} actionable findings require evidence, a primary location, and a safe direction"
            )
    return result


def _limitation(value: Any, index: int) -> dict[str, Any]:
    label = f"limitations[{index}]"
    item = _object(value, label, {"code", "message", "source_ids", "material"})
    return {
        "code": _enum(item["code"], LIMITATION_CODES, f"{label}.code"),
        "message": _text(item["message"], f"{label}.message", 4000),
        "source_ids": _unique_strings(
            item["source_ids"], f"{label}.source_ids", 1000, item_maximum=256
        ),
        "material": _boolean(item["material"], f"{label}.material"),
    }


def _fingerprint(source: dict[str, Any], finding: dict[str, Any]) -> str:
    primary = finding["primary_location"]
    payload = {
        "reviewer": source["reviewer"],
        "source_id": finding["source_id"],
        "source_fingerprint": finding["source_fingerprint"],
        "title": finding["title"],
        "problem": finding["problem"],
        "primary_path": None if primary is None else primary["path"],
        "safe_direction": finding["safe_direction"],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _batch_envelope(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    item = _object(value, "batch envelope", {"target", "source"})
    return _target(item["target"]), _source(item["source"])


def _normalization_draft(value: Any) -> dict[str, Any]:
    item = _object(value, "normalization", {"confidence", "notes"})
    notes = [
        _text(note, f"normalization.notes[{index}]", 2000) or ""
        for index, note in enumerate(_sequence(item["notes"], "normalization.notes", 256))
    ]
    return {
        "confidence": _enum(item["confidence"], LEVELS, "normalization.confidence"),
        "notes": notes,
    }


def finalize_batch(draft: Any, envelope_value: Any) -> dict[str, Any]:
    item = _object(draft, "batch draft", {"normalization", "findings", "limitations"})
    target, source = _batch_envelope(envelope_value)
    normalization_draft = _normalization_draft(item["normalization"])
    expected_modes = {
        "project_review_json": "deterministic",
        "neutral_json": "native",
        "structured": "independent_agent",
        "prose": "independent_agent",
    }
    normalization = {
        "mode": expected_modes[source["output_format"]],
        **normalization_draft,
    }
    findings = [
        _finding_draft(finding, index)
        for index, finding in enumerate(_sequence(item["findings"], "findings", 1000))
    ]
    requested_paths = set(target["requested_paths"])
    for index, finding in enumerate(findings):
        if finding["source_fingerprint"] == source["output_sha256"]:
            raise WorkflowError(
                f"findings[{index}].source_fingerprint must not reuse the raw output digest"
            )
        primary = finding["primary_location"]
        if primary is not None and primary["path"] not in requested_paths:
            raise WorkflowError(
                f"findings[{index}].primary_location.path must be an exact target path"
            )
    limitations = [
        _limitation(limitation, index)
        for index, limitation in enumerate(_sequence(item["limitations"], "limitations", 256))
    ]
    material_codes = {
        limitation["code"] for limitation in limitations if limitation["material"]
    }
    if not source["completed"] and source["outcome"] != "incomplete":
        raise WorkflowError("an incomplete source must use outcome incomplete")
    if source["completed"] and source["outcome"] == "incomplete":
        raise WorkflowError("a completed source cannot use outcome incomplete")
    if not source["completed"] and not any(
        limitation["code"] == "source_incomplete" and limitation["material"]
        for limitation in limitations
    ):
        raise WorkflowError("an incomplete source requires a material source_incomplete limitation")
    if source["outcome"] == "unknown" and "output_ambiguous" not in material_codes:
        raise WorkflowError("an unknown source outcome requires a material output_ambiguous limitation")
    if (
        source["outcome"] == "pass"
        and any(finding["disposition"] == "blocker" for finding in findings)
        and "contradictory_output" not in material_codes
    ):
        raise WorkflowError(
            "a pass source with blockers requires a material contradictory_output limitation"
        )
    if (
        source["outcome"] == "changes_requested"
        and not findings
        and not material_codes.intersection(
            {"missing_evidence", "missing_location", "contradictory_output", "output_ambiguous"}
        )
    ):
        raise WorkflowError(
            "a changes_requested source without findings requires a material source limitation"
        )
    for finding in findings:
        finding["fingerprint"] = _fingerprint(source, finding)
    source_ids = [finding["source_id"] for finding in findings if finding["source_id"] is not None]
    if len(source_ids) != len(set(source_ids)):
        raise WorkflowError("findings must not repeat a non-null source_id")
    findings.sort(
        key=lambda finding: (
            DISPOSITION_ORDER[finding["disposition"]],
            "" if finding["primary_location"] is None else finding["primary_location"]["path"],
            finding["title"].casefold(),
            finding["fingerprint"],
        )
    )
    for index, finding in enumerate(findings, 1):
        finding["finding_id"] = f"RF{index:03d}"
        finding_order = [
            "finding_id",
            "fingerprint",
            "source_id",
            "source_fingerprint",
            "disposition",
            "severity",
            "confidence",
            "scope_relation",
            "actionability",
            "title",
            "problem",
            "impact",
            "evidence",
            "primary_location",
            "related_locations",
            "safe_direction",
            "field_provenance",
            "normalization_confidence",
            "normalization_notes",
        ]
        findings[index - 1] = {key: finding[key] for key in finding_order}
    status = "partial" if any(limitation["material"] for limitation in limitations) else "complete"
    result = {
        "schema_version": BATCH_SCHEMA_VERSION,
        "target": target,
        "source": source,
        "normalization": normalization,
        "status": status,
        "findings": findings,
        "limitations": limitations,
    }
    return result


def validate_batch(value: Any) -> dict[str, Any]:
    item = _object(
        value,
        "batch",
        {"schema_version", "target", "source", "normalization", "status", "findings", "limitations"},
    )
    if item["schema_version"] != BATCH_SCHEMA_VERSION:
        raise WorkflowError(f"schema_version must be {BATCH_SCHEMA_VERSION}")
    canonical_findings = _sequence(item["findings"], "findings", 1000)
    draft_findings: list[dict[str, Any]] = []
    for index, finding in enumerate(canonical_findings):
        canonical = _object(
            finding,
            f"findings[{index}]",
            {
                "finding_id",
                "fingerprint",
                "source_id",
                "source_fingerprint",
                "disposition",
                "severity",
                "confidence",
                "scope_relation",
                "actionability",
                "title",
                "problem",
                "impact",
                "evidence",
                "primary_location",
                "related_locations",
                "safe_direction",
                "field_provenance",
                "normalization_confidence",
                "normalization_notes",
            },
        )
        finding_id = _text(canonical["finding_id"], f"findings[{index}].finding_id", 16, single_line=True)
        digest = _text(canonical["fingerprint"], f"findings[{index}].fingerprint", 64, single_line=True)
        if finding_id is None or not FINDING_ID.fullmatch(finding_id):
            raise WorkflowError(f"findings[{index}].finding_id is invalid")
        if digest is None or not HEX_DIGEST.fullmatch(digest):
            raise WorkflowError(f"findings[{index}].fingerprint is invalid")
        draft_findings.append(
            {key: copy.deepcopy(value) for key, value in canonical.items() if key not in {"finding_id", "fingerprint"}}
        )
    draft = {
        "normalization": {
            "confidence": copy.deepcopy(item["normalization"]["confidence"]),
            "notes": copy.deepcopy(item["normalization"]["notes"]),
        },
        "findings": draft_findings,
        "limitations": copy.deepcopy(item["limitations"]),
    }
    envelope = {
        "target": copy.deepcopy(item["target"]),
        "source": copy.deepcopy(item["source"]),
    }
    expected = finalize_batch(draft, envelope)
    if item != expected:
        raise WorkflowError("batch is not in canonical finalized form")
    return expected


def _project_review_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_digest(value: Any) -> str:
    encoded = _bounded_json_bytes(value, "canonical value", compact=True)
    return hashlib.sha256(encoded).hexdigest()


def _assert_bounded_json(value: Any, label: str) -> None:
    pending: list[tuple[Any, int, bool]] = [(value, 0, False)]
    active: set[int] = set()
    while pending:
        current, depth, leaving = pending.pop()
        if not isinstance(current, (dict, list)):
            continue
        identity = id(current)
        if leaving:
            active.remove(identity)
            continue
        if identity in active:
            raise WorkflowError(f"{label} contains a circular value")
        if depth >= MAX_JSON_DEPTH:
            raise WorkflowError(
                f"{label} exceeds the {MAX_JSON_DEPTH}-level nesting limit"
            )
        active.add(identity)
        pending.append((current, depth, True))
        children = current.values() if isinstance(current, dict) else current
        pending.extend((child, depth + 1, False) for child in children)


def _bounded_json_bytes(value: Any, label: str, *, compact: bool) -> bytes:
    _assert_bounded_json(value, label)
    try:
        if compact:
            rendered = json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        else:
            rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        encoded = rendered.encode("utf-8")
    except (RecursionError, UnicodeEncodeError, ValueError) as exc:
        raise WorkflowError(f"{label} is not bounded UTF-8 JSON: {exc}") from exc
    if len(encoded) > MAX_JSON_BYTES:
        raise WorkflowError(f"{label} exceeds the {MAX_JSON_BYTES}-byte limit")
    return encoded


def convert_project_review(
    value: Any, expected_target_value: Any, output_sha256: str | None = None
) -> dict[str, Any]:
    result = _object(
        value,
        "project-review result",
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
    if result["schema_version"] != "1.0.0":
        raise WorkflowError("unsupported project-review schema_version")
    expected_target = _target(expected_target_value)
    review_target = _target(result["target"])
    if review_target != expected_target:
        raise WorkflowError(
            "project-review target does not match the lead-owned expected target"
        )
    verdict = _enum(result["verdict"], {"PASS", "BLOCK", "INCOMPLETE"}, "project-review verdict")
    findings: list[dict[str, Any]] = []
    for index, raw in enumerate(_sequence(result["findings"], "project-review findings", 1000)):
        label = f"project-review findings[{index}]"
        finding = _object(
            raw,
            label,
            {
                "finding_id",
                "fingerprint",
                "disposition",
                "severity",
                "confidence",
                "category",
                "scope_relation",
                "blocking_basis",
                "title",
                "explanation",
                "impact",
                "evidence",
                "primary_location",
                "related_locations",
                "governing_rule",
                "safe_direction",
            },
        )
        source_id = _text(finding["finding_id"], f"{label}.finding_id", 256, single_line=True)
        source_fingerprint = _text(
            finding["fingerprint"], f"{label}.fingerprint", 64, single_line=True
        )
        if source_fingerprint is None or not HEX_DIGEST.fullmatch(source_fingerprint):
            raise WorkflowError(f"{label}.fingerprint is invalid")
        disposition = _enum(finding["disposition"], DISPOSITIONS - {"unknown"}, f"{label}.disposition")
        severity = _enum(finding["severity"], SEVERITIES - {"unknown"}, f"{label}.severity")
        confidence = _enum(finding["confidence"], CONFIDENCES - {"unknown"}, f"{label}.confidence")
        relation = _enum(
            finding["scope_relation"], SCOPE_RELATIONS - {"unknown"}, f"{label}.scope_relation"
        )
        primary = _location(finding["primary_location"], f"{label}.primary_location")
        evidence = [
            _evidence(evidence_item, f"{label}.evidence[{evidence_index}]")
            for evidence_index, evidence_item in enumerate(
                _sequence(finding["evidence"], f"{label}.evidence", 32, minimum=1)
            )
        ]
        related = [
            _location(location, f"{label}.related_locations[{location_index}]")
            for location_index, location in enumerate(
                _sequence(finding["related_locations"], f"{label}.related_locations", 32)
            )
        ]
        safe_direction = _text(finding["safe_direction"], f"{label}.safe_direction", 4000)
        actionability = "actionable"
        findings.append(
            {
                "source_id": source_id,
                "source_fingerprint": source_fingerprint,
                "disposition": disposition,
                "severity": severity,
                "confidence": confidence,
                "scope_relation": relation,
                "actionability": actionability,
                "title": _text(finding["title"], f"{label}.title", 300),
                "problem": _text(finding["explanation"], f"{label}.explanation", 8000),
                "impact": _text(finding["impact"], f"{label}.impact", 4000),
                "evidence": evidence,
                "primary_location": primary,
                "related_locations": related,
                "safe_direction": safe_direction,
                "field_provenance": {
                    "disposition": "explicit",
                    "severity": "explicit",
                    "confidence": "explicit",
                    "scope_relation": "explicit",
                    "actionability": "inferred",
                    "safe_direction": "explicit",
                },
                "normalization_confidence": "high",
                "normalization_notes": [
                    "Actionability was derived from the canonical finding's evidence, location, and safe direction.",
                ],
            }
        )
    limitations: list[dict[str, Any]] = []
    for index, raw in enumerate(_sequence(result["limitations"], "project-review limitations", 256)):
        limitation = _object(
            raw,
            f"project-review limitations[{index}]",
            {"code", "message", "affected_paths", "material"},
        )
        limitations.append(
            {
                "code": "source_limitation",
                "message": _text(
                    limitation["message"], f"project-review limitations[{index}].message", 4000
                ),
                "source_ids": [],
                "material": _boolean(
                    limitation["material"], f"project-review limitations[{index}].material"
                ),
            }
        )
    expected_verdict = (
        "BLOCK"
        if any(finding["disposition"] == "blocker" for finding in findings)
        else "INCOMPLETE"
        if any(limitation["material"] for limitation in limitations)
        else "PASS"
    )
    if verdict != expected_verdict:
        raise WorkflowError(
            f"project-review verdict is inconsistent with findings and limitations; expected {expected_verdict}"
        )
    if verdict == "INCOMPLETE":
        limitations.append(
            {
                "code": "source_incomplete",
                "message": "The project-review source did not complete.",
                "source_ids": [],
                "material": True,
            }
        )
    digest = output_sha256 or _project_review_digest(value)
    draft = {
        "normalization": {
            "confidence": "high",
            "notes": ["Converted from canonical project-review JSON without semantic reinterpretation."],
        },
        "findings": findings,
        "limitations": limitations,
    }
    envelope = {
        "target": expected_target,
        "source": {
            "reviewer": "project-review",
            "reviewer_version": result["schema_version"],
            "output_format": "project_review_json",
            "output_sha256": digest,
            "completed": verdict != "INCOMPLETE",
            "verdict": verdict,
            "outcome": (
                "pass"
                if verdict == "PASS"
                else "incomplete"
                if verdict == "INCOMPLETE"
                else "changes_requested"
            ),
        },
    }
    return finalize_batch(draft, envelope)


def _selection(value: Any) -> dict[str, str]:
    item = _object(value, "finding.selection", {"source_kind", "basis", "source"})
    return {
        "source_kind": _enum(item["source_kind"], {"default", "caller"}, "finding.selection.source_kind"),
        "basis": _enum(
            item["basis"],
            {"default_policy", "caller_explicit", "path_snapshot_request"},
            "finding.selection.basis",
        ),
        "source": _text(item["source"], "finding.selection.source", 1000) or "",
    }


def _finding_ref_from_batch(
    batch: dict[str, Any], context_value: Any
) -> dict[str, Any]:
    context = _object(context_value, "plan context", {"finding_id", "selection"})
    finding_id = _text(context["finding_id"], "plan context.finding_id", 16, single_line=True)
    if finding_id is None or not FINDING_ID.fullmatch(finding_id):
        raise WorkflowError("plan context.finding_id is invalid")
    matches = [item for item in batch["findings"] if item["finding_id"] == finding_id]
    if len(matches) != 1:
        raise WorkflowError("plan context.finding_id must identify exactly one batch finding")
    source = matches[0]
    selection = _selection(context["selection"])
    if selection["source_kind"] == "default" and selection["basis"] != "default_policy":
        raise WorkflowError("default selection requires basis default_policy")
    if selection["source_kind"] == "caller" and selection["basis"] == "default_policy":
        raise WorkflowError("caller selection cannot use basis default_policy")
    if selection["basis"] == "path_snapshot_request" and not (
        batch["target"]["kind"] == "paths"
        and source["disposition"] == "blocker"
        and source["scope_relation"] in {"unknown", "uncertain"}
        and source["actionability"] == "actionable"
    ):
        raise WorkflowError(
            "path_snapshot_request selection is limited to actionable unknown-relation path blockers"
        )
    return {
        "finding_id": source["finding_id"],
        "fingerprint": source["fingerprint"],
        "disposition": source["disposition"],
        "confidence": source["confidence"],
        "scope_relation": source["scope_relation"],
        "normalization_confidence": source["normalization_confidence"],
        "actionability": source["actionability"],
        "selection": selection,
    }


def _assessment(value: Any) -> dict[str, Any]:
    item = _object(
        value,
        "assessment",
        {
            "intent_status",
            "intent_source",
            "behavior_effect",
            "change_kind",
            "remedy_shape",
            "scope_size",
            "reversible",
            "validation",
            "plan_confidence",
            "risk_factors",
        },
    )
    risks = _unique_strings(item["risk_factors"], "assessment.risk_factors", 64, item_maximum=128)
    unknown = set(risks) - RISK_FACTORS
    if unknown:
        raise WorkflowError(f"assessment.risk_factors contains unknown values: {', '.join(sorted(unknown))}")
    return {
        "intent_status": _enum(item["intent_status"], INTENT_STATUSES, "assessment.intent_status"),
        "intent_source": _enum(item["intent_source"], INTENT_SOURCES, "assessment.intent_source"),
        "behavior_effect": _enum(
            item["behavior_effect"], BEHAVIOR_EFFECTS, "assessment.behavior_effect"
        ),
        "change_kind": _enum(item["change_kind"], CHANGE_KINDS, "assessment.change_kind"),
        "remedy_shape": _enum(item["remedy_shape"], REMEDY_SHAPES, "assessment.remedy_shape"),
        "scope_size": _enum(item["scope_size"], SCOPE_SIZES, "assessment.scope_size"),
        "reversible": _boolean(item["reversible"], "assessment.reversible"),
        "validation": _enum(item["validation"], VALIDATION_STATES, "assessment.validation"),
        "plan_confidence": _enum(
            item["plan_confidence"], LEVELS, "assessment.plan_confidence"
        ),
        "risk_factors": sorted(risks),
    }


def _proposal(value: Any) -> dict[str, Any]:
    item = _object(
        value,
        "proposal",
        {"summary", "rationale", "paths", "steps", "alternatives", "validation_steps"},
    )
    return {
        "summary": _text(item["summary"], "proposal.summary", 2000),
        "rationale": _text(item["rationale"], "proposal.rationale", 4000),
        "paths": _unique_strings(
            _sequence(item["paths"], "proposal.paths", 256, minimum=1),
            "proposal.paths",
            256,
            item_maximum=4096,
            paths=True,
        ),
        "steps": [
            _text(step, f"proposal.steps[{index}]", 2000) or ""
            for index, step in enumerate(_sequence(item["steps"], "proposal.steps", 128, minimum=1))
        ],
        "alternatives": [
            _text(alternative, f"proposal.alternatives[{index}]", 2000) or ""
            for index, alternative in enumerate(
                _sequence(item["alternatives"], "proposal.alternatives", 32)
            )
        ],
        "validation_steps": [
            _text(step, f"proposal.validation_steps[{index}]", 2000) or ""
            for index, step in enumerate(
                _sequence(item["validation_steps"], "proposal.validation_steps", 128, minimum=1)
            )
        ],
    }


def derive_decision(finding: dict[str, Any], assessment: dict[str, Any]) -> tuple[str, list[str]]:
    authorization = sorted(set(assessment["risk_factors"]) & AUTHORIZATION_RISKS)
    reasons: list[str] = []
    if finding["selection"]["source_kind"] == "default" and not (
        finding["disposition"] == "blocker"
        and finding["scope_relation"] in {"introduced", "worsened"}
    ):
        reasons.append("finding_not_default_eligible")
    if finding["actionability"] != "actionable":
        reasons.append("finding_not_actionable")
    if finding["normalization_confidence"] != "high":
        reasons.append("normalization_not_high_confidence")
    if finding["confidence"] != "high":
        reasons.append("reviewer_confidence_not_high")
    if assessment["intent_status"] != "explicit":
        reasons.append("intent_not_explicit")
    if assessment["intent_source"] == "none":
        reasons.append("intent_source_missing")
    if assessment["behavior_effect"] not in {"none", "restorative"}:
        reasons.append("behavior_not_predecided")
    if assessment["change_kind"] == "other":
        reasons.append("unsupported_change_kind")
    if assessment["remedy_shape"] != "singular":
        reasons.append("remedy_not_singular")
    if assessment["scope_size"] != "small":
        reasons.append("scope_not_small")
    if not assessment["reversible"]:
        reasons.append("not_reversible")
    if assessment["validation"] not in {"available", "static_sufficient"}:
        reasons.append("validation_not_sufficient")
    if assessment["change_kind"] in {"code", "configuration"} and assessment["validation"] != "available":
        reasons.append("code_validation_unavailable")
    if assessment["plan_confidence"] != "high":
        reasons.append("plan_not_high_confidence")
    for risk in assessment["risk_factors"]:
        reasons.append(f"risk:{risk}")
    reasons = list(dict.fromkeys(reasons))
    non_authorization_reasons = [
        reason
        for reason in reasons
        if reason not in {f"risk:{risk}" for risk in AUTHORIZATION_RISKS}
    ]
    if authorization and non_authorization_reasons:
        return "user_decision_required", reasons
    if authorization:
        return "authorization_required", reasons
    if reasons:
        return "user_decision_required", reasons
    return "auto", ["all_auto_conditions_satisfied"]


def finalize_plan(draft: Any, batch_value: Any, context_value: Any) -> dict[str, Any]:
    item = _object(draft, "plan draft", {"assessment", "proposal"})
    batch = validate_batch(batch_value)
    if batch["status"] != "complete":
        raise WorkflowError("a partial finding batch cannot enter fix planning")
    if batch["target"]["kind"] == "ref_range":
        raise WorkflowError(
            "ref-range batches are review-only; re-scope and re-review a working tree or path target"
        )
    finding = _finding_ref_from_batch(batch, context_value)
    assessment = _assessment(item["assessment"])
    proposal = _proposal(item["proposal"])
    outside_target = sorted(set(proposal["paths"]) - set(batch["target"]["requested_paths"]))
    if outside_target:
        raise WorkflowError(
            "proposal.paths require target expansion and re-review before planning: "
            + ", ".join(outside_target)
        )
    decision, reasons = derive_decision(finding, assessment)
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "batch_sha256": _canonical_digest(batch),
        "finding": finding,
        "assessment": assessment,
        "proposal": proposal,
        "decision": decision,
        "decision_reasons": reasons,
    }


def validate_plan(value: Any, batch_value: Any, context_value: Any) -> dict[str, Any]:
    item = _object(
        value,
        "plan",
        {
            "schema_version",
            "batch_sha256",
            "finding",
            "assessment",
            "proposal",
            "decision",
            "decision_reasons",
        },
    )
    if item["schema_version"] != PLAN_SCHEMA_VERSION:
        raise WorkflowError(f"schema_version must be {PLAN_SCHEMA_VERSION}")
    batch = validate_batch(batch_value)
    batch_digest = _text(item["batch_sha256"], "batch_sha256", 64, single_line=True)
    if batch_digest is None or not HEX_DIGEST.fullmatch(batch_digest):
        raise WorkflowError("batch_sha256 must be a lowercase SHA-256 digest")
    if batch_digest != _canonical_digest(batch):
        raise WorkflowError("batch_sha256 does not match the canonical batch")
    _enum(item["decision"], DECISIONS, "decision")
    _unique_strings(item["decision_reasons"], "decision_reasons", 128, item_maximum=200)
    expected = finalize_plan(
        {
            "assessment": copy.deepcopy(item["assessment"]),
            "proposal": copy.deepcopy(item["proposal"]),
        },
        batch,
        context_value,
    )
    if item != expected:
        raise WorkflowError("plan is not in canonical finalized form")
    return expected


def _reviewer_identity(value: Any, label: str) -> dict[str, str | None]:
    item = _object(value, label, {"reviewer", "reviewer_version"})
    return {
        "reviewer": _text(item["reviewer"], f"{label}.reviewer", 128, single_line=True),
        "reviewer_version": _text(
            item["reviewer_version"],
            f"{label}.reviewer_version",
            128,
            nullable=True,
            single_line=True,
        ),
    }


def _batch_set(value: Any, label: str) -> list[dict[str, Any]]:
    batches = [
        validate_batch(batch)
        for batch in _sequence(value, label, 32, minimum=1)
    ]
    return batches


def _identity_key(value: dict[str, Any]) -> tuple[str, str]:
    return (value["reviewer"], value["reviewer_version"] or "")


def _batch_identities(batches: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return sorted(_identity_key(batch["source"]) for batch in batches)


def _remaining_blockers(batches: list[dict[str, Any]]) -> list[str]:
    return sorted(
        finding["fingerprint"]
        for batch in batches
        for finding in batch["findings"]
        if finding["disposition"] == "blocker"
    )


def assess_round(value: Any) -> dict[str, Any]:
    item = _object(
        value,
        "round assessment",
        {"round", "expected_reviewers", "previous_batches", "current_batches"},
    )
    round_number = item["round"]
    if (
        not isinstance(round_number, int)
        or isinstance(round_number, bool)
        or not 1 <= round_number <= 3
    ):
        raise WorkflowError("round must be an integer from 1 through 3")
    expected = [
        _reviewer_identity(identity, f"expected_reviewers[{index}]")
        for index, identity in enumerate(
            _sequence(item["expected_reviewers"], "expected_reviewers", 32, minimum=1)
        )
    ]
    expected_keys = sorted(_identity_key(identity) for identity in expected)
    if len(expected_keys) != len(set(expected_keys)):
        raise WorkflowError("expected_reviewers must not contain duplicates")
    previous = _batch_set(item["previous_batches"], "previous_batches")
    current = _batch_set(item["current_batches"], "current_batches")
    previous_blockers = _remaining_blockers(previous)
    current_blockers = _remaining_blockers(current)

    action = "continue"
    reason = "actionable_blockers_remain"
    if _batch_identities(previous) != expected_keys or _batch_identities(current) != expected_keys:
        action, reason = "stop", "reviewer_set_drift"
    elif any(batch["target"] != previous[0]["target"] for batch in previous + current):
        action, reason = "stop", "target_drift"
    elif previous[0]["target"]["kind"] == "ref_range":
        action, reason = "stop", "ref_range_review_only"
    elif any(
        batch["status"] != "complete"
        or not batch["source"]["completed"]
        or batch["normalization"]["confidence"] != "high"
        or any(
            finding["disposition"] == "unknown"
            or finding["actionability"] == "needs_triage"
            for finding in batch["findings"]
        )
        for batch in current
    ):
        action, reason = "stop", "incomplete_review"
    elif not current_blockers:
        if all(batch["source"]["outcome"] == "pass" for batch in current):
            action, reason = "accept", "reviewer_pass"
        else:
            action, reason = "stop", "reviewer_not_passed"
    elif current_blockers == previous_blockers:
        action, reason = "stop", "no_material_progress"
    elif round_number == 3:
        action, reason = "stop", "maximum_rounds_reached"

    return {
        "round": round_number,
        "action": action,
        "reason": reason,
        "previous_blocker_fingerprints": previous_blockers,
        "current_blocker_fingerprints": current_blockers,
    }


def _run_context(value: Any) -> dict[str, Any]:
    item = _object(value, "run context", {"schema_version", "target", "reviewers"})
    if item["schema_version"] != RUN_SCHEMA_VERSION:
        raise WorkflowError(f"run context schema_version must be {RUN_SCHEMA_VERSION}")
    reviewers: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for index, raw in enumerate(
        _sequence(item["reviewers"], "run context.reviewers", 32, minimum=1)
    ):
        reviewer = _object(
            raw,
            f"run context.reviewers[{index}]",
            {"reviewer", "reviewer_version", "context_sha256", "context"},
        )
        identity = _reviewer_identity(
            {
                "reviewer": reviewer["reviewer"],
                "reviewer_version": reviewer["reviewer_version"],
            },
            f"run context.reviewers[{index}]",
        )
        key = _identity_key(identity)
        if key in identities:
            raise WorkflowError("run context reviewers must not contain duplicates")
        identities.add(key)
        digest = _text(
            reviewer["context_sha256"],
            f"run context.reviewers[{index}].context_sha256",
            64,
            single_line=True,
        )
        if digest is None or not HEX_DIGEST.fullmatch(digest):
            raise WorkflowError("run context reviewer context_sha256 is invalid")
        if not isinstance(reviewer["context"], dict):
            raise WorkflowError("run context reviewer context must be an object")
        if digest != _canonical_digest(reviewer["context"]):
            raise WorkflowError("run context reviewer context digest does not match")
        reviewers.append(
            {
                **identity,
                "context_sha256": digest,
                "context": reviewer["context"],
            }
        )
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "target": _target(item["target"], "run context.target"),
        "reviewers": reviewers,
    }


def _run_reviewer_summaries(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "reviewer": item["reviewer"],
            "reviewer_version": item["reviewer_version"],
            "context_sha256": item["context_sha256"],
        }
        for item in context["reviewers"]
    ]


def _run_rounds(
    value: Any, context: dict[str, Any]
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, int],
]:
    raw_rounds = _sequence(value, "run rounds", 4, minimum=1)
    rounds: list[dict[str, Any]] = []
    batches_by_digest: dict[str, dict[str, Any]] = {}
    batch_first_round: dict[str, int] = {}
    expected_reviewers = [
        {
            "reviewer": item["reviewer"],
            "reviewer_version": item["reviewer_version"],
        }
        for item in context["reviewers"]
    ]
    expected_keys = sorted(_identity_key(item) for item in expected_reviewers)
    previous_batches: list[dict[str, Any]] | None = None
    for index, raw_round in enumerate(raw_rounds):
        item = _object(raw_round, f"rounds[{index}]", {"round", "batches", "assessment"})
        round_number = item["round"]
        if not isinstance(round_number, int) or isinstance(round_number, bool) or round_number != index:
            raise WorkflowError("run rounds must be contiguous from round 0")
        batches = _batch_set(item["batches"], f"rounds[{index}].batches")
        if _batch_identities(batches) != expected_keys:
            raise WorkflowError(f"rounds[{index}] reviewer set does not match run context")
        if any(batch["target"] != context["target"] for batch in batches):
            raise WorkflowError(f"rounds[{index}] target does not match run context")
        for batch in batches:
            digest = _canonical_digest(batch)
            existing = batches_by_digest.get(digest)
            if existing is not None and existing != batch:
                raise WorkflowError("a run batch digest identifies different content")
            batches_by_digest[digest] = batch
            batch_first_round.setdefault(digest, index)
        if index == 0:
            if item["assessment"] is not None:
                raise WorkflowError("initial round assessment must be null")
            assessment = None
        else:
            if previous_batches is None:  # pragma: no cover - loop invariant
                raise WorkflowError("previous round is missing")
            expected_assessment = assess_round(
                {
                    "round": index,
                    "expected_reviewers": expected_reviewers,
                    "previous_batches": previous_batches,
                    "current_batches": batches,
                }
            )
            if item["assessment"] != expected_assessment:
                raise WorkflowError(f"rounds[{index}].assessment is not canonical")
            assessment = expected_assessment
            previous_assessment = rounds[-1]["assessment"]
            if previous_assessment is not None and previous_assessment["action"] != "continue":
                raise WorkflowError("a run cannot continue after an accepting or stopping round")
        rounds.append(
            {"round": round_number, "batches": batches, "assessment": assessment}
        )
        previous_batches = batches
    return rounds, batches_by_digest, batch_first_round


def _run_plans(
    value: Any, batches_by_digest: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for index, raw in enumerate(_sequence(value, "run plans", 128)):
        item = _object(raw, f"plans[{index}]", {"context", "plan", "applied"})
        if not isinstance(item["plan"], dict):
            raise WorkflowError(f"plans[{index}].plan must be an object")
        digest = item["plan"].get("batch_sha256")
        if not isinstance(digest, str) or digest not in batches_by_digest:
            raise WorkflowError(f"plans[{index}] does not identify a run batch")
        plan = validate_plan(item["plan"], batches_by_digest[digest], item["context"])
        applied = _boolean(item["applied"], f"plans[{index}].applied")
        if applied and plan["decision"] != "auto":
            raise WorkflowError("only an auto plan may be recorded as applied")
        identity = (plan["batch_sha256"], plan["finding"]["fingerprint"])
        if identity in identities:
            raise WorkflowError("run plans must not repeat a finding from the same batch")
        identities.add(identity)
        plans.append({"context": item["context"], "plan": plan, "applied": applied})
    return plans


def _run_changes(value: Any, target: dict[str, Any]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    seen: set[str] = set()
    allowed = set(target["requested_paths"])
    for index, raw in enumerate(_sequence(value, "run changes", 5000)):
        item = _object(raw, f"changes[{index}]", {"path", "before_sha256", "after_sha256"})
        path = _repo_path(item["path"], f"changes[{index}].path")
        if path not in allowed:
            raise WorkflowError(f"changes[{index}].path must be an exact reviewed target path")
        if path in seen:
            raise WorkflowError("run changes must not repeat a path")
        seen.add(path)
        digests: list[str] = []
        for key in ("before_sha256", "after_sha256"):
            digest = _text(item[key], f"changes[{index}].{key}", 64, single_line=True)
            if digest is None or not HEX_DIGEST.fullmatch(digest):
                raise WorkflowError(f"changes[{index}].{key} is invalid")
            digests.append(digest)
        if digests[0] == digests[1]:
            raise WorkflowError("a run change must alter file content")
        changes.append(
            {"path": path, "before_sha256": digests[0], "after_sha256": digests[1]}
        )
    return sorted(changes, key=lambda item: item["path"])


def _run_validation(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, raw in enumerate(_sequence(value, "run validation", 128)):
        item = _object(
            raw,
            f"validation[{index}]",
            {"method", "description", "status", "command", "authorization_source"},
        )
        method = _enum(item["method"], {"static", "command"}, f"validation[{index}].method")
        command = _text(
            item["command"],
            f"validation[{index}].command",
            4000,
            nullable=True,
            single_line=True,
        )
        authority = _enum(
            item["authorization_source"],
            {"caller", "user_global", "not_required", None},
            f"validation[{index}].authorization_source",
        )
        if method == "static" and (command is not None or authority != "not_required"):
            raise WorkflowError("static validation must have no command and use not_required authority")
        if method == "command" and command is None:
            raise WorkflowError("command validation requires a bounded command summary")
        records.append(
            {
                "method": method,
                "description": _text(item["description"], f"validation[{index}].description", 2000),
                "status": _enum(
                    item["status"], {"passed", "failed", "not_run"}, f"validation[{index}].status"
                ),
                "command": command,
                "authorization_source": authority,
            }
        )
    return records


def _derive_run_outcome(
    rounds: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    changes: list[dict[str, str]],
    validation: list[dict[str, Any]],
) -> tuple[str, str]:
    changed_paths = {item["path"] for item in changes}
    applied_paths = {
        path
        for item in plans
        if item["applied"]
        for path in item["plan"]["proposal"]["paths"]
    }
    if changed_paths != applied_paths:
        raise WorkflowError("run changes must exactly match the paths of applied auto plans")
    if changes and (not validation or any(item["status"] != "passed" for item in validation)):
        return "incomplete", "validation_failed"

    final_assessment = rounds[-1]["assessment"]
    if final_assessment is not None:
        if final_assessment["action"] == "accept":
            if _remaining_blockers(rounds[0]["batches"]) and not changes:
                raise WorkflowError("a fixed blocker cannot be accepted without a recorded change")
            return "completed", "reviewer_pass"
        if final_assessment["action"] == "stop":
            mapping = {
                "incomplete_review": ("incomplete", "reviewer_incomplete"),
                "reviewer_not_passed": ("stopped", "reviewer_not_passed"),
                "reviewer_set_drift": ("incomplete", "reviewer_set_drift"),
                "target_drift": ("incomplete", "target_drift"),
                "ref_range_review_only": ("incomplete", "ref_range_review_only"),
                "no_material_progress": ("stopped", "no_material_progress"),
                "maximum_rounds_reached": ("stopped", "maximum_rounds_reached"),
            }
            if final_assessment["reason"] not in mapping:
                raise WorkflowError("run round has an unsupported stop reason")
            return mapping[final_assessment["reason"]]

    un_applied = [item["plan"] for item in plans if not item["applied"]]
    if any(plan["decision"] == "authorization_required" for plan in un_applied):
        return "authorization_required", "authorization_required"
    if any(plan["decision"] == "user_decision_required" for plan in un_applied):
        return "decision_required", "user_decision_required"

    initial = rounds[0]["batches"]
    if any(
        batch["status"] != "complete"
        or not batch["source"]["completed"]
        or batch["normalization"]["confidence"] != "high"
        for batch in initial
    ):
        return "incomplete", "reviewer_incomplete"
    if not _remaining_blockers(initial) and all(
        batch["source"]["outcome"] == "pass" for batch in initial
    ):
        if changes:
            raise WorkflowError("a passing initial review cannot claim applied changes")
        return "completed", "reviewer_pass"
    return "incomplete", "workflow_incomplete"


def finalize_run(draft: Any, context_value: Any) -> dict[str, Any]:
    _assert_bounded_json(draft, "run draft")
    _assert_bounded_json(context_value, "run context")
    item = _object(draft, "run draft", {"rounds", "plans", "changes", "validation", "summary"})
    context = _run_context(context_value)
    rounds, batches_by_digest, batch_first_round = _run_rounds(item["rounds"], context)
    plans = _run_plans(item["plans"], batches_by_digest)
    changes = _run_changes(item["changes"], context["target"])
    validation = _run_validation(item["validation"])
    status, stop_reason = _derive_run_outcome(rounds, plans, changes, validation)
    if status == "completed" and rounds[-1]["assessment"] is not None:
        final_round = rounds[-1]["round"]
        for plan_record in plans:
            if (
                plan_record["applied"]
                and batch_first_round[plan_record["plan"]["batch_sha256"]] >= final_round
            ):
                raise WorkflowError(
                    "an accepted applied plan must be followed by a fresh review round"
                )
    summary = _object(item["summary"], "summary", {"conclusion"})
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "context_sha256": _canonical_digest(context),
        "target": context["target"],
        "reviewers": _run_reviewer_summaries(context),
        "rounds": rounds,
        "plans": plans,
        "changes": changes,
        "validation": validation,
        "status": status,
        "stop_reason": stop_reason,
        "summary": {"conclusion": _text(summary["conclusion"], "summary.conclusion", 2000)},
    }


def validate_run(value: Any, context_value: Any) -> dict[str, Any]:
    _assert_bounded_json(value, "run result")
    _assert_bounded_json(context_value, "run context")
    item = _object(
        value,
        "run result",
        {
            "schema_version",
            "context_sha256",
            "target",
            "reviewers",
            "rounds",
            "plans",
            "changes",
            "validation",
            "status",
            "stop_reason",
            "summary",
        },
    )
    if item["schema_version"] != RUN_SCHEMA_VERSION:
        raise WorkflowError(f"run result schema_version must be {RUN_SCHEMA_VERSION}")
    _enum(item["status"], RUN_STATUSES, "run result.status")
    _enum(item["stop_reason"], RUN_STOP_REASONS, "run result.stop_reason")
    expected = finalize_run(
        {
            "rounds": copy.deepcopy(item["rounds"]),
            "plans": copy.deepcopy(item["plans"]),
            "changes": copy.deepcopy(item["changes"]),
            "validation": copy.deepcopy(item["validation"]),
            "summary": copy.deepcopy(item["summary"]),
        },
        context_value,
    )
    if item != expected:
        raise WorkflowError("run result is not in canonical finalized form")
    return expected


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkflowError(f"input JSON contains duplicate object member: {key}")
        result[key] = value
    return result


def _read_regular_bytes(path: Path) -> bytes:
    if _has_symlink_component(path):
        raise WorkflowError("input path must not contain symlinks or reparse points")
    try:
        before = path.lstat()
    except OSError as exc:
        raise WorkflowError(f"cannot inspect input: {exc}") from exc
    if _is_link_like(before) or not stat.S_ISREG(before.st_mode):
        raise WorkflowError("input path must identify a regular file")
    if before.st_size > MAX_JSON_BYTES:
        raise WorkflowError(f"input JSON exceeds the {MAX_JSON_BYTES}-byte limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            after = os.fstat(handle.fileno())
            if _is_link_like(after) or not stat.S_ISREG(after.st_mode):
                raise WorkflowError("input path must identify a regular file")
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise WorkflowError("input path changed while it was being opened")
            data = handle.read(MAX_JSON_BYTES + 1)
            if len(data) > MAX_JSON_BYTES:
                raise WorkflowError(
                    f"input JSON exceeds the {MAX_JSON_BYTES}-byte limit"
                )
            return data
    except WorkflowError:
        raise
    except OSError as exc:
        raise WorkflowError(f"cannot read input: {exc}") from exc


def _read_json(path_value: str) -> tuple[Any, bytes]:
    try:
        if path_value == "-":
            raw = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
            if len(raw) > MAX_JSON_BYTES:
                raise WorkflowError(
                    f"input JSON exceeds the {MAX_JSON_BYTES}-byte limit"
                )
        else:
            raw = _read_regular_bytes(Path(path_value))
    except WorkflowError:
        raise
    except OSError as exc:
        raise WorkflowError(f"cannot read input: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_object)
        _assert_bounded_json(value, "input JSON")
        return value, raw
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise WorkflowError(f"input is not valid UTF-8 JSON: {exc}") from exc


def _is_link_like(metadata: os.stat_result) -> bool:
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return True
        if _is_link_like(metadata):
            return True
    return False


def _emit(value: Any, output: str | None, replace: bool) -> None:
    rendered = _bounded_json_bytes(value, "output JSON", compact=False).decode("utf-8")
    if output is None:
        sys.stdout.write(rendered)
        return
    path = Path(output)
    if _has_symlink_component(path):
        raise WorkflowError("output path must not contain symlinks")
    if not path.parent.is_dir():
        raise WorkflowError("output parent directory does not exist")
    if replace and path.exists():
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise WorkflowError(f"cannot inspect existing output: {exc}") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise WorkflowError("refusing to replace an output that is not a regular file")
        if metadata.st_nlink > 1:
            raise WorkflowError("refusing to replace an output with multiple hard links")
    if path.exists() and not replace:
        raise WorkflowError("output already exists; pass --replace only with explicit replacement intent")
    if replace:
        temporary: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(rendered)
            os.replace(temporary, path)
            temporary = None
        except OSError as exc:
            raise WorkflowError(f"cannot replace output: {exc}") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        return
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
    except OSError as exc:
        raise WorkflowError(f"cannot write output: {exc}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "from-project-review",
        "finalize-batch",
        "validate-batch",
        "finalize-plan",
        "validate-plan",
        "assess-round",
        "finalize-run",
        "validate-run",
    ):
        command = subparsers.add_parser(name)
        command.add_argument("--input", required=True, help="UTF-8 JSON input path or - for stdin")
        if name == "finalize-batch":
            command.add_argument(
                "--envelope",
                required=True,
                help="lead-owned target/source envelope JSON path",
            )
        if name == "from-project-review":
            command.add_argument(
                "--target",
                required=True,
                help="lead-owned expected target JSON path",
            )
        if name in {"finalize-plan", "validate-plan"}:
            command.add_argument(
                "--batch",
                required=True,
                help="canonical finding-batch JSON path",
            )
            command.add_argument(
                "--context",
                required=True,
                help="lead-owned finding selection context JSON path",
            )
        if name in {"finalize-run", "validate-run"}:
            command.add_argument(
                "--context",
                required=True,
                help="lead-owned review-and-fix run context JSON path",
            )
        command.add_argument("--output", help="explicit JSON output path; stdout when omitted")
        command.add_argument(
            "--replace",
            action="store_true",
            help="replace an existing explicit output path",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.replace and args.output is None:
            raise WorkflowError("--replace requires --output")
        value, raw = _read_json(args.input)
        if args.command == "from-project-review":
            expected_target, _ = _read_json(args.target)
            result = convert_project_review(
                value, expected_target, hashlib.sha256(raw).hexdigest()
            )
        elif args.command == "finalize-batch":
            envelope, _ = _read_json(args.envelope)
            result = finalize_batch(value, envelope)
        elif args.command == "validate-batch":
            result = validate_batch(value)
        elif args.command == "finalize-plan":
            batch, _ = _read_json(args.batch)
            context, _ = _read_json(args.context)
            result = finalize_plan(value, batch, context)
        elif args.command == "validate-plan":
            batch, _ = _read_json(args.batch)
            context, _ = _read_json(args.context)
            result = validate_plan(value, batch, context)
        elif args.command == "assess-round":
            result = assess_round(value)
        elif args.command == "finalize-run":
            context, _ = _read_json(args.context)
            result = finalize_run(value, context)
        elif args.command == "validate-run":
            context, _ = _read_json(args.context)
            result = validate_run(value, context)
        else:  # pragma: no cover - argparse owns this boundary
            raise WorkflowError(f"unknown command: {args.command}")
        _emit(result, args.output, args.replace)
    except WorkflowError as exc:
        print(f"review-workflow: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
