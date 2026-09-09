#!/usr/bin/env python3
"""Freeze selected session evidence and finalize eval candidate recommendations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import path_safety


VERSION = "1.0.0"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 16 * 1024 * 1024
MAX_SESSIONS = 256
MAX_EVIDENCE = 4096
MAX_SUMMARY_BYTES = 1024 * 1024
MAX_REPOSITORY_ENTRIES = 40_000
MAX_REPOSITORY_FILES = 20_000
MAX_REPOSITORY_BYTES = 64 * 1024 * 1024
ID_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}={0,2}\b", re.IGNORECASE),
    re.compile(r"\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{6,}", re.IGNORECASE),
)


class AuditError(ValueError):
    """Raised for malformed or unsafe candidate-audit input."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise AuditError(f"duplicate JSON member: {key}")
        value[key] = item
    return value


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path, label: str, maximum: int = MAX_JSON_BYTES) -> tuple[Any, bytes]:
    try:
        _, raw = path_safety.read_regular(path, maximum, require_single_link=True)
        text, canonical_raw = path_safety.canonical_text(raw, label)
        value = json.loads(text, object_pairs_hook=_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError, path_safety.SafetyError) as exc:
        raise AuditError(f"cannot read {label}: {exc}") from exc
    return value, canonical_raw


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuditError(f"{label} must be an object")
    return value


def _array(value: Any, label: str, *, minimum: int = 0, maximum: int) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise AuditError(f"{label} must be an array with {minimum}..{maximum} items")
    return value


def _exact(value: dict[str, Any], label: str, keys: tuple[str, ...]) -> None:
    if set(value) != set(keys):
        raise AuditError(f"{label} must contain exactly: {', '.join(keys)}")


