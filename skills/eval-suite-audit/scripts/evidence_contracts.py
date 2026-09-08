"""Self-contained validators for evidence accepted by eval-suite-audit."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Iterable


ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
PROFILE_ID = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
RUN_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$")
REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}={0,2}\b", re.IGNORECASE),
    re.compile(r"\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{6,}", re.IGNORECASE),
)


class ContractError(ValueError):
    """Raised when selected producer evidence is not canonical."""


def _canonical_bytes(value: Any, *, newline: bool = False) -> bytes:
    data = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (data + ("\n" if newline else "")).encode("utf-8")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _array(value: Any, label: str, *, minimum: int = 0, maximum: int) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ContractError(f"{label} must contain between {minimum} and {maximum} items")
    return value


def _exact(value: dict[str, Any], label: str, fields: Iterable[str]) -> None:
    expected = set(fields)
    if set(value) != expected:
        raise ContractError(f"{label} members differ")


def _text(value: Any, label: str, maximum: int, *, secret_check: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ContractError(f"{label} must be non-empty bounded text")
    if any(unicodedata.category(char) in {"Cc", "Cs"} for char in value):
        raise ContractError(f"{label} contains unsupported control characters")
    if secret_check and any(pattern.search(value) for pattern in SECRET_PATTERNS):
        raise ContractError(f"{label} contains secret-like content")
    return value


def _identifier(value: Any, label: str, pattern: re.Pattern[str] = ID) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ContractError(f"{label} must be a canonical identifier")
    return value


def _enum(value: Any, label: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ContractError(f"{label} must be one of {sorted(allowed)}")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ContractError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ContractError(f"{label} must be a lowercase SHA-256")
    return value


def _limitation(value: Any, label: str, *, candidate: bool = False) -> dict[str, Any]:
    item = _object(value, label)
    _exact(item, label, ("code", "message", "material"))
    _identifier(item["code"], f"{label}.code", PROFILE_ID)
    _text(item["message"], f"{label}.message", 2000, secret_check=candidate)
    if not isinstance(item["material"], bool):
        raise ContractError(f"{label}.material must be boolean")
    return item


def _measurement(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label)
    _exact(item, label, ("value", "provenance"))
    if item["value"] is not None:
        _integer(item["value"], f"{label}.value", 0, 1_000_000_000)
    provenance = _enum(
        item["provenance"],
        f"{label}.provenance",
        {"host_observed", "runner_reported", "unavailable"},
    )
    if provenance == "unavailable" and item["value"] is not None:
        raise ContractError(f"{label} unavailable provenance requires null value")
    return item


def _run_evidence(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label)
    _exact(item, label, ("evidence_id", "kind", "status", "sha256", "summary", "redacted"))
    _identifier(item["evidence_id"], f"{label}.evidence_id", PROFILE_ID)
    _enum(item["kind"], f"{label}.kind", {"assertion", "check", "measurement", "failure"})
    _enum(item["status"], f"{label}.status", {"pass", "fail", "unknown", "informational"})
    _sha(item["sha256"], f"{label}.sha256")
    _text(item["summary"], f"{label}.summary", 500)
    if item["redacted"] is not True:
        raise ContractError(f"{label}.redacted must be true")
    return item


def validate_project_eval_run(value: Any) -> dict[str, Any]:
    """Validate the complete public project-eval run-result v1 contract."""

    result = _object(value, "run result")
    _exact(
        result,
        "run result",
        (
            "schema_version", "run_id", "producer", "suite", "source", "target",
            "configuration", "completion", "outcome", "next_action", "cases",
            "summary", "limitations",
        ),
    )
    if result["schema_version"] != "project-eval-run-result/v1":
        raise ContractError("unsupported run result schema_version")
    _identifier(result["run_id"], "run result.run_id", RUN_ID)
    producer = _object(result["producer"], "run result.producer")
    _exact(producer, "run result.producer", ("name", "version"))
    _identifier(producer["name"], "run result.producer.name")
    _identifier(producer["version"], "run result.producer.version", SAFE_VALUE)
    suite = _object(result["suite"], "run result.suite")
    _exact(suite, "run result.suite", ("suite_id", "suite_sha256", "profile"))
    _identifier(suite["suite_id"], "run result.suite.suite_id")
    _sha(suite["suite_sha256"], "run result.suite.suite_sha256")
    _identifier(suite["profile"], "run result.suite.profile", PROFILE_ID)
    source = _object(result["source"], "run result.source")
    _exact(source, "run result.source", ("kind", "authority", "bundle_sha256"))
    source_kind = _enum(source["kind"], "run result.source.kind", {"local", "imported"})
    if source["authority"] != "evidence_only":
        raise ContractError("run result source must be evidence_only")
    if source["bundle_sha256"] is not None:
        _sha(source["bundle_sha256"], "run result.source.bundle_sha256")
    if (source_kind == "local") != (source["bundle_sha256"] is None):
        raise ContractError("run result source kind and bundle digest disagree")
    target = _object(result["target"], "run result.target")
    _exact(target, "run result.target", ("repository_sha256", "definition_sha256", "fixture_set_sha256", "revision"))
    for field in ("repository_sha256", "definition_sha256", "fixture_set_sha256"):
        _sha(target[field], f"run result.target.{field}")
    if target["revision"] is not None:
        _identifier(target["revision"], "run result.target.revision", REVISION)
    configuration = _object(result["configuration"], "run result.configuration")
    configuration_fields = (
        "runner", "runner_version", "agent", "model", "reasoning", "platform",
        "environment_sha256", "adapter_sha256", "launcher_sha256",
        "instructions_sha256", "profile_sha256", "configuration_sha256",
    )
    _exact(configuration, "run result.configuration", configuration_fields)
    _identifier(configuration["runner"], "run result.configuration.runner", PROFILE_ID)
    _identifier(configuration["runner_version"], "run result.configuration.runner_version", SAFE_VALUE)
    _identifier(configuration["agent"], "run result.configuration.agent", PROFILE_ID)
    for field in ("model", "reasoning"):
        if configuration[field] is not None:
            _identifier(configuration[field], f"run result.configuration.{field}", PROFILE_ID)
    _enum(configuration["platform"], "run result.configuration.platform", {"linux", "windows", "macos"})
    for field in ("environment_sha256", "adapter_sha256", "launcher_sha256", "instructions_sha256", "profile_sha256", "configuration_sha256"):
        _sha(configuration[field], f"run result.configuration.{field}")
    expected_configuration = hashlib.sha256(
        _canonical_bytes({field: configuration[field] for field in configuration_fields[:-1]})
    ).hexdigest()
    if configuration["configuration_sha256"] != expected_configuration:
        raise ContractError("run result configuration digest is inconsistent")
    completion = _enum(result["completion"], "run result.completion", {"complete", "incomplete"})
    outcome = _enum(result["outcome"], "run result.outcome", {"pass", "fail", "unknown"})
    next_action = _enum(result["next_action"], "run result.next_action", {"none", "retry", "triage", "decision", "authorization", "rescope", "manual"})
    cases = _array(result["cases"], "run result.cases", maximum=50_000)
    seen_cases: set[str] = set()
    incomplete_case = False
    required_failed = False
    for index, raw_case in enumerate(cases):
        label = f"run result.cases[{index}]"
        case = _object(raw_case, label)
        _exact(case, label, ("case_id", "importance", "status", "last_observation", "stability", "repetitions", "passed", "failed", "forbidden_effect_failures", "duration_ms", "tokens", "target_sha256", "grader_sha256", "observation_sha256s", "evidence", "limitations"))
        case_id = _identifier(case["case_id"], f"{label}.case_id")
        if case_id in seen_cases:
            raise ContractError("run result contains duplicate case identity")
        seen_cases.add(case_id)
        importance = _enum(case["importance"], f"{label}.importance", {"required", "important", "standard", "exploratory"})
        status = _enum(case["status"], f"{label}.status", {"passed", "failed", "unavailable", "not_applicable", "incomplete"})
        last = _enum(case["last_observation"], f"{label}.last_observation", {"passed", "failed", "incomplete", "unavailable", "not_applicable", "none"})
        stability = _enum(case["stability"], f"{label}.stability", {"single_observation", "repeated_observations", "insufficient"})
        repetitions = _integer(case["repetitions"], f"{label}.repetitions", 0, 100)
        passed = _integer(case["passed"], f"{label}.passed", 0, 100)
        failed = _integer(case["failed"], f"{label}.failed", 0, 100)
        forbidden = _integer(case["forbidden_effect_failures"], f"{label}.forbidden_effect_failures", 0, 100)
        if passed + failed > repetitions or forbidden > failed:
            raise ContractError(f"{label} observation counts are inconsistent")
        if status == "passed" and (passed != repetitions or failed):
            raise ContractError(f"{label} passed status is inconsistent")
        if status == "failed" and not failed:
            raise ContractError(f"{label} failed status is inconsistent")
        if status in {"unavailable", "not_applicable"} and (passed or failed):
            raise ContractError(f"{label} unavailable status is inconsistent")
        if repetitions == 0 and (last not in {"unavailable", "not_applicable", "none"} or stability != "insufficient"):
            raise ContractError(f"{label} unobserved stability is inconsistent")
        if repetitions and last == "none":
            raise ContractError(f"{label} observed run lacks a last observation")
        if stability == "single_observation" and repetitions != 1:
            raise ContractError(f"{label} single-observation stability is inconsistent")
        if stability == "repeated_observations" and repetitions < 2:
            raise ContractError(f"{label} repeated stability is inconsistent")
        if case["duration_ms"] is not None:
            _integer(case["duration_ms"], f"{label}.duration_ms", 0, 604_800_000)
        _measurement(case["tokens"], f"{label}.tokens")
        _sha(case["target_sha256"], f"{label}.target_sha256")
        _sha(case["grader_sha256"], f"{label}.grader_sha256")
        observations = _array(case["observation_sha256s"], f"{label}.observation_sha256s", maximum=100)
        for item in observations:
            _sha(item, f"{label}.observation_sha256s")
        if len(observations) != repetitions:
            raise ContractError(f"{label} does not bind every repetition")
        evidence = _array(case["evidence"], f"{label}.evidence", maximum=512)
        evidence_ids = [_run_evidence(item, f"{label}.evidence")["evidence_id"] for item in evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ContractError(f"{label} contains duplicate evidence")
        for limitation in _array(case["limitations"], f"{label}.limitations", maximum=256):
            _limitation(limitation, f"{label}.limitations")
        required_failed |= importance == "required" and status != "passed"
        incomplete_case |= status == "incomplete"
    summary = _object(result["summary"], "run result.summary")
    summary_fields = ("total_cases", "passed_cases", "failed_cases", "unavailable_cases", "total_repetitions", "passed_repetitions", "failed_repetitions", "required_failures", "important_failures", "forbidden_effect_failures", "last_observation", "stability", "duration_ms", "tokens")
    _exact(summary, "run result.summary", summary_fields)
    expected = {
        "total_cases": len(cases),
        "passed_cases": sum(item["status"] == "passed" for item in cases),
        "failed_cases": sum(item["status"] == "failed" for item in cases),
        "unavailable_cases": sum(item["status"] in {"unavailable", "not_applicable", "incomplete"} for item in cases),
        "total_repetitions": sum(item["repetitions"] for item in cases),
        "passed_repetitions": sum(item["passed"] for item in cases),
        "failed_repetitions": sum(item["failed"] for item in cases),
        "required_failures": sum(item["importance"] == "required" and item["status"] != "passed" for item in cases),
        "important_failures": sum(item["importance"] == "important" and item["status"] != "passed" for item in cases),
        "forbidden_effect_failures": sum(item["forbidden_effect_failures"] for item in cases),
        "duration_ms": sum(item["duration_ms"] or 0 for item in cases),
    }
    for field, expected_value in expected.items():
        if _integer(summary[field], f"run result.summary.{field}", 0, 604_800_000) != expected_value:
            raise ContractError(f"run result summary {field} is inconsistent")
    expected_last = cases[-1]["last_observation"] if cases else "none"
    if summary["last_observation"] != expected_last:
        raise ContractError("run result summary last observation is inconsistent")
    observed = [item for item in cases if item["repetitions"]]
    expected_stability = "repeated_observations" if observed and all(item["stability"] == "repeated_observations" for item in observed) else "single_observation" if observed else "insufficient"
    if summary["stability"] != expected_stability:
        raise ContractError("run result summary stability is inconsistent")
    summary_tokens = _measurement(summary["tokens"], "run result.summary.tokens")
    token_values = [item["tokens"]["value"] for item in cases]
    if any(item is None for item in token_values):
        if summary_tokens != {"value": None, "provenance": "unavailable"}:
            raise ContractError("run result summary tokens are inconsistent")
    elif summary_tokens["value"] != sum(token_values) or summary_tokens["provenance"] == "unavailable":
        raise ContractError("run result summary tokens are inconsistent")
    limitations = [_limitation(item, "run result.limitations") for item in _array(result["limitations"], "run result.limitations", maximum=2000)]
    if completion == "complete" and (incomplete_case or any(item["material"] for item in limitations)):
        raise ContractError("complete run retains incomplete evidence")
    if outcome == "pass" and (not cases or completion != "complete" or required_failed or next_action != "none"):
        raise ContractError("passing run is inconsistent")
    if len(_canonical_bytes(result)) > 4 * 1024 * 1024:
        raise ContractError("canonical run result exceeds the supported limit")
    return result


def _candidate_evidence(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label)
    _exact(item, label, ("evidence_id", "kind", "sha256", "summary", "redacted"))
    _identifier(item["evidence_id"], f"{label}.evidence_id", PROFILE_ID)
    _enum(item["kind"], f"{label}.kind", {"session_summary", "run_receipt", "assertion", "measurement", "repository"})
    _sha(item["sha256"], f"{label}.sha256")
    _text(item["summary"], f"{label}.summary", 500, secret_check=True)
    if item["redacted"] is not True:
        raise ContractError(f"{label}.redacted must be true")
    return item


def validate_eval_candidate(value: Any) -> dict[str, Any]:
    """Validate the complete public eval-candidate result v1 contract."""

    result = _object(value, "candidate result")
    _exact(result, "candidate result", ("schema_version", "producer", "context_sha256", "completion", "outcome", "next_action", "source_digest", "target", "candidates", "limitations"))
    if result["schema_version"] != "eval-candidate-result/v1":
        raise ContractError("unsupported candidate result schema_version")
    producer = _object(result["producer"], "candidate result.producer")
    _exact(producer, "candidate result.producer", ("name", "version"))
    _identifier(producer["name"], "candidate result.producer.name")
    _identifier(producer["version"], "candidate result.producer.version", SAFE_VALUE)
    _sha(result["context_sha256"], "candidate result.context_sha256")
    _sha(result["source_digest"], "candidate result.source_digest")
    completion = _enum(result["completion"], "candidate result.completion", {"complete", "incomplete"})
    outcome = _enum(result["outcome"], "candidate result.outcome", {"candidates", "none", "unknown"})
    next_action = _enum(result["next_action"], "candidate result.next_action", {"none", "draft", "decision", "retry", "manual"})
    target = _object(result["target"], "candidate result.target")
    _exact(target, "candidate result.target", ("repository_sha256", "suite_sha256"))
    _sha(target["repository_sha256"], "candidate result.target.repository_sha256")
    if target["suite_sha256"] is not None:
        _sha(target["suite_sha256"], "candidate result.target.suite_sha256")
    candidates = _array(result["candidates"], "candidate result.candidates", maximum=2000)
    seen: set[str] = set()
    readiness_values: list[str] = []
    for index, raw_candidate in enumerate(candidates):
        label = f"candidate result.candidates[{index}]"
        candidate = _object(raw_candidate, label)
        _exact(candidate, label, ("candidate_id", "pain_point", "proposed_case", "reason", "evidence", "evidence_count", "independent_session_count", "overlap", "confidence", "proposed_importance", "behavior_basis", "cost_effect", "promotion_requirements", "readiness"))
        candidate_id = _identifier(candidate["candidate_id"], f"{label}.candidate_id", PROFILE_ID)
        if candidate_id in seen:
            raise ContractError("candidate result contains duplicate candidate identities")
        seen.add(candidate_id)
        _text(candidate["pain_point"], f"{label}.pain_point", 2000, secret_check=True)
        proposed = _object(candidate["proposed_case"], f"{label}.proposed_case")
        _exact(proposed, f"{label}.proposed_case", ("kind", "phase", "task_summary"))
        _enum(proposed["kind"], f"{label}.proposed_case.kind", {"explanation", "implementation", "trajectory"})
        if proposed["phase"] is not None:
            _enum(proposed["phase"], f"{label}.proposed_case.phase", {"intake", "clarification", "specification", "planning", "implementation", "verification", "reporting"})
        _text(proposed["task_summary"], f"{label}.proposed_case.task_summary", 2000, secret_check=True)
        _text(candidate["reason"], f"{label}.reason", 2000, secret_check=True)
        evidence = [_candidate_evidence(item, f"{label}.evidence") for item in _array(candidate["evidence"], f"{label}.evidence", minimum=1, maximum=256)]
        if len({item["evidence_id"] for item in evidence}) != len(evidence):
            raise ContractError(f"{label} contains duplicate evidence")
        count = _integer(candidate["evidence_count"], f"{label}.evidence_count", 1, 1_000_000)
        sessions = _integer(candidate["independent_session_count"], f"{label}.independent_session_count", 1, 1_000_000)
        if count != len(evidence) or sessions > count:
            raise ContractError(f"{label} evidence counts are inconsistent")
        expected_confidence = "high" if sessions >= 3 else "medium" if sessions == 2 else "low"
        if candidate["confidence"] != expected_confidence:
            raise ContractError(f"{label} confidence is inconsistent")
        overlap = _object(candidate["overlap"], f"{label}.overlap")
        _exact(overlap, f"{label}.overlap", ("relation", "case_ids", "reason"))
        relation = _enum(overlap["relation"], f"{label}.overlap.relation", {"none", "partial", "duplicate", "extends"})
        case_ids = [_identifier(item, f"{label}.overlap.case_ids", PROFILE_ID) for item in _array(overlap["case_ids"], f"{label}.overlap.case_ids", maximum=256)]
        if len(set(case_ids)) != len(case_ids) or ((relation == "none") != (not case_ids)):
            raise ContractError(f"{label} overlap is inconsistent")
        _text(overlap["reason"], f"{label}.overlap.reason", 1000, secret_check=True)
        _enum(candidate["proposed_importance"], f"{label}.proposed_importance", {"required", "important", "standard", "exploratory"})
        basis = _enum(candidate["behavior_basis"], f"{label}.behavior_basis", {"existing", "new", "ambiguous"})
        cost = _enum(candidate["cost_effect"], f"{label}.cost_effect", {"decrease", "none", "increase", "unknown"})
        requirements = _array(candidate["promotion_requirements"], f"{label}.promotion_requirements", maximum=64)
        for requirement in requirements:
            _text(requirement, f"{label}.promotion_requirements", 500, secret_check=True)
        expected_readiness = "decision_required" if basis in {"new", "ambiguous"} or cost in {"increase", "unknown"} else "needs_evidence" if requirements else "ready"
        readiness = _enum(candidate["readiness"], f"{label}.readiness", {"ready", "decision_required", "needs_evidence"})
        if readiness != expected_readiness:
            raise ContractError(f"{label} readiness is inconsistent")
        readiness_values.append(readiness)
    limitations = [_limitation(item, "candidate result.limitations", candidate=True) for item in _array(result["limitations"], "candidate result.limitations", maximum=2000)]
    expected_completion = "incomplete" if any(item["material"] for item in limitations) else "complete"
    if completion != expected_completion:
        raise ContractError("candidate result completion is inconsistent")
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
        raise ContractError("candidate result outcome is inconsistent")
    if len(_canonical_bytes(result, newline=True)) > 16 * 1024 * 1024:
        raise ContractError("canonical candidate result exceeds the supported limit")
    return result
