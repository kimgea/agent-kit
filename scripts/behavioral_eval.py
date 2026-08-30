#!/usr/bin/env python3
"""Check, run, and grade local behavioral evaluations for agent-kit skills."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from typing import Any
import uuid


ROOT = Path(__file__).resolve().parent.parent
RESOURCE_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 16 * 1024 * 1024
MAX_ENVELOPE_BYTES = 32 * 1024 * 1024
MAX_EVENT_BYTES = 32 * 1024 * 1024
MAX_RUNNER_BYTES = 512 * 1024 * 1024
MAX_FIXTURE_FILES = 1000
MAX_FIXTURE_FILE_BYTES = 2 * 1024 * 1024
MAX_FIXTURE_BYTES = 16 * 1024 * 1024
MAX_CASES = 256
MAX_ASSERTIONS = 128
MAX_PROMPT_BYTES = 64 * 1024
MAX_TIMEOUT_SECONDS = 3600
DEFAULT_TIMEOUT_SECONDS = 900
RESULT_KEYS = ("target", "guidance", "context_metrics")


CONTRACTS = {
    "review-guidance-audit/v1": {
        "skill": "review-guidance-audit",
        "context": "skills/review-guidance-audit/scripts/guidance_context.py",
        "validator": "skills/review-guidance-audit/scripts/guidance_result.py",
        "schema": "skills/review-guidance-audit/references/review-guidance-result.schema.json",
    }
}


class EvalError(ValueError):
    """Raised when behavioral evaluation input or execution is unsafe or invalid."""


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvalError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _read_bytes(path: Path, label: str, ceiling: int) -> bytes:
    _assert_no_link_components(path, include_final=True)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise EvalError(f"cannot inspect {label}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise EvalError(f"{label} must be a regular non-link file")
    if metadata.st_size > ceiling:
        raise EvalError(f"{label} exceeds the {ceiling}-byte limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            data = handle.read(ceiling + 1)
    except OSError as exc:
        raise EvalError(f"cannot read {label}: {exc}") from exc
    if len(data) > ceiling:
        raise EvalError(f"{label} exceeds the {ceiling}-byte limit")
    return data


def _load_json(path: Path, label: str, ceiling: int = MAX_RESULT_BYTES) -> Any:
    data = _read_bytes(path, label, ceiling)
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvalError(f"invalid UTF-8 JSON in {label}: {exc}") from exc


def _sha256_file(path: Path, label: str, ceiling: int) -> str:
    _assert_no_link_components(path, include_final=True)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise EvalError(f"cannot inspect {label}: {exc}") from exc
    if _metadata_is_link_like(metadata) or not stat.S_ISREG(metadata.st_mode):
        raise EvalError(f"{label} must be a regular non-link file")
    if metadata.st_size > ceiling:
        raise EvalError(f"{label} exceeds the {ceiling}-byte limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    digest = hashlib.sha256()
    total = 0
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                total += len(chunk)
                if total > ceiling:
                    raise EvalError(f"{label} exceeds the {ceiling}-byte limit")
                digest.update(chunk)
    except OSError as exc:
        raise EvalError(f"cannot read {label}: {exc}") from exc
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _object(value: Any, label: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvalError(f"{label} must be an object")
    missing = keys - set(value)
    extra = set(value) - keys
    if missing:
        raise EvalError(f"{label} is missing fields: {sorted(missing)}")
    if extra:
        raise EvalError(f"{label} has unknown fields: {sorted(extra)}")
    return value


def _string(value: Any, label: str, maximum_bytes: int) -> str:
    if not isinstance(value, str) or not value:
        raise EvalError(f"{label} must be a non-empty string")
    if CONTROL.search(value):
        raise EvalError(f"{label} must not contain control characters")
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise EvalError(f"{label} must be valid UTF-8") from exc
    if len(encoded) > maximum_bytes:
        raise EvalError(f"{label} exceeds the {maximum_bytes}-byte limit")
    return value


def _resource_id(value: Any, label: str) -> str:
    text = _string(value, label, 64)
    if not RESOURCE_ID.fullmatch(text):
        raise EvalError(f"{label} must be lowercase kebab-case")
    return text


def _relative_path(value: Any, label: str, *, allow_root: bool = False) -> str:
    text = _string(value, label, 4096)
    if text == "." and allow_root:
        return text
    if "\\" in text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise EvalError(f"{label} must be a canonical repository-relative path")
    parts = PurePosixPath(text).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise EvalError(f"{label} must be a canonical repository-relative path")
    if PurePosixPath(*parts).as_posix() != text or text.endswith("/"):
        raise EvalError(f"{label} must be a canonical repository-relative path")
    return text


def _safe_repository_path(root: Path, relative: str, label: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise EvalError(f"{label} escapes the repository") from exc
    return candidate


def _is_link_like(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return _metadata_is_link_like(metadata)


def _metadata_is_link_like(metadata: os.stat_result | Any) -> bool:
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
            raise EvalError(f"refusing link-like path component: {current}")


def _load_catalog(root: Path) -> dict[str, Any]:
    path = root / "toolkit.toml"
    try:
        return tomllib.loads(
            _read_bytes(path, "toolkit catalog", MAX_MANIFEST_BYTES).decode("utf-8")
        )
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise EvalError(f"cannot load toolkit catalog: {exc}") from exc


def _validate_agent_envelope_schema_path(path: Path) -> Path:
    value = _load_json(path, "behavioral agent result schema", 65536)
    expected = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["result_json"],
        "properties": {"result_json": {"type": "string"}},
    }
    if value != expected:
        raise EvalError("behavioral agent result schema does not match the fixed contract")
    return path


def _validate_agent_envelope_schema(root: Path) -> Path:
    return _validate_agent_envelope_schema_path(
        root / "evals" / "behavioral-agent-result.schema.json"
    )


def _suite_path(root: Path, suite_id: str) -> Path:
    catalog = _load_catalog(root)
    matches = [
        item
        for item in catalog.get("resources", [])
        if isinstance(item, dict) and item.get("id") == suite_id
    ]
    if len(matches) != 1:
        raise EvalError(f"unknown or ambiguous suite resource: {suite_id}")
    relative = matches[0].get("behavioral_evals")
    if not isinstance(relative, str):
        raise EvalError(f"{suite_id} has no executable behavioral suite")
    canonical = _relative_path(relative, f"{suite_id}.behavioral_evals")
    path = _safe_repository_path(root, canonical, "behavioral suite")
    if not path.is_file() or path.is_symlink():
        raise EvalError(f"behavioral suite is not a regular file: {canonical}")
    return path


def _validate_target(value: Any, label: str) -> dict[str, Any]:
    target = _object(value, label, {"kind", "path", "start_line", "end_line"})
    kind = target["kind"]
    if kind not in {"path", "part"}:
        raise EvalError(f"{label}.kind must be path or part")
    target["path"] = _relative_path(target["path"], f"{label}.path", allow_root=True)
    start = target["start_line"]
    end = target["end_line"]
    if kind == "part":
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 1
            or end < start
            or end > 100_000_000
        ):
            raise EvalError(f"{label} has an invalid part range")
    elif start is not None or end is not None:
        raise EvalError(f"{label} path target must use null line values")
    return target


def _validate_assertion(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label, {"id", "path", "operator", "value"})
    _resource_id(item["id"], f"{label}.id")
    pointer = _string(item["path"], f"{label}.path", 4096)
    if pointer != "" and not pointer.startswith("/"):
        raise EvalError(f"{label}.path must be an empty or slash-prefixed JSON pointer")
    operator = item["operator"]
    if operator not in {
        "equals",
        "not_equals",
        "any",
        "none",
        "count_equals",
        "count_at_least",
        "sequence",
    }:
        raise EvalError(f"{label}.operator is unsupported")
    if operator in {"count_equals", "count_at_least"} and (
        not isinstance(item["value"], int)
        or isinstance(item["value"], bool)
        or item["value"] < 0
    ):
        raise EvalError(f"{label}.value must be a non-negative integer")
    if operator == "sequence" and not isinstance(item["value"], list):
        raise EvalError(f"{label}.value must be an array for sequence")
    if len(_canonical_json(item["value"])) > 65536:
        raise EvalError(f"{label}.value is too large")
    return item


def _load_suite_bundle(
    root: Path, suite_id: str
) -> tuple[dict[str, Any], Path, bytes]:
    _validate_agent_envelope_schema(root)
    path = _suite_path(root, suite_id)
    source_bytes = _read_bytes(path, "behavioral suite", MAX_MANIFEST_BYTES)
    try:
        value = json.loads(
            source_bytes.decode("utf-8"), object_pairs_hook=_reject_duplicates
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvalError(f"invalid UTF-8 JSON in behavioral suite: {exc}") from exc
    suite = _object(
        value,
        "suite",
        {
            "schema_version",
            "suite",
            "skill",
            "result_contract",
            "default_assertions",
            "cases",
        },
    )
    if suite["schema_version"] != 1:
        raise EvalError("suite.schema_version must be 1")
    if _resource_id(suite["suite"], "suite.suite") != suite_id:
        raise EvalError("suite id does not match the requested resource")
    skill = _resource_id(suite["skill"], "suite.skill")
    contract_id = _string(suite["result_contract"], "suite.result_contract", 128)
    contract = CONTRACTS.get(contract_id)
    if contract is None or contract["skill"] != skill:
        raise EvalError("suite selects an unsupported result contract")
    for label, contract_path in _contract(suite, root).items():
        _read_bytes(contract_path, f"result contract {label}", MAX_RESULT_BYTES)
    defaults = suite["default_assertions"]
    if not isinstance(defaults, list) or len(defaults) > MAX_ASSERTIONS:
        raise EvalError("suite.default_assertions must be a bounded array")
    default_ids: set[str] = set()
    for index, assertion in enumerate(defaults):
        validated = _validate_assertion(assertion, f"default_assertions[{index}]")
        if validated["id"] in default_ids:
            raise EvalError(f"duplicate default assertion id: {validated['id']}")
        default_ids.add(validated["id"])
    cases = suite["cases"]
    if not isinstance(cases, list) or not cases or len(cases) > MAX_CASES:
        raise EvalError("suite.cases must be a non-empty bounded array")
    case_ids: set[str] = set()
    manifest_root = path.parent
    fixture_root = manifest_root / "fixtures"
    for index, raw_case in enumerate(cases):
        case = _object(
            raw_case,
            f"cases[{index}]",
            {"id", "fixture", "target", "prompt", "assertions", "forbidden_commands"},
        )
        case_id = _resource_id(case["id"], f"cases[{index}].id")
        if case_id in case_ids:
            raise EvalError(f"duplicate case id: {case_id}")
        case_ids.add(case_id)
        fixture = _relative_path(case["fixture"], f"cases[{index}].fixture")
        expected_fixture = f"fixtures/{case_id}"
        if fixture != expected_fixture:
            raise EvalError(
                f"cases[{index}].fixture must be {expected_fixture!r}"
            )
        _validate_target(case["target"], f"cases[{index}].target")
        _string(case["prompt"], f"cases[{index}].prompt", MAX_PROMPT_BYTES)
        assertions = case["assertions"]
        if not isinstance(assertions, list) or len(assertions) > MAX_ASSERTIONS:
            raise EvalError(f"cases[{index}].assertions must be a bounded array")
        assertion_ids = set(default_ids)
        for assertion_index, assertion in enumerate(assertions):
            validated = _validate_assertion(
                assertion, f"cases[{index}].assertions[{assertion_index}]"
            )
            if validated["id"] in assertion_ids:
                raise EvalError(
                    f"duplicate assertion id in {case_id}: {validated['id']}"
                )
            assertion_ids.add(validated["id"])
        forbidden = case["forbidden_commands"]
        if not isinstance(forbidden, list) or len(forbidden) > 32:
            raise EvalError(f"cases[{index}].forbidden_commands must be a bounded array")
        for command_index, pattern in enumerate(forbidden):
            _relative_path(
                pattern,
                f"cases[{index}].forbidden_commands[{command_index}]",
            )
        fixture_path = _safe_repository_path(manifest_root, fixture, "fixture")
        if fixture_root not in fixture_path.parents:
            raise EvalError(f"fixture is outside the suite fixture root: {fixture}")
        snapshot_fixture(fixture_path)
    return suite, path, source_bytes


def load_suite(root: Path, suite_id: str) -> dict[str, Any]:
    return _load_suite_bundle(root, suite_id)[0]


def snapshot_fixture(root: Path) -> dict[str, dict[str, Any]]:
    _assert_no_link_components(root, include_final=True)
    try:
        metadata = root.lstat()
    except OSError as exc:
        raise EvalError(f"cannot inspect fixture {root}: {exc}") from exc
    if _metadata_is_link_like(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise EvalError(f"fixture must be a regular non-link directory: {root}")
    snapshot: dict[str, dict[str, Any]] = {}
    total = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise EvalError(f"cannot inspect fixture directory {directory}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            _relative_path(relative, "fixture entry")
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise EvalError(f"cannot inspect fixture entry {relative}: {exc}") from exc
            if _metadata_is_link_like(info) or _is_link_like(path):
                raise EvalError(f"fixture contains a link-like entry: {relative}")
            if stat.S_ISDIR(info.st_mode):
                pending.append(path)
                continue
            if not stat.S_ISREG(info.st_mode):
                raise EvalError(f"fixture contains a non-regular entry: {relative}")
            if len(snapshot) >= MAX_FIXTURE_FILES:
                raise EvalError("fixture has too many files")
            data = _read_bytes(path, f"fixture file {relative}", MAX_FIXTURE_FILE_BYTES)
            total += len(data)
            if total > MAX_FIXTURE_BYTES:
                raise EvalError("fixture exceeds the total byte limit")
            snapshot[relative] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "mode": stat.S_IMODE(info.st_mode),
                "data": data,
            }
    if not snapshot:
        raise EvalError(f"fixture must contain at least one file: {root}")
    return snapshot


def _snapshot_identity(snapshot: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        path: {key: value[key] for key in ("sha256", "bytes", "mode")}
        for path, value in snapshot.items()
    }


def materialize_fixture(source: Path, destination: Path) -> dict[str, dict[str, Any]]:
    snapshot = snapshot_fixture(source)
    _materialize_snapshot(snapshot, destination)
    return snapshot


def _materialize_snapshot(
    snapshot: dict[str, dict[str, Any]], destination: Path
) -> None:
    destination.mkdir(mode=0o700)
    for relative, item in snapshot.items():
        output = destination.joinpath(*PurePosixPath(relative).parts)
        output.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(output, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(item["data"])
        os.chmod(output, item["mode"])


def materialize_skill(source: Path, destination: Path) -> dict[str, dict[str, Any]]:
    snapshot = skill_snapshot(source)
    _materialize_snapshot(snapshot, destination)
    return snapshot


def skill_snapshot(source: Path) -> dict[str, dict[str, Any]]:
    snapshot = {
        path: item
        for path, item in snapshot_fixture(source).items()
        if "__pycache__" not in PurePosixPath(path).parts and not path.endswith(".pyc")
    }
    if not snapshot:
        raise EvalError("evaluated skill has no distributable files")
    return snapshot


def _snapshot_digest(snapshot: dict[str, dict[str, Any]]) -> str:
    return _sha256_json(
        [
            (
                relative,
                item["sha256"],
                item["bytes"],
                item["mode"],
            )
            for relative, item in sorted(snapshot.items())
        ]
    )


def _case_by_id(suite: dict[str, Any], case_id: str) -> dict[str, Any]:
    matches = [case for case in suite["cases"] if case["id"] == case_id]
    if len(matches) != 1:
        raise EvalError(f"unknown case: {case_id}")
    return matches[0]


def _contract(
    suite: dict[str, Any], root: Path, runtime_skill: Path | None = None
) -> dict[str, Path]:
    raw = CONTRACTS[suite["result_contract"]]
    result: dict[str, Path] = {}
    prefix = f"skills/{suite['skill']}/"
    for key, value in raw.items():
        if key == "skill":
            continue
        relative = _relative_path(value, key)
        if runtime_skill is not None and relative.startswith(prefix):
            nested = relative[len(prefix) :]
            result[key] = _safe_repository_path(runtime_skill, nested, key)
        else:
            result[key] = _safe_repository_path(root, relative, key)
    return result


def resolve_context(
    suite: dict[str, Any],
    case: dict[str, Any],
    fixture: Path,
    output: Path,
    root: Path,
    runtime_skill: Path | None = None,
) -> dict[str, Any]:
    contract = _contract(suite, root, runtime_skill)
    target = case["target"]
    command = [sys.executable, str(contract["context"]), "--repo", str(fixture)]
    if target["kind"] == "part":
        command.extend(
            [
                "--part",
                f"{target['path']}:{target['start_line']}:{target['end_line']}",
            ]
        )
    else:
        command.extend(["--path", target["path"]])
    command.extend(["--output", str(output)])
    completed = subprocess.run(
        command,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace")[:2000]
        raise EvalError(f"context resolver failed: {message}")
    return _load_json(output, "resolved context")


def validate_result_contract(
    suite: dict[str, Any],
    result_path: Path,
    root: Path,
    runtime_skill: Path | None = None,
) -> tuple[bool, str]:
    contract = _contract(suite, root, runtime_skill)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(contract["validator"]),
                "validate",
                "--input",
                str(result_path),
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "result validator timed out"
    if completed.returncode == 0:
        return True, "canonical result validator passed"
    message = completed.stderr.decode("utf-8", "replace")[:2000].strip()
    return False, message or "canonical result validator failed"


def _result_guidance(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "chain_id": chain["chain_id"],
            "applies_to": list(chain["applies_to"]),
            "sources": [
                {
                    key: source[key]
                    for key in (
                        "source_kind",
                        "path",
                        "revision",
                        "sha256",
                        "bytes",
                        "words",
                        "lines",
                        "loaded",
                    )
                }
                for source in chain["sources"]
            ],
            "effective_bytes": chain["effective_bytes"],
            "effective_words": chain["effective_words"],
            "complete": chain["complete"],
        }
        for chain in context["guidance"]
    ]


def _bind_result(context: Any, result: Any) -> tuple[bool, str]:
    if not isinstance(context, dict) or not isinstance(result, dict):
        return False, "context and result must be objects"
    if result.get("context_sha256") != _sha256_json(context):
        return False, "result context digest does not match the lead-owned context"
    expected = {
        "target": context.get("target"),
        "guidance": _result_guidance(context) if isinstance(context.get("guidance"), list) else None,
        "context_metrics": context.get("context_metrics"),
    }
    for key in RESULT_KEYS:
        if result.get(key) != expected[key]:
            return False, f"result {key} does not match the lead-owned context"
    return True, "result authority fields match the lead-owned context"


def _normalize_context_root(context: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(context))
    if isinstance(value.get("target"), dict):
        value["target"]["repository_root"] = "<fixture-root>"
    for chain in value.get("guidance", []):
        if not isinstance(chain, dict):
            continue
        for source in chain.get("sources", []):
            if isinstance(source, dict) and source.get("source_kind") == "skill":
                source["path"] = "<evaluated-skill>/SKILL.md"
    return value


def _decode_pointer_segment(value: str) -> str:
    return value.replace("~1", "/").replace("~0", "~")


def select_values(document: Any, pointer: str) -> list[Any]:
    if pointer == "":
        return [document]
    segments = [_decode_pointer_segment(item) for item in pointer[1:].split("/")]
    current = [document]
    for segment in segments:
        following: list[Any] = []
        for value in current:
            if segment == "*" and isinstance(value, list):
                following.extend(value)
            elif segment == "*" and isinstance(value, dict):
                following.extend(value[key] for key in sorted(value))
            elif isinstance(value, dict) and segment in value:
                following.append(value[segment])
            elif isinstance(value, list) and segment.isdigit():
                index = int(segment)
                if index < len(value):
                    following.append(value[index])
        current = following
    return current


def partial_match(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and partial_match(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(partial_match(item, expected_item) for item in actual)
            for expected_item in expected
        )
    return actual == expected


def evaluate_assertion(result: Any, assertion: dict[str, Any]) -> dict[str, Any]:
    selected = select_values(result, assertion["path"])
    operator = assertion["operator"]
    expected = assertion["value"]
    if operator == "equals":
        passed = len(selected) == 1 and selected[0] == expected
    elif operator == "not_equals":
        passed = len(selected) == 1 and selected[0] != expected
    elif operator == "any":
        passed = any(partial_match(value, expected) for value in selected)
    elif operator == "none":
        passed = not any(partial_match(value, expected) for value in selected)
    elif operator == "count_equals":
        passed = len(selected) == expected
    elif operator == "count_at_least":
        passed = len(selected) >= expected
    else:
        cursor = 0
        for value in selected:
            if cursor < len(expected) and partial_match(value, expected[cursor]):
                cursor += 1
        passed = cursor == len(expected)
    return {
        "id": assertion["id"],
        "passed": passed,
        "operator": operator,
        "path": assertion["path"],
        "observed_count": len(selected),
    }


def grade_case(
    suite: dict[str, Any],
    case: dict[str, Any],
    context: dict[str, Any],
    expected_context: dict[str, Any],
    result: dict[str, Any],
    result_path: Path,
    root: Path,
    *,
    runtime_skill: Path | None = None,
    mutation_free: bool | None,
    forbidden_commands: list[str] | None,
) -> dict[str, Any]:
    contract_ok, contract_message = validate_result_contract(
        suite, result_path, root, runtime_skill
    )
    binding_ok, binding_message = _bind_result(context, result)
    fixture_context_ok = _normalize_context_root(context) == _normalize_context_root(
        expected_context
    )
    assertions = [*suite["default_assertions"], *case["assertions"]]
    assertion_results = [evaluate_assertion(result, item) for item in assertions]
    forbidden_ok = not forbidden_commands
    passed = (
        contract_ok
        and binding_ok
        and fixture_context_ok
        and all(item["passed"] for item in assertion_results)
        and mutation_free is not False
        and forbidden_ok
    )
    return {
        "schema_version": 1,
        "suite": suite["suite"],
        "case": case["id"],
        "passed": passed,
        "canonical_validation": {"passed": contract_ok, "message": contract_message},
        "authority_binding": {"passed": binding_ok, "message": binding_message},
        "fixture_context": {
            "passed": fixture_context_ok,
            "message": "context matches the suite fixture and selected target"
            if fixture_context_ok
            else "context does not match the suite fixture and selected target",
        },
        "fixture_mutation_free": mutation_free,
        "forbidden_commands": forbidden_commands or [],
        "assertions": assertion_results,
    }


def _write_new_json(path: Path, value: Any) -> None:
    data = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    if len(data) > MAX_RESULT_BYTES:
        raise EvalError("evaluation evidence exceeds the result size limit")
    _assert_no_link_components(path, include_final=False)
    if not path.parent.is_dir() or _is_link_like(path.parent):
        raise EvalError(f"output parent must be an existing non-link directory: {path.parent}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise EvalError(f"cannot create output {path}: {exc}") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def _command_strings(value: Any) -> list[str]:
    commands: list[str] = []
    if isinstance(value, dict):
        event_type = value.get("type")
        command_event = isinstance(event_type, str) and any(
            marker in event_type.casefold() for marker in ("command", "shell", "exec")
        )
        if command_event:
            for key in ("command", "cmd"):
                command = value.get(key)
                if isinstance(command, str):
                    commands.append(command)
                elif isinstance(command, list) and all(
                    isinstance(item, str) for item in command
                ):
                    commands.append(" ".join(command))
        for nested in value.values():
            commands.extend(_command_strings(nested))
    elif isinstance(value, list):
        for nested in value:
            commands.extend(_command_strings(nested))
    return commands


def _parse_event_commands(path: Path) -> list[str]:
    data = _read_bytes(path, "Codex event stream", MAX_EVENT_BYTES)
    commands: list[str] = []
    for line_number, line in enumerate(data.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line.decode("utf-8"), object_pairs_hook=_reject_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvalError(f"invalid Codex JSONL event at line {line_number}: {exc}") from exc
        commands.extend(_command_strings(event))
    return commands


def _command_segments(command: str) -> list[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return [[command]]
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and all(character in ";|&" for character in token):
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _forbidden_command_hits(
    commands: list[str], forbidden_paths: list[str]
) -> list[str]:
    readers = {"cat", "file", "grep", "head", "rg", "sed", "stat", "tail", "wc"}
    shell_names = {"bash", "dash", "sh", "zsh"}
    hits: list[str] = []

    def token_matches(token: str, forbidden: str) -> bool:
        normalized = token.replace("\\", "/").rstrip("/")
        return normalized == forbidden or normalized.endswith(f"/{forbidden}")

    def inspect(command_text: str) -> None:
        for segment in _command_segments(command_text):
            if not segment:
                continue
            executable = PurePosixPath(segment[0].replace("\\", "/")).name
            if executable in shell_names and "-c" in segment:
                index = segment.index("-c")
                if index + 1 < len(segment):
                    inspect(segment[index + 1])
                continue
            matched = [
                forbidden
                for forbidden in forbidden_paths
                if any(token_matches(token, forbidden) for token in segment)
            ]
            if matched and executable not in readers:
                hits.extend(matched)

    for command in commands:
        inspect(command)
    return list(dict.fromkeys(hits))


def _event_error_summary(path: Path) -> str:
    data = _read_bytes(path, "Codex event stream", MAX_EVENT_BYTES)
    messages: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in {"message", "error", "detail", "reason"} and isinstance(
                    nested, str
                ):
                    messages.append(nested)
                else:
                    collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    for line in data.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line.decode("utf-8"), object_pairs_hook=_reject_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        event_type = event.get("type") if isinstance(event, dict) else None
        if isinstance(event_type, str) and any(
            marker in event_type.casefold() for marker in ("error", "fail")
        ):
            collect(event)
    summary = " | ".join(dict.fromkeys(message.strip() for message in messages if message.strip()))
    return summary[:2000]


def _runner_prompt(
    suite: dict[str, Any],
    case: dict[str, Any],
    fixture: Path,
    work: Path,
    runtime_skill: Path,
) -> str:
    skill = runtime_skill / "SKILL.md"
    context = work / "context.json"
    draft = work / "draft.json"
    return f"""Use the skill at {skill} to perform this request against the repository at {fixture}.