def _text(value: Any, label: str, *, maximum: int, secret_check: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise AuditError(f"{label} must be non-empty text up to {maximum} characters")
    if any(unicodedata.category(char) in {"Cc", "Cs"} and char not in "\n\t" for char in value):
        raise AuditError(f"{label} contains unsupported control characters")
    if secret_check and any(pattern.search(value) for pattern in SECRET_PATTERNS):
        raise AuditError(f"{label} contains secret-like content")
    return value


def _enum(value: Any, label: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise AuditError(f"{label} must be one of: {', '.join(sorted(allowed))}")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
        raise AuditError(f"{label} must be a canonical identifier")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise AuditError(f"{label} must be a lowercase SHA-256")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise AuditError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise AuditError(f"{label} must be a boolean")
    return value


def _limitation(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label)
    _exact(item, label, ("code", "message", "material"))
    _identifier(item["code"], f"{label}.code")
    _text(item["message"], f"{label}.message", maximum=2000)
    _bool(item["material"], f"{label}.material")
    return item


def _validate_source(value: Any) -> dict[str, Any]:
    source = _object(value, "source")
    _exact(source, "source", ("schema_version", "selection", "sessions"))
    if source["schema_version"] != "eval-candidate-source/v1":
        raise AuditError("unsupported source schema_version")
    selection = _object(source["selection"], "source.selection")
    _exact(selection, "source.selection", ("kind", "source"))
    _enum(selection["kind"], "source.selection.kind", {"caller", "project_opt_in"})
    _text(selection["source"], "source.selection.source", maximum=500, secret_check=True)
    sessions = _array(source["sessions"], "source.sessions", minimum=1, maximum=MAX_SESSIONS)
    seen_sessions: set[str] = set()
    seen_evidence: set[str] = set()
    evidence_total = 0
    summary_total = 0
    for index, raw_session in enumerate(sessions):
        label = f"source.sessions[{index}]"
        session = _object(raw_session, label)
        _exact(session, label, ("session_sha256", "independence_sha256", "eligible", "sanitized", "evidence"))
        session_sha = _sha(session["session_sha256"], f"{label}.session_sha256")
        _sha(session["independence_sha256"], f"{label}.independence_sha256")
        if session_sha in seen_sessions:
            raise AuditError("source contains a duplicate session")
        seen_sessions.add(session_sha)
        if session["eligible"] is not True or session["sanitized"] is not True:
            raise AuditError(f"{label} must be explicitly eligible and sanitized")
        evidence = _array(session["evidence"], f"{label}.evidence", minimum=1, maximum=256)
        evidence_total += len(evidence)
        if evidence_total > MAX_EVIDENCE:
            raise AuditError(f"source exceeds the {MAX_EVIDENCE}-evidence limit")
        for evidence_index, raw_evidence in enumerate(evidence):
            evidence_label = f"{label}.evidence[{evidence_index}]"
            item = _object(raw_evidence, evidence_label)
            _exact(item, evidence_label, ("evidence_id", "kind", "sha256", "summary", "redacted", "relevant"))
            evidence_id = _identifier(item["evidence_id"], f"{evidence_label}.evidence_id")
            if evidence_id in seen_evidence:
                raise AuditError(f"duplicate evidence_id: {evidence_id}")
            seen_evidence.add(evidence_id)
            _enum(item["kind"], f"{evidence_label}.kind", {"user_request", "agent_action", "review_finding", "verification", "friction"})
            _sha(item["sha256"], f"{evidence_label}.sha256")
            summary = _text(item["summary"], f"{evidence_label}.summary", maximum=1000, secret_check=True)
            summary_total += len(summary.encode("utf-8"))
            if item["redacted"] is not True or item["relevant"] is not True:
                raise AuditError(f"{evidence_label} must be explicitly redacted and relevant")
    if summary_total > MAX_SUMMARY_BYTES:
        raise AuditError(f"source summaries exceed the {MAX_SUMMARY_BYTES}-byte limit")
    return source


def _validate_suite(value: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    suite = _object(value, "suite")
    if suite.get("schema_version") != "project-eval-suite/v1":
        raise AuditError("suite must use project-eval-suite/v1")
    cases = _array(suite.get("cases"), "suite.cases", maximum=2000)
    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_case in enumerate(cases):
        case = _object(raw_case, f"suite.cases[{index}]")
        case_id = _identifier(case.get("case_id"), f"suite.cases[{index}].case_id")
        if case_id in seen:
            raise AuditError(f"duplicate suite case_id: {case_id}")
        seen.add(case_id)
        kind = _enum(case.get("kind"), f"suite.cases[{index}].kind", {"explanation", "implementation", "trajectory"})
        phase = case.get("phase")
        if phase is not None:
            _enum(phase, f"suite.cases[{index}].phase", {"intake", "clarification", "specification", "planning", "implementation", "verification", "reporting"})
        task = _text(case.get("task"), f"suite.cases[{index}].task", maximum=2000)
        importance = _enum(case.get("importance"), f"suite.cases[{index}].importance", {"required", "important", "standard", "exploratory"})
        summaries.append({"case_id": case_id, "kind": kind, "phase": phase, "task_summary": task, "importance": importance})
    return suite, summaries


def _evidence_kind(kind: str) -> str:
    return {
        "user_request": "session_summary",
        "agent_action": "session_summary",
        "review_finding": "assertion",
        "verification": "measurement",
        "friction": "session_summary",
    }[kind]


def _source_sessions(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "session_sha256": session["session_sha256"],
            "independence_sha256": session["independence_sha256"],
            "evidence": [
                {
                    "evidence_id": evidence["evidence_id"],
                    "kind": _evidence_kind(evidence["kind"]),
                    "sha256": evidence["sha256"],
                    "summary": evidence["summary"][:500],
                    "redacted": True,
                }
                for evidence in session["evidence"]
            ],
        }
        for session in source["sessions"]
    ]


def _relative_existing_path(path: Path, root: Path) -> str:
    """Resolve an existing path beneath a physical root across Windows aliases."""
    absolute = path.absolute()
    boundary = root.absolute()
    for ancestor in (absolute, *absolute.parents):
        try:
            matches = os.path.samefile(ancestor, boundary)
        except OSError:
            matches = False
        if matches:
            return path_safety.canonical_path(absolute.relative_to(ancestor).as_posix())
    raise AuditError(f"path stays outside the selected root: {path}")


def _repository_digest(root: Path, excluded: set[Path]) -> str:
    try:
        excluded_identities = {
            path_safety.filesystem_alias_identity(path) for path in excluded
        }
    except (OSError, path_safety.SafetyError) as exc:
        raise AuditError(f"cannot bind excluded repository input: {exc}") from exc
    ignored_roots = {".git", ".eval-results", "dist", "__pycache__"}
    pending = [root]
    records: list[dict[str, Any]] = []
    traversed_entries = 0
    files = 0
    total_bytes = 0
    while pending:
        directory = pending.pop()
        remaining = MAX_REPOSITORY_ENTRIES - traversed_entries
        if remaining <= 0:
            raise AuditError(
                f"repository exceeds the {MAX_REPOSITORY_ENTRIES}-entry traversal limit"
            )
        entries, _, complete = path_safety.bound_directory_entries(directory, remaining)
        if not complete:
            raise AuditError(
                f"repository exceeds the {MAX_REPOSITORY_ENTRIES}-entry traversal limit"
            )
        for entry in entries:
            traversed_entries += 1
            if directory == root and entry.name in ignored_roots:
                continue
            if entry.identity in excluded_identities:
                continue
            try:
                relative = _relative_existing_path(entry.path, root)
            except AuditError as exc:
                raise AuditError(f"repository entry escaped the selected root: {exc}") from exc
            if entry.link_like:
                raise AuditError(f"repository snapshot contains a link-like entry: {relative}")
            if entry.is_directory:
                pending.append(entry.path)
                continue
            if not entry.is_regular:
                raise AuditError(f"repository snapshot contains an unsupported entry: {relative}")
            files += 1
            if files > MAX_REPOSITORY_FILES:
                raise AuditError(f"repository exceeds the {MAX_REPOSITORY_FILES}-file limit")
            remaining_bytes = MAX_REPOSITORY_BYTES - total_bytes
            if remaining_bytes < 0:
                raise AuditError(f"repository exceeds the {MAX_REPOSITORY_BYTES}-byte limit")
            metadata, raw = path_safety.read_regular(
                entry.path, remaining_bytes, require_single_link=True
            )
            total_bytes += len(raw)
            records.append(
                {
                    "path": relative,
                    "bytes": len(raw),
                    "executable": bool(metadata.st_mode & 0o111),
                    "sha256": _sha_bytes(raw),
                }
            )
    records.sort(key=lambda item: item["path"])
    return _sha_bytes(_canonical_bytes({"files": records}))


def _stable_repository_digest(root: Path, excluded: set[Path]) -> str:
    first = _repository_digest(root, excluded)
    second = _repository_digest(root, excluded)
    if first != second:
        raise AuditError("repository changed during context resolution")
    return first


def _context_without_digest(context: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in context.items() if key != "context_sha256"}


def validate_context(value: Any, *, current: bool = False) -> dict[str, Any]:
    context = _object(value, "context")
    _exact(context, "context", ("schema_version", "repository_root", "source", "source_digest", "target", "sessions", "existing_cases", "limits", "limitations", "context_sha256"))
    if context["schema_version"] != "eval-candidate-context/v1":
        raise AuditError("unsupported context schema_version")
    _text(context["repository_root"], "context.repository_root", maximum=4096)
    source_meta = _object(context["source"], "context.source")
    _exact(source_meta, "context.source", ("path", "selection_kind", "selection_source", "sha256"))
    _text(source_meta["path"], "context.source.path", maximum=4096)
    _enum(source_meta["selection_kind"], "context.source.selection_kind", {"caller", "project_opt_in"})
    _text(source_meta["selection_source"], "context.source.selection_source", maximum=500, secret_check=True)
    _sha(source_meta["sha256"], "context.source.sha256")
    _sha(context["source_digest"], "context.source_digest")
    target = _object(context["target"], "context.target")
    _exact(target, "context.target", ("repository_sha256", "suite_sha256", "suite_path"))
    _sha(target["repository_sha256"], "context.target.repository_sha256")
    if target["suite_sha256"] is not None:
        _sha(target["suite_sha256"], "context.target.suite_sha256")
    if target["suite_path"] is not None:
        _text(target["suite_path"], "context.target.suite_path", maximum=4096)
    sessions = _array(context["sessions"], "context.sessions", minimum=1, maximum=MAX_SESSIONS)
    evidence_ids: set[str] = set()
    session_ids: set[str] = set()
    evidence_total = 0
    summary_total = 0
    for index, raw_session in enumerate(sessions):
        label = f"context.sessions[{index}]"
        session = _object(raw_session, label)
        _exact(session, label, ("session_sha256", "independence_sha256", "evidence"))
        session_id = _sha(session["session_sha256"], f"{label}.session_sha256")
        if session_id in session_ids:
            raise AuditError("context contains a duplicate session")
        session_ids.add(session_id)
        _sha(session["independence_sha256"], f"{label}.independence_sha256")
        session_evidence = _array(session["evidence"], f"{label}.evidence", minimum=1, maximum=256)
        evidence_total += len(session_evidence)
        if evidence_total > MAX_EVIDENCE:
            raise AuditError(f"context exceeds the {MAX_EVIDENCE}-evidence limit")
        for evidence_index, raw_evidence in enumerate(session_evidence):
            evidence_label = f"{label}.evidence[{evidence_index}]"
            evidence = _object(raw_evidence, evidence_label)
            _exact(evidence, evidence_label, ("evidence_id", "kind", "sha256", "summary", "redacted"))
            evidence_id = _identifier(evidence["evidence_id"], f"{evidence_label}.evidence_id")
            if evidence_id in evidence_ids:
                raise AuditError(f"duplicate context evidence_id: {evidence_id}")
            evidence_ids.add(evidence_id)
            _enum(evidence["kind"], f"{evidence_label}.kind", {"session_summary", "run_receipt", "assertion", "measurement", "repository"})
            _sha(evidence["sha256"], f"{evidence_label}.sha256")
            summary = _text(evidence["summary"], f"{evidence_label}.summary", maximum=500, secret_check=True)
            summary_total += len(summary.encode("utf-8"))
            if evidence["redacted"] is not True:
                raise AuditError(f"{evidence_label}.redacted must be true")
    if summary_total > MAX_SUMMARY_BYTES:
        raise AuditError(f"context summaries exceed the {MAX_SUMMARY_BYTES}-byte limit")
    case_ids: set[str] = set()
    for index, raw_case in enumerate(_array(context["existing_cases"], "context.existing_cases", maximum=2000)):
        label = f"context.existing_cases[{index}]"
        case = _object(raw_case, label)
        _exact(case, label, ("case_id", "kind", "phase", "task_summary", "importance"))
        case_id = _identifier(case["case_id"], f"{label}.case_id")
        if case_id in case_ids:
            raise AuditError(f"duplicate context case_id: {case_id}")
        case_ids.add(case_id)
        _enum(case["kind"], f"{label}.kind", {"explanation", "implementation", "trajectory"})
        if case["phase"] is not None:
            _enum(case["phase"], f"{label}.phase", {"intake", "clarification", "specification", "planning", "implementation", "verification", "reporting"})
        _text(case["task_summary"], f"{label}.task_summary", maximum=2000)
        _enum(case["importance"], f"{label}.importance", {"required", "important", "standard", "exploratory"})
    limits = _object(context["limits"], "context.limits")
    expected_limits = {"max_source_bytes": MAX_JSON_BYTES, "max_sessions": MAX_SESSIONS, "max_evidence": MAX_EVIDENCE, "max_summary_bytes": MAX_SUMMARY_BYTES, "max_repository_entries": MAX_REPOSITORY_ENTRIES, "max_repository_files": MAX_REPOSITORY_FILES, "max_repository_bytes": MAX_REPOSITORY_BYTES}
    if limits != expected_limits:
        raise AuditError("context.limits do not match the locked v1 limits")
    for index, limitation in enumerate(_array(context["limitations"], "context.limitations", maximum=2000)):
        _limitation(limitation, f"context.limitations[{index}]")
    expected_digest = _sha_bytes(_canonical_bytes(_context_without_digest(context)))
    if _sha(context["context_sha256"], "context.context_sha256") != expected_digest:
        raise AuditError("context_sha256 does not match canonical context")
    if current:
        source_value, source_raw = _read_json(Path(source_meta["path"]), "selected source")
        source = _validate_source(source_value)
        if _sha_bytes(source_raw) != source_meta["sha256"] or _sha_bytes(_canonical_bytes(source)) != context["source_digest"]:
            raise AuditError("selected source changed after context resolution")
        if source["selection"] != {"kind": source_meta["selection_kind"], "source": source_meta["selection_source"]}:
            raise AuditError("selected source authority changed")
        if _source_sessions(source) != context["sessions"]:
            raise AuditError("candidate context evidence differs from the selected source")
        suite_path = target["suite_path"]
        if suite_path is not None:
            suite_value, suite_raw = _read_json(Path(suite_path), "project eval suite")
            _, cases = _validate_suite(suite_value)
            if _sha_bytes(suite_raw) != target["suite_sha256"] or cases != context["existing_cases"]:
                raise AuditError("project eval suite changed after context resolution")
        root = Path(context["repository_root"])
        excluded = {Path(source_meta["path"])}
        if suite_path is not None:
            excluded.add(Path(suite_path))
        if _stable_repository_digest(root, excluded) != target["repository_sha256"]:
            raise AuditError("repository changed after context resolution")
    return context


def resolve_context(repo: Path, source_path: Path, suite_path: Path | None) -> dict[str, Any]:
    try:
        original_repo = repo.absolute()
        path_safety.assert_no_link_components(original_repo, include_final=True)
        repository_root = original_repo.resolve(strict=True)
    except (OSError, path_safety.SafetyError) as exc:
        raise AuditError(f"cannot resolve repository root: {exc}") from exc
    if not repository_root.is_dir():
        raise AuditError("repository root must be a directory")
    original_source = source_path.absolute()
    source_value, source_raw = _read_json(original_source, "selected source")
    source = _validate_source(source_value)
    existing_cases: list[dict[str, Any]] = []
    suite_sha: str | None = None
    resolved_suite: str | None = None
    if suite_path is not None:
        candidate = (suite_path if suite_path.is_absolute() else repository_root / suite_path).absolute()
        try:
            relative = _relative_existing_path(candidate, repository_root)
            candidate = path_safety.safe_repo_path(repository_root, relative)
        except (AuditError, path_safety.SafetyError) as exc:
            raise AuditError("suite must stay inside the selected repository") from exc
        suite_value, suite_raw = _read_json(candidate, "project eval suite")
        _, existing_cases = _validate_suite(suite_value)
        suite_sha = _sha_bytes(suite_raw)
        resolved_suite = str(candidate)
    excluded = {original_source}
    if resolved_suite is not None:
        excluded.add(Path(resolved_suite))
    repository_sha = _stable_repository_digest(repository_root, excluded)
    sessions = _source_sessions(source)
    context: dict[str, Any] = {
        "schema_version": "eval-candidate-context/v1",
        "repository_root": str(repository_root),
        "source": {
            "path": str(original_source),
            "selection_kind": source["selection"]["kind"],
            "selection_source": source["selection"]["source"],
            "sha256": _sha_bytes(source_raw),
        },
        "source_digest": _sha_bytes(_canonical_bytes(source)),
        "target": {"repository_sha256": repository_sha, "suite_sha256": suite_sha, "suite_path": resolved_suite},
        "sessions": sessions,
        "existing_cases": existing_cases,
        "limits": {"max_source_bytes": MAX_JSON_BYTES, "max_sessions": MAX_SESSIONS, "max_evidence": MAX_EVIDENCE, "max_summary_bytes": MAX_SUMMARY_BYTES, "max_repository_entries": MAX_REPOSITORY_ENTRIES, "max_repository_files": MAX_REPOSITORY_FILES, "max_repository_bytes": MAX_REPOSITORY_BYTES},
        "limitations": [],
    }
    context["context_sha256"] = _sha_bytes(_canonical_bytes(context))
    return validate_context(context)


def _validate_draft(value: Any) -> dict[str, Any]:
    draft = _object(value, "draft")
    _exact(draft, "draft", ("completion", "candidates", "limitations"))
    _enum(draft["completion"], "draft.completion", {"complete", "incomplete"})
    for index, raw_candidate in enumerate(_array(draft["candidates"], "draft.candidates", maximum=2000)):
        label = f"draft.candidates[{index}]"
        candidate = _object(raw_candidate, label)
        _exact(candidate, label, ("pain_point", "proposed_case", "reason", "evidence_ids", "overlap", "proposed_importance", "behavior_basis", "cost_effect", "promotion_requirements"))
        _text(candidate["pain_point"], f"{label}.pain_point", maximum=2000, secret_check=True)
        proposed = _object(candidate["proposed_case"], f"{label}.proposed_case")
        _exact(proposed, f"{label}.proposed_case", ("kind", "phase", "task_summary"))
        _enum(proposed["kind"], f"{label}.proposed_case.kind", {"explanation", "implementation", "trajectory"})
        if proposed["phase"] is not None:
            _enum(proposed["phase"], f"{label}.proposed_case.phase", {"intake", "clarification", "specification", "planning", "implementation", "verification", "reporting"})
        _text(proposed["task_summary"], f"{label}.proposed_case.task_summary", maximum=2000, secret_check=True)
        _text(candidate["reason"], f"{label}.reason", maximum=2000, secret_check=True)
        evidence_ids = _array(candidate["evidence_ids"], f"{label}.evidence_ids", minimum=1, maximum=256)
        if len({_identifier(item, f"{label}.evidence_ids") for item in evidence_ids}) != len(evidence_ids):
            raise AuditError(f"{label}.evidence_ids must be unique")
        overlap = _object(candidate["overlap"], f"{label}.overlap")
        _exact(overlap, f"{label}.overlap", ("relation", "case_ids", "reason"))
        relation = _enum(overlap["relation"], f"{label}.overlap.relation", {"none", "partial", "duplicate", "extends"})
        case_ids = _array(overlap["case_ids"], f"{label}.overlap.case_ids", maximum=256)
        if len({_identifier(item, f"{label}.overlap.case_ids") for item in case_ids}) != len(case_ids):
            raise AuditError(f"{label}.overlap.case_ids must be unique")
        if relation == "none" and case_ids:
            raise AuditError(f"{label}.overlap.case_ids must be empty when relation is none")
        if relation != "none" and not case_ids:
            raise AuditError(f"{label}.overlap.case_ids must name existing coverage")
        _text(overlap["reason"], f"{label}.overlap.reason", maximum=1000, secret_check=True)
        _enum(candidate["proposed_importance"], f"{label}.proposed_importance", {"required", "important", "standard", "exploratory"})
        _enum(candidate["behavior_basis"], f"{label}.behavior_basis", {"existing", "new", "ambiguous"})
        _enum(candidate["cost_effect"], f"{label}.cost_effect", {"decrease", "none", "increase", "unknown"})
        for requirement_index, requirement in enumerate(_array(candidate["promotion_requirements"], f"{label}.promotion_requirements", maximum=64)):
            _text(requirement, f"{label}.promotion_requirements[{requirement_index}]", maximum=500, secret_check=True)
    for index, limitation in enumerate(_array(draft["limitations"], "draft.limitations", maximum=2000)):
        _limitation(limitation, f"draft.limitations[{index}]")
    return draft


def _readiness(candidate: dict[str, Any]) -> str:
    if candidate["behavior_basis"] in {"new", "ambiguous"} or candidate["cost_effect"] in {"increase", "unknown"}:
        return "decision_required"
    if candidate["promotion_requirements"]:
        return "needs_evidence"
    return "ready"


def _confidence(independent_sessions: int) -> str:
    if independent_sessions >= 3:
        return "high"
    if independent_sessions == 2:
        return "medium"
    return "low"


def finalize(context_value: Any, draft_value: Any) -> dict[str, Any]:
    context = validate_context(context_value, current=True)
    draft = _validate_draft(draft_value)
    evidence: dict[str, tuple[dict[str, Any], str]] = {}
    for session in context["sessions"]:
        for item in session["evidence"]:
            evidence[item["evidence_id"]] = (item, session["independence_sha256"])
    known_cases = {case["case_id"] for case in context["existing_cases"]}
    candidates: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    for index, raw_candidate in enumerate(draft["candidates"]):
        selected: list[dict[str, Any]] = []
        sessions: set[str] = set()
        for evidence_id in raw_candidate["evidence_ids"]:
            bound = evidence.get(evidence_id)
            if bound is None:
                raise AuditError(f"draft.candidates[{index}] cites unknown evidence_id: {evidence_id}")
            selected.append(bound[0])
            sessions.add(bound[1])
        for case_id in raw_candidate["overlap"]["case_ids"]:
            if case_id not in known_cases:
                raise AuditError(f"draft.candidates[{index}] cites unknown overlap case_id: {case_id}")
        semantic = {key: raw_candidate[key] for key in ("pain_point", "proposed_case", "overlap", "behavior_basis")}
        fingerprint = _sha_bytes(_canonical_bytes(semantic))
        if fingerprint in fingerprints:
            raise AuditError("draft contains duplicate semantic candidates")
        fingerprints.add(fingerprint)
        candidate = {
            "candidate_id": f"candidate-{fingerprint[:12]}",
            "pain_point": raw_candidate["pain_point"],
            "proposed_case": raw_candidate["proposed_case"],
            "reason": raw_candidate["reason"],
            "evidence": selected,
            "evidence_count": len(selected),
            "independent_session_count": len(sessions),
            "overlap": raw_candidate["overlap"],
            "confidence": _confidence(len(sessions)),
            "proposed_importance": raw_candidate["proposed_importance"],
            "behavior_basis": raw_candidate["behavior_basis"],
            "cost_effect": raw_candidate["cost_effect"],
            "promotion_requirements": raw_candidate["promotion_requirements"],
            "readiness": _readiness(raw_candidate),
        }
        candidates.append(candidate)
    limitations = [*context["limitations"], *draft["limitations"]]
    material = any(item["material"] for item in limitations)
    completion = "incomplete" if material or draft["completion"] == "incomplete" else "complete"
    if completion == "incomplete":
        outcome, next_action = "unknown", "retry"
    elif not candidates:
        outcome, next_action = "none", "none"
    elif any(item["readiness"] == "decision_required" for item in candidates):
        outcome, next_action = "candidates", "decision"
    elif any(item["readiness"] == "ready" for item in candidates):
        outcome, next_action = "candidates", "draft"
    else:
        outcome, next_action = "candidates", "manual"
    result = {
        "schema_version": "eval-candidate-result/v1",
        "producer": {"name": "eval-candidate-audit", "version": VERSION},
        "context_sha256": context["context_sha256"],
        "completion": completion,
        "outcome": outcome,
        "next_action": next_action,
        "source_digest": context["source_digest"],
        "target": {"repository_sha256": context["target"]["repository_sha256"], "suite_sha256": context["target"]["suite_sha256"]},
        "candidates": sorted(candidates, key=lambda item: item["candidate_id"]),
        "limitations": limitations,
    }
    return validate_result(result, context=context)


def _validate_evidence(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label)
    _exact(item, label, ("evidence_id", "kind", "sha256", "summary", "redacted"))
    _identifier(item["evidence_id"], f"{label}.evidence_id")
    _enum(item["kind"], f"{label}.kind", {"session_summary", "run_receipt", "assertion", "measurement", "repository"})
    _sha(item["sha256"], f"{label}.sha256")
    _text(item["summary"], f"{label}.summary", maximum=500, secret_check=True)
    if item["redacted"] is not True:
        raise AuditError(f"{label}.redacted must be true")
    return item


def validate_result(value: Any, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    result = _object(value, "result")
    _exact(result, "result", ("schema_version", "producer", "context_sha256", "completion", "outcome", "next_action", "source_digest", "target", "candidates", "limitations"))
    if result["schema_version"] != "eval-candidate-result/v1":
        raise AuditError("unsupported result schema_version")
    producer = _object(result["producer"], "result.producer")
    _exact(producer, "result.producer", ("name", "version"))
    _identifier(producer["name"], "result.producer.name")
    _text(producer["version"], "result.producer.version", maximum=128)
    _sha(result["context_sha256"], "result.context_sha256")
    completion = _enum(result["completion"], "result.completion", {"complete", "incomplete"})
    outcome = _enum(result["outcome"], "result.outcome", {"candidates", "none", "unknown"})
    next_action = _enum(result["next_action"], "result.next_action", {"none", "draft", "decision", "retry", "manual"})
    _sha(result["source_digest"], "result.source_digest")
    target = _object(result["target"], "result.target")
    _exact(target, "result.target", ("repository_sha256", "suite_sha256"))
    _sha(target["repository_sha256"], "result.target.repository_sha256")
    if target["suite_sha256"] is not None:
        _sha(target["suite_sha256"], "result.target.suite_sha256")
    candidates = _array(result["candidates"], "result.candidates", maximum=2000)
    candidate_ids: set[str] = set()
    readiness_values: list[str] = []
    for index, raw_candidate in enumerate(candidates):
        label = f"result.candidates[{index}]"
        candidate = _object(raw_candidate, label)
        _exact(candidate, label, ("candidate_id", "pain_point", "proposed_case", "reason", "evidence", "evidence_count", "independent_session_count", "overlap", "confidence", "proposed_importance", "behavior_basis", "cost_effect", "promotion_requirements", "readiness"))
        candidate_id = _identifier(candidate["candidate_id"], f"{label}.candidate_id")
        if candidate_id in candidate_ids:
            raise AuditError(f"duplicate result candidate_id: {candidate_id}")
        candidate_ids.add(candidate_id)
        _text(candidate["pain_point"], f"{label}.pain_point", maximum=2000, secret_check=True)
        proposed = _object(candidate["proposed_case"], f"{label}.proposed_case")
        _exact(proposed, f"{label}.proposed_case", ("kind", "phase", "task_summary"))
        _enum(proposed["kind"], f"{label}.proposed_case.kind", {"explanation", "implementation", "trajectory"})
        if proposed["phase"] is not None:
            _enum(proposed["phase"], f"{label}.proposed_case.phase", {"intake", "clarification", "specification", "planning", "implementation", "verification", "reporting"})
        _text(proposed["task_summary"], f"{label}.proposed_case.task_summary", maximum=2000, secret_check=True)
        _text(candidate["reason"], f"{label}.reason", maximum=2000, secret_check=True)
        evidence = _array(candidate["evidence"], f"{label}.evidence", minimum=1, maximum=256)
        for evidence_index, item in enumerate(evidence):
            _validate_evidence(item, f"{label}.evidence[{evidence_index}]")
        if len({item["evidence_id"] for item in evidence}) != len(evidence):
            raise AuditError(f"{label}.evidence must be unique by evidence_id")
        count = _integer(candidate["evidence_count"], f"{label}.evidence_count", 1, 1_000_000)
        sessions = _integer(candidate["independent_session_count"], f"{label}.independent_session_count", 1, 1_000_000)
        if count != len(evidence) or sessions > count:
            raise AuditError(f"{label} evidence counts are inconsistent")
        expected_confidence = _confidence(sessions)
        if _enum(candidate["confidence"], f"{label}.confidence", {"high", "medium", "low", "unknown"}) != expected_confidence:
            raise AuditError(f"{label}.confidence does not match independent recurrence")
        overlap = _object(candidate["overlap"], f"{label}.overlap")
        _exact(overlap, f"{label}.overlap", ("relation", "case_ids", "reason"))
        relation = _enum(overlap["relation"], f"{label}.overlap.relation", {"none", "partial", "duplicate", "extends"})
        case_ids = _array(overlap["case_ids"], f"{label}.overlap.case_ids", maximum=256)
        if len({_identifier(item, f"{label}.overlap.case_ids") for item in case_ids}) != len(case_ids):
            raise AuditError(f"{label}.overlap.case_ids must be unique")
        if (relation == "none") != (not case_ids):
            raise AuditError(f"{label}.overlap relation and case_ids disagree")
        _text(overlap["reason"], f"{label}.overlap.reason", maximum=1000, secret_check=True)
        _enum(candidate["proposed_importance"], f"{label}.proposed_importance", {"required", "important", "standard", "exploratory"})
        basis = _enum(candidate["behavior_basis"], f"{label}.behavior_basis", {"existing", "new", "ambiguous"})
        cost = _enum(candidate["cost_effect"], f"{label}.cost_effect", {"decrease", "none", "increase", "unknown"})
        requirements = _array(candidate["promotion_requirements"], f"{label}.promotion_requirements", maximum=64)
        for requirement_index, requirement in enumerate(requirements):
            _text(requirement, f"{label}.promotion_requirements[{requirement_index}]", maximum=500, secret_check=True)
        expected_readiness = "decision_required" if basis in {"new", "ambiguous"} or cost in {"increase", "unknown"} else ("needs_evidence" if requirements else "ready")
        readiness = _enum(candidate["readiness"], f"{label}.readiness", {"ready", "decision_required", "needs_evidence"})
        if readiness != expected_readiness:
            raise AuditError(f"{label}.readiness does not match behavior, cost, and promotion requirements")
        readiness_values.append(readiness)
    limitations = [_limitation(item, f"result.limitations[{index}]") for index, item in enumerate(_array(result["limitations"], "result.limitations", maximum=2000))]
    material = any(item["material"] for item in limitations)
    expected_completion = "incomplete" if material else "complete"
    if completion != expected_completion:
        raise AuditError("result.completion does not match material limitations")
    if completion == "incomplete":
        expected_outcome, expected_action = "unknown", "retry"
    elif not candidates:
        expected_outcome, expected_action = "none", "none"
    elif "decision_required" in readiness_values:
        expected_outcome, expected_action = "candidates", "decision"
    elif "ready" in readiness_values:
        expected_outcome, expected_action = "candidates", "draft"
    else:
        expected_outcome, expected_action = "candidates", "manual"
    if (outcome, next_action) != (expected_outcome, expected_action):
        raise AuditError("result outcome or next_action is inconsistent")
    if context is not None:
        frozen = validate_context(context, current=True)
        if result["context_sha256"] != frozen["context_sha256"]:
            raise AuditError("result is not bound to the selected candidate context")
        if result["source_digest"] != frozen["source_digest"] or result["target"] != {
            "repository_sha256": frozen["target"]["repository_sha256"],
            "suite_sha256": frozen["target"]["suite_sha256"],
        }:
            raise AuditError("result source or target differs from the selected candidate context")
        if producer != {"name": "eval-candidate-audit", "version": VERSION}:
            raise AuditError("context-bound result has an unexpected producer")
        bound_evidence: dict[str, tuple[dict[str, Any], str]] = {}
        for session in frozen["sessions"]:
            for item in session["evidence"]:
                bound_evidence[item["evidence_id"]] = (item, session["independence_sha256"])
        known_cases = {item["case_id"] for item in frozen["existing_cases"]}
        for index, candidate in enumerate(candidates):
            sessions: set[str] = set()
            for item in candidate["evidence"]:
                bound = bound_evidence.get(item["evidence_id"])
                if bound is None or bound[0] != item:
                    raise AuditError(f"result.candidates[{index}] evidence is not frozen in the selected context")
                sessions.add(bound[1])
            if candidate["independent_session_count"] != len(sessions):
                raise AuditError(f"result.candidates[{index}] independent session count is not context-derived")
            if any(case_id not in known_cases for case_id in candidate["overlap"]["case_ids"]):
                raise AuditError(f"result.candidates[{index}] overlap is not frozen in the selected context")
            semantic = {key: candidate[key] for key in ("pain_point", "proposed_case", "overlap", "behavior_basis")}
            expected_id = f"candidate-{_sha_bytes(_canonical_bytes(semantic))[:12]}"
            if candidate["candidate_id"] != expected_id:
                raise AuditError(f"result.candidates[{index}].candidate_id is not derived from its semantics")
    if len(_canonical_bytes(result)) > MAX_RESULT_BYTES:
        raise AuditError("canonical result exceeds the output limit")
    return result


def _display(value: str) -> str:
    parts: list[str] = []
    for char in value:
        category = unicodedata.category(char)
        if char in {"&", "<", ">"}:
            parts.append({"&": "&amp;", "<": "&lt;", ">": "&gt;"}[char])
        elif category in {"Cc", "Cf", "Cs"}:
            parts.append(f"\\u{ord(char):04x}")
        else:
            parts.append(char)
    return "".join(parts)


def render(result: dict[str, Any]) -> str:
    value = validate_result(result)
    lines = [
        "Eval candidate audit",
        f"Completion: {value['completion']}",
        f"Outcome: {value['outcome']}",
        f"Next action: {value['next_action']}",
        f"Candidates: {len(value['candidates'])}",
    ]
    for candidate in value["candidates"]:
        lines.extend([
            "",
            f"- [{candidate['readiness']}] {_display(candidate['pain_point'])}",
            f"  Case: {candidate['proposed_case']['kind']} / {candidate['proposed_case']['phase'] or 'whole task'} — {_display(candidate['proposed_case']['task_summary'])}",
            f"  Strength: {candidate['confidence']} from {candidate['evidence_count']} evidence item(s) across {candidate['independent_session_count']} independent session(s)",
            f"  Importance: {candidate['proposed_importance']} (proposal only)",
            f"  Overlap: {candidate['overlap']['relation']} — {_display(candidate['overlap']['reason'])}",
            f"  Reason: {_display(candidate['reason'])}",
        ])
        if candidate["promotion_requirements"]:
            lines.append("  Promotion requirements: " + "; ".join(_display(item) for item in candidate["promotion_requirements"]))
    if value["limitations"]:
        lines.append("")
        lines.append("Limitations:")
        for limitation in value["limitations"]:
            lines.append(f"- {'material' if limitation['material'] else 'non-material'} {_display(limitation['code'])}: {_display(limitation['message'])}")
    return "\n".join(lines) + "\n"


def _emit(value: dict[str, Any], output_format: str, output: Path | None) -> None:
    if output_format == "human":
        data = render(value).encode("utf-8")
    elif output_format == "json":
        data = _canonical_bytes(value)
    else:
        data = (render(value) + _canonical_bytes(value).decode("utf-8")).encode("utf-8")
    if len(data) > MAX_RESULT_BYTES:
        raise AuditError("rendered output exceeds the output limit")
    if output is None:
        sys.stdout.buffer.write(data)
    else:
        path_safety.write_created_output(output, data)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve", help="freeze selected sanitized session evidence")
    resolve.add_argument("--repo", required=True)
    resolve.add_argument("--source", required=True)
    resolve.add_argument("--suite")
    resolve.add_argument("--output", required=True)
    finalize_command = commands.add_parser("finalize", help="bind and finalize a semantic candidate draft")
    finalize_command.add_argument("--context", required=True)
    finalize_command.add_argument("--input", required=True)
    finalize_command.add_argument("--format", choices=("human", "json", "both"), default="human")
    finalize_command.add_argument("--output")
    validate_command = commands.add_parser("validate", help="validate canonical candidate JSON")
    validate_command.add_argument("--input", required=True)
    validate_command.add_argument("--context")
    render_command = commands.add_parser("render", help="render canonical candidate JSON")
    render_command.add_argument("--input", required=True)
    render_command.add_argument("--format", choices=("human", "json"), default="human")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "resolve":
            context = resolve_context(Path(args.repo), Path(args.source), Path(args.suite) if args.suite else None)
            path_safety.write_created_output(Path(args.output), _canonical_bytes(context))
        elif args.command == "finalize":
            context, _ = _read_json(Path(args.context), "candidate context")
            draft, _ = _read_json(Path(args.input), "candidate draft")
            _emit(finalize(context, draft), args.format, Path(args.output) if args.output else None)
        elif args.command == "validate":
            value, _ = _read_json(Path(args.input), "candidate result", MAX_RESULT_BYTES)
            context = None
            if args.context:
                context, _ = _read_json(Path(args.context), "candidate context")
            validate_result(value, context=context)
            sys.stdout.write('{"schema_version":"eval-candidate-result/v1","valid":true}\n')
        else:
            value, _ = _read_json(Path(args.input), "candidate result", MAX_RESULT_BYTES)
            _emit(validate_result(value), args.format, None)
    except (AuditError, OSError, path_safety.SafetyError) as exc:
        print(f"eval-candidate-audit: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
