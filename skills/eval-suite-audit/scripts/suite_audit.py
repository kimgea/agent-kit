#!/usr/bin/env python3
"""Freeze a committed eval suite and finalize lifecycle recommendations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

import path_safety
import evidence_contracts


VERSION = "1.0.0"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_SOURCES = 32
MAX_EVIDENCE = 4096
MAX_SUMMARY_BYTES = 1024 * 1024
MAX_FIXTURE_ENTRIES = 40_000
MAX_FIXTURE_FILES = 20_000
MAX_FIXTURE_BYTES = 64 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 200_000
ID_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
HEAD_RE = re.compile(r"^[0-9a-f]{40,64}$")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}={0,2}\b", re.IGNORECASE),
    re.compile(r"\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{6,}", re.IGNORECASE),
)
RETIREMENT_BASES = {
    "removed_behavior",
    "duplicate_coverage",
    "superseded_coverage",
    "obsolete_fixture",
    "obsolete_architecture",
    "no_unique_agent_value",
    "cost_without_unique_coverage",
}


class AuditError(ValueError):
    """Raised for malformed or unsafe suite-audit input."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise AuditError(f"duplicate JSON member: {key}")
        value[key] = item
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path, label: str) -> tuple[Any, bytes]:
    try:
        _, raw = path_safety.read_regular(path, MAX_INPUT_BYTES, require_single_link=True)
    except (OSError, path_safety.SafetyError) as exc:
        raise AuditError(f"cannot read {label}: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise AuditError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    pending = [(value, 0)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise AuditError(f"{label} exceeds the JSON structure limit")
        if isinstance(current, dict):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
    return value, raw


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuditError(f"{label} must be an object")
    return value


def _array(value: Any, label: str, *, minimum: int = 0, maximum: int) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise AuditError(f"{label} must contain between {minimum} and {maximum} items")
    return value


def _exact(value: dict[str, Any], label: str, keys: tuple[str, ...]) -> None:
    if set(value) != set(keys):
        raise AuditError(f"{label} fields must be exactly {sorted(keys)}")


def _text(value: Any, label: str, *, maximum: int = 4000, secret_check: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise AuditError(f"{label} must be non-empty bounded text")
    if secret_check and any(pattern.search(value) for pattern in SECRET_PATTERNS):
        raise AuditError(f"{label} contains secret-like content")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
        raise AuditError(f"{label} must be a canonical identifier")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise AuditError(f"{label} must be a lowercase SHA-256")
    return value


def _enum(value: Any, label: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise AuditError(f"{label} must be one of {sorted(allowed)}")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise AuditError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _number_or_null(value: Any, label: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1_000_000_000:
        raise AuditError(f"{label} must be null or a bounded non-negative number")
    return value


def _limitation(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label)
    _exact(item, label, ("code", "message", "material"))
    _identifier(item["code"], f"{label}.code")
    _text(item["message"], f"{label}.message", maximum=2000, secret_check=True)
    if not isinstance(item["material"], bool):
        raise AuditError(f"{label}.material must be boolean")
    return item


def _git(root: Path, *arguments: str, maximum: int = MAX_INPUT_BYTES) -> bytes:
    environment = os.environ.copy()
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        environment.pop(key, None)
    command = [
        "git",
        "--no-pager",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        *arguments,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuditError(f"cannot inspect committed suite: {exc}") from exc
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace")[:500]
        raise AuditError(f"cannot inspect committed suite: {message}")
    if len(completed.stdout) > maximum:
        raise AuditError("Git metadata exceeds the selected input limit")
    return completed.stdout


def _repository(root: Path) -> tuple[Path, str, str]:
    original = root.absolute()
    try:
        path_safety.assert_no_link_components(original, include_final=True)
    except path_safety.SafetyError as exc:
        raise AuditError(f"cannot bind repository root: {exc}") from exc
    if not original.is_dir():
        raise AuditError("repository root must be a directory")
    top_raw = _git(original, "rev-parse", "--show-toplevel")
    try:
        top = Path(top_raw.decode("utf-8").strip()).absolute()
    except UnicodeDecodeError as exc:
        raise AuditError("Git repository root is not UTF-8") from exc
    try:
        same = os.path.samefile(original, top)
    except OSError:
        same = os.path.normcase(str(original)) == os.path.normcase(str(top))
    if not same:
        raise AuditError("--repo must name the Git worktree root")
    head = _git(original, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
    if HEAD_RE.fullmatch(head) is None:
        raise AuditError("Git HEAD is not a supported object identifier")
    return original, head, _sha_bytes(_canonical_bytes({"git_head": head}))


def _unique_identifiers(value: Any, label: str, *, minimum: int = 0, maximum: int = 256) -> list[str]:
    items = _array(value, label, minimum=minimum, maximum=maximum)
    normalized = [_identifier(item, label) for item in items]
    if len(set(normalized)) != len(normalized):
        raise AuditError(f"{label} must be unique")
    return normalized


def _validate_suite(value: Any) -> dict[str, Any]:
    suite = _object(value, "suite")
    _exact(suite, "suite", ("schema_version", "suite_id", "title", "cases", "profiles"))
    if suite["schema_version"] != "project-eval-suite/v1":
        raise AuditError("suite schema_version must be project-eval-suite/v1")
    _identifier(suite["suite_id"], "suite.suite_id")
    _text(suite["title"], "suite.title", maximum=200)
    cases = _array(suite["cases"], "suite.cases", minimum=1, maximum=500)
    case_ids: set[str] = set()
    for index, raw_case in enumerate(cases):
        label = f"suite.cases[{index}]"
        case = _object(raw_case, label)
        _exact(case, label, ("case_id", "title", "kind", "importance", "fixture", "task", "coverage", "platforms", "required_capabilities", "assertion_ids"))
        case_id = _identifier(case["case_id"], f"{label}.case_id")
        if case_id in case_ids:
            raise AuditError(f"duplicate suite case_id: {case_id}")
        case_ids.add(case_id)
        _text(case["title"], f"{label}.title", maximum=200)
        _enum(case["kind"], f"{label}.kind", {"explanation", "implementation", "trajectory"})
        _enum(case["importance"], f"{label}.importance", {"required", "important", "standard", "exploratory"})
        path_safety.canonical_path(case["fixture"])
        _text(case["task"], f"{label}.task", maximum=4000)
        _enum(case["coverage"], f"{label}.coverage", {"development", "holdout", "regression"})
        platforms = _array(case["platforms"], f"{label}.platforms", minimum=1, maximum=3)
        if len(set(platforms)) != len(platforms) or any(item not in {"linux", "windows", "macos"} for item in platforms):
            raise AuditError(f"{label}.platforms are invalid")
        _unique_identifiers(case["required_capabilities"], f"{label}.required_capabilities", maximum=64)
        _unique_identifiers(case["assertion_ids"], f"{label}.assertion_ids", minimum=1)
    profiles = _object(suite["profiles"], "suite.profiles")
    if not 1 <= len(profiles) <= 32:
        raise AuditError("suite.profiles must contain between 1 and 32 profiles")
    for profile_id, raw_profile in profiles.items():
        _identifier(profile_id, "suite profile id")
        label = f"suite.profiles.{profile_id}"
        profile = _object(raw_profile, label)
        _exact(profile, label, ("case_ids", "repetitions", "max_invocations", "max_seconds", "max_tokens", "max_cost_usd", "network", "effects"))
        selected = _unique_identifiers(profile["case_ids"], f"{label}.case_ids", minimum=1, maximum=500)
        if set(selected) - case_ids:
            raise AuditError(f"{label} names unknown cases")
        repetitions = _integer(profile["repetitions"], f"{label}.repetitions", 1, 100)
        if _integer(profile["max_invocations"], f"{label}.max_invocations", 1, 10000) < len(selected) * repetitions:
            raise AuditError(f"{label}.max_invocations cannot cover repetitions")
        _integer(profile["max_seconds"], f"{label}.max_seconds", 1, 86400)
        if profile["max_tokens"] is not None:
            _integer(profile["max_tokens"], f"{label}.max_tokens", 1, 1_000_000_000)
        _number_or_null(profile["max_cost_usd"], f"{label}.max_cost_usd")
        if not isinstance(profile["network"], bool):
            raise AuditError(f"{label}.network must be boolean")
        effects = _array(profile["effects"], f"{label}.effects", maximum=16)
        if len(set(effects)) != len(effects) or any(item not in {"workspace_edit", "command_execution", "local_output", "external_read"} for item in effects):
            raise AuditError(f"{label}.effects are invalid")
    return suite


def _committed_fixture_bindings(
    repository: Path,
    suite_relative: str,
    suite: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    suite_parent = Path(suite_relative).parent
    cache: dict[str, dict[str, Any]] = {}
    bindings: dict[str, dict[str, Any]] = {}
    seen_files: set[str] = set()
    total_bytes = 0
    first_live_budget = {"entries": 0, "bytes": 0}
    second_live_budget = {"entries": 0, "bytes": 0}
    for case in suite["cases"]:
        fixture_relative = (suite_parent / case["fixture"]).as_posix()
        try:
            fixture_relative = path_safety.canonical_path(fixture_relative)
        except path_safety.SafetyError as exc:
            raise AuditError(f"case {case['case_id']} fixture is unsafe: {exc}") from exc
        if fixture_relative not in cache:
            raw_tree = _git(
                repository,
                "ls-tree",
                "-r",
                "-z",
                "--full-tree",
                "HEAD",
                "--",
                fixture_relative,
                maximum=MAX_INPUT_BYTES,
            )
            records: list[dict[str, Any]] = []
            prefix = fixture_relative + "/"
            for raw_entry in raw_tree.split(b"\0"):
                if not raw_entry:
                    continue
                try:
                    header, raw_path = raw_entry.split(b"\t", 1)
                    mode, object_type, object_id = header.decode("ascii").split(" ", 2)
                    path = raw_path.decode("utf-8", "strict")
                except (ValueError, UnicodeDecodeError) as exc:
                    raise AuditError("committed fixture inventory is malformed") from exc
                if not path.startswith(prefix) or path_safety.canonical_path(path) != path:
                    raise AuditError("committed fixture inventory escaped its selected directory")
                if object_type != "blob" or mode not in {"100644", "100755"} or HEAD_RE.fullmatch(object_id) is None:
                    raise AuditError(f"committed fixture contains unsupported entry: {path}")
                content = _git(repository, "cat-file", "blob", object_id, maximum=MAX_INPUT_BYTES)
                if path not in seen_files:
                    seen_files.add(path)
                    total_bytes += len(content)
                    if len(seen_files) > MAX_FIXTURE_FILES or total_bytes > MAX_FIXTURE_BYTES:
                        raise AuditError("committed fixtures exceed the locked aggregate limits")
                records.append(
                    {
                        "path": path,
                        "mode": mode,
                        "bytes": len(content),
                        "sha256": _sha_bytes(content),
                    }
                )
            if not records:
                raise AuditError(f"case {case['case_id']} fixture has no committed files")
            records.sort(key=lambda item: item["path"])
            cache[fixture_relative] = {
                "fixture_sha256": _sha_bytes(_canonical_bytes(records)),
                "fixture_files": len(records),
                "fixture_bytes": sum(item["bytes"] for item in records),
            }
            first_live = _live_fixture_records(repository, fixture_relative, records, first_live_budget)
            second_live = _live_fixture_records(repository, fixture_relative, records, second_live_budget)
            if first_live != records or second_live != records:
                raise AuditError(f"case {case['case_id']} fixture differs from committed HEAD")
        bindings[case["case_id"]] = cache[fixture_relative]
    return bindings


def _live_fixture_records(
    repository: Path,
    fixture_relative: str,
    committed_records: list[dict[str, Any]],
    budget: dict[str, int],
) -> list[dict[str, Any]]:
    try:
        root = path_safety.safe_repo_path(repository, fixture_relative)
    except path_safety.SafetyError as exc:
        raise AuditError(f"fixture path is unsafe: {exc}") from exc
    if not root.is_dir():
        raise AuditError(f"fixture is not a directory: {fixture_relative}")
    committed_modes = {item["path"]: item["mode"] for item in committed_records}
    committed_directories: set[str] = set()
    prefix = fixture_relative + "/"
    for item in committed_records:
        relative_parts = Path(item["path"][len(prefix):]).parts[:-1]
        current = Path(fixture_relative)
        for part in relative_parts:
            current /= part
            committed_directories.add(current.as_posix())
    pending = [root]
    records: list[dict[str, Any]] = []
    while pending:
        directory = pending.pop()
        remaining = MAX_FIXTURE_ENTRIES - budget["entries"]
        if remaining <= 0:
            raise AuditError("live fixture exceeds the locked traversal limit")
        try:
            entries, consumed, complete = path_safety.bound_directory_entries(directory, remaining)
        except path_safety.SafetyError as exc:
            raise AuditError(f"cannot inspect live fixture: {exc}") from exc
        budget["entries"] += consumed
        if not complete:
            raise AuditError("live fixture exceeds the locked traversal limit")
        for entry in entries:
            relative = entry.path.relative_to(repository).as_posix()
            if entry.link_like:
                raise AuditError(f"live fixture contains a link-like entry: {relative}")
            if entry.is_directory:
                if relative not in committed_directories:
                    raise AuditError(f"live fixture contains an uncommitted directory: {relative}")
                pending.append(entry.path)
                continue
            if not entry.is_regular or relative not in committed_modes:
                raise AuditError(f"live fixture contains an uncommitted or unsupported entry: {relative}")
            remaining_bytes = MAX_FIXTURE_BYTES - budget["bytes"]
            try:
                metadata, content = path_safety.read_regular(
                    entry.path,
                    remaining_bytes,
                    require_single_link=True,
                )
            except path_safety.SafetyError as exc:
                raise AuditError(f"cannot inspect live fixture file: {exc}") from exc
            budget["bytes"] += len(content)
            mode = committed_modes[relative] if os.name == "nt" else "100755" if metadata.st_mode & 0o111 else "100644"
            records.append(
                {
                    "path": relative,
                    "mode": mode,
                    "bytes": len(content),
                    "sha256": _sha_bytes(content),
                }
            )
    records.sort(key=lambda item: item["path"])
    return records


def _load_committed_suite(root: Path, suite_path: str) -> tuple[dict[str, Any], bytes, str, str, str, dict[str, dict[str, Any]]]:
    repository, head, repository_sha = _repository(root)
    relative = path_safety.canonical_path(suite_path)
    live = path_safety.safe_repo_path(repository, relative)
    live_value, _ = _read_json(live, "live suite")
    live_suite = _validate_suite(live_value)
    committed_raw = _git(repository, "cat-file", "blob", f"HEAD:{relative}")
    try:
        committed_value = json.loads(committed_raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"committed suite is not valid UTF-8 JSON: {exc}") from exc
    committed_suite = _validate_suite(committed_value)
    if _canonical_bytes(live_suite) != _canonical_bytes(committed_suite):
        raise AuditError("selected suite differs from committed HEAD")
    fixture_bindings = _committed_fixture_bindings(repository, relative, committed_suite)
    return committed_suite, committed_raw, relative, head, repository_sha, fixture_bindings


def _case_context(
    suite: dict[str, Any],
    fixture_bindings: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    memberships: dict[str, list[str]] = {case["case_id"]: [] for case in suite["cases"]}
    profiles: list[dict[str, Any]] = []
    for profile_id in sorted(suite["profiles"]):
        profile = suite["profiles"][profile_id]
        for case_id in profile["case_ids"]:
            memberships[case_id].append(profile_id)
        profiles.append({key: value for key, value in {"profile_id": profile_id, **profile}.items() if key not in {"network", "effects"}})
    cases = [
        {
            "case_id": case["case_id"],
            "title": case["title"],
            "kind": case["kind"],
            "importance": case["importance"],
            "fixture": case["fixture"],
            **fixture_bindings[case["case_id"]],
            "task": case["task"],
            "coverage": case["coverage"],
            "platforms": case["platforms"],
            "assertion_ids": case["assertion_ids"],
            "profiles": sorted(memberships[case["case_id"]]),
        }
        for case in suite["cases"]
    ]
    return cases, profiles


def _evidence_item(kind: str, summary: str, case_ids: list[str], semantic: Any) -> dict[str, Any]:
    summary = _text(summary[:500], "evidence summary", maximum=500, secret_check=True)
    digest = _sha_bytes(_canonical_bytes(semantic))
    return {"evidence_id": f"e-{digest[:16]}", "kind": kind, "sha256": digest, "summary": summary, "redacted": True, "case_ids": sorted(case_ids)}


def _definition_evidence(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _evidence_item(
            "repository",
            f"Committed case {case['case_id']} is {case['importance']} {case['kind']} coverage in {len(case['profiles'])} profile(s) with {len(case['assertion_ids'])} assertion(s).",
            [case["case_id"]],
            case,
        )
        for case in cases
    ]


def _extract_evidence(value: Any, suite_digest: str, known_cases: set[str]) -> tuple[str, list[dict[str, Any]]]:
    artifact = _object(value, "evidence artifact")
    schema = artifact.get("schema_version")
    extracted: list[dict[str, Any]] = []
    if schema == "project-eval-run-result/v1":
        try:
            evidence_contracts.validate_project_eval_run(artifact)
        except evidence_contracts.ContractError as exc:
            raise AuditError(f"run evidence is not canonical: {exc}") from exc
        suite = _object(artifact.get("suite"), "run evidence.suite")
        if _sha(suite.get("suite_sha256"), "run evidence suite digest") != suite_digest:
            raise AuditError("run evidence does not match the selected suite")
        run_id = _identifier(artifact.get("run_id"), "run evidence.run_id")
        cases = _array(artifact.get("cases"), "run evidence.cases", maximum=2000)
        for index, raw_case in enumerate(cases):
            case = _object(raw_case, f"run evidence.cases[{index}]")
            case_id = _identifier(case.get("case_id"), f"run evidence.cases[{index}].case_id")
            if case_id not in known_cases:
                raise AuditError(f"run evidence names unknown case {case_id}")
            status = case["status"]
            stability = case["stability"]
            repetitions = case["repetitions"]
            passed = case["passed"]
            failed = case["failed"]
            duration = case["duration_ms"] or 0
            semantic = {"artifact": _sha_bytes(_canonical_bytes(artifact)), "case_id": case_id, "status": status, "stability": stability, "repetitions": repetitions, "passed": passed, "failed": failed, "duration_ms": duration}
            extracted.append(_evidence_item("run_receipt", f"Run {run_id}: {case_id} was {status}; {passed} pass and {failed} fail across {repetitions} repetition(s), {stability}, {duration} ms.", [case_id], semantic))
    elif schema == "eval-candidate-result/v1":
        try:
            evidence_contracts.validate_eval_candidate(artifact)
        except evidence_contracts.ContractError as exc:
            raise AuditError(f"candidate evidence is not canonical: {exc}") from exc
        target = _object(artifact.get("target"), "candidate evidence.target")
        if _sha(target.get("suite_sha256"), "candidate evidence suite digest") != suite_digest:
            raise AuditError("candidate evidence does not match the selected suite")
        for index, raw_candidate in enumerate(_array(artifact.get("candidates"), "candidate evidence.candidates", maximum=2000)):
            candidate = _object(raw_candidate, f"candidate evidence.candidates[{index}]")
            candidate_id = _identifier(candidate.get("candidate_id"), "candidate evidence candidate_id")
            overlap = _object(candidate.get("overlap"), "candidate evidence overlap")
            case_ids = _unique_identifiers(overlap.get("case_ids"), "candidate evidence overlap case_ids")
            if set(case_ids) - known_cases:
                raise AuditError("candidate evidence names an unknown existing case")
            if not case_ids:
                continue
            relation = _enum(overlap.get("relation"), "candidate evidence overlap relation", {"partial", "duplicate", "extends"})
            confidence = _enum(candidate.get("confidence"), "candidate evidence confidence", {"high", "medium", "low", "unknown"})
            readiness = _enum(candidate.get("readiness"), "candidate evidence readiness", {"ready", "decision_required", "needs_evidence"})
            semantic = {"artifact": _sha_bytes(_canonical_bytes(artifact)), "candidate_id": candidate_id, "case_ids": case_ids, "relation": relation, "confidence": confidence, "readiness": readiness}
            extracted.append(_evidence_item("session_summary", f"Candidate {candidate_id} has {relation} overlap with {', '.join(case_ids)}; confidence {confidence}, readiness {readiness}.", case_ids, semantic))
    else:
        raise AuditError("evidence must be project-eval-run-result/v1 or eval-candidate-result/v1")
    return schema, extracted


def _context_without_digest(context: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in context.items() if key != "context_sha256"}


def _validate_context(value: Any, *, current: bool = False) -> dict[str, Any]:
    context = _object(value, "context")
    _exact(context, "context", ("schema_version", "repository_root", "repository_head", "repository_sha256", "suite", "cases", "profiles", "evidence_sources", "evidence", "limits", "limitations", "context_sha256"))
    if context["schema_version"] != "eval-suite-audit-context/v1":
        raise AuditError("unsupported context schema_version")
    _text(context["repository_root"], "context.repository_root", maximum=4096)
    if not isinstance(context["repository_head"], str) or HEAD_RE.fullmatch(context["repository_head"]) is None:
        raise AuditError("context.repository_head is invalid")
    _sha(context["repository_sha256"], "context.repository_sha256")
    suite_meta = _object(context["suite"], "context.suite")
    _exact(suite_meta, "context.suite", ("path", "source_sha256", "suite_digest", "suite_id", "title"))
    path_safety.canonical_path(suite_meta["path"])
    _sha(suite_meta["source_sha256"], "context.suite.source_sha256")
    _sha(suite_meta["suite_digest"], "context.suite.suite_digest")
    _identifier(suite_meta["suite_id"], "context.suite.suite_id")
    _text(suite_meta["title"], "context.suite.title", maximum=200)
    cases = _array(context["cases"], "context.cases", minimum=1, maximum=500)
    known_cases: set[str] = set()
    for index, raw_case in enumerate(cases):
        label = f"context.cases[{index}]"
        case = _object(raw_case, label)
        _exact(case, label, ("case_id", "title", "kind", "importance", "fixture", "fixture_sha256", "fixture_files", "fixture_bytes", "task", "coverage", "platforms", "assertion_ids", "profiles"))
        case_id = _identifier(case["case_id"], f"{label}.case_id")
        if case_id in known_cases:
            raise AuditError(f"duplicate context case_id: {case_id}")
        known_cases.add(case_id)
        _text(case["title"], f"{label}.title", maximum=200)
        _enum(case["kind"], f"{label}.kind", {"explanation", "implementation", "trajectory"})
        _enum(case["importance"], f"{label}.importance", {"required", "important", "standard", "exploratory"})
        path_safety.canonical_path(case["fixture"])
        _sha(case["fixture_sha256"], f"{label}.fixture_sha256")
        _integer(case["fixture_files"], f"{label}.fixture_files", 1, MAX_FIXTURE_FILES)
        _integer(case["fixture_bytes"], f"{label}.fixture_bytes", 0, MAX_FIXTURE_BYTES)
        _text(case["task"], f"{label}.task", maximum=4000)
        _enum(case["coverage"], f"{label}.coverage", {"development", "holdout", "regression"})
        _array(case["platforms"], f"{label}.platforms", minimum=1, maximum=3)
        _unique_identifiers(case["assertion_ids"], f"{label}.assertion_ids", minimum=1)
        _unique_identifiers(case["profiles"], f"{label}.profiles", maximum=32)
    profiles = _array(context["profiles"], "context.profiles", minimum=1, maximum=32)
    profile_ids: set[str] = set()
    for index, raw_profile in enumerate(profiles):
        label = f"context.profiles[{index}]"
        profile = _object(raw_profile, label)
        _exact(profile, label, ("profile_id", "case_ids", "repetitions", "max_invocations", "max_seconds", "max_tokens", "max_cost_usd"))
        profile_id = _identifier(profile["profile_id"], f"{label}.profile_id")
        if profile_id in profile_ids:
            raise AuditError(f"duplicate context profile_id: {profile_id}")
        profile_ids.add(profile_id)
        selected = _unique_identifiers(profile["case_ids"], f"{label}.case_ids", minimum=1, maximum=500)
        if set(selected) - known_cases:
            raise AuditError(f"{label} names unknown cases")
        _integer(profile["repetitions"], f"{label}.repetitions", 1, 100)
        _integer(profile["max_invocations"], f"{label}.max_invocations", 1, 10000)
        _integer(profile["max_seconds"], f"{label}.max_seconds", 1, 86400)
        if profile["max_tokens"] is not None:
            _integer(profile["max_tokens"], f"{label}.max_tokens", 1, 1_000_000_000)
        _number_or_null(profile["max_cost_usd"], f"{label}.max_cost_usd")
    sources = _array(context["evidence_sources"], "context.evidence_sources", maximum=MAX_EVIDENCE_SOURCES)
    source_ids: set[str] = set()
    for index, raw_source in enumerate(sources):
        label = f"context.evidence_sources[{index}]"
        source = _object(raw_source, label)
        _exact(source, label, ("source_id", "path", "sha256", "schema_version", "authority"))
        source_id = _identifier(source["source_id"], f"{label}.source_id")
        if source_id in source_ids:
            raise AuditError(f"duplicate context source_id: {source_id}")
        source_ids.add(source_id)
        _text(source["path"], f"{label}.path", maximum=4096)
        _sha(source["sha256"], f"{label}.sha256")
        _enum(source["schema_version"], f"{label}.schema_version", {"project-eval-run-result/v1", "eval-candidate-result/v1"})
        if source["authority"] != "evidence_only":
            raise AuditError(f"{label}.authority must be evidence_only")
    evidence = _array(context["evidence"], "context.evidence", maximum=MAX_EVIDENCE)
    evidence_ids: set[str] = set()
    summary_bytes = 0
    for index, raw_item in enumerate(evidence):
        label = f"context.evidence[{index}]"
        item = _object(raw_item, label)
        _exact(item, label, ("evidence_id", "kind", "sha256", "summary", "redacted", "case_ids"))
        evidence_id = _identifier(item["evidence_id"], f"{label}.evidence_id")
        if evidence_id in evidence_ids:
            raise AuditError(f"duplicate context evidence_id: {evidence_id}")
        evidence_ids.add(evidence_id)
        _enum(item["kind"], f"{label}.kind", {"session_summary", "run_receipt", "assertion", "measurement", "repository"})
        _sha(item["sha256"], f"{label}.sha256")
        summary = _text(item["summary"], f"{label}.summary", maximum=500, secret_check=True)
        summary_bytes += len(summary.encode("utf-8"))
        if item["redacted"] is not True:
            raise AuditError(f"{label}.redacted must be true")
        item_cases = _unique_identifiers(item["case_ids"], f"{label}.case_ids", minimum=1)
        if set(item_cases) - known_cases:
            raise AuditError(f"{label} names unknown cases")
    if summary_bytes > MAX_SUMMARY_BYTES:
        raise AuditError("context evidence summaries exceed the byte limit")
    limits = {"max_input_bytes": MAX_INPUT_BYTES, "max_evidence_sources": MAX_EVIDENCE_SOURCES, "max_evidence": MAX_EVIDENCE, "max_summary_bytes": MAX_SUMMARY_BYTES, "max_fixture_entries": MAX_FIXTURE_ENTRIES, "max_fixture_files": MAX_FIXTURE_FILES, "max_fixture_bytes": MAX_FIXTURE_BYTES}
    if context["limits"] != limits:
        raise AuditError("context.limits do not match locked v1 limits")
    for index, item in enumerate(_array(context["limitations"], "context.limitations", maximum=2000)):
        _limitation(item, f"context.limitations[{index}]")
    if _sha(context["context_sha256"], "context.context_sha256") != _sha_bytes(_canonical_bytes(_context_without_digest(context))):
        raise AuditError("context_sha256 does not match canonical context")
    if current:
        suite, committed_raw, relative, head, repository_sha, fixture_bindings = _load_committed_suite(Path(context["repository_root"]), suite_meta["path"])
        current_cases, current_profiles = _case_context(suite, fixture_bindings)
        suite_digest = _sha_bytes(_canonical_bytes(suite))
        if head != context["repository_head"] or repository_sha != context["repository_sha256"]:
            raise AuditError("repository changed after suite context resolution")
        if relative != suite_meta["path"] or _sha_bytes(committed_raw) != suite_meta["source_sha256"] or suite_digest != suite_meta["suite_digest"]:
            raise AuditError("suite changed after context resolution")
        if current_cases != cases or current_profiles != profiles:
            raise AuditError("suite context differs from committed definitions")
        rebuilt = _definition_evidence(current_cases)
        for source in sources:
            source_value, source_raw = _read_json(Path(source["path"]), "selected evidence")
            if _sha_bytes(source_raw) != source["sha256"]:
                raise AuditError("selected evidence changed after context resolution")
            schema, items = _extract_evidence(source_value, suite_digest, known_cases)
            if schema != source["schema_version"]:
                raise AuditError("selected evidence schema changed")
            rebuilt.extend(items)
        if rebuilt != evidence:
            raise AuditError("context evidence differs from current selected inputs")
    return context


def resolve_context(root: Path, suite_path: str, evidence_paths: list[Path]) -> dict[str, Any]:
    if len(evidence_paths) > MAX_EVIDENCE_SOURCES:
        raise AuditError("too many selected evidence files")
    suite, committed_raw, relative, head, repository_sha, fixture_bindings = _load_committed_suite(root, suite_path)
    suite_digest = _sha_bytes(_canonical_bytes(suite))
    cases, profiles = _case_context(suite, fixture_bindings)
    known_cases = {case["case_id"] for case in cases}
    evidence = _definition_evidence(cases)
    sources: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, requested in enumerate(evidence_paths, start=1):
        path = requested.absolute()
        key = os.path.normcase(str(path))
        if key in seen_paths:
            raise AuditError("selected evidence paths must be unique")
        seen_paths.add(key)
        value, raw = _read_json(path, "selected evidence")
        schema, items = _extract_evidence(value, suite_digest, known_cases)
        if len(evidence) + len(items) > MAX_EVIDENCE:
            raise AuditError("selected evidence exceeds the evidence item limit")
        source_id = f"source-{index:03d}"
        sources.append({"source_id": source_id, "path": str(path), "sha256": _sha_bytes(raw), "schema_version": schema, "authority": "evidence_only"})
        evidence.extend(items)
    if len({item["evidence_id"] for item in evidence}) != len(evidence):
        raise AuditError("selected evidence produces duplicate evidence identities")
    context: dict[str, Any] = {
        "schema_version": "eval-suite-audit-context/v1",
        "repository_root": str(root.absolute()),
        "repository_head": head,
        "repository_sha256": repository_sha,
        "suite": {"path": relative, "source_sha256": _sha_bytes(committed_raw), "suite_digest": suite_digest, "suite_id": suite["suite_id"], "title": suite["title"]},
        "cases": cases,
        "profiles": profiles,
        "evidence_sources": sources,
        "evidence": evidence,
        "limits": {"max_input_bytes": MAX_INPUT_BYTES, "max_evidence_sources": MAX_EVIDENCE_SOURCES, "max_evidence": MAX_EVIDENCE, "max_summary_bytes": MAX_SUMMARY_BYTES, "max_fixture_entries": MAX_FIXTURE_ENTRIES, "max_fixture_files": MAX_FIXTURE_FILES, "max_fixture_bytes": MAX_FIXTURE_BYTES},
        "limitations": [],
    }
    context["context_sha256"] = _sha_bytes(_canonical_bytes(context))
    return _validate_context(context)


def _validate_replacement(value: Any, label: str) -> dict[str, Any]:
    replacement = _object(value, label)
    _exact(replacement, label, ("status", "case_ids", "explanation"))
    status = _enum(replacement["status"], f"{label}.status", {"none", "partial", "complete", "unknown"})
    cases = _unique_identifiers(replacement["case_ids"], f"{label}.case_ids")
    if (status == "none") != (not cases):
        raise AuditError(f"{label} status and case_ids disagree")
    _text(replacement["explanation"], f"{label}.explanation", maximum=2000, secret_check=True)
    return replacement


def _validate_draft(value: Any) -> dict[str, Any]:
    draft = _object(value, "draft")
    _exact(draft, "draft", ("completion", "recommendations", "limitations"))
    _enum(draft["completion"], "draft.completion", {"complete", "incomplete"})
    for index, raw_recommendation in enumerate(_array(draft["recommendations"], "draft.recommendations", maximum=2000)):
        label = f"draft.recommendations[{index}]"
        recommendation = _object(raw_recommendation, label)
        _exact(recommendation, label, ("case_ids", "action", "strength", "reason", "confidence", "evidence_ids", "basis", "unique_coverage", "replacement_coverage", "coverage_effect", "cost_effect", "limitations"))
        _unique_identifiers(recommendation["case_ids"], f"{label}.case_ids", minimum=1)
        _enum(recommendation["action"], f"{label}.action", {"keep", "refresh", "merge", "simplify", "demote", "retire"})
        _enum(recommendation["strength"], f"{label}.strength", {"strong", "moderate", "optional"})
        _text(recommendation["reason"], f"{label}.reason", maximum=2000, secret_check=True)
        _enum(recommendation["confidence"], f"{label}.confidence", {"high", "medium", "low", "unknown"})
        _unique_identifiers(recommendation["evidence_ids"], f"{label}.evidence_ids", minimum=1)
        _enum(recommendation["basis"], f"{label}.basis", RETIREMENT_BASES | {"healthy_unique_coverage", "stale_but_relevant", "compaction", "other"})
        _text(recommendation["unique_coverage"], f"{label}.unique_coverage", maximum=2000, secret_check=True)
        _validate_replacement(recommendation["replacement_coverage"], f"{label}.replacement_coverage")
        _enum(recommendation["coverage_effect"], f"{label}.coverage_effect", {"preserved", "loss", "changed", "unknown"})
        _enum(recommendation["cost_effect"], f"{label}.cost_effect", {"decrease", "none", "increase", "unknown"})
        for limitation_index, item in enumerate(_array(recommendation["limitations"], f"{label}.limitations", maximum=64)):
            _limitation(item, f"{label}.limitations[{limitation_index}]")
    root_limits = _array(draft["limitations"], "draft.limitations", maximum=2000)
    for index, item in enumerate(root_limits):
        _limitation(item, f"draft.limitations[{index}]")
    incomplete = draft["completion"] == "incomplete"
    if incomplete != any(item["material"] for item in root_limits):
        raise AuditError("draft.completion must match material root limitations")
    return draft


def _core_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in ("evidence_id", "kind", "sha256", "summary", "redacted")}


def _derived_decision(action: str, coverage: str, cost: str) -> bool:
    return action != "keep" and (
        action == "demote" or coverage != "preserved" or cost in {"increase", "unknown"}
    )


def finalize(context_value: Any, draft_value: Any) -> dict[str, Any]:
    context = _validate_context(context_value, current=True)
    draft = _validate_draft(draft_value)
    known_cases = {case["case_id"] for case in context["cases"]}
    evidence_by_id = {item["evidence_id"]: item for item in context["evidence"]}
    recommendations: list[dict[str, Any]] = []
    for index, item in enumerate(draft["recommendations"]):
        label = f"draft.recommendations[{index}]"
        case_ids = item["case_ids"]
        if set(case_ids) - known_cases:
            raise AuditError(f"{label} names unknown suite cases")
        if item["action"] == "merge" and len(case_ids) < 2:
            raise AuditError(f"{label} merge requires at least two cases")
        if item["action"] == "retire" and item["basis"] not in RETIREMENT_BASES:
            raise AuditError(f"{label} retire lacks a permitted evidence-backed retirement basis")
        replacement = item["replacement_coverage"]
        if set(replacement["case_ids"]) - known_cases:
            raise AuditError(f"{label} replacement coverage names unknown suite cases")
        selected_evidence: list[dict[str, Any]] = []
        for evidence_id in item["evidence_ids"]:
            bound = evidence_by_id.get(evidence_id)
            if bound is None:
                raise AuditError(f"{label} cites evidence outside the frozen context")
            if not set(bound["case_ids"]) & set(case_ids):
                raise AuditError(f"{label} cites evidence unrelated to its cases")
            selected_evidence.append(_core_evidence(bound))
        limitations = item["limitations"]
        decision = _derived_decision(item["action"], item["coverage_effect"], item["cost_effect"])
        ready = item["action"] != "keep" and not decision and item["confidence"] in {"high", "medium"} and not any(limitation["material"] for limitation in limitations)
        semantic = {key: item[key] for key in ("case_ids", "action", "basis", "replacement_coverage")}
        recommendations.append({
            "recommendation_id": f"recommendation-{_sha_bytes(_canonical_bytes(semantic))[:12]}",
            "case_ids": case_ids,
            "action": item["action"],
            "strength": item["strength"],
            "reason": item["reason"],
            "confidence": item["confidence"],
            "evidence": selected_evidence,
            "basis": item["basis"],
            "unique_coverage": item["unique_coverage"],
            "replacement_coverage": replacement,
            "coverage_effect": item["coverage_effect"],
            "cost_effect": item["cost_effect"],
            "decision_required": decision,
            "ready": ready,
            "limitations": limitations,
        })
    limitations = context["limitations"] + draft["limitations"]
    material = any(item["material"] for item in limitations)
    completion = "incomplete" if material or draft["completion"] == "incomplete" else "complete"
    changes = [item for item in recommendations if item["action"] != "keep"]
    if completion == "incomplete":
        outcome, next_action = "unknown", "retry"
    elif not changes:
        outcome, next_action = "pass", "none"
    elif any(item["decision_required"] for item in changes):
        outcome, next_action = "maintenance_recommended", "decision"
    elif any(item["ready"] for item in changes):
        outcome, next_action = "maintenance_recommended", "maintain"
    else:
        outcome, next_action = "maintenance_recommended", "manual"
    result = {
        "schema_version": "eval-suite-audit-result/v1",
        "producer": {"name": "eval-suite-audit", "version": VERSION},
        "context_sha256": context["context_sha256"],
        "completion": completion,
        "outcome": outcome,
        "next_action": next_action,
        "repository_sha256": context["repository_sha256"],
        "suite_digest": context["suite"]["suite_digest"],
        "recommendations": recommendations,
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
    _exact(result, "result", ("schema_version", "producer", "context_sha256", "completion", "outcome", "next_action", "repository_sha256", "suite_digest", "recommendations", "limitations"))
    if result["schema_version"] != "eval-suite-audit-result/v1":
        raise AuditError("unsupported result schema_version")
    producer = _object(result["producer"], "result.producer")
    _exact(producer, "result.producer", ("name", "version"))
    _identifier(producer["name"], "result.producer.name")
    _text(producer["version"], "result.producer.version", maximum=128)
    _sha(result["context_sha256"], "result.context_sha256")
    completion = _enum(result["completion"], "result.completion", {"complete", "incomplete"})
    outcome = _enum(result["outcome"], "result.outcome", {"pass", "maintenance_recommended", "unknown"})
    next_action = _enum(result["next_action"], "result.next_action", {"none", "maintain", "decision", "retry", "manual"})
    _sha(result["repository_sha256"], "result.repository_sha256")
    _sha(result["suite_digest"], "result.suite_digest")
    recommendations = _array(result["recommendations"], "result.recommendations", maximum=2000)
    ids: set[str] = set()
    changes: list[dict[str, Any]] = []
    for index, raw_item in enumerate(recommendations):
        label = f"result.recommendations[{index}]"
        item = _object(raw_item, label)
        _exact(item, label, ("recommendation_id", "case_ids", "action", "strength", "reason", "confidence", "evidence", "basis", "unique_coverage", "replacement_coverage", "coverage_effect", "cost_effect", "decision_required", "ready", "limitations"))
        recommendation_id = _identifier(item["recommendation_id"], f"{label}.recommendation_id")
        if recommendation_id in ids:
            raise AuditError(f"duplicate recommendation_id: {recommendation_id}")
        ids.add(recommendation_id)
        case_ids = _unique_identifiers(item["case_ids"], f"{label}.case_ids", minimum=1)
        action = _enum(item["action"], f"{label}.action", {"keep", "refresh", "merge", "simplify", "demote", "retire"})
        if action == "merge" and len(case_ids) < 2:
            raise AuditError(f"{label} merge requires at least two cases")
        _enum(item["strength"], f"{label}.strength", {"strong", "moderate", "optional"})
        _text(item["reason"], f"{label}.reason", maximum=2000, secret_check=True)
        confidence = _enum(item["confidence"], f"{label}.confidence", {"high", "medium", "low", "unknown"})
        evidence = _array(item["evidence"], f"{label}.evidence", minimum=1, maximum=256)
        for evidence_index, evidence_item in enumerate(evidence):
            _validate_evidence(evidence_item, f"{label}.evidence[{evidence_index}]")
        if len({evidence_item["evidence_id"] for evidence_item in evidence}) != len(evidence):
            raise AuditError(f"{label}.evidence must be unique")
        basis = _enum(item["basis"], f"{label}.basis", RETIREMENT_BASES | {"healthy_unique_coverage", "stale_but_relevant", "compaction", "other"})
        if action == "retire" and basis not in RETIREMENT_BASES:
            raise AuditError(f"{label} retire lacks a permitted retirement basis")
        _text(item["unique_coverage"], f"{label}.unique_coverage", maximum=2000, secret_check=True)
        replacement = _validate_replacement(item["replacement_coverage"], f"{label}.replacement_coverage")
        coverage = _enum(item["coverage_effect"], f"{label}.coverage_effect", {"preserved", "loss", "changed", "unknown"})
        cost = _enum(item["cost_effect"], f"{label}.cost_effect", {"decrease", "none", "increase", "unknown"})
        if not isinstance(item["decision_required"], bool) or not isinstance(item["ready"], bool):
            raise AuditError(f"{label} decision_required and ready must be boolean")
        limitations = [_limitation(limit, f"{label}.limitations[{limit_index}]") for limit_index, limit in enumerate(_array(item["limitations"], f"{label}.limitations", maximum=64))]
        expected_decision = _derived_decision(action, coverage, cost)
        expected_ready = action != "keep" and not expected_decision and confidence in {"high", "medium"} and not any(limit["material"] for limit in limitations)
        if item["decision_required"] != expected_decision or item["ready"] != expected_ready:
            raise AuditError(f"{label} readiness is inconsistent")
        semantic = {"case_ids": case_ids, "action": action, "basis": basis, "replacement_coverage": replacement}
        if recommendation_id != f"recommendation-{_sha_bytes(_canonical_bytes(semantic))[:12]}":
            raise AuditError(f"{label}.recommendation_id is not derived from semantics")
        if action != "keep":
            changes.append(item)
    limitations = [_limitation(item, f"result.limitations[{index}]") for index, item in enumerate(_array(result["limitations"], "result.limitations", maximum=2000))]
    expected_completion = "incomplete" if any(item["material"] for item in limitations) else "complete"
    if completion != expected_completion:
        raise AuditError("result.completion does not match material limitations")
    if completion == "incomplete":
        expected = ("unknown", "retry")
    elif not changes:
        expected = ("pass", "none")
    elif any(item["decision_required"] for item in changes):
        expected = ("maintenance_recommended", "decision")
    elif any(item["ready"] for item in changes):
        expected = ("maintenance_recommended", "maintain")
    else:
        expected = ("maintenance_recommended", "manual")
    if (outcome, next_action) != expected:
        raise AuditError("result outcome or next_action is inconsistent")
    if context is not None:
        frozen = _validate_context(context, current=True)
        if result["context_sha256"] != frozen["context_sha256"] or result["repository_sha256"] != frozen["repository_sha256"] or result["suite_digest"] != frozen["suite"]["suite_digest"]:
            raise AuditError("result is not bound to the selected suite context")
        if producer != {"name": "eval-suite-audit", "version": VERSION}:
            raise AuditError("context-bound result has an unexpected producer")
        known_cases = {case["case_id"] for case in frozen["cases"]}
        evidence_by_id = {item["evidence_id"]: item for item in frozen["evidence"]}
        for index, item in enumerate(recommendations):
            if set(item["case_ids"]) - known_cases or set(item["replacement_coverage"]["case_ids"]) - known_cases:
                raise AuditError(f"result.recommendations[{index}] is not bound to suite cases")
            for evidence_item in item["evidence"]:
                bound = evidence_by_id.get(evidence_item["evidence_id"])
                if bound is None or _core_evidence(bound) != evidence_item or not set(bound["case_ids"]) & set(item["case_ids"]):
                    raise AuditError(f"result.recommendations[{index}] evidence is not context-bound")
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
    lines = ["Eval suite audit", f"Completion: {value['completion']}", f"Outcome: {value['outcome']}", f"Next action: {value['next_action']}", f"Recommendations: {len(value['recommendations'])}"]
    for item in value["recommendations"]:
        lines.extend([
            "",
            f"- [{item['strength']}] {item['action']} — {', '.join(_display(case_id) for case_id in item['case_ids'])}",
            f"  Confidence: {item['confidence']}; ready: {str(item['ready']).lower()}; decision required: {str(item['decision_required']).lower()}",
            f"  Basis: {item['basis']}; coverage: {item['coverage_effect']}; cost: {item['cost_effect']}",
            f"  Reason: {_display(item['reason'])}",
            f"  Unique coverage: {_display(item['unique_coverage'])}",
            f"  Replacement: {item['replacement_coverage']['status']} — {_display(item['replacement_coverage']['explanation'])}",
            "  Evidence: " + "; ".join(f"{_display(evidence['evidence_id'])}: {_display(evidence['summary'])}" for evidence in item["evidence"]),
        ])
    if value["limitations"]:
        lines.extend(["", "Limitations:"])
        for item in value["limitations"]:
            lines.append(f"- {'material' if item['material'] else 'non-material'} {_display(item['code'])}: {_display(item['message'])}")
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
    resolve = commands.add_parser("resolve")
    resolve.add_argument("--repo", required=True)
    resolve.add_argument("--suite", required=True)
    resolve.add_argument("--evidence", action="append", default=[])
    resolve.add_argument("--output", required=True)
    finalize_command = commands.add_parser("finalize")
    finalize_command.add_argument("--context", required=True)
    finalize_command.add_argument("--input", required=True)
    finalize_command.add_argument("--format", choices=("human", "json", "both"), default="human")
    finalize_command.add_argument("--output")
    validate_command = commands.add_parser("validate")
    validate_command.add_argument("--input", required=True)
    validate_command.add_argument("--context")
    render_command = commands.add_parser("render")
    render_command.add_argument("--input", required=True)
    render_command.add_argument("--format", choices=("human", "json"), default="human")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "resolve":
            context = resolve_context(Path(args.repo), args.suite, [Path(item) for item in args.evidence])
            path_safety.write_created_output(Path(args.output), _canonical_bytes(context))
        elif args.command == "finalize":
            context, _ = _read_json(Path(args.context), "suite context")
            draft, _ = _read_json(Path(args.input), "suite audit draft")
            _emit(finalize(context, draft), args.format, Path(args.output) if args.output else None)
        elif args.command == "validate":
            result, _ = _read_json(Path(args.input), "suite audit result")
            context = None
            if args.context:
                context, _ = _read_json(Path(args.context), "suite context")
            validate_result(result, context=context)
            sys.stdout.write('{"schema_version":"eval-suite-audit-result/v1","valid":true}\n')
        else:
            result, _ = _read_json(Path(args.input), "suite audit result")
            value = validate_result(result)
            if args.format == "json":
                sys.stdout.buffer.write(_canonical_bytes(value))
            else:
                sys.stdout.write(render(value))
    except (AuditError, OSError, path_safety.SafetyError) as exc:
        sys.stderr.write(f"eval-suite-audit: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
