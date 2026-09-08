#!/usr/bin/env python3
"""Validate project-eval protocols and manage sanitized portable evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import stat
import sys
from typing import Any, Iterable
import zipfile

_PATH_SAFETY_SPEC = importlib.util.spec_from_file_location(
    "project_eval_path_safety", Path(__file__).with_name("path_safety.py")
)
if _PATH_SAFETY_SPEC is None or _PATH_SAFETY_SPEC.loader is None:
    raise RuntimeError("cannot load bundled project-eval path safety helpers")
_PATH_SAFETY = importlib.util.module_from_spec(_PATH_SAFETY_SPEC)
_PATH_SAFETY_SPEC.loader.exec_module(_PATH_SAFETY)
SafetyError = _PATH_SAFETY.SafetyError
assert_no_link_components = _PATH_SAFETY.assert_no_link_components
bound_directory_entries = _PATH_SAFETY.bound_directory_entries
canonical_path = _PATH_SAFETY.canonical_path
ensure_private_directory = _PATH_SAFETY.ensure_private_directory
is_link_like = _PATH_SAFETY.is_link_like
publish_immutable_output = _PATH_SAFETY.publish_immutable_output
read_regular = _PATH_SAFETY.read_regular
safe_repo_path = _PATH_SAFETY.safe_repo_path
write_created_output = _PATH_SAFETY.write_created_output

_CASE_ENGINE_SPEC = importlib.util.spec_from_file_location(
    "project_eval_case_engine", Path(__file__).with_name("case_engine.py")
)
if _CASE_ENGINE_SPEC is None or _CASE_ENGINE_SPEC.loader is None:
    raise RuntimeError("cannot load bundled project-eval case engine")
_CASE_ENGINE = importlib.util.module_from_spec(_CASE_ENGINE_SPEC)
_CASE_ENGINE_SPEC.loader.exec_module(_CASE_ENGINE)
CaseError = _CASE_ENGINE.CaseError


VERSION = "1.0.0"
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_CONTENT = 8 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 128
MAX_DEPTH = 64
MAX_NODES = 200_000
MAX_TEXT = 20_000
MAX_STATE_ENTRIES = 10_000
ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
PROFILE_ID = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
RUN_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
NAMESPACE = re.compile(r"^[0-9a-f]{32}$")
REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
FORMAT_CONTROLS = {
    *(chr(value) for value in range(0x202A, 0x202F)),
    *(chr(value) for value in range(0x2066, 0x206A)),
    "\u200e",
    "\u200f",
    "\u061c",
}
SENSITIVE_KEYS = {
    "raw_transcript",
    "raw_transcripts",
    "prompt",
    "prompts",
    "event_stream",
    "event_streams",
    "stderr",
    "credential",
    "credentials",
    "secret",
    "secrets",
    "environment_values",
    "workspace_contents",
}


class EvalError(ValueError):
    """Raised when a project-eval contract cannot be trusted."""


def _duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvalError(f"duplicate JSON member: {key!r}")
        result[key] = value
    return result


def _decode_json(raw: bytes, label: str) -> Any:
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise EvalError(f"{label} must be valid UTF-8") from exc
    try:
        value = json.loads(text, object_pairs_hook=_duplicate_object)
    except (json.JSONDecodeError, EvalError) as exc:
        raise EvalError(f"invalid JSON in {label}: {exc}") from exc
    _bounded_tree(value, label)
    return value


def _bounded_tree(value: Any, label: str) -> None:
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_NODES:
            raise EvalError(f"{label} has too many JSON values")
        if depth > MAX_DEPTH:
            raise EvalError(f"{label} exceeds the maximum JSON depth")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, float) and not (float("-inf") < current < float("inf")):
            raise EvalError(f"{label} contains a non-finite number")


def _load_json(path_value: str, label: str) -> tuple[Any, bytes]:
    if path_value == "-":
        raw = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise EvalError(f"{label} exceeds {MAX_JSON_BYTES} bytes")
    else:
        path = Path(path_value)
        try:
            _, raw = read_regular(path, MAX_JSON_BYTES, require_single_link=True)
        except SafetyError as exc:
            raise EvalError(f"cannot read {label}: {exc}") from exc
    return _decode_json(raw, label), raw


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvalError(f"{label} must be an object")
    return value


def _array(value: Any, label: str, *, maximum: int, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise EvalError(f"{label} must contain between {minimum} and {maximum} items")
    return value


def _exact(value: dict[str, Any], label: str, required: Iterable[str]) -> None:
    expected = set(required)
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise EvalError(f"{label} members differ; missing={missing}, extra={extra}")


def _text(value: Any, label: str, *, maximum: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise EvalError(f"{label} must be a non-empty string of at most {maximum} characters")
    if CONTROL.search(value):
        raise EvalError(f"{label} must not contain control characters")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise EvalError(f"{label} must be valid UTF-8") from exc
    return value


def _identifier(value: Any, label: str, pattern: re.Pattern[str] = ID) -> str:
    value = _text(value, label, maximum=128)
    if not pattern.fullmatch(value):
        raise EvalError(f"{label} is not canonical: {value!r}")
    return value


def _enum(value: Any, label: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise EvalError(f"{label} must be one of {sorted(allowed)}")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise EvalError(f"{label} must be an integer from {minimum} through {maximum}")
    return value


def _number_or_null(value: Any, label: str, maximum: float) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= maximum:
        raise EvalError(f"{label} must be null or a non-negative number no greater than {maximum}")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise EvalError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _object_digest(value: Any) -> str:
    return _sha(_canonical_bytes(value))


def _relative(value: Any, label: str) -> str:
    value = _text(value, label, maximum=4096)
    try:
        return canonical_path(value)
    except SafetyError as exc:
        raise EvalError(f"{label}: {exc}") from exc


def _unique_strings(value: Any, label: str, *, maximum: int, allowed: set[str] | None = None) -> list[str]:
    items = _array(value, label, maximum=maximum)
    result: list[str] = []
    for index, item in enumerate(items):
        current = _text(item, f"{label}[{index}]", maximum=128)
        if allowed is not None and current not in allowed:
            raise EvalError(f"{label}[{index}] must be one of {sorted(allowed)}")
        if current in result:
            raise EvalError(f"{label} contains duplicate {current!r}")
        result.append(current)
    return result


def validate_suite(value: Any) -> dict[str, Any]:
    suite = _mapping(value, "suite")
    _exact(suite, "suite", ("schema_version", "suite_id", "title", "cases", "profiles"))
    if suite["schema_version"] != "project-eval-suite/v1":
        raise EvalError("suite.schema_version must be project-eval-suite/v1")
    _identifier(suite["suite_id"], "suite.suite_id")
    _text(suite["title"], "suite.title", maximum=200)
    cases = _array(suite["cases"], "suite.cases", maximum=500, minimum=1)
    case_ids: set[str] = set()
    for index, raw_case in enumerate(cases):
        label = f"suite.cases[{index}]"
        case = _mapping(raw_case, label)
        _exact(
            case,
            label,
            (
                "case_id",
                "title",
                "kind",
                "importance",
                "fixture",
                "task",
                "coverage",
                "platforms",
                "required_capabilities",
                "assertion_ids",
            ),
        )
        case_id = _identifier(case["case_id"], f"{label}.case_id")
        if case_id in case_ids:
            raise EvalError(f"duplicate case_id: {case_id}")
        case_ids.add(case_id)
        _text(case["title"], f"{label}.title", maximum=200)
        _enum(case["kind"], f"{label}.kind", {"explanation", "implementation", "trajectory"})
        _enum(case["importance"], f"{label}.importance", {"required", "important", "standard", "exploratory"})
        _relative(case["fixture"], f"{label}.fixture")
        _text(case["task"], f"{label}.task")
        _enum(case["coverage"], f"{label}.coverage", {"development", "holdout", "regression"})
        platforms = _unique_strings(
            case["platforms"],
            f"{label}.platforms",
            maximum=3,
            allowed={"linux", "windows", "macos"},
        )
        if not platforms:
            raise EvalError(f"{label}.platforms must not be empty")
        capabilities = _unique_strings(case["required_capabilities"], f"{label}.required_capabilities", maximum=64)
        for capability in capabilities:
            _identifier(capability, f"{label}.required_capabilities", PROFILE_ID)
        assertions = _unique_strings(case["assertion_ids"], f"{label}.assertion_ids", maximum=256)
        if not assertions:
            raise EvalError(f"{label}.assertion_ids must not be empty")
        for assertion in assertions:
            _identifier(assertion, f"{label}.assertion_ids", PROFILE_ID)
    profiles = _mapping(suite["profiles"], "suite.profiles")
    if not 1 <= len(profiles) <= 32:
        raise EvalError("suite.profiles must contain between 1 and 32 profiles")
    for profile_name, raw_profile in profiles.items():
        _identifier(profile_name, "suite profile name", PROFILE_ID)
        profile = _mapping(raw_profile, f"suite.profiles.{profile_name}")
        _exact(
            profile,
            f"suite.profiles.{profile_name}",
            ("case_ids", "repetitions", "max_invocations", "max_seconds", "max_tokens", "max_cost_usd", "network", "effects"),
        )
        selected = _unique_strings(profile["case_ids"], f"suite.profiles.{profile_name}.case_ids", maximum=500)
        if not selected:
            raise EvalError(f"suite.profiles.{profile_name}.case_ids must not be empty")
        unknown = sorted(set(selected) - case_ids)
        if unknown:
            raise EvalError(f"suite.profiles.{profile_name} names unknown cases: {unknown}")
        repetitions = _integer(profile["repetitions"], f"suite.profiles.{profile_name}.repetitions", 1, 100)
        invocations = _integer(profile["max_invocations"], f"suite.profiles.{profile_name}.max_invocations", 1, 10_000)
        if invocations < len(selected) * repetitions:
            raise EvalError(f"suite.profiles.{profile_name}.max_invocations cannot cover its selected repetitions")
        _integer(profile["max_seconds"], f"suite.profiles.{profile_name}.max_seconds", 1, 86_400)
        if profile["max_tokens"] is not None:
            _integer(profile["max_tokens"], f"suite.profiles.{profile_name}.max_tokens", 1, 1_000_000_000)
        _number_or_null(profile["max_cost_usd"], f"suite.profiles.{profile_name}.max_cost_usd", 1_000_000)
        if not isinstance(profile["network"], bool):
            raise EvalError(f"suite.profiles.{profile_name}.network must be boolean")
        _unique_strings(
            profile["effects"],
            f"suite.profiles.{profile_name}.effects",
            maximum=16,
            allowed={"workspace_edit", "command_execution", "local_output", "external_read"},
        )
    return suite


def load_repository_suite(
    repository: Path, eval_root_value: str, suite_value: str
) -> tuple[dict[str, Any], bytes, Path]:
    repository = repository.absolute()
    try:
        assert_no_link_components(repository, include_final=True)
    except SafetyError as exc:
        raise EvalError(f"cannot bind repository root: {exc}") from exc
    if not repository.is_dir():
        raise EvalError(f"repository is not a directory: {repository}")
    eval_root_relative = _relative(eval_root_value, "evaluation root")
    suite_relative = _relative(suite_value, "suite path")
    if not suite_relative.endswith(".json"):
        raise EvalError("suite path must name a JSON file")
    try:
        eval_root = safe_repo_path(repository, eval_root_relative)
        if not eval_root.is_dir():
            raise EvalError(f"evaluation root is not a directory: {eval_root_relative}")
        suite_path = safe_repo_path(eval_root, suite_relative)
    except SafetyError as exc:
        raise EvalError(f"cannot resolve repository suite: {exc}") from exc
    value, raw = _load_json(str(suite_path), "suite")
    suite = validate_suite(value)
    for case in suite["cases"]:
        try:
            fixture = safe_repo_path(eval_root, case["fixture"])
        except SafetyError as exc:
            raise EvalError(
                f"case {case['case_id']} fixture cannot be resolved safely: {exc}"
            ) from exc
        if not fixture.is_dir():
            raise EvalError(f"case {case['case_id']} fixture is not a directory")
    return suite, raw, suite_path


def _case_components(
    repository: Path, eval_root_value: str, suite_value: str, case_id: str
) -> tuple[dict[str, Any], dict[str, Any], bytes, Path]:
    suite, raw, _ = load_repository_suite(repository, eval_root_value, suite_value)
    _identifier(case_id, "case id")
    selected = next((item for item in suite["cases"] if item["case_id"] == case_id), None)
    if selected is None:
        raise EvalError(f"suite does not contain case {case_id!r}")
    try:
        eval_root = safe_repo_path(repository.absolute(), _relative(eval_root_value, "evaluation root"))
        fixture = safe_repo_path(eval_root, selected["fixture"])
    except SafetyError as exc:
        raise EvalError(f"cannot bind selected case fixture: {exc}") from exc
    return suite, selected, raw, fixture


def _external_workspace_path(repository: Path, value: str, label: str) -> Path:
    repository = repository.absolute()
    candidate = Path(value).absolute()
    if candidate == repository or repository in candidate.parents:
        raise EvalError(f"{label} must remain outside the repository")
    return candidate


def _prepared_context_output(repository: Path, workspace_root: Path, value: str) -> Path:
    context_output = _external_workspace_path(repository, value, "prepared context output")
    workspace_root = workspace_root.absolute()
    if context_output == workspace_root or workspace_root in context_output.parents:
        raise EvalError("prepared context output must remain outside the workspace root")
    return context_output


def _validate_producer(value: Any, label: str) -> None:
    producer = _mapping(value, label)
    _exact(producer, label, ("name", "version"))
    _identifier(producer["name"], f"{label}.name")
    _identifier(producer["version"], f"{label}.version", SAFE_VALUE)


def _validate_limitation(value: Any, label: str) -> None:
    limitation = _mapping(value, label)
    _exact(limitation, label, ("code", "message", "material"))
    _identifier(limitation["code"], f"{label}.code", PROFILE_ID)
    _text(limitation["message"], f"{label}.message", maximum=2000)
    if not isinstance(limitation["material"], bool):
        raise EvalError(f"{label}.material must be boolean")


def _validate_target(value: Any, label: str) -> None:
    target = _mapping(value, label)
    _exact(
        target,
        label,
        ("repository_sha256", "definition_sha256", "fixture_set_sha256", "revision"),
    )
    _digest(target["repository_sha256"], f"{label}.repository_sha256")
    _digest(target["definition_sha256"], f"{label}.definition_sha256")
    _digest(target["fixture_set_sha256"], f"{label}.fixture_set_sha256")
    if target["revision"] is not None:
        _identifier(target["revision"], f"{label}.revision", REVISION)


def _validate_configuration(value: Any, label: str) -> None:
    configuration = _mapping(value, label)
    fields = (
        "runner",
        "runner_version",
        "agent",
        "model",
        "reasoning",
        "platform",
        "environment_sha256",
        "configuration_sha256",
    )
    _exact(configuration, label, fields)
    _identifier(configuration["runner"], f"{label}.runner", PROFILE_ID)
    _identifier(configuration["runner_version"], f"{label}.runner_version", SAFE_VALUE)
    _identifier(configuration["agent"], f"{label}.agent", PROFILE_ID)
    for field in ("model", "reasoning"):
        if configuration[field] is not None:
            _identifier(configuration[field], f"{label}.{field}", PROFILE_ID)
    _enum(configuration["platform"], f"{label}.platform", {"linux", "windows", "macos"})
    _digest(configuration["environment_sha256"], f"{label}.environment_sha256")
    expected = _object_digest({key: configuration[key] for key in fields[:-1]})
    actual = _digest(configuration["configuration_sha256"], f"{label}.configuration_sha256")
    if actual != expected:
        raise EvalError(f"{label}.configuration_sha256 does not bind its configuration")


def _validate_evidence(value: Any, label: str) -> None:
    evidence = _mapping(value, label)
    _exact(evidence, label, ("evidence_id", "kind", "status", "sha256", "summary", "redacted"))
    _identifier(evidence["evidence_id"], f"{label}.evidence_id", PROFILE_ID)
    _enum(evidence["kind"], f"{label}.kind", {"assertion", "check", "measurement", "failure"})
    _enum(evidence["status"], f"{label}.status", {"pass", "fail", "unknown", "informational"})
    _digest(evidence["sha256"], f"{label}.sha256")
    _text(evidence["summary"], f"{label}.summary", maximum=500)
    if evidence["redacted"] is not True:
        raise EvalError(f"{label}.redacted must be true")


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise EvalError(f"{label} must be boolean")
    return value


def _validate_evidence_reference(value: Any, label: str) -> None:
    evidence = _mapping(value, label)
    _exact(evidence, label, ("evidence_id", "kind", "sha256", "summary", "redacted"))
    _identifier(evidence["evidence_id"], f"{label}.evidence_id", PROFILE_ID)
    _enum(
        evidence["kind"],
        f"{label}.kind",
        {"session_summary", "run_receipt", "assertion", "measurement", "repository"},
    )
    _digest(evidence["sha256"], f"{label}.sha256")
    _text(evidence["summary"], f"{label}.summary", maximum=500)
    if evidence["redacted"] is not True:
        raise EvalError(f"{label}.redacted must be true")


def _validate_candidate_item(value: Any, label: str) -> None:
    candidate = _mapping(value, label)
    _exact(
        candidate,
        label,
        (
            "candidate_id",
            "pain_point",
            "proposed_case",
            "reason",
            "evidence",
            "evidence_count",
            "independent_session_count",
            "overlap",
            "confidence",
            "proposed_importance",
            "behavior_basis",
            "cost_effect",
            "promotion_requirements",
            "readiness",
        ),
    )
    _identifier(candidate["candidate_id"], f"{label}.candidate_id", PROFILE_ID)
    _text(candidate["pain_point"], f"{label}.pain_point", maximum=2000)
    proposed = _mapping(candidate["proposed_case"], f"{label}.proposed_case")
    _exact(proposed, f"{label}.proposed_case", ("kind", "phase", "task_summary"))
    _enum(proposed["kind"], f"{label}.proposed_case.kind", {"explanation", "implementation", "trajectory"})
    if proposed["phase"] is not None:
        _enum(proposed["phase"], f"{label}.proposed_case.phase", {"intake", "clarification", "specification", "planning", "implementation", "verification", "reporting"})
    _text(proposed["task_summary"], f"{label}.proposed_case.task_summary", maximum=2000)
    _text(candidate["reason"], f"{label}.reason", maximum=2000)
    evidence = _array(candidate["evidence"], f"{label}.evidence", maximum=256, minimum=1)
    for index, item in enumerate(evidence):
        _validate_evidence_reference(item, f"{label}.evidence[{index}]")
    evidence_count = _integer(candidate["evidence_count"], f"{label}.evidence_count", 1, 1_000_000)
    sessions = _integer(candidate["independent_session_count"], f"{label}.independent_session_count", 1, 1_000_000)
    if sessions > evidence_count:
        raise EvalError(f"{label}.independent_session_count cannot exceed evidence_count")
    overlap = _mapping(candidate["overlap"], f"{label}.overlap")
    _exact(overlap, f"{label}.overlap", ("relation", "case_ids", "reason"))
    _enum(overlap["relation"], f"{label}.overlap.relation", {"none", "partial", "duplicate", "extends"})
    overlap_case_ids = _unique_strings(overlap["case_ids"], f"{label}.overlap.case_ids", maximum=256)
    for case_id in overlap_case_ids:
        _identifier(case_id, f"{label}.overlap.case_ids", PROFILE_ID)
    _text(overlap["reason"], f"{label}.overlap.reason", maximum=1000)
    _enum(candidate["confidence"], f"{label}.confidence", {"high", "medium", "low", "unknown"})
    _enum(candidate["proposed_importance"], f"{label}.proposed_importance", {"required", "important", "standard", "exploratory"})
    basis = _enum(candidate["behavior_basis"], f"{label}.behavior_basis", {"existing", "new", "ambiguous"})
    cost = _enum(candidate["cost_effect"], f"{label}.cost_effect", {"decrease", "none", "increase", "unknown"})
    requirements = _array(candidate["promotion_requirements"], f"{label}.promotion_requirements", maximum=64)
    for index, requirement in enumerate(requirements):
        _text(requirement, f"{label}.promotion_requirements[{index}]", maximum=500)
    readiness = _enum(candidate["readiness"], f"{label}.readiness", {"ready", "decision_required", "needs_evidence"})
    if readiness == "ready" and (basis != "existing" or cost in {"increase", "unknown"}):
        raise EvalError(f"{label} cannot be ready with new/ambiguous behavior or material cost uncertainty")


def _validate_experiment_candidate(value: Any, label: str) -> None:
    candidate = _mapping(value, label)
    _exact(candidate, label, ("candidate_id", "patch_sha256", "run_sha256", "target_sha256", "configuration_sha256", "classification", "objective_delta", "required_cases_passed", "guardrail_regression", "budget_breach", "evidence"))
    _identifier(candidate["candidate_id"], f"{label}.candidate_id", PROFILE_ID)
    for field in ("patch_sha256", "run_sha256", "target_sha256", "configuration_sha256"):
        _digest(candidate[field], f"{label}.{field}")
    classification = _enum(candidate["classification"], f"{label}.classification", {"clear_improvement", "tradeoff", "inconclusive", "no_improvement", "incomplete"})
    delta = candidate["objective_delta"]
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not -1_000_000_000 <= delta <= 1_000_000_000:
        raise EvalError(f"{label}.objective_delta must be a bounded number")
    required_passed = _boolean(candidate["required_cases_passed"], f"{label}.required_cases_passed")
    regression = _boolean(candidate["guardrail_regression"], f"{label}.guardrail_regression")
    breach = _boolean(candidate["budget_breach"], f"{label}.budget_breach")
    evidence = _array(candidate["evidence"], f"{label}.evidence", maximum=256, minimum=1)
    for index, item in enumerate(evidence):
        _validate_evidence_reference(item, f"{label}.evidence[{index}]")
    if classification == "clear_improvement" and (not required_passed or regression or breach):
        raise EvalError(f"{label} cannot claim clear improvement after a quality, guardrail, or budget failure")


def _validate_suite_recommendation(value: Any, label: str) -> None:
    recommendation = _mapping(value, label)
    _exact(recommendation, label, ("recommendation_id", "case_ids", "action", "strength", "reason", "confidence", "evidence", "unique_coverage", "replacement_coverage", "cost_effect", "decision_required", "ready", "limitations"))
    _identifier(recommendation["recommendation_id"], f"{label}.recommendation_id", PROFILE_ID)
    cases = _unique_strings(recommendation["case_ids"], f"{label}.case_ids", maximum=256)
    if not cases:
        raise EvalError(f"{label}.case_ids must not be empty")
    for case_id in cases:
        _identifier(case_id, f"{label}.case_ids", PROFILE_ID)
    action = _enum(recommendation["action"], f"{label}.action", {"keep", "refresh", "merge", "simplify", "demote", "retire"})
    _enum(recommendation["strength"], f"{label}.strength", {"strong", "moderate", "optional"})
    _text(recommendation["reason"], f"{label}.reason", maximum=2000)
    _enum(recommendation["confidence"], f"{label}.confidence", {"high", "medium", "low", "unknown"})
    evidence = _array(recommendation["evidence"], f"{label}.evidence", maximum=256, minimum=1)
    for index, item in enumerate(evidence):
        _validate_evidence_reference(item, f"{label}.evidence[{index}]")
    _text(recommendation["unique_coverage"], f"{label}.unique_coverage", maximum=2000)
    _text(recommendation["replacement_coverage"], f"{label}.replacement_coverage", maximum=2000)
    _enum(recommendation["cost_effect"], f"{label}.cost_effect", {"decrease", "none", "increase", "unknown"})
    decision = _boolean(recommendation["decision_required"], f"{label}.decision_required")
    ready = _boolean(recommendation["ready"], f"{label}.ready")
    limitations = _array(recommendation["limitations"], f"{label}.limitations", maximum=64)
    for index, item in enumerate(limitations):
        _validate_limitation(item, f"{label}.limitations[{index}]")
    if ready and (decision or any(item["material"] for item in limitations)):
        raise EvalError(f"{label} cannot be ready while a decision or material limitation remains")
    if action == "keep" and ready:
        raise EvalError(f"{label} keep recommendations are informational, not ready mutations")


def validate_run_result(value: Any) -> dict[str, Any]:
    result = _mapping(value, "run result")
    _exact(
        result,
        "run result",
        ("schema_version", "run_id", "producer", "suite", "source", "target", "configuration", "completion", "outcome", "next_action", "cases", "summary", "limitations"),
    )
    if result["schema_version"] != "project-eval-run-result/v1":
        raise EvalError("run result schema_version must be project-eval-run-result/v1")
    _identifier(result["run_id"], "run result.run_id", RUN_ID)
    _validate_producer(result["producer"], "run result.producer")
    suite = _mapping(result["suite"], "run result.suite")
    _exact(suite, "run result.suite", ("suite_id", "suite_sha256", "profile"))
    _identifier(suite["suite_id"], "run result.suite.suite_id")
    _digest(suite["suite_sha256"], "run result.suite.suite_sha256")
    _identifier(suite["profile"], "run result.suite.profile", PROFILE_ID)
    source = _mapping(result["source"], "run result.source")
    _exact(source, "run result.source", ("kind", "authority", "bundle_sha256"))
    kind = _enum(source["kind"], "run result.source.kind", {"local", "imported"})
    if source["authority"] != "evidence_only":
        raise EvalError("run result.source.authority must be evidence_only")
    if source["bundle_sha256"] is not None:
        _digest(source["bundle_sha256"], "run result.source.bundle_sha256")
    if kind == "local" and source["bundle_sha256"] is not None:
        raise EvalError("a local result cannot claim an imported bundle digest")
    if kind == "imported" and source["bundle_sha256"] is None:
        raise EvalError("an imported result must carry its portable bundle digest")
    _validate_target(result["target"], "run result.target")
    _validate_configuration(result["configuration"], "run result.configuration")
    completion = _enum(result["completion"], "run result.completion", {"complete", "incomplete"})
    outcome = _enum(result["outcome"], "run result.outcome", {"pass", "fail", "unknown"})
    next_action = _enum(result["next_action"], "run result.next_action", {"none", "retry", "triage", "decision", "authorization", "rescope", "manual"})
    cases = _array(result["cases"], "run result.cases", maximum=50_000)
    case_keys: set[str] = set()
    required_failed = False
    incomplete_case = False
    for index, raw_case in enumerate(cases):
        label = f"run result.cases[{index}]"
        case = _mapping(raw_case, label)
        _exact(case, label, ("case_id", "importance", "status", "repetitions", "passed", "failed", "duration_ms", "tokens", "target_sha256", "grader_sha256", "evidence", "limitations"))
        case_id = _identifier(case["case_id"], f"{label}.case_id")
        repetition_count = _integer(case["repetitions"], f"{label}.repetitions", 0, 100)
        if case_id in case_keys:
            raise EvalError(f"duplicate case result identity: {case_id}")
        case_keys.add(case_id)
        importance = _enum(case["importance"], f"{label}.importance", {"required", "important", "standard", "exploratory"})
        status_value = _enum(case["status"], f"{label}.status", {"passed", "failed", "unavailable", "not_applicable", "incomplete"})
        passed = _integer(case["passed"], f"{label}.passed", 0, 100)
        failed = _integer(case["failed"], f"{label}.failed", 0, 100)
        if passed + failed > repetition_count:
            raise EvalError(f"{label} pass/fail counts exceed repetitions")
        if status_value == "passed" and (passed != repetition_count or failed != 0):
            raise EvalError(f"{label} passed status must account for every repetition")
        if status_value == "failed" and failed == 0:
            raise EvalError(f"{label} failed status requires a failed repetition")
        if status_value in {"unavailable", "not_applicable"} and (passed or failed):
            raise EvalError(f"{label} unavailable status cannot claim pass/fail observations")
        if case["duration_ms"] is not None:
            _integer(case["duration_ms"], f"{label}.duration_ms", 0, 604_800_000)
        tokens = _mapping(case["tokens"], f"{label}.tokens")
        _exact(tokens, f"{label}.tokens", ("value", "provenance"))
        if tokens["value"] is not None:
            _integer(tokens["value"], f"{label}.tokens.value", 0, 1_000_000_000)
        provenance = _enum(tokens["provenance"], f"{label}.tokens.provenance", {"host_observed", "runner_reported", "unavailable"})
        if provenance == "unavailable" and tokens["value"] is not None:
            raise EvalError(f"{label}.tokens unavailable provenance requires null value")
        _digest(case["target_sha256"], f"{label}.target_sha256")
        _digest(case["grader_sha256"], f"{label}.grader_sha256")
        evidence = _array(case["evidence"], f"{label}.evidence", maximum=256)
        evidence_ids: set[str] = set()
        for evidence_index, item in enumerate(evidence):
            evidence_label = f"{label}.evidence[{evidence_index}]"
            _validate_evidence(item, evidence_label)
            if item["evidence_id"] in evidence_ids:
                raise EvalError(f"{label}.evidence contains a duplicate evidence_id")
            evidence_ids.add(item["evidence_id"])
        limitations = _array(case["limitations"], f"{label}.limitations", maximum=256)
        for limitation_index, limitation in enumerate(limitations):
            _validate_limitation(limitation, f"{label}.limitations[{limitation_index}]")
        required_failed |= importance == "required" and status_value != "passed"
        incomplete_case |= status_value == "incomplete"
    summary = _mapping(result["summary"], "run result.summary")
    _exact(
        summary,
        "run result.summary",
        (
            "total_cases",
            "passed_cases",
            "failed_cases",
            "unavailable_cases",
            "total_repetitions",
            "passed_repetitions",
            "failed_repetitions",
            "duration_ms",
            "tokens",
        ),
    )
    expected_summary = {
        "total_cases": len(cases),
        "passed_cases": sum(item["status"] == "passed" for item in cases),
        "failed_cases": sum(item["status"] == "failed" for item in cases),
        "unavailable_cases": sum(item["status"] in {"unavailable", "not_applicable", "incomplete"} for item in cases),
        "total_repetitions": sum(item["repetitions"] for item in cases),
        "passed_repetitions": sum(item["passed"] for item in cases),
        "failed_repetitions": sum(item["failed"] for item in cases),
        "duration_ms": sum(item["duration_ms"] or 0 for item in cases),
    }
    for field, expected_value in expected_summary.items():
        actual_value = _integer(summary[field], f"run result.summary.{field}", 0, 604_800_000)
        if actual_value != expected_value:
            raise EvalError(f"run result.summary.{field} does not match case results")
    summary_tokens = _mapping(summary["tokens"], "run result.summary.tokens")
    _exact(summary_tokens, "run result.summary.tokens", ("value", "provenance"))
    if summary_tokens["value"] is not None:
        _integer(summary_tokens["value"], "run result.summary.tokens.value", 0, 1_000_000_000)
    summary_provenance = _enum(summary_tokens["provenance"], "run result.summary.tokens.provenance", {"host_observed", "runner_reported", "unavailable"})
    case_token_values = [item["tokens"]["value"] for item in cases]
    if any(value is None for value in case_token_values):
        if summary_tokens["value"] is not None or summary_provenance != "unavailable":
            raise EvalError("run result.summary.tokens must remain unavailable when a case token count is unavailable")
    else:
        expected_tokens = sum(case_token_values)
        if summary_tokens["value"] != expected_tokens or summary_provenance == "unavailable":
            raise EvalError("run result.summary.tokens does not match case measurements")
    limitations = _array(result["limitations"], "run result.limitations", maximum=2000)
    for index, limitation in enumerate(limitations):
        _validate_limitation(limitation, f"run result.limitations[{index}]")
    material = any(item["material"] for item in limitations)
    if completion == "complete" and (material or incomplete_case):
        raise EvalError("a complete run cannot retain a material limitation or incomplete case")
    if outcome == "pass" and not cases:
        raise EvalError("a passing run must contain at least one case result")
    if outcome == "pass" and (completion != "complete" or required_failed):
        raise EvalError("a passing run must be complete with every required case passed")
    if outcome == "pass" and next_action != "none":
        raise EvalError("a passing run must have next_action none")
    return result


def _validate_family_result(value: Any, family: str) -> dict[str, Any]:
    result = _mapping(value, family)
    contracts = {
        "candidate": (
            "eval-candidate-result/v1",
            ("schema_version", "producer", "completion", "outcome", "next_action", "source_digest", "target", "candidates", "limitations"),
            {"candidates", "none", "unknown"},
            {"none", "draft", "decision", "retry", "manual"},
            "candidates",
        ),
        "experiment": (
            "eval-experiment-result/v1",
            ("schema_version", "producer", "completion", "outcome", "next_action", "objective", "baseline", "candidates", "limitations"),
            {"clear_improvement", "tradeoff", "inconclusive", "no_improvement", "incomplete"},
            {"none", "review_candidate", "decision", "retry", "manual"},
            "candidates",
        ),
        "suite-audit": (
            "eval-suite-audit-result/v1",
            ("schema_version", "producer", "completion", "outcome", "next_action", "repository_sha256", "suite_digest", "recommendations", "limitations"),
            {"pass", "maintenance_recommended", "unknown"},
            {"none", "maintain", "decision", "retry", "manual"},
            "recommendations",
        ),
    }
    schema, keys, outcomes, actions, collection_key = contracts[family]
    _exact(result, family, keys)
    if result["schema_version"] != schema:
        raise EvalError(f"{family}.schema_version must be {schema}")
    _validate_producer(result["producer"], f"{family}.producer")
    completion = _enum(result["completion"], f"{family}.completion", {"complete", "incomplete"})
    _enum(result["outcome"], f"{family}.outcome", outcomes)
    _enum(result["next_action"], f"{family}.next_action", actions)
    if family == "candidate":
        _digest(result["source_digest"], "candidate.source_digest")
        target = _mapping(result["target"], "candidate.target")
        _exact(target, "candidate.target", ("repository_sha256", "suite_sha256"))
        _digest(target["repository_sha256"], "candidate.target.repository_sha256")
        if target["suite_sha256"] is not None:
            _digest(target["suite_sha256"], "candidate.target.suite_sha256")
    elif family == "suite-audit":
        _digest(result["repository_sha256"], "suite-audit.repository_sha256")
        _digest(result["suite_digest"], "suite-audit.suite_digest")
    else:
        objective = _mapping(result["objective"], "experiment.objective")
        _exact(objective, "experiment.objective", ("metric", "direction", "tolerance"))
        _enum(objective["metric"], "experiment.objective.metric", {"correctness", "completion", "time", "tokens", "cost"})
        _enum(objective["direction"], "experiment.objective.direction", {"increase", "decrease"})
        tolerance = objective["tolerance"]
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not 0 <= tolerance <= 1_000_000_000:
            raise EvalError("experiment.objective.tolerance must be a bounded non-negative number")
        baseline = _mapping(result["baseline"], "experiment.baseline")
        _exact(baseline, "experiment.baseline", ("run_sha256", "target_sha256", "configuration_sha256"))
        for field in ("run_sha256", "target_sha256", "configuration_sha256"):
            _digest(baseline[field], f"experiment.baseline.{field}")
    collection = _array(result[collection_key], f"{family}.{collection_key}", maximum=2000)
    identities: set[str] = set()
    for index, item in enumerate(collection):
        label = f"{family}.{collection_key}[{index}]"
        if family == "candidate":
            _validate_candidate_item(item, label)
            identity = item["candidate_id"]
        elif family == "experiment":
            _validate_experiment_candidate(item, label)
            identity = item["candidate_id"]
            if item["target_sha256"] != baseline["target_sha256"] or item["configuration_sha256"] != baseline["configuration_sha256"]:
                raise EvalError(f"{label} does not match the baseline target and configuration")
        else:
            _validate_suite_recommendation(item, label)
            identity = item["recommendation_id"]
        if identity in identities:
            raise EvalError(f"{family}.{collection_key} contains duplicate identity {identity!r}")
        identities.add(identity)
    limitations = _array(result["limitations"], f"{family}.limitations", maximum=2000)
    for index, limitation in enumerate(limitations):
        _validate_limitation(limitation, f"{family}.limitations[{index}]")
    if completion == "complete" and any(item["material"] for item in limitations):
        raise EvalError(f"complete {family} cannot retain a material limitation")
    if family == "candidate" and result["outcome"] == "candidates" and not collection:
        raise EvalError("candidate outcome candidates requires at least one candidate")
    if family == "candidate" and result["outcome"] == "none" and collection:
        raise EvalError("candidate outcome none cannot retain candidates")
    if family == "suite-audit" and result["outcome"] == "maintenance_recommended" and not any(
        item["action"] != "keep" for item in collection
    ):
        raise EvalError("maintenance_recommended requires a non-keep recommendation")
    if family == "experiment" and result["outcome"] == "clear_improvement" and not any(
        item["classification"] == "clear_improvement" for item in collection
    ):
        raise EvalError("clear_improvement outcome requires a clear candidate")
    return result


def validate_artifact(value: Any, kind: str) -> dict[str, Any]:
    if kind == "suite":
        return validate_suite(value)
    if kind == "run":
        return validate_run_result(value)
    if kind in {"candidate", "experiment", "suite-audit"}:
        return _validate_family_result(value, kind)
    raise EvalError(f"unsupported artifact kind: {kind}")


def validate_bundle_evidence(value: Any, *, require_portable: bool) -> dict[str, Any]:
    evidence = _mapping(value, "bundle evidence")
    schema = evidence.get("schema_version")
    kinds = {"project-eval-run-result/v1": "run"}
    if schema not in kinds:
        raise EvalError("bundle evidence has an unknown or incompatible schema version")
    validated = validate_artifact(evidence, kinds[schema])
    portable = _portable_run_result(validated)
    if require_portable and _canonical_bytes(validated) != _canonical_bytes(portable):
        raise EvalError("bundle evidence contains non-portable free text")
    return portable


def _display(value: str) -> str:
    pieces: list[str] = []
    for char in value:
        code = ord(char)
        if char == "&":
            pieces.append("&amp;")
        elif char == "<":
            pieces.append("&lt;")
        elif char == ">":
            pieces.append("&gt;")
        elif char in FORMAT_CONTROLS or code < 0x20 or code == 0x7F:
            pieces.append(f"\\u{code:04x}")
        else:
            pieces.append(char)
    return "".join(pieces)


def render_run(result: dict[str, Any]) -> str:
    suite = result["suite"]
    lines = [
        f"Project eval: {_display(suite['suite_id'])} / {_display(suite['profile'])}",
        f"Status: {result['completion']} · {result['outcome']} · next {result['next_action']}",
        f"Run: {_display(result['run_id'])}",
    ]
    if not result["cases"]:
        lines.append("Cases: none recorded")
    else:
        lines.append("Cases:")
        for case in result["cases"]:
            lines.append(
                f"- {_display(case['case_id'])}: {case['status']} "
                f"({case['passed']}/{case['repetitions']} passed, importance {case['importance']})"
            )
    material = [item for item in result["limitations"] if item["material"]]
    if material:
        lines.append("Material limitations:")
        lines.extend(f"- {_display(item['code'])}: {_display(item['message'])}" for item in material)
    return "\n".join(lines)


def _default_state_root() -> Path:
    system = platform.system().lower()
    if system == "windows":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise EvalError("LOCALAPPDATA is required for the default Windows state root")
        return Path(base) / "Agent Kit" / "project-eval"
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "Agent Kit" / "project-eval"
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        root = Path(base)
        if not root.is_absolute():
            raise EvalError("XDG_STATE_HOME must be absolute")
        return root / "agent-kit" / "project-eval"
    return Path.home() / ".local" / "state" / "agent-kit" / "project-eval"


def _state_root(value: str | None) -> Path:
    root = Path(value) if value else _default_state_root()
    if not root.is_absolute():
        raise EvalError("the state root must be absolute")
    return root


def _ensure_private_directory(path: Path) -> None:
    try:
        ensure_private_directory(path)
    except SafetyError as exc:
        raise EvalError(f"cannot create private state directory {path}: {exc}") from exc


def _read_small_text(path: Path, label: str) -> str:
    try:
        _, raw = read_regular(path, 8192, require_single_link=True)
    except SafetyError as exc:
        raise EvalError(f"cannot read {label}: {exc}") from exc
    try:
        value = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise EvalError(f"{label} must be UTF-8") from exc
    if CONTROL.search(value.rstrip("\r\n")):
        raise EvalError(f"{label} contains control characters")
    return value.strip()


def _git_common_directory(repository: Path) -> Path | None:
    repository = repository.absolute()
    assert_no_link_components(repository, include_final=True)
    if not repository.is_dir():
        raise EvalError(f"repository is not a directory: {repository}")
    marker = repository / ".git"
    try:
        marker_metadata = marker.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise EvalError(f"cannot inspect .git entry: {exc}") from exc
    if stat.S_ISLNK(marker_metadata.st_mode) or is_link_like(marker):
        raise EvalError("refusing a link-like .git entry")
    if stat.S_ISDIR(marker_metadata.st_mode):
        git_dir = marker.absolute()
    elif stat.S_ISREG(marker_metadata.st_mode):
        line = _read_small_text(marker, ".git file")
        prefix = "gitdir: "
        if not line.startswith(prefix):
            raise EvalError("invalid .git file")
        raw = line[len(prefix) :]
        if not raw or CONTROL.search(raw):
            raise EvalError("invalid gitdir path")
        candidate = Path(raw)
        git_dir = (repository / candidate).absolute() if not candidate.is_absolute() else candidate.absolute()
        assert_no_link_components(git_dir, include_final=True)
        if not git_dir.is_dir():
            raise EvalError("gitdir does not name a directory")
    else:
        raise EvalError(".git entry is neither a file nor a directory")
    common_file = git_dir / "commondir"
    try:
        common_metadata = common_file.lstat()
    except FileNotFoundError:
        common = git_dir
    except OSError as exc:
        raise EvalError(f"cannot inspect Git commondir: {exc}") from exc
    else:
        if stat.S_ISLNK(common_metadata.st_mode) or is_link_like(common_file):
            raise EvalError("refusing a link-like Git commondir entry")
        if not stat.S_ISREG(common_metadata.st_mode):
            raise EvalError("Git commondir entry is not a regular file")
        raw_common = _read_small_text(common_file, "Git commondir")
        candidate = Path(raw_common)
        common = (git_dir / candidate).absolute() if not candidate.is_absolute() else candidate.absolute()
    assert_no_link_components(common, include_final=True)
    if not common.is_dir():
        raise EvalError("Git common directory is not a directory")
    return common


def _namespace_link(repository: Path) -> Path | None:
    common = _git_common_directory(repository)
    return common / "agent-kit-project-eval-id" if common is not None else None


def _existing_namespace(repository: Path) -> str | None:
    link = _namespace_link(repository)
    if link is None:
        return None
    try:
        metadata = link.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise EvalError(f"cannot inspect project-eval namespace: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or is_link_like(link):
        raise EvalError("refusing a link-like project-eval namespace entry")
    if not stat.S_ISREG(metadata.st_mode):
        raise EvalError("project-eval namespace entry is not a regular file")
    namespace = _read_small_text(link, "project-eval namespace")
    if not NAMESPACE.fullmatch(namespace):
        raise EvalError("project-eval namespace is malformed")
    return namespace


def _non_git_namespace(repository: Path) -> str:
    return hashlib.sha256(str(repository.absolute()).encode("utf-8")).hexdigest()[:32]


def state_info(repository: Path, root: Path) -> dict[str, Any]:
    common = _git_common_directory(repository)
    namespace = _existing_namespace(repository) if common is not None else _non_git_namespace(repository)
    initialized = False
    if namespace is not None:
        project = root / "projects" / namespace
        try:
            metadata = project.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise EvalError(f"cannot inspect private project state: {exc}") from exc
        else:
            try:
                assert_no_link_components(project, include_final=True)
            except SafetyError as exc:
                raise EvalError(f"cannot trust private project state: {exc}") from exc
            if not stat.S_ISDIR(metadata.st_mode):
                raise EvalError("private project state is not a directory")
            initialized = True
    return {
        "schema_version": "project-eval-state-info/v1",
        "repository_kind": "git" if common is not None else "path",
        "initialized": initialized,
        "namespace": namespace,
        "state_root": str(root),
        "project_state": str(root / "projects" / namespace) if namespace is not None else None,
    }


def _publish_namespace_link(path: Path, namespace: str) -> bool:
    try:
        return publish_immutable_output(
            path,
            (namespace + "\n").encode("ascii"),
            f".{path.name}.{secrets.token_hex(16)}.tmp",
            require_identical=False,
        )
    except (OSError, SafetyError) as exc:
        raise EvalError(f"cannot create project-eval namespace link: {exc}") from exc


def _remove_empty_project_state(project: Path) -> None:
    for path in (
        project / "imports",
        project / "bundles",
        project / "receipts",
        project,
    ):
        try:
            path.rmdir()
        except FileNotFoundError:
            continue
        except OSError:
            return


def state_init(repository: Path, root: Path, requested_namespace: str | None) -> dict[str, Any]:
    common = _git_common_directory(repository)
    existing = _existing_namespace(repository) if common is not None else None
    if requested_namespace is not None and not NAMESPACE.fullmatch(requested_namespace):
        raise EvalError("--namespace must be exactly 32 lowercase hexadecimal characters")
    if existing is not None and requested_namespace not in {None, existing}:
        raise EvalError("repository already has a different private namespace")
    namespace = existing or requested_namespace or (
        secrets.token_hex(16) if common is not None else _non_git_namespace(repository)
    )
    _ensure_private_directory(root)
    project = root / "projects" / namespace
    project_preexisting = project.exists()
    for directory in (root / "projects", project, project / "receipts", project / "bundles", project / "imports"):
        _ensure_private_directory(directory)
    if common is not None and existing is None:
        link = common / "agent-kit-project-eval-id"
        if not _publish_namespace_link(link, namespace):
            winner = _read_small_text(link, "project-eval namespace")
            if not NAMESPACE.fullmatch(winner):
                raise EvalError("concurrently created project-eval namespace is malformed")
            if requested_namespace is not None and winner != requested_namespace:
                if not project_preexisting:
                    _remove_empty_project_state(project)
                raise EvalError("another initializer selected a different private namespace")
            if winner != namespace:
                if not project_preexisting:
                    _remove_empty_project_state(project)
                namespace = winner
                project = root / "projects" / namespace
                for directory in (project, project / "receipts", project / "bundles", project / "imports"):
                    _ensure_private_directory(directory)
    return state_info(repository, root)


def _sanitized(value: Any, label: str) -> None:
    stack: list[tuple[Any, str]] = [(value, label)]
    while stack:
        current, current_label = stack.pop()
        if isinstance(current, dict):
            for key, item in current.items():
                if key.lower() in SENSITIVE_KEYS:
                    raise EvalError(f"{current_label} contains prohibited sensitive field {key!r}")
                stack.append((item, f"{current_label}.{key}"))
        elif isinstance(current, list):
            stack.extend((item, f"{current_label}[{index}]") for index, item in enumerate(current))


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    return info


def _bundle_manifest(result_raw: bytes, evidence: list[tuple[str, bytes]]) -> dict[str, Any]:
    members = [
        {"path": "result.json", "size": len(result_raw), "sha256": _sha(result_raw), "media_type": "application/json"}
    ]
    members.extend(
        {"path": path, "size": len(raw), "sha256": _sha(raw), "media_type": "application/json"}
        for path, raw in evidence
    )
    return {
        "schema_version": "project-eval-bundle/v1",
        "authority": "evidence_only",
        "result_schema_version": "project-eval-run-result/v1",
        "result_sha256": _sha(result_raw),
        "sanitization": {
            "raw_transcripts": "excluded",
            "prompts": "excluded",
            "reasoning": "excluded",
            "event_streams": "excluded",
            "stderr": "excluded",
            "credentials": "excluded",
            "workspace": "excluded",
        },
        "members": sorted(members, key=lambda item: item["path"]),
    }


def _portable_run_result(result: dict[str, Any]) -> dict[str, Any]:
    portable = copy.deepcopy(result)
    for limitation in portable["limitations"]:
        limitation["message"] = "redacted; see the originating local receipt"
    for case in portable["cases"]:
        for evidence in case["evidence"]:
            evidence["summary"] = "redacted; use the bound evidence digest"
        for limitation in case["limitations"]:
            limitation["message"] = "redacted; see the originating local receipt"
    return validate_run_result(portable)


def validate_bundle_manifest(value: Any) -> dict[str, Any]:
    manifest = _mapping(value, "bundle manifest")
    _exact(manifest, "bundle manifest", ("schema_version", "authority", "result_schema_version", "result_sha256", "sanitization", "members"))
    if manifest["schema_version"] != "project-eval-bundle/v1":
        raise EvalError("unsupported bundle schema_version")
    if manifest["authority"] != "evidence_only":
        raise EvalError("bundle authority must be evidence_only")
    if manifest["result_schema_version"] != "project-eval-run-result/v1":
        raise EvalError("unsupported bundle result schema")
    _digest(manifest["result_sha256"], "bundle result_sha256")
    sanitization = _mapping(manifest["sanitization"], "bundle sanitization")
    _exact(sanitization, "bundle sanitization", ("raw_transcripts", "prompts", "reasoning", "event_streams", "stderr", "credentials", "workspace"))
    if any(value != "excluded" for value in sanitization.values()):
        raise EvalError("every bundle sanitization category must be excluded")
    members = _array(manifest["members"], "bundle members", maximum=MAX_ARCHIVE_MEMBERS, minimum=1)
    paths: set[str] = set()
    total = 0
    for index, raw_member in enumerate(members):
        label = f"bundle members[{index}]"
        member = _mapping(raw_member, label)
        _exact(member, label, ("path", "size", "sha256", "media_type"))
        path = _relative(member["path"], f"{label}.path")
        digest = _digest(member["sha256"], f"{label}.sha256")
        if path != "result.json" and path != f"evidence/{digest}.json":
            raise EvalError(f"unsupported bundle member path: {path}")
        if path in paths:
            raise EvalError(f"duplicate bundle member path: {path}")
        paths.add(path)
        size = _integer(member["size"], f"{label}.size", 0, MAX_JSON_BYTES)
        total += size
        if member["media_type"] != "application/json":
            raise EvalError(f"{label}.media_type must be application/json")
    if "result.json" not in paths:
        raise EvalError("bundle must contain result.json")
    if total > MAX_ARCHIVE_CONTENT:
        raise EvalError("bundle members exceed the aggregate content limit")
    return manifest


def bundle_export(result_path: str, evidence_paths: list[str], destination: Path) -> dict[str, Any]:
    result, _ = _load_json(result_path, "run result")
    canonical_result = _canonical_bytes(_portable_run_result(validate_run_result(result)))
    _sanitized(result, "run result")
    evidence: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    for path_value in evidence_paths:
        value, _ = _load_json(path_value, "bundle evidence")
        _sanitized(value, "bundle evidence")
        value = validate_bundle_evidence(value, require_portable=False)
        raw = _canonical_bytes(value)
        digest = _sha(raw)
        if digest in seen:
            continue
        seen.add(digest)
        evidence.append((f"evidence/{digest}.json", raw))
    evidence.sort(key=lambda item: item[0])
    manifest = _bundle_manifest(canonical_result, evidence)
    manifest_raw = _canonical_bytes(validate_bundle_manifest(manifest))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        archive.writestr(_zip_info("manifest.json"), manifest_raw)
        archive.writestr(_zip_info("result.json"), canonical_result)
        for name, raw in evidence:
            archive.writestr(_zip_info(name), raw)
    raw_bundle = output.getvalue()
    if len(raw_bundle) > MAX_ARCHIVE_BYTES:
        raise EvalError("portable bundle exceeds the archive size limit")
    try:
        write_created_output(destination, raw_bundle)
    except SafetyError as exc:
        raise EvalError(f"cannot create portable bundle: {exc}") from exc
    return {"schema_version": "project-eval-bundle-export/v1", "bundle_sha256": _sha(raw_bundle), "result_sha256": manifest["result_sha256"], "members": len(manifest["members"]), "output": str(destination)}


def _archive_member_name(value: str) -> str:
    if "\\" in value or value.startswith("/") or value.endswith("/"):
        raise EvalError(f"unsafe archive member name: {value!r}")
    path = PurePosixPath(value)
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != value:
        raise EvalError(f"unsafe archive member name: {value!r}")
    if CONTROL.search(value):
        raise EvalError("archive member name contains control characters")
    return value


def _read_bundle(path: Path) -> tuple[bytes, dict[str, Any], dict[str, bytes]]:
    try:
        _, raw_bundle = read_regular(path, MAX_ARCHIVE_BYTES, require_single_link=True)
    except SafetyError as exc:
        raise EvalError(f"cannot read portable bundle: {exc}") from exc
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw_bundle), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise EvalError(f"invalid portable bundle: {exc}") from exc
    with archive:
        infos = archive.infolist()
        if not 2 <= len(infos) <= MAX_ARCHIVE_MEMBERS + 1:
            raise EvalError("portable bundle has an invalid member count")
        names: set[str] = set()
        contents: dict[str, bytes] = {}
        total = 0
        for info in infos:
            name = _archive_member_name(info.filename)
            if name in names:
                raise EvalError(f"duplicate archive member: {name}")
            names.add(name)
            mode = (info.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            if info.is_dir() or file_type not in {0, stat.S_IFREG}:
                raise EvalError(f"archive member is not a regular file: {name}")
            if info.file_size > MAX_JSON_BYTES:
                raise EvalError(f"archive member exceeds its size limit: {name}")
            total += info.file_size
            if total > MAX_ARCHIVE_CONTENT:
                raise EvalError("portable bundle exceeds the aggregate content limit")
            if info.compress_size and info.file_size > info.compress_size * 100 + 1024:
                raise EvalError(f"archive member has an unsafe compression ratio: {name}")
            data = archive.read(info)
            if len(data) != info.file_size:
                raise EvalError(f"archive member size changed while reading: {name}")
            contents[name] = data
    if "manifest.json" not in contents or "result.json" not in contents:
        raise EvalError("portable bundle lacks manifest.json or result.json")
    manifest = validate_bundle_manifest(_decode_json(contents["manifest.json"], "bundle manifest"))
    expected = {item["path"] for item in manifest["members"]} | {"manifest.json"}
    if set(contents) != expected:
        raise EvalError("archive members do not exactly match the bundle manifest")
    for member in manifest["members"]:
        raw = contents[member["path"]]
        if len(raw) != member["size"] or _sha(raw) != member["sha256"]:
            raise EvalError(f"archive member digest or size mismatch: {member['path']}")
        value = _decode_json(raw, member["path"])
        if raw != _canonical_bytes(value):
            raise EvalError(f"archive member is not canonical JSON: {member['path']}")
        _sanitized(value, member["path"])
        if member["path"].startswith("evidence/"):
            validate_bundle_evidence(value, require_portable=True)
    result = validate_run_result(_decode_json(contents["result.json"], "bundle result"))
    if _canonical_bytes(result) != _canonical_bytes(_portable_run_result(result)):
        raise EvalError("bundle result contains non-portable free text")
    if _canonical_bytes(result) != contents["result.json"]:
        raise EvalError("bundle result is not canonical JSON")
    if _sha(contents["result.json"]) != manifest["result_sha256"]:
        raise EvalError("bundle result digest does not match its manifest")
    return raw_bundle, manifest, contents


def _write_content_addressed(path: Path, raw: bytes) -> None:
    try:
        publish_immutable_output(
            path,
            raw,
            f".{path.name}.{secrets.token_hex(16)}.tmp",
        )
    except (OSError, SafetyError) as exc:
        raise EvalError(f"cannot store evidence atomically: {exc}") from exc


def _require_state_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
        assert_no_link_components(path, include_final=True)
    except (OSError, SafetyError) as exc:
        raise EvalError(f"cannot bind {label}: {exc}") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise EvalError(f"{label} is not a directory")
    if os.name == "posix" and metadata.st_mode & 0o077:
        raise EvalError(f"{label} permissions are too broad")


def bundle_import(bundle_path: Path, repository: Path, root: Path) -> dict[str, Any]:
    raw_bundle, manifest, contents = _read_bundle(bundle_path)
    info = state_init(repository, root, None)
    namespace = info["namespace"]
    if not isinstance(namespace, str):
        raise EvalError("private state namespace was not initialized")
    project = root / "projects" / namespace
    bundle_digest = _sha(raw_bundle)
    original_result_digest = manifest["result_sha256"]
    imported_result = _decode_json(contents["result.json"], "bundle result")
    imported_result["source"] = {
        "kind": "imported",
        "authority": "evidence_only",
        "bundle_sha256": bundle_digest,
    }
    imported_result_raw = _canonical_bytes(validate_run_result(imported_result))
    result_digest = _sha(imported_result_raw)
    _write_content_addressed(project / "bundles" / f"{bundle_digest}.zip", raw_bundle)
    import_receipt = {
        "schema_version": "project-eval-import-receipt/v1",
        "authority": "evidence_only",
        "bundle_sha256": bundle_digest,
        "original_result_sha256": original_result_digest,
        "result_sha256": result_digest,
        "member_count": len(manifest["members"]),
    }
    _write_content_addressed(project / "imports" / f"{bundle_digest}.json", _canonical_bytes(import_receipt))
    _write_content_addressed(project / "receipts" / f"{result_digest}.json", imported_result_raw)
    return import_receipt


def state_index(repository: Path, root: Path) -> dict[str, Any]:
    info = state_info(repository, root)
    namespace = info["namespace"]
    receipts: list[dict[str, Any]] = []
    imports: dict[str, str] = {}
    if isinstance(namespace, str):
        if not info["initialized"]:
            if info["repository_kind"] == "git":
                raise EvalError("Git namespace exists but its private project state is missing")
            return {"schema_version": "project-eval-state-index/v1", "namespace": namespace, "receipts": receipts}
        project = root / "projects" / namespace
        for directory, label in (
            (project, "private project state"),
            (project / "imports", "private import receipt directory"),
            (project / "receipts", "private run receipt directory"),
            (project / "bundles", "private bundle directory"),
        ):
            _require_state_directory(directory, label)
        bundle_dir = project / "bundles"
        try:
            bundle_entries, _, bundles_complete = bound_directory_entries(bundle_dir, MAX_STATE_ENTRIES)
        except SafetyError as exc:
            raise EvalError(f"cannot inspect stored bundles: {exc}") from exc
        if not bundles_complete:
            raise EvalError("private bundle directory exceeds its entry limit")
        for entry in bundle_entries:
            if not re.fullmatch(r"[0-9a-f]{64}\.zip", entry.name) or not entry.is_regular or entry.link_like:
                raise EvalError(f"unexpected entry in private bundle directory: {entry.name}")
        import_dir = project / "imports"
        try:
            import_entries, _, imports_complete = bound_directory_entries(import_dir, MAX_STATE_ENTRIES)
        except SafetyError as exc:
            raise EvalError(f"cannot inspect import receipts: {exc}") from exc
        if not imports_complete:
            raise EvalError("private import receipt directory exceeds its entry limit")
        for entry in import_entries:
            path = entry.path
            if not re.fullmatch(r"[0-9a-f]{64}\.json", entry.name) or not entry.is_regular or entry.link_like:
                raise EvalError(f"unexpected entry in private import receipt directory: {entry.name}")
            value, _ = _load_json(str(path), "import receipt")
            receipt = _mapping(value, "import receipt")
            _exact(
                receipt,
                "import receipt",
                (
                    "schema_version",
                    "authority",
                    "bundle_sha256",
                    "original_result_sha256",
                    "result_sha256",
                    "member_count",
                ),
            )
            if receipt["schema_version"] != "project-eval-import-receipt/v1" or receipt["authority"] != "evidence_only":
                raise EvalError("stored import receipt has an invalid contract")
            bundle_digest = _digest(receipt["bundle_sha256"], "import receipt.bundle_sha256")
            if entry.name != f"{bundle_digest}.json":
                raise EvalError("stored import receipt is not content-addressed")
            _digest(receipt["original_result_sha256"], "import receipt.original_result_sha256")
            result_digest = _digest(receipt["result_sha256"], "import receipt.result_sha256")
            _integer(receipt["member_count"], "import receipt.member_count", 1, MAX_ARCHIVE_MEMBERS)
            if result_digest in imports and imports[result_digest] != bundle_digest:
                raise EvalError("stored import receipts disagree about result provenance")
            imports[result_digest] = bundle_digest
        receipt_dir = project / "receipts"
        try:
            receipt_entries, _, receipts_complete = bound_directory_entries(receipt_dir, MAX_STATE_ENTRIES)
        except SafetyError as exc:
            raise EvalError(f"cannot inspect stored run results: {exc}") from exc
        if not receipts_complete:
            raise EvalError("private run receipt directory exceeds its entry limit")
        for entry in receipt_entries:
            path = entry.path
            if not re.fullmatch(r"[0-9a-f]{64}\.json", entry.name) or not entry.is_regular or entry.link_like:
                raise EvalError(f"unexpected entry in private run receipt directory: {entry.name}")
            value, raw = _load_json(str(path), "stored run result")
            result = validate_run_result(value)
            digest = _sha(_canonical_bytes(result))
            if path.name != f"{digest}.json" or raw != _canonical_bytes(result):
                raise EvalError(f"stored receipt is not canonical or content-addressed: {path.name}")
            source = result["source"]
            if source["kind"] == "imported":
                expected_bundle = imports.get(digest)
                if expected_bundle is None or expected_bundle != source["bundle_sha256"]:
                    raise EvalError("imported run receipt lacks matching import provenance")
                bundle_path = project / "bundles" / f"{expected_bundle}.zip"
                try:
                    _, bundle_raw = read_regular(bundle_path, MAX_ARCHIVE_BYTES, require_single_link=True)
                except SafetyError as exc:
                    raise EvalError(f"imported run receipt lacks its bound bundle: {exc}") from exc
                if _sha(bundle_raw) != expected_bundle:
                    raise EvalError("stored imported bundle is not content-addressed")
            elif digest in imports:
                raise EvalError("local run receipt is referenced by imported provenance")
            receipts.append({"result_sha256": digest, "run_id": result["run_id"], "suite_id": result["suite"]["suite_id"], "profile": result["suite"]["profile"], "completion": result["completion"], "outcome": result["outcome"], "source": source["kind"]})
    return {"schema_version": "project-eval-state-index/v1", "namespace": namespace, "receipts": receipts}


def _write_stdout(value: Any, *, canonical: bool = False) -> None:
    if isinstance(value, str) and not canonical:
        raw = (value + "\n").encode("utf-8")
    else:
        raw = _canonical_bytes(value) + b"\n"
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        sys.stdout.write(raw.decode("utf-8"))
        sys.stdout.flush()
    else:
        stream.write(raw)
        stream.flush()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)

    validate_suite_command = commands.add_parser("validate-suite", help="validate a suite without running an agent")
    validate_suite_command.add_argument("--repo", required=True)
    validate_suite_command.add_argument("--eval-root", default="evals/project")
    validate_suite_command.add_argument("--suite", required=True)

    validate_case_command = commands.add_parser("validate-case", help="validate one evaluator-owned case control")
    validate_case_command.add_argument("--repo", required=True)
    validate_case_command.add_argument("--eval-root", default="evals/project")
    validate_case_command.add_argument("--suite", required=True)
    validate_case_command.add_argument("--case", required=True)

    prepare_case_command = commands.add_parser("prepare-case", help="materialize one isolated case without invoking an agent")
    prepare_case_command.add_argument("--repo", required=True)
    prepare_case_command.add_argument("--eval-root", default="evals/project")
    prepare_case_command.add_argument("--suite", required=True)
    prepare_case_command.add_argument("--case", required=True)
    prepare_case_command.add_argument("--workspace-root", required=True)
    prepare_case_command.add_argument("--context-output", required=True)
    prepare_case_command.add_argument("--capability", action="append", default=[])

    grade_case_command = commands.add_parser("grade-case", help="grade one prepared workspace without invoking an agent")
    grade_case_command.add_argument("--repo", required=True)
    grade_case_command.add_argument("--eval-root", default="evals/project")
    grade_case_command.add_argument("--suite", required=True)
    grade_case_command.add_argument("--case", required=True)
    grade_case_command.add_argument("--prepared", required=True)
    grade_case_command.add_argument("--allow-hidden-grader", action="store_true")
    grade_case_command.add_argument("--allow-project-checks", action="store_true")

    calibrate_command = commands.add_parser("calibrate-reconstruction", help="prove one reconstruction fixture's deterministic boundaries")
    calibrate_command.add_argument("--repo", required=True)
    calibrate_command.add_argument("--eval-root", default="evals/project")
    calibrate_command.add_argument("--suite", required=True)
    calibrate_command.add_argument("--case", required=True)
    calibrate_command.add_argument("--workspace-root", required=True)
    calibrate_command.add_argument("--allow-hidden-grader", action="store_true")
    calibrate_command.add_argument("--allow-project-checks", action="store_true")

    respond_command = commands.add_parser("respond", help="answer one bounded clarification question")
    respond_command.add_argument("--repo", required=True)
    respond_command.add_argument("--eval-root", default="evals/project")
    respond_command.add_argument("--suite", required=True)
    respond_command.add_argument("--case", required=True)
    respond_command.add_argument("--phase", required=True)
    respond_command.add_argument("--question", required=True)

    validate_artifact_command = commands.add_parser("validate-artifact", help="validate one canonical protocol artifact")
    validate_artifact_command.add_argument("--kind", choices=("suite", "run", "candidate", "experiment", "suite-audit"), required=True)
    validate_artifact_command.add_argument("--input", required=True)

    render = commands.add_parser("render", help="render a validated run result")
    render.add_argument("--input", required=True)
    render.add_argument("--format", choices=("human", "json"), default="human")

    state_info_command = commands.add_parser("state-info", help="show private evidence namespace information")
    state_info_command.add_argument("--repo", required=True)
    state_info_command.add_argument("--state-root")

    state_init_command = commands.add_parser("state-init", help="initialize private evidence state")
    state_init_command.add_argument("--repo", required=True)
    state_init_command.add_argument("--state-root")
    state_init_command.add_argument("--namespace")

    index = commands.add_parser("state-index", help="rebuild the compact evidence index")
    index.add_argument("--repo", required=True)
    index.add_argument("--state-root")

    export = commands.add_parser("bundle-export", help="create a deterministic sanitized bundle")
    export.add_argument("--result", required=True)
    export.add_argument("--evidence", action="append", default=[])
    export.add_argument("--output", required=True)

    import_command = commands.add_parser("bundle-import", help="validate and store an external evidence bundle")
    import_command.add_argument("--bundle", required=True)
    import_command.add_argument("--repo", required=True)
    import_command.add_argument("--state-root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate-suite":
            value, raw, path = load_repository_suite(
                Path(args.repo), args.eval_root, args.suite
            )
            _write_stdout(
                {
                    "valid": True,
                    "schema_version": value["schema_version"],
                    "suite_id": value["suite_id"],
                    "suite_sha256": _sha(_canonical_bytes(value)),
                    "source_sha256": _sha(raw),
                    "path": str(path),
                },
                canonical=True,
            )
        elif args.command == "validate-case":
            _, case, _, fixture = _case_components(Path(args.repo), args.eval_root, args.suite, args.case)
            control, _, fixture_digest = _CASE_ENGINE.validate_case_fixture(fixture, case)
            _write_stdout(
                {
                    "valid": True,
                    "schema_version": control["schema_version"],
                    "case_id": case["case_id"],
                    "control_sha256": _sha(_CASE_ENGINE._canonical(control)),
                    "fixture_sha256": fixture_digest,
                },
                canonical=True,
            )
        elif args.command == "prepare-case":
            repository = Path(args.repo)
            _, case, _, fixture = _case_components(repository, args.eval_root, args.suite, args.case)
            eligibility = _CASE_ENGINE.platform_eligibility(case, set(args.capability))
            if eligibility["status"] != "eligible":
                _write_stdout(
                    {
                        "schema_version": "project-eval-preparation-result/v1",
                        "case_id": case["case_id"],
                        "status": eligibility["status"],
                        "missing_capabilities": eligibility["missing_capabilities"],
                        "workspace": None,
                    },
                    canonical=True,
                )
            else:
                workspace_root = _external_workspace_path(repository, args.workspace_root, "workspace root")
                context_output = _prepared_context_output(repository, workspace_root, args.context_output)
                prepared = _CASE_ENGINE.materialize_case(fixture, case, workspace_root)
                write_created_output(context_output, _canonical_bytes(prepared) + b"\n")
                _write_stdout(prepared, canonical=True)
        elif args.command == "grade-case":
            repository = Path(args.repo)
            _, case, _, fixture = _case_components(repository, args.eval_root, args.suite, args.case)
            prepared_path = _external_workspace_path(repository, args.prepared, "prepared context")
            prepared, _ = _load_json(str(prepared_path), "prepared context")
            workspace_value = prepared.get("workspace") if isinstance(prepared, dict) else None
            if isinstance(workspace_value, str) and workspace_value:
                workspace_path = Path(workspace_value).absolute()
                if prepared_path == workspace_path or workspace_path in prepared_path.parents:
                    raise EvalError("prepared context must remain outside the graded workspace")
            grade = _CASE_ENGINE.grade_case(
                fixture,
                case,
                prepared,
                allow_hidden_grader=args.allow_hidden_grader,
                allow_project_checks=args.allow_project_checks,
            )
            _write_stdout(grade, canonical=True)
        elif args.command == "calibrate-reconstruction":
            repository = Path(args.repo)
            _, case, _, fixture = _case_components(repository, args.eval_root, args.suite, args.case)
            workspace_root = _external_workspace_path(repository, args.workspace_root, "workspace root")
            calibration = _CASE_ENGINE.calibrate_reconstruction(
                fixture,
                case,
                workspace_root,
                allow_hidden_grader=args.allow_hidden_grader,
                allow_project_checks=args.allow_project_checks,
            )
            _write_stdout(calibration, canonical=True)
        elif args.command == "respond":
            _, case, _, fixture = _case_components(Path(args.repo), args.eval_root, args.suite, args.case)
            control, _ = _CASE_ENGINE.load_control(fixture)
            if case["kind"] != "trajectory":
                raise EvalError("respond requires a trajectory case")
            _write_stdout(
                _CASE_ENGINE.respond_to_question(control, args.phase, args.question),
                canonical=True,
            )
        elif args.command == "validate-artifact":
            value, _ = _load_json(args.input, args.kind)
            artifact = validate_artifact(value, args.kind)
            _write_stdout({"valid": True, "schema_version": artifact["schema_version"]}, canonical=True)
        elif args.command == "render":
            value, _ = _load_json(args.input, "run result")
            result = validate_run_result(value)
            _write_stdout(result if args.format == "json" else render_run(result), canonical=args.format == "json")
        elif args.command == "state-info":
            _write_stdout(state_info(Path(args.repo), _state_root(args.state_root)), canonical=True)
        elif args.command == "state-init":
            _write_stdout(state_init(Path(args.repo), _state_root(args.state_root), args.namespace), canonical=True)
        elif args.command == "state-index":
            _write_stdout(state_index(Path(args.repo), _state_root(args.state_root)), canonical=True)
        elif args.command == "bundle-export":
            _write_stdout(bundle_export(args.result, args.evidence, Path(args.output)), canonical=True)
        elif args.command == "bundle-import":
            _write_stdout(bundle_import(Path(args.bundle), Path(args.repo), _state_root(args.state_root)), canonical=True)
        else:
            raise EvalError("unknown command")
        return 0
    except (EvalError, CaseError, SafetyError, OSError, zipfile.BadZipFile) as exc:
        print(f"project-eval: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
