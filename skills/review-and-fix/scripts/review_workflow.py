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
HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
FINDING_ID = re.compile(r"^RF[0-9]{3,6}$")

TARGET_KINDS = {"ref_range", "working_tree", "paths"}
WORKING_TREE_MODES = {"staged", "unstaged", "combined", None}
OUTPUT_FORMATS = {"project_review_json", "neutral_json", "structured", "prose"}
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
    if value not in allowed:
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
        {"reviewer", "reviewer_version", "output_format", "output_sha256", "completed", "verdict"},
    )
    digest = _text(item["output_sha256"], "source.output_sha256", 64, single_line=True)
    if digest is None or not HEX_DIGEST.fullmatch(digest):
        raise WorkflowError("source.output_sha256 must be a lowercase SHA-256 digest")
    return {
        "reviewer": _text(item["reviewer"], "source.reviewer", 128, single_line=True),
        "reviewer_version": _text(
            item["reviewer_version"], "source.reviewer_version", 128, nullable=True, single_line=True
        ),
        "output_format": _enum(item["output_format"], OUTPUT_FORMATS, "source.output_format"),
        "output_sha256": digest,
        "completed": _boolean(item["completed"], "source.completed"),
        "verdict": _text(item["verdict"], "source.verdict", 128, nullable=True, single_line=True),
    }


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
    if not source["completed"] and not any(
        limitation["code"] == "source_incomplete" and limitation["material"]
        for limitation in limitations
    ):
        raise WorkflowError("an incomplete source requires a material source_incomplete limitation")
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
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def convert_project_review(value: Any, output_sha256: str | None = None) -> dict[str, Any]:
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
        "target": copy.deepcopy(result["target"]),
        "source": {
            "reviewer": "project-review",
            "reviewer_version": result["schema_version"],
            "output_format": "project_review_json",
            "output_sha256": digest,
            "completed": True,
            "verdict": verdict,
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
    elif any(
        batch["status"] != "complete"
        or not batch["source"]["completed"]
        or any(
            finding["disposition"] == "unknown"
            or finding["actionability"] == "needs_triage"
            for finding in batch["findings"]
        )
        for batch in current
    ):
        action, reason = "stop", "incomplete_review"
    elif not current_blockers:
        action, reason = "accept", "reviewer_pass"
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


def _read_json(path_value: str) -> tuple[Any, bytes]:
    try:
        if path_value == "-":
            raw = sys.stdin.buffer.read()
        else:
            raw = Path(path_value).read_bytes()
    except OSError as exc:
        raise WorkflowError(f"cannot read input: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8")), raw
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
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
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
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
    ):
        command = subparsers.add_parser(name)
        command.add_argument("--input", required=True, help="UTF-8 JSON input path or - for stdin")
        if name == "finalize-batch":
            command.add_argument(
                "--envelope",
                required=True,
                help="lead-owned target/source envelope JSON path",
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
            result = convert_project_review(value, hashlib.sha256(raw).hexdigest())
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
        else:  # pragma: no cover - argparse owns this boundary
            raise WorkflowError(f"unknown command: {args.command}")
        _emit(result, args.output, args.replace)
    except WorkflowError as exc:
        print(f"review-workflow: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