The caller has already selected and resolved the target. The exact lead-owned
resolver context is {context}. Treat it as immutable authority: do not replace,
regenerate, or edit it. Keep any semantic draft at {draft}; do not write inside
the repository. Follow the skill completely, finalize against that exact
context. Your final response must be one JSON object with exactly one field,
`result_json`, whose string value is the exact canonical JSON emitted by the
skill finalizer. Do not add a Markdown fence or prose. Do not install
dependencies, access remote systems, or perform mutations.

Request:
{case['prompt']}
"""


def _codex_command_prefix(
    launcher: Path, platform: str, command_processor: Path | None = None
) -> tuple[list[str], str]:
    if platform == "nt" and launcher.suffix.casefold() in {".bat", ".cmd"}:
        if command_processor is None:
            raise EvalError("Windows batch launch requires a command processor")
        return (
            [
                str(command_processor),
                "/d",
                "/s",
                "/c",
                str(launcher),
            ],
            "windows-batch",
        )
    return [str(launcher)], "native"


def discover_codex_runner() -> dict[str, Any]:
    names = ("codex.exe", "codex") if os.name == "nt" else ("codex",)
    discovered = None
    for name in names:
        discovered = shutil.which(name)
        if discovered:
            break
    if discovered is None:
        raise EvalError("Codex CLI is not installed")
    candidate = Path(discovered).absolute()
    suffix = candidate.suffix.casefold()
    if os.name == "nt" and suffix in {".bat", ".cmd"}:
        _assert_no_link_components(candidate, include_final=True)
        launcher = candidate
        raw_executor = os.environ.get("COMSPEC") or shutil.which("cmd.exe")
        if not raw_executor:
            raise EvalError("Windows command processor is unavailable")
        try:
            executor = Path(raw_executor).resolve(strict=True)
        except OSError as exc:
            raise EvalError(f"cannot resolve Windows command processor: {exc}") from exc
        command, kind = _codex_command_prefix(launcher, os.name, executor)
    else:
        try:
            launcher = candidate.resolve(strict=True)
        except OSError as exc:
            raise EvalError(f"cannot resolve Codex launcher: {exc}") from exc
        _assert_no_link_components(launcher, include_final=True)
        if os.name == "nt" and launcher.suffix.casefold() not in {".com", ".exe"}:
            raise EvalError("Codex launcher must be a Windows executable or batch file")
        command, kind = _codex_command_prefix(launcher, os.name)
    components = [
        ("launcher", _sha256_file(launcher, "Codex launcher", MAX_RUNNER_BYTES))
    ]
    if os.name == "nt" and suffix in {".bat", ".cmd"}:
        components.append(
            (
                "command-processor",
                _sha256_file(executor, "Windows command processor", MAX_RUNNER_BYTES),
            )
        )
    runner_sha256 = _sha256_json(components)
    try:
        completed = subprocess.run(
            [*command, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvalError(f"cannot inspect Codex version: {exc}") from exc
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace")[:1000].strip()
        raise EvalError(message or "Codex version command failed")
    version = completed.stdout.decode("utf-8", "replace").strip()
    if not version or CONTROL.search(version) or len(version.encode("utf-8")) > 1000:
        raise EvalError("Codex version output is invalid")
    return {
        "command": command,
        "kind": kind,
        "sha256": runner_sha256,
        "version": version,
    }


def build_codex_command(
    suite: dict[str, Any],
    fixture: Path,
    work: Path,
    result: Path,
    root: Path,
    model: str,
    reasoning_effort: str,
    runner: dict[str, Any] | None = None,
) -> list[str]:
    runner = runner or discover_codex_runner()
    output_schema = _validate_agent_envelope_schema_path(
        work / "agent-result.schema.json"
    )
    command = [
        *runner["command"],
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--strict-config",
        "--approve-for-me",
        "--cd",
        str(fixture),
        "--add-dir",
        str(work),
        "--skip-git-repo-check",
        "--output-schema",
        str(output_schema),
        "--json",
        "--color",
        "never",
        "--output-last-message",
        str(result),
    ]
    if not MODEL_ID.fullmatch(model):
        raise EvalError("model id contains unsupported characters")
    if reasoning_effort not in {"low", "medium", "high", "xhigh"}:
        raise EvalError("unsupported reasoning effort")
    command.extend(
        [
            "--model",
            model,
            "--config",
            f'model_reasoning_effort="{reasoning_effort}"',
        ]
    )
    command.append("-")
    return command


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        process.kill()
        process.communicate()
        raise EvalError(f"could not terminate the Codex process group: {exc}") from exc
    try:
        process.communicate(timeout=30)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise EvalError("Codex process tree did not exit after termination") from exc


class _WindowsJob:
    _KILL_ON_CLOSE = 0x00002000
    _EXTENDED_LIMIT_INFORMATION = 9
    _BASIC_ACCOUNTING_INFORMATION = 1

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class BasicAccountingInformation(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._accounting_type = BasicAccountingInformation
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self._kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._kernel32.TerminateJobObject.restype = wintypes.BOOL
        self._kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
        ]
        self._kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._handle = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise EvalError(f"cannot create Windows job: {ctypes.WinError(ctypes.get_last_error())}")
        limits = ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = self._KILL_ON_CLOSE
        if not self._kernel32.SetInformationJobObject(
            self._handle,
            self._EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise EvalError(f"cannot configure Windows job: {error}")

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        raw_handle = getattr(process, "_handle", None)
        if raw_handle is None or not self._kernel32.AssignProcessToJobObject(
            self._handle, self._wintypes.HANDLE(raw_handle)
        ):
            error = self._ctypes.WinError(self._ctypes.get_last_error())
            raise EvalError(f"cannot assign Codex to Windows job: {error}")

    def _active_processes(self) -> int:
        accounting = self._accounting_type()
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            self._BASIC_ACCOUNTING_INFORMATION,
            self._ctypes.byref(accounting),
            self._ctypes.sizeof(accounting),
            None,
        ):
            raise EvalError(
                "cannot query Windows job: "
                f"{self._ctypes.WinError(self._ctypes.get_last_error())}"
            )
        return accounting.ActiveProcesses

    def terminate_and_wait(self) -> None:
        if not self._handle:
            return
        if self._active_processes() == 0:
            return
        if not self._kernel32.TerminateJobObject(self._handle, 1):
            raise EvalError(
                "cannot terminate Windows job: "
                f"{self._ctypes.WinError(self._ctypes.get_last_error())}"
            )
        deadline = time.monotonic() + 30
        while True:
            if self._active_processes() == 0:
                return
            if time.monotonic() >= deadline:
                raise EvalError("Windows job still has active processes after termination")
            time.sleep(0.05)

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


_WINDOWS_GATE = (
    "import os,sys; "
    "gate=os.read(0,3); "
    "gate==b'GO\\n' or sys.exit(125); "
    "os.execv(sys.argv[1],sys.argv[1:])"
)


def _run_codex(
    suite: dict[str, Any],
    case: dict[str, Any],
    fixture: Path,
    work: Path,
    result: Path,
    events: Path,
    errors: Path,
    root: Path,
    runtime_skill: Path,
    model: str,
    reasoning_effort: str,
    timeout: int,
    runner: dict[str, Any] | None = None,
) -> dict[str, Any]:
    command = build_codex_command(
        suite, fixture, work, result, root, model, reasoning_effort, runner
    )
    prompt = _runner_prompt(suite, case, fixture, work, runtime_skill)
    started = dt.datetime.now(dt.timezone.utc)
    timed_out = False
    with events.open("wb") as stdout_handle, errors.open("wb") as stderr_handle:
        windows_job = _WindowsJob() if os.name == "nt" else None
        if windows_job is not None:
            launched_command = [sys.executable, "-c", _WINDOWS_GATE, *command]
            input_bytes = b"GO\n" + prompt.encode("utf-8")
            isolation = {
                "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            }
        else:
            launched_command = command
            input_bytes = prompt.encode("utf-8")
            isolation = {"start_new_session": True}
        try:
            process = subprocess.Popen(
                launched_command,
                cwd=root,
                stdin=subprocess.PIPE,
                stdout=stdout_handle,
                stderr=stderr_handle,
                **isolation,
            )
        except OSError:
            if windows_job is not None:
                windows_job.close()
            raise
        try:
            if windows_job is not None:
                try:
                    windows_job.assign(process)
                except EvalError:
                    process.kill()
                    process.communicate()
                    raise
            try:
                process.communicate(input_bytes, timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                if windows_job is not None:
                    windows_job.terminate_and_wait()
                    try:
                        process.communicate(timeout=30)
                    except subprocess.TimeoutExpired as exc:
                        raise EvalError(
                            "Codex process did not exit after Windows job termination"
                        ) from exc
                else:
                    _terminate_process_tree(process)
            else:
                if windows_job is not None:
                    windows_job.terminate_and_wait()
                else:
                    _terminate_process_tree(process)
        finally:
            if windows_job is not None:
                windows_job.close()
    finished = dt.datetime.now(dt.timezone.utc)
    if events.stat().st_size > MAX_EVENT_BYTES:
        raise EvalError("Codex event stream exceeds the size limit")
    if errors.stat().st_size > MAX_RESULT_BYTES:
        raise EvalError("Codex error stream exceeds the size limit")
    return {
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 3),
    }


def _run_directory(parent: Path, suite_id: str) -> Path:
    _assert_no_link_components(parent, include_final=True)
    if parent.exists():
        if _is_link_like(parent) or not parent.is_dir():
            raise EvalError("output directory must be a non-link directory")
    else:
        parent.mkdir(mode=0o700, parents=True)
    name = (
        f"{suite_id}-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{uuid.uuid4().hex[:8]}"
    )
    path = parent / name
    path.mkdir(mode=0o700)
    return path


def command_check(args: argparse.Namespace) -> int:
    root = Path(args.root).absolute() if args.root else ROOT
    _assert_no_link_components(root, include_final=True)
    suite = load_suite(root, args.suite)
    print(f"valid behavioral suite: {suite['suite']} ({len(suite['cases'])} cases)")
    return 0


def command_grade(args: argparse.Namespace) -> int:
    suite = load_suite(ROOT, args.suite)
    case = _case_by_id(suite, args.case)
    context_path = Path(args.context).absolute()
    result_path = Path(args.result).absolute()
    context = _load_json(context_path, "recorded context")
    result = _load_json(result_path, "recorded result")
    manifest = _suite_path(ROOT, suite["suite"])
    source = manifest.parent / case["fixture"]
    with tempfile.TemporaryDirectory(prefix="agent-kit-eval-grade-") as temporary:
        base = Path(temporary)
        fixture = base / "fixture"
        materialize_fixture(source, fixture)
        expected_path = base / "expected-context.json"
        expected_context = resolve_context(suite, case, fixture, expected_path, ROOT)
        report = grade_case(
            suite,
            case,
            context,
            expected_context,
            result,
            result_path,
            ROOT,
            mutation_free=None,
            forbidden_commands=None,
        )
    if args.output:
        _write_new_json(Path(args.output).absolute(), report)
    else:
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


def command_run(args: argparse.Namespace) -> int:
    suite, manifest, suite_bytes = _load_suite_bundle(ROOT, args.suite)
    if args.runner != "codex":
        raise EvalError("the only direct runner in v1 is codex")
    selected = (
        [_case_by_id(suite, case_id) for case_id in args.case]
        if args.case
        else list(suite["cases"])
    )
    timeout = args.timeout
    if timeout < 1 or timeout > MAX_TIMEOUT_SECONDS:
        raise EvalError(f"timeout must be between 1 and {MAX_TIMEOUT_SECONDS} seconds")
    output_parent = Path(args.output_dir).absolute() if args.output_dir else ROOT / ".eval-results"
    run_directory = _run_directory(output_parent, suite["suite"])
    run_results: list[dict[str, Any]] = []
    envelope_schema = _load_json(
        _validate_agent_envelope_schema(ROOT),
        "behavioral agent result schema",
        65536,
    )
    frozen_skill = skill_snapshot(ROOT / "skills" / suite["skill"])
    frozen_fixtures = {
        case["id"]: snapshot_fixture(manifest.parent / case["fixture"])
        for case in selected
    }
    runner = discover_codex_runner()
    harness_bytes = _read_bytes(
        Path(__file__).resolve(), "behavioral evaluation harness", MAX_RESULT_BYTES
    )
    skill_sha256 = _snapshot_digest(frozen_skill)
    suite_sha256 = hashlib.sha256(suite_bytes).hexdigest()
    harness_sha256 = hashlib.sha256(harness_bytes).hexdigest()
    for index, case in enumerate(selected, start=1):
        print(
            f"[{index}/{len(selected)}] {case['id']}: running",
            file=sys.stderr,
            flush=True,
        )
        case_directory = run_directory / "cases" / case["id"]
        case_directory.mkdir(mode=0o700, parents=True)
        with tempfile.TemporaryDirectory(prefix=f"agent-kit-eval-{case['id']}-") as temporary:
            base = Path(temporary)
            fixture = base / "fixture"
            work = base / "work"
            work.mkdir(mode=0o700)
            skill_parent = base / "evaluated-skill"
            skill_parent.mkdir(mode=0o700)
            runtime_skill = skill_parent / suite["skill"]
            _materialize_snapshot(frozen_skill, runtime_skill)
            _write_new_json(work / "agent-result.schema.json", envelope_schema)
            before = frozen_fixtures[case["id"]]
            _materialize_snapshot(before, fixture)
            context_path = work / "context.json"
            context = resolve_context(
                suite, case, fixture, context_path, ROOT, runtime_skill
            )
            original_context_digest = hashlib.sha256(
                _read_bytes(context_path, "lead-owned context", MAX_RESULT_BYTES)
            ).hexdigest()
            result_path = work / "result.json"
            events_path = work / "events.jsonl"
            errors_path = work / "stderr.txt"
            execution = _run_codex(
                suite,
                case,
                fixture,
                work,
                result_path,
                events_path,
                errors_path,
                ROOT,
                runtime_skill,
                args.model,
                args.reasoning_effort,
                timeout,
                runner,
            )
            isolation_errors: list[str] = []
            try:
                after = snapshot_fixture(fixture)
                mutation_free = _snapshot_identity(before) == _snapshot_identity(after)
            except EvalError as exc:
                mutation_free = False
                isolation_errors.append(str(exc))
            try:
                context_unchanged = original_context_digest == hashlib.sha256(
                    _read_bytes(context_path, "lead-owned context", MAX_RESULT_BYTES)
                ).hexdigest()
            except EvalError as exc:
                context_unchanged = False
                isolation_errors.append(str(exc))
            try:
                commands = _parse_event_commands(events_path)
                forbidden = _forbidden_command_hits(
                    commands, case["forbidden_commands"]
                )
            except EvalError as exc:
                forbidden = list(case["forbidden_commands"])
                isolation_errors.append(str(exc))
            if execution["exit_code"] == 0 and result_path.is_file():
                try:
                    envelope = _load_json(
                        result_path, "Codex result envelope", MAX_ENVELOPE_BYTES
                    )
                    envelope = _object(envelope, "Codex result envelope", {"result_json"})
                    result_text = envelope["result_json"]
                    if not isinstance(result_text, str) or not result_text:
                        raise EvalError("Codex result envelope must contain non-empty JSON text")
                    if len(result_text.encode("utf-8")) > MAX_RESULT_BYTES:
                        raise EvalError("canonical result exceeds the result size limit")
                    try:
                        result = json.loads(
                            result_text, object_pairs_hook=_reject_duplicates
                        )
                    except json.JSONDecodeError as exc:
                        raise EvalError(
                            f"Codex result envelope contains invalid canonical JSON: {exc}"
                        ) from exc
                    canonical_path = work / "canonical-result.json"
                    _write_new_json(canonical_path, result)
                    report = grade_case(
                        suite,
                        case,
                        context,
                        context,
                        result,
                        canonical_path,
                        ROOT,
                        runtime_skill=runtime_skill,
                        mutation_free=mutation_free and context_unchanged,
                        forbidden_commands=forbidden,
                    )
                    _write_new_json(case_directory / "context.json", context)
                    _write_new_json(case_directory / "result.json", result)
                except EvalError as exc:
                    report = {
                        "schema_version": 1,
                        "suite": suite["suite"],
                        "case": case["id"],
                        "passed": False,
                        "runner_error": str(exc),
                        "fixture_mutation_free": mutation_free and context_unchanged,
                        "forbidden_commands": forbidden,
                        "assertions": [],
                    }
            else:
                stderr = _read_bytes(errors_path, "Codex error stream", MAX_RESULT_BYTES)
                error_text = stderr.decode("utf-8", "replace")[:2000].strip()
                if not error_text:
                    error_text = _event_error_summary(events_path)
                report = {
                    "schema_version": 1,
                    "suite": suite["suite"],
                    "case": case["id"],
                    "passed": False,
                    "runner_error": error_text or "Codex exited without a canonical result",
                    "fixture_mutation_free": mutation_free and context_unchanged,
                    "forbidden_commands": forbidden,
                    "assertions": [],
                }
            if isolation_errors:
                report["isolation_errors"] = isolation_errors
                report["passed"] = False
            report["fixture_sha256"] = _snapshot_digest(before)
            report["execution"] = execution
            _write_new_json(case_directory / "score.json", report)
            run_results.append(report)
            outcome = "passed" if report["passed"] else "failed"
            print(
                f"[{index}/{len(selected)}] {case['id']}: {outcome}",
                file=sys.stderr,
                flush=True,
            )
    summary = {
        "schema_version": 1,
        "suite": suite["suite"],
        "runner": "codex",
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "codex_version": runner["version"],
        "runner_kind": runner["kind"],
        "runner_sha256": runner["sha256"],
        "skill_sha256": skill_sha256,
        "harness_sha256": harness_sha256,
        "suite_sha256": suite_sha256,
        "total": len(run_results),
        "passed": sum(item["passed"] for item in run_results),
        "failed": sum(not item["passed"] for item in run_results),
        "cases": [
            {
                "id": item["case"],
                "passed": item["passed"],
                "fixture_sha256": item["fixture_sha256"],
            }
            for item in run_results
        ],
    }
    _write_new_json(run_directory / "summary.json", summary)
    print(json.dumps({**summary, "output_directory": str(run_directory)}, indent=2, sort_keys=True))
    return 0 if summary["failed"] == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="validate a suite without invoking a model")
    check.add_argument("--suite", required=True)
    check.add_argument("--root", help="repository root to validate; defaults to this checkout")
    grade = commands.add_parser("grade", help="grade one recorded context and result")
    grade.add_argument("--suite", required=True)
    grade.add_argument("--case", required=True)
    grade.add_argument("--context", required=True)
    grade.add_argument("--result", required=True)
    grade.add_argument("--output")
    run = commands.add_parser("run", help="explicitly invoke a local agent runner")
    run.add_argument("--suite", required=True)
    run.add_argument("--runner", required=True, choices=("codex",))
    run.add_argument("--case", action="append", default=[])
    run.add_argument("--model", required=True)
    run.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high", "xhigh"),
        default="medium",
    )
    run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    run.add_argument("--output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check":
            return command_check(args)
        if args.command == "grade":
            return command_grade(args)
        return command_run(args)
    except (EvalError, OSError, subprocess.SubprocessError) as exc:
        print(f"behavioral-eval: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
