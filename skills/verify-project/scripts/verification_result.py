#!/usr/bin/env python3
"""Finalize, validate, and render canonical verify-project results."""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

from path_safety import (
    SafetyError,
    assert_no_link_components,
    canonical_path,
    filesystem_alias_identity,
    filesystem_path,
    filesystem_snapshot,
    is_link_like,
    read_regular,
    safe_repo_path,
    text,
    write_created_output,
)
from verification_context import _protected_digest, _target_snapshot_digest
from verification_plan import (
    ALL_EFFECTS,
    DISCOVERY_KINDS,
    DISCOVERY_PROVENANCE,
    ORDINARY_EFFECTS,
    PlanError,
    _revalidate_target,
    _validate_guidance_bindings,
    _validate_target,
    _validate_target_record,
    validate_plan,
)


SCHEMA_VERSION = "1.0.0"
MAX_JSON_BYTES = 16 * 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ATTEMPT_STATUSES = {"passed", "failed", "timed_out", "unavailable", "skipped"}
NEXT_ACTIONS = {"none", "triage", "plan", "decision", "authorization", "retry", "rescope", "manual"}
RESULT_LIMITATION_CODES = {
    "target_drift", "guidance_drift", "plan_drift", "protected_state_changed",
    "check_unavailable", "check_timeout", "execution_interrupted", "evidence_gap",
    "output_unavailable", "hard_limit", "authority_unavailable", "unsupported_effect",
    "caller_cap", "semantic_ambiguity", "other",
}
OBSERVATION_CATEGORIES = {
    "missing_coverage", "disconnected_check", "late_feedback", "slow_feedback",
    "flakiness", "nondeterminism", "unsafe_mutation", "failure_visibility",
    "discoverability", "local_ci_drift", "other",
}


class ResultError(ValueError):
    """Raised when execution evidence or result data violates the contract."""


def _fail_closed(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ResultError:
            raise
        except (PlanError, SafetyError, TypeError, KeyError, IndexError) as exc:
            raise ResultError(f"malformed {function.__name__.replace('_', ' ')} input: {exc}") from exc
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
        raise ResultError(f"{label} must be an object")
    if set(value) != keys:
        raise ResultError(f"{label} fields differ: expected {sorted(keys)}, got {sorted(value)}")
    return value


def _array(value: Any, label: str, maximum: int, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ResultError(f"{label} must contain between {minimum} and {maximum} items")
    return value


def _string_array(
    value: Any, label: str, maximum: int, *, minimum: int = 0, item_maximum: int = 32
) -> list[str]:
    values = _array(value, label, maximum, minimum=minimum)
    result = [text(item, f"{label} item", maximum=item_maximum) for item in values]
    if len(result) != len(set(result)):
        raise ResultError(f"{label} contains duplicates")
    return result


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ResultError(f"{label} must be a boolean")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ResultError(f"{label} must be an integer from {minimum} through {maximum}")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ResultError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResultError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _read_json(path_value: str) -> dict[str, Any]:
    if path_value == "-":
        data = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            raise ResultError("JSON input is too large")
    else:
        _, data = read_regular(
            filesystem_path(path_value, "JSON input", expand_user=True).absolute(),
            MAX_JSON_BYTES,
            require_single_link=True,
        )
    try:
        value = json.loads(data.decode("utf-8", "strict"), object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResultError(f"invalid JSON input: {exc}") from exc
    if not isinstance(value, dict):
        raise ResultError("JSON input root must be an object")
    return value


def _stream(value: Any, label: str) -> dict[str, Any]:
    item = _exact(value, {"byte_count", "captured_byte_count", "sha256", "truncated", "excerpt", "excerpt_redacted"}, label)
    byte_count = _integer(item["byte_count"], f"{label} byte count", 0, 9007199254740991)
    captured = _integer(item["captured_byte_count"], f"{label} captured byte count", 0, 16777216)
    if captured > byte_count:
        raise ResultError(f"{label} captured bytes exceed total bytes")
    _digest(item["sha256"], f"{label} digest")
    truncated = _boolean(item["truncated"], f"{label} truncated")
    if truncated != (captured < byte_count):
        raise ResultError(f"{label} truncation state contradicts byte counts")
    if item["excerpt"] is not None:
        if not isinstance(item["excerpt"], str) or len(item["excerpt"]) > 16384:
            raise ResultError(f"{label} excerpt is invalid")
    excerpt_redacted = _boolean(item["excerpt_redacted"], f"{label} excerpt redaction")
    if (item["excerpt"] is not None) != excerpt_redacted:
        raise ResultError(f"{label} excerpt must be present only as explicitly redacted text")
    return item


def _effect(value: Any) -> dict[str, Any]:
    item = _exact(value, {"effect", "root_kind", "path", "before_sha256", "after_sha256", "classification"}, "observed effect")
    if item["effect"] not in {
        "repository_read", "local_process", "disposable_repository_write", "bounded_temporary_write",
        "source_mutation", "configuration_mutation", "dependency_installation", "network_access",
        "external_service", "persistent_process", "destructive_action", "permission_change",
        "remote_mutation", "outside_bounded_roots",
    }:
        raise ResultError("observed effect class is invalid")
    if item["root_kind"] not in {"repository", "run_temp", "outside"}:
        raise ResultError("observed effect root kind is invalid")
    canonical_path(item["path"])
    for field in ("before_sha256", "after_sha256"):
        if item[field] is not None:
            _digest(item[field], f"effect {field}")
    if item["classification"] not in {"allowed", "unexpected"}:
        raise ResultError("observed effect classification is invalid")
    return item


def _within(path: str, boundary: str) -> bool:
    return path == boundary or path.startswith(f"{boundary}/")


def _validate_effects(
    check: dict[str, Any],
    effects: list[dict[str, Any]],
    owned: dict[tuple[str, str], str | None],
    protected_path_hashes: set[str],
) -> tuple[list[dict[str, Any]], bool]:
    unexpected = False
    boundaries = check["artifact_boundaries"]
    for effect in effects:
        allowed = effect["effect"] in check["expected_effects"] and effect["root_kind"] in {"repository", "run_temp"}
        matching = [
            value for value in boundaries
            if value["root_kind"] == effect["root_kind"] and _within(effect["path"], value["path"])
        ]
        if effect["effect"] in {"disposable_repository_write", "bounded_temporary_write"}:
            allowed = allowed and bool(matching)
        elif effect["root_kind"] != "outside":
            allowed = allowed and effect["effect"] in {"repository_read", "local_process"}
        key = (effect["root_kind"], effect["path"])
        if key in owned:
            allowed = allowed and effect["before_sha256"] == owned[key]
        elif effect["effect"] in {"disposable_repository_write", "bounded_temporary_write"}:
            allowed = allowed and effect["before_sha256"] is None
            if effect["root_kind"] == "repository":
                allowed = allowed and _sha256(effect["path"].encode("utf-8")) not in protected_path_hashes
        if effect["classification"] != ("allowed" if allowed else "unexpected"):
            raise ResultError("observed effect classification is not derived from the plan")
        if allowed:
            owned[key] = effect["after_sha256"]
        else:
            unexpected = True
    return effects, unexpected


def _attempt(
    value: Any,
    check_map: dict[str, dict[str, Any]],
    seen_attempts: set[str],
    owned: dict[tuple[str, str], str | None],
    protected_path_hashes: set[str],
    target_sha256: str,
    protected_sha256: str,
    run_temp_sha256: str | None,
) -> tuple[dict[str, Any], bool, bool, bool, bool]:
    keys = {
        "attempt_id", "check_id", "repetition", "status", "exit_code",
        "duration_ms", "argv", "cwd", "target_before_sha256",
        "target_after_sha256", "protected_before_sha256",
        "protected_after_sha256", "protected_before_excluded_paths",
        "protected_after_excluded_paths", "run_temp_before_sha256",
        "run_temp_after_sha256", "run_temp_before_path_hashes",
        "run_temp_after_path_hashes", "run_temp_before_excluded_paths",
        "run_temp_after_excluded_paths", "stdout", "stderr", "observed_effects",
    }
    item = _exact(value, keys, "attempt")
    if not isinstance(item["attempt_id"], str) or not re.fullmatch(r"A[0-9]{3,6}", item["attempt_id"]) or item["attempt_id"] in seen_attempts:
        raise ResultError("attempt id is invalid or duplicated")
    seen_attempts.add(item["attempt_id"])
    if not isinstance(item["check_id"], str) or item["check_id"] not in check_map:
        raise ResultError("attempt cites an unknown check")
    check = check_map[item["check_id"]]
    repetition = _integer(item["repetition"], "attempt repetition", 1, check["repetitions"])
    if item["status"] not in ATTEMPT_STATUSES:
        raise ResultError("attempt status is invalid")
    if item["exit_code"] is not None:
        _integer(item["exit_code"], "attempt exit code", -2147483648, 2147483647)
    if item["status"] == "passed" and item["exit_code"] != 0:
        raise ResultError("passed attempt must have exit code zero")
    if item["status"] in {"unavailable", "skipped"} and item["exit_code"] is not None:
        raise ResultError("unavailable or skipped attempt cannot have an exit code")
    duration = item["duration_ms"]
    if duration is not None:
        _integer(duration, "attempt duration", 0, 86400000)
    argv = _array(item["argv"], "attempt argv", 128, minimum=1)
    if argv != check["argv"] or item["cwd"] != check["cwd"]:
        raise ResultError("attempt command differs from the canonical plan")
    stdout = _stream(item["stdout"], "stdout")
    stderr = _stream(item["stderr"], "stderr")
    target_before = _digest(item["target_before_sha256"], "attempt target-before digest")
    target_after = _digest(item["target_after_sha256"], "attempt target-after digest")
    protected_before = _digest(item["protected_before_sha256"], "attempt protected-before digest")
    protected_after = _digest(item["protected_after_sha256"], "attempt protected-after digest")
    before_excluded = [canonical_path(value) for value in _string_array(item["protected_before_excluded_paths"], "protected-before exclusions", 5000, item_maximum=4096)]
    if before_excluded != sorted(path for root_kind, path in owned if root_kind == "repository"):
        raise ResultError("attempt protected-before exclusions are not derived")
    run_temp_before = item["run_temp_before_sha256"]
    run_temp_after = item["run_temp_after_sha256"]
    run_temp_before_paths = _string_array(item["run_temp_before_path_hashes"], "run-temp-before path hashes", 100000, item_maximum=64)
    run_temp_after_paths = _string_array(item["run_temp_after_path_hashes"], "run-temp-after path hashes", 100000, item_maximum=64)
    run_temp_before_excluded = [canonical_path(value) for value in _string_array(item["run_temp_before_excluded_paths"], "run-temp-before exclusions", 5000, item_maximum=4096)]
    if run_temp_before_excluded != sorted(path for root_kind, path in owned if root_kind == "run_temp"):
        raise ResultError("attempt run-temp-before exclusions are not derived")
    if run_temp_sha256 is None:
        if run_temp_before is not None or run_temp_after is not None or run_temp_before_paths or run_temp_after_paths or run_temp_before_excluded or item["run_temp_after_excluded_paths"]:
            raise ResultError("attempt records run-temp state without a planned run-temp root")
    else:
        run_temp_before = _digest(run_temp_before, "attempt run-temp-before digest")
        run_temp_after = _digest(run_temp_after, "attempt run-temp-after digest")
        for value in run_temp_before_paths + run_temp_after_paths:
            _digest(value, "attempt run-temp path hash")
        expected_paths = [_sha256(b".")]
        if run_temp_before_paths != expected_paths or run_temp_after_paths != expected_paths:
            raise ResultError("run-temp snapshot contains undeclared paths")
    effects = [_effect(value) for value in _array(item["observed_effects"], "observed effects", 5000)]
    effects, unexpected = _validate_effects(
        check, effects, owned, protected_path_hashes
    )
    after_excluded = [canonical_path(value) for value in _string_array(item["protected_after_excluded_paths"], "protected-after exclusions", 5000, item_maximum=4096)]
    if after_excluded != sorted(path for root_kind, path in owned if root_kind == "repository"):
        raise ResultError("attempt protected-after exclusions are not derived")
    run_temp_after_excluded = [canonical_path(value) for value in _string_array(item["run_temp_after_excluded_paths"], "run-temp-after exclusions", 5000, item_maximum=4096)]
    if run_temp_after_excluded != sorted(path for root_kind, path in owned if root_kind == "run_temp"):
        raise ResultError("attempt run-temp-after exclusions are not derived")
    target_drift = target_before != target_sha256 or target_after != target_sha256
    protected_drift = protected_before != protected_sha256 or protected_after != protected_sha256
    run_temp_drift = run_temp_sha256 is not None and (
        run_temp_before != run_temp_sha256 or run_temp_after != run_temp_sha256
    )
    return ({
        "attempt_id": item["attempt_id"],
        "check_id": item["check_id"],
        "repetition": repetition,
        "status": item["status"],
        "exit_code": item["exit_code"],
        "duration_ms": duration,
        "cwd": item["cwd"],
        "argv_sha256": _sha256(_canonical_json(argv)),
        "target_before_sha256": target_before,
        "target_after_sha256": target_after,
        "protected_before_sha256": protected_before,
        "protected_after_sha256": protected_after,
        "protected_before_excluded_paths": before_excluded,
        "protected_after_excluded_paths": after_excluded,
        "run_temp_before_sha256": run_temp_before,
        "run_temp_after_sha256": run_temp_after,
        "run_temp_before_path_hashes": run_temp_before_paths,
        "run_temp_after_path_hashes": run_temp_after_paths,
        "run_temp_before_excluded_paths": run_temp_before_excluded,
        "run_temp_after_excluded_paths": run_temp_after_excluded,
        "stdout": stdout,
        "stderr": stderr,
        "observed_effects": effects,
    }, unexpected, target_drift, protected_drift, run_temp_drift)


def _derive_check_status(check: dict[str, Any], attempts: list[dict[str, Any]], prior_failed: set[str]) -> str:
    if check["decision"] != "run":
        if attempts:
            raise ResultError("a non-runnable check has execution attempts")
        return "not_run"
    failed_dependency = any(value in prior_failed for value in check["depends_on"])
    if failed_dependency and not check["useful_after_failure"]:
        if attempts:
            raise ResultError("a dependent check ran after its dependency failed")
        return "skipped"
    if not attempts:
        return "unavailable"
    statuses = {value["status"] for value in attempts}
    if "failed" in statuses:
        return "failed"
    if "timed_out" in statuses:
        return "timed_out"
    if "unavailable" in statuses:
        return "unavailable"
    if "skipped" in statuses:
        return "skipped"
    repetitions = [value["repetition"] for value in attempts]
    if len(repetitions) != check["repetitions"] or sorted(repetitions) != list(range(1, check["repetitions"] + 1)):
        return "unavailable"
    return "passed"


def _evidence(
    value: Any,
    sources: dict[str, str],
    check_map: dict[str, dict[str, Any]],
    attempt_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    item = _exact(value, {"kind", "description", "source_id", "check_id", "attempt_id", "location"}, "evidence")
    if item["kind"] not in {"target", "policy", "guidance", "discovery", "attempt", "reasoning"}:
        raise ResultError("evidence kind is invalid")
    description = text(item["description"], "evidence description", maximum=4000)
    location = item["location"]
    if location is not None:
        location = _exact(location, {"path", "start_line", "end_line"}, "evidence location")
        canonical_path(location["path"], allow_root=True)
        for field in ("start_line", "end_line"):
            if location[field] is not None:
                _integer(location[field], field.replace("_", " "), 1, 2147483647)
    if item["kind"] == "attempt":
        if item["source_id"] is not None or not isinstance(item["check_id"], str) or not isinstance(item["attempt_id"], str) or item["check_id"] not in check_map or item["attempt_id"] not in attempt_map:
            raise ResultError("attempt evidence has invalid references")
        if attempt_map[item["attempt_id"]]["check_id"] != item["check_id"]:
            raise ResultError("attempt evidence check and attempt disagree")
    elif item["kind"] in {"target", "policy", "guidance", "discovery"}:
        if not isinstance(item["source_id"], str) or sources.get(item["source_id"]) != item["kind"] or item["check_id"] is not None or item["attempt_id"] is not None:
            raise ResultError("static evidence has invalid references")
    elif any(item[field] is not None for field in ("source_id", "check_id", "attempt_id")):
        raise ResultError("reasoning evidence cannot cite an execution record")
    return {**item, "description": description, "location": location}


def _limitation(value: Any, *, derived_id: str | None = None) -> dict[str, Any]:
    expected = {"code", "message", "source_ids", "target_ids", "claim_ids", "check_ids", "material", "next_action"}
    if derived_id is None:
        item = _exact(value, expected, "result limitation draft")
    else:
        item = _exact(value, expected | {"limitation_id"}, "result limitation")
        if item["limitation_id"] != derived_id:
            raise ResultError("limitation id is not canonical")
    if item["code"] not in RESULT_LIMITATION_CODES or item["next_action"] not in NEXT_ACTIONS:
        raise ResultError("result limitation code or next action is invalid")
    result = {
        "code": item["code"],
        "message": text(item["message"], "limitation message", maximum=4000),
        "source_ids": sorted(_string_array(item["source_ids"], "limitation sources", 5000)),
        "target_ids": sorted(_string_array(item["target_ids"], "limitation targets", 20000)),
        "claim_ids": sorted(_string_array(item["claim_ids"], "limitation claims", 20000)),
        "check_ids": sorted(_string_array(item["check_ids"], "limitation checks", 128)),
        "material": _boolean(item["material"], "limitation material"),
        "next_action": item["next_action"],
    }
    return ({"limitation_id": derived_id, **result} if derived_id is not None else result)


def _next_action(limitations: list[dict[str, Any]], default: str) -> str:
    priority = ["manual", "rescope", "decision", "authorization", "retry", "plan", "triage", "none"]
    values = {item["next_action"] for item in limitations if item["material"]}
    for value in priority:
        if value in values:
            return value
    return default


def _guidance_interpretations(
    value: Any,
    *,
    source_map: dict[str, dict[str, Any]],
    target_ids: set[str],
    chain_map: dict[str, dict[str, Any]],
    targets: list[dict[str, Any]],
    claim_ids: set[str] | None,
) -> tuple[list[dict[str, Any]], set[str]]:
    interpretations: list[dict[str, Any]] = []
    interpretation_map: dict[str, dict[str, Any]] = {}
    source_order_by_chain = {
        chain_id: {
            source_id: index for index, source_id in enumerate(chain["source_ids"])
        }
        for chain_id, chain in chain_map.items()
    }
    target_chain_ids = {
        target["target_id"]: [target["guidance_chain_id"]]
        + ([target["old_guidance_chain_id"]] if target["old_guidance_chain_id"] else [])
        for target in targets
    }
    for index, raw in enumerate(
        _array(value, "guidance interpretations", 5000), start=1
    ):
        item = _exact(
            raw,
            {
                "interpretation_id",
                "source_id",
                "target_ids",
                "claim_ids",
                "kind",
                "requirement",
                "replaces_interpretation_id",
                "replacement_reason",
            },
            "guidance interpretation",
        )
        interpretation_id = text(
            item["interpretation_id"], "interpretation id", maximum=16
        )
        if interpretation_id != f"I{index:03d}":
            raise ResultError("guidance interpretation ids are not canonical")
        source_id = text(item["source_id"], "interpretation source id", maximum=16)
        selected_targets = _string_array(
            item["target_ids"], "interpretation targets", 20000, minimum=1
        )
        selected_claims = _string_array(
            item["claim_ids"], "interpretation claims", 20000
        )
        if source_id not in source_map or any(
            target_id not in target_ids for target_id in selected_targets
        ):
            raise ResultError("guidance interpretation cites an unknown source or target")
        if claim_ids is not None and any(
            claim_id not in claim_ids for claim_id in selected_claims
        ):
            raise ResultError("guidance interpretation cites an unknown claim")
        if item["kind"] not in {
            "required",
            "conditional",
            "recommended",
            "replacement",
            "artifact",
        }:
            raise ResultError("guidance interpretation kind is invalid")
        if item["kind"] in {"required", "conditional", "replacement"} and not selected_claims:
            raise ResultError("required guidance interpretation lacks a mapped claim")
        requirement = text(
            item["requirement"], "guidance interpretation requirement", maximum=4000
        )
        replaces = item["replaces_interpretation_id"]
        replacement_reason = item["replacement_reason"]
        if item["kind"] == "replacement":
            if not isinstance(replaces, str) or replaces not in interpretation_map:
                raise ResultError("replacement cites an unknown or later interpretation")
            replacement_reason = text(
                replacement_reason, "replacement reason", maximum=4000
            )
            replaced = interpretation_map[replaces]
            if replaced["kind"] == "replacement" or not set(selected_targets).issubset(
                replaced["target_ids"]
            ):
                raise ResultError("replacement scope does not identify a broader requirement")
            for target_id in selected_targets:
                if not any(
                    source_id in source_order_by_chain[chain_id]
                    and replaced["source_id"] in source_order_by_chain[chain_id]
                    and source_order_by_chain[chain_id][source_id]
                    > source_order_by_chain[chain_id][replaced["source_id"]]
                    for chain_id in target_chain_ids[target_id]
                ):
                    raise ResultError(
                        "replacement source is not closer than the replaced source"
                    )
        elif replaces is not None or replacement_reason is not None:
            raise ResultError("only replacement guidance may set replacement fields")
        canonical = {
            "interpretation_id": interpretation_id,
            "source_id": source_id,
            "target_ids": selected_targets,
            "claim_ids": selected_claims,
            "kind": item["kind"],
            "requirement": requirement,
            "replaces_interpretation_id": replaces,
            "replacement_reason": replacement_reason,
        }
        if canonical != item:
            raise ResultError("guidance interpretation arrays are not canonical")
        interpretations.append(canonical)
        interpretation_map[interpretation_id] = canonical

    replaced_targets: dict[str, set[str]] = {}
    for interpretation in interpretations:
        replaced_id = interpretation["replaces_interpretation_id"]
        if replaced_id is not None:
            replaced_targets.setdefault(replaced_id, set()).update(
                interpretation["target_ids"]
            )
    required_claims: set[str] = set()
    for interpretation in interpretations:
        if interpretation["kind"] == "replacement":
            required_claims.update(interpretation["claim_ids"])
        elif interpretation["kind"] in {"required", "conditional"} and (
            set(interpretation["target_ids"])
            - replaced_targets.get(interpretation["interpretation_id"], set())
        ):
            required_claims.update(interpretation["claim_ids"])
    return interpretations, required_claims


def _run_temp_state(
    repository_root: Path,
    root_value: str,
    excluded_paths: set[str],
) -> tuple[Path, str, str, list[str], list[dict[str, Any]]]:
    root = filesystem_path(root_value, "run temporary root", expand_user=True)
    if not root.is_absolute():
        raise ResultError("run temporary root must be absolute")
    root = root.absolute()
    repository = repository_root.absolute()
    try:
        if os.path.commonpath([os.path.normcase(str(repository)), os.path.normcase(str(root))]) == os.path.normcase(str(repository)):
            raise ResultError("run temporary root must be outside the repository")
    except ValueError:
        pass
    assert_no_link_components(root, include_final=True)
    metadata = root.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or is_link_like(root):
        raise ResultError("run temporary root must be a safe directory")
    identity = filesystem_alias_identity(root, metadata)
    identity_sha = _sha256(_canonical_json(list(identity)))
    state_sha, path_hashes, limitations = _protected_digest(
        root,
        False,
        64 * 1024 * 1024,
        excluded_paths=excluded_paths,
    )
    final = root.lstat()
    if is_link_like(root) or filesystem_alias_identity(root, final) != identity:
        raise ResultError("run temporary root changed during snapshot")
    return root, identity_sha, state_sha, path_hashes, limitations


@_fail_closed
def capture_snapshot(
    plan: dict[str, Any],
    excluded_paths: list[str],
    *,
    run_temp_root: str | None = None,
    excluded_run_temp_paths: list[str] | None = None,
) -> dict[str, Any]:
    plan = validate_plan(plan)
    root = Path(plan["target"]["repository_root"])
    excluded = sorted({canonical_path(value) for value in excluded_paths})
    baseline = set(plan["repository_state"]["protected_path_hashes"])
    boundaries = [
        boundary
        for check in plan["checks"]
        if "disposable_repository_write" in check["expected_effects"]
        for boundary in check["artifact_boundaries"]
        if boundary["root_kind"] == "repository"
    ]
    for relative in excluded:
        if _sha256(relative.encode("utf-8")) in baseline:
            raise ResultError(f"cannot exclude pre-existing protected path: {relative}")
        if not any(_within(relative, boundary["path"]) for boundary in boundaries):
            raise ResultError(f"excluded path is outside planned disposable boundaries: {relative}")
    run_temp_boundaries = [
        boundary
        for check in plan["checks"]
        if "bounded_temporary_write" in check["expected_effects"]
        for boundary in check["artifact_boundaries"]
        if boundary["root_kind"] == "run_temp"
    ]
    run_temp_excluded = sorted({canonical_path(value) for value in (excluded_run_temp_paths or [])})
    for relative in run_temp_excluded:
        if not any(_within(relative, boundary["path"]) for boundary in run_temp_boundaries):
            raise ResultError(f"run-temp exclusion is outside planned temporary boundaries: {relative}")
    if bool(run_temp_boundaries) != (run_temp_root is not None):
        raise ResultError("a run temporary root is required exactly when the plan permits temporary writes")
    target_sha, target_limits = _target_snapshot_digest(root, plan["targets"])
    protected_sha, _, protected_limits = _protected_digest(
        root,
        plan["repository_state"]["git_repository"],
        256 * 1024 * 1024,
        excluded_paths=set(excluded),
    )
    limitations = [
        {
            "code": value["code"],
            "message": value["message"],
            "material": value["material"],
        }
        for value in target_limits + protected_limits
    ]
    run_temp_identity = None
    run_temp_sha = None
    run_temp_paths: list[str] = []
    if run_temp_root is not None:
        _, run_temp_identity, run_temp_sha, run_temp_paths, run_temp_limits = _run_temp_state(
            root, run_temp_root, set(run_temp_excluded)
        )
        limitations.extend(
            {
                "code": value["code"],
                "message": value["message"],
                "material": value["material"],
            }
            for value in run_temp_limits
        )
        if run_temp_paths != [_sha256(b".")]:
            limitations.append({
                "code": "protected_state_changed",
                "message": "The bounded temporary root contains undeclared paths.",
                "material": True,
            })
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_sha256": _sha256(_canonical_json(plan)),
        "target_sha256": target_sha,
        "protected_state_sha256": protected_sha,
        "excluded_repository_paths": excluded,
        "run_temp_identity_sha256": run_temp_identity,
        "run_temp_state_sha256": run_temp_sha,
        "run_temp_path_hashes": run_temp_paths,
        "excluded_run_temp_paths": run_temp_excluded,
        "limitations": limitations,
    }


def _owned_outputs_are_safe(
    roots: dict[str, Path], owned: dict[tuple[str, str], str | None]
) -> tuple[bool, str | None]:
    for (root_kind, relative), expected_digest in owned.items():
        if root_kind not in roots:
            continue
        try:
            root = roots[root_kind]
            path = safe_repo_path(root, relative, allow_absent_final=True)
            if expected_digest is None:
                if path.exists() or path.is_symlink():
                    return False, f"deleted disposable output still exists: {relative}"
                continue
            metadata = path.lstat()
            if is_link_like(path):
                return False, f"disposable output is link-like: {relative}"
            if stat.S_ISDIR(metadata.st_mode):
                if expected_digest != _sha256(b"directory"):
                    return False, f"disposable directory digest is invalid: {relative}"
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                return False, f"disposable output is not a singly linked regular file: {relative}"
            snapshot = filesystem_snapshot(path, metadata)
            _, raw = read_regular(
                path,
                16 * 1024 * 1024,
                expected_snapshot=snapshot,
                require_single_link=True,
            )
            if _sha256(raw) != expected_digest:
                return False, f"disposable output digest does not match: {relative}"
        except (SafetyError, OSError) as exc:
            return False, f"cannot validate disposable output {relative}: {exc}"
    return True, None


@_fail_closed
def finalize(plan: dict[str, Any], run: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    try:
        plan = validate_plan(plan)
    except PlanError as exc:
        raise ResultError(str(exc)) from exc
    plan_sha = _sha256(_canonical_json(plan))
    run = _exact(run, {
        "context_sha256", "plan_sha256", "target_sha256",
        "protected_before_sha256", "protected_after_sha256",
        "run_temp_root", "run_temp_identity_sha256",
        "run_temp_before_sha256", "run_temp_after_sha256",
        "attempts", "plan_deviations", "limitations",
    }, "run record")
    context_match = _digest(run["context_sha256"], "run context digest") == plan["context_sha256"]
    plan_match = _digest(run["plan_sha256"], "run plan digest") == plan_sha
    target_match = _digest(run["target_sha256"], "run target digest") == plan["target_sha256"]
    before_match = _digest(run["protected_before_sha256"], "protected before digest") == plan["repository_state"]["protected_state_sha256"]
    needs_run_temp = any(
        "bounded_temporary_write" in check["expected_effects"]
        for check in plan["checks"]
    )
    if needs_run_temp:
        if not isinstance(run["run_temp_root"], str):
            raise ResultError("run record lacks the planned temporary root")
        run_temp_root = filesystem_path(run["run_temp_root"], "run temporary root", expand_user=True).absolute()
        run_temp_identity = _digest(run["run_temp_identity_sha256"], "run temporary root identity")
        run_temp_before = _digest(run["run_temp_before_sha256"], "run temporary before digest")
        run_temp_after_recorded = _digest(run["run_temp_after_sha256"], "run temporary after digest")
    else:
        if any(run[field] is not None for field in ("run_temp_root", "run_temp_identity_sha256", "run_temp_before_sha256", "run_temp_after_sha256")):
            raise ResultError("run record supplies temporary state for a plan without temporary writes")
        run_temp_root = None
        run_temp_identity = None
        run_temp_before = None
        run_temp_after_recorded = None
    check_map = {item["check_id"]: item for item in plan["checks"]}
    attempts_by_check = {key: [] for key in check_map}
    seen_attempts: set[str] = set()
    owned: dict[tuple[str, str], str | None] = {}
    unexpected_effect = False
    per_attempt_target_drift = False
    per_attempt_protected_drift = False
    per_attempt_run_temp_drift = False
    attempts = []
    seen_repetitions: set[tuple[str, int]] = set()
    last_check_position = -1
    terminal_checks: set[str] = set()
    check_positions = {check_id: index for index, check_id in enumerate(check_map)}
    for index, value in enumerate(_array(run["attempts"], "run attempts", 4096), start=1):
        attempt, unexpected, target_drift, protected_drift, run_temp_drift = _attempt(
            value,
            check_map,
            seen_attempts,
            owned,
            set(plan["repository_state"]["protected_path_hashes"]),
            plan["target_sha256"],
            plan["repository_state"]["protected_state_sha256"],
            run_temp_before,
        )
        expected_id = f"A{index:03d}"
        if attempt["attempt_id"] != expected_id:
            raise ResultError("attempt ids are not canonical and sequential")
        repetition_key = (attempt["check_id"], attempt["repetition"])
        if repetition_key in seen_repetitions:
            raise ResultError("a planned repetition was executed more than once")
        seen_repetitions.add(repetition_key)
        position = check_positions[attempt["check_id"]]
        if position < last_check_position:
            raise ResultError("checks were not executed in canonical plan order")
        last_check_position = position
        if attempt["check_id"] in terminal_checks:
            raise ResultError("execution retried a failed or unavailable check")
        if attempt["status"] != "passed":
            terminal_checks.add(attempt["check_id"])
        attempts.append(attempt)
        attempts_by_check[attempt["check_id"]].append(attempt)
        unexpected_effect = unexpected_effect or unexpected
        per_attempt_target_drift = per_attempt_target_drift or target_drift
        per_attempt_protected_drift = per_attempt_protected_drift or protected_drift
        per_attempt_run_temp_drift = per_attempt_run_temp_drift or run_temp_drift
        if (unexpected_effect or per_attempt_target_drift or per_attempt_protected_drift or per_attempt_run_temp_drift) and index < len(run["attempts"]):
            raise ResultError("execution continued after unexpected mutation or snapshot drift")
    check_results = []
    prior_failed: set[str] = set()
    for check in plan["checks"]:
        status = _derive_check_status(check, attempts_by_check[check["check_id"]], prior_failed)
        if status in {"failed", "timed_out", "unavailable"}:
            prior_failed.add(check["check_id"])
        check_results.append({
            "check_id": check["check_id"],
            "fingerprint": check["fingerprint"],
            "candidate_id": check["candidate_id"],
            "argv": check["argv"],
            "cwd": check["cwd"],
            "tier": check["tier"],
            "claim_ids": check["claim_ids"],
            "timeout_seconds": check["timeout_seconds"],
            "repetitions": check["repetitions"],
            "depends_on": check["depends_on"],
            "useful_after_failure": check["useful_after_failure"],
            "expected_effects": check["expected_effects"],
            "artifact_boundaries": check["artifact_boundaries"],
            "authority": check["authority"],
            "decision": check["decision"],
            "status": status,
            "attempts": [
                {key: value for key, value in attempt.items() if key != "check_id"}
                for attempt in attempts_by_check[check["check_id"]]
            ],
            "reason": check["reason"],
        })
    deviation_drafts = []
    for value in _array(run["plan_deviations"], "plan deviations", 256):
        deviation = _exact(value, {"kind", "check_id", "message", "material"}, "plan deviation")
        if deviation["kind"] not in {"unplanned_check", "changed_command", "changed_effect", "missing_attempt", "extra_attempt", "order_change", "other"}:
            raise ResultError("plan deviation kind is invalid")
        if deviation["check_id"] is not None and (not isinstance(deviation["check_id"], str) or deviation["check_id"] not in check_map):
            raise ResultError("plan deviation cites an unknown check")
        deviation_drafts.append({"kind": deviation["kind"], "check_id": deviation["check_id"], "message": text(deviation["message"], "plan deviation message", maximum=4000), "material": _boolean(deviation["material"], "plan deviation material")})
    draft = _exact(draft, {"claims", "conclusion", "observations", "limitations"}, "result draft")
    attempt_map = {item["attempt_id"]: item for item in attempts}
    static_sources = {
        **{item["target_id"]: "target" for item in plan["targets"]},
        **{item["policy_id"]: "policy" for item in plan["policy"]},
        **{item["source_id"]: "guidance" for item in plan["guidance"]["sources"]},
        **{item["discovery_id"]: "discovery" for item in plan["discovery"]},
    }
    claim_map = {item["claim_id"]: item for item in plan["claims"]}
    claim_results = []
    seen_claims: set[str] = set()
    for value in _array(draft["claims"], "result claims", 20000):
        claim = _exact(value, {"claim_id", "outcome", "evidence", "reason"}, "claim result draft")
        claim_id = claim["claim_id"]
        if not isinstance(claim_id, str) or claim_id not in claim_map or claim_id in seen_claims:
            raise ResultError("claim result cites an unknown or duplicate claim")
        seen_claims.add(claim_id)
        if claim["outcome"] not in {"supported", "disproved", "unresolved"}:
            raise ResultError("claim result outcome is invalid")
        evidence = [_evidence(item, static_sources, check_map, attempt_map) for item in _array(claim["evidence"], "claim evidence", 64)]
        attempt_statuses = [attempt_map[item["attempt_id"]]["status"] for item in evidence if item["kind"] == "attempt"]
        has_static = any(item["kind"] in {"target", "guidance", "discovery"} for item in evidence)
        requirement = claim_map[claim_id]["evidence_requirement"]
        if claim["outcome"] == "supported":
            command_support = bool(attempt_statuses) and all(value == "passed" for value in attempt_statuses)
            static_support = has_static and requirement in {"static", "either"}
            if not command_support and not static_support:
                raise ResultError("supported claim lacks compatible passing evidence")
        elif claim["outcome"] == "disproved" and not any(value in {"failed", "timed_out"} for value in attempt_statuses):
            raise ResultError("disproved claim lacks failed command evidence")
        claim_results.append({
            "claim_id": claim_id,
            "fingerprint": claim_map[claim_id]["fingerprint"],
            "material": claim_map[claim_id]["material"],
            "outcome": claim["outcome"],
            "evidence": evidence,
            "reason": text(claim["reason"], "claim result reason", maximum=4000),
        })
    if seen_claims != set(claim_map):
        raise ResultError("result draft must classify every canonical claim")
    claim_results.sort(key=lambda value: value["claim_id"])
    observations = []
    for value in _array(draft["observations"], "observations", 1000):
        observation = _exact(value, {"category", "strength", "confidence", "title", "reason", "current_run_impact", "evidence", "safe_direction"}, "observation")
        if observation["category"] not in OBSERVATION_CATEGORIES or observation["strength"] not in {"essential", "strong", "moderate", "optional"} or observation["confidence"] not in {"high", "medium", "low"} or observation["current_run_impact"] not in {"affected", "not_affected", "unknown"}:
            raise ResultError("observation classification is invalid")
        evidence = [_evidence(item, static_sources, check_map, attempt_map) for item in _array(observation["evidence"], "observation evidence", 64, minimum=1)]
        semantic = {
            "category": observation["category"],
            "strength": observation["strength"],
            "confidence": observation["confidence"],
            "title": text(observation["title"], "observation title", maximum=300),
            "reason": text(observation["reason"], "observation reason", maximum=4000),
            "current_run_impact": observation["current_run_impact"],
            "evidence": evidence,
            "safe_direction": text(observation["safe_direction"], "observation safe direction", maximum=4000),
        }
        observations.append((semantic, _sha256(_canonical_json(semantic))))
    observations.sort(key=lambda value: (value[1], value[0]["title"]))
    observations = [{"observation_id": f"O{index:03d}", "fingerprint": fingerprint, **semantic} for index, (semantic, fingerprint) in enumerate(observations, start=1)]
    limitations = []
    plan_code_map = {
        "target_unavailable": "target_drift",
        "target_limit": "hard_limit",
        "guidance_unavailable": "guidance_drift",
        "guidance_conflict": "semantic_ambiguity",
        "guidance_limit": "hard_limit",
        "discovery_unavailable": "evidence_gap",
        "discovery_limit": "hard_limit",
        "coverage_gap": "evidence_gap",
        "authority_unavailable": "authority_unavailable",
        "unsafe_candidate": "unsupported_effect",
        "unsupported_effect": "unsupported_effect",
        "caller_cap": "caller_cap",
        "context_drift": "plan_drift",
        "semantic_ambiguity": "semantic_ambiguity",
        "other": "other",
    }
    for value in plan["limitations"]:
        limitations.append({
            "code": plan_code_map[value["code"]],
            "message": value["message"],
            "source_ids": value["source_ids"],
            "target_ids": value["target_ids"],
            "claim_ids": value["claim_ids"],
            "check_ids": [],
            "material": value["material"],
            "next_action": value["next_action"],
        })
    for value in _array(run["limitations"], "run limitations", 256):
        limitations.append(_limitation(value))
    for value in _array(draft["limitations"], "draft limitations", 256):
        limitations.append(_limitation(value))
    if not context_match or not plan_match or not target_match:
        limitations.append({"code": "plan_drift" if not plan_match else "target_drift", "message": "Run evidence is not bound to the exact canonical context, plan, and target.", "source_ids": [], "target_ids": [item["target_id"] for item in plan["targets"]], "claim_ids": [], "check_ids": [], "material": True, "next_action": "retry"})
    if not before_match:
        limitations.append({"code": "protected_state_changed", "message": "Protected state did not match the plan baseline before execution.", "source_ids": [], "target_ids": [], "claim_ids": [], "check_ids": [], "material": True, "next_action": "retry"})
    for check in check_results:
        if check["status"] == "unavailable":
            limitations.append({"code": "check_unavailable", "message": f"{check['check_id']} could not produce its planned evidence.", "source_ids": [], "target_ids": [], "claim_ids": check["claim_ids"], "check_ids": [check["check_id"]], "material": True, "next_action": "retry"})
        elif check["status"] == "timed_out":
            limitations.append({"code": "check_timeout", "message": f"{check['check_id']} timed out.", "source_ids": [], "target_ids": [], "claim_ids": check["claim_ids"], "check_ids": [check["check_id"]], "material": True, "next_action": "retry"})
    if unexpected_effect:
        limitations.append({"code": "protected_state_changed", "message": "A check produced an effect outside its frozen disposable boundaries.", "source_ids": [], "target_ids": [], "claim_ids": [], "check_ids": [], "material": True, "next_action": "manual"})
    if per_attempt_target_drift:
        limitations.append({"code": "target_drift", "message": "Target state did not match the frozen plan around an executed check.", "source_ids": [], "target_ids": [item["target_id"] for item in plan["targets"]], "claim_ids": [], "check_ids": [], "material": True, "next_action": "retry"})
    if per_attempt_protected_drift:
        limitations.append({"code": "protected_state_changed", "message": "Protected repository state did not match the frozen baseline around an executed check.", "source_ids": [], "target_ids": [], "claim_ids": [], "check_ids": [], "material": True, "next_action": "manual"})
    if per_attempt_run_temp_drift:
        limitations.append({"code": "protected_state_changed", "message": "The bounded temporary root contained undeclared or changed state around an executed check.", "source_ids": [], "target_ids": [], "claim_ids": [], "check_ids": [], "material": True, "next_action": "manual"})
    if any(value["material"] for value in deviation_drafts):
        limitations.append({"code": "plan_drift", "message": "Execution materially deviated from the canonical plan.", "source_ids": [], "target_ids": [], "claim_ids": [], "check_ids": [], "material": True, "next_action": "retry"})
    supported = sorted(value["claim_id"] for value in claim_results if value["outcome"] == "supported")
    disproved = sorted(value["claim_id"] for value in claim_results if value["outcome"] == "disproved")
    unresolved = sorted(value["claim_id"] for value in claim_results if value["outcome"] == "unresolved")
    material_claims = set(plan["coverage"]["material_claim_ids"])
    unique = {_canonical_json(value): value for value in limitations}
    limitations = [unique[key] for key in sorted(unique)]
    if len(limitations) > 256:
        raise ResultError("result limitations exceed the canonical ceiling")
    limitations = [{"limitation_id": f"L{index:03d}", **value} for index, value in enumerate(limitations, start=1)]
    allowed_effects = [effect for attempt in attempts for effect in attempt["observed_effects"] if effect["classification"] == "allowed"]
    unexpected_effects = [effect for attempt in attempts for effect in attempt["observed_effects"] if effect["classification"] == "unexpected"]
    excluded_new_repo = {
        path for (root_kind, path), _ in owned.items()
        if root_kind == "repository"
    }
    repository_outputs = {
        key: value for key, value in owned.items() if key[0] == "repository"
    }
    repository_outputs_safe, repository_output_error = _owned_outputs_are_safe(
        {"repository": Path(plan["target"]["repository_root"])},
        repository_outputs,
    )
    if not repository_outputs_safe:
        limitations.append({"limitation_id": f"L{len(limitations) + 1:03d}", "code": "protected_state_changed", "message": repository_output_error or "A disposable output could not be validated.", "source_ids": [], "target_ids": [], "claim_ids": [], "check_ids": [], "material": True, "next_action": "manual"})
    after_digest, _, after_limits = _protected_digest(
        Path(plan["target"]["repository_root"]),
        plan["repository_state"]["git_repository"],
        256 * 1024 * 1024,
        excluded_paths=excluded_new_repo,
    )
    recorded_after = _digest(run["protected_after_sha256"], "protected after digest")
    protected_unchanged = before_match and repository_outputs_safe and after_digest == recorded_after == plan["repository_state"]["protected_state_sha256"] and not unexpected_effects and not after_limits
    run_temp_unchanged = True
    if run_temp_root is not None:
        run_temp_outputs = {
            key: value for key, value in owned.items() if key[0] == "run_temp"
        }
        run_temp_outputs_safe, run_temp_output_error = _owned_outputs_are_safe(
            {"run_temp": run_temp_root},
            run_temp_outputs,
        )
        if not run_temp_outputs_safe:
            limitations.append({"limitation_id": f"L{len(limitations) + 1:03d}", "code": "protected_state_changed", "message": run_temp_output_error or "A temporary output could not be validated.", "source_ids": [], "target_ids": [], "claim_ids": [], "check_ids": [], "material": True, "next_action": "manual"})
        excluded_new_temp = {
            path for (root_kind, path), _ in owned.items()
            if root_kind == "run_temp"
        }
        try:
            _, actual_identity, actual_temp_after, actual_temp_paths, temp_limits = _run_temp_state(
                Path(plan["target"]["repository_root"]),
                str(run_temp_root),
                excluded_new_temp,
            )
            run_temp_unchanged = (
                actual_identity == run_temp_identity
                and actual_temp_after == run_temp_after_recorded == run_temp_before
                and actual_temp_paths == [_sha256(b".")]
                and not temp_limits
                and run_temp_outputs_safe
                and not unexpected_effects
            )
        except (ResultError, SafetyError, OSError):
            run_temp_unchanged = False
        if not run_temp_unchanged and not any(value["code"] == "protected_state_changed" for value in limitations):
            limitations.append({"limitation_id": f"L{len(limitations) + 1:03d}", "code": "protected_state_changed", "message": "The bounded temporary root changed outside its declared new outputs or could not be revalidated.", "source_ids": [], "target_ids": [], "claim_ids": [], "check_ids": [], "material": True, "next_action": "manual"})
    if not protected_unchanged and not any(value["code"] == "protected_state_changed" for value in limitations):
        limitations.append({"limitation_id": f"L{len(limitations) + 1:03d}", "code": "protected_state_changed", "message": "Protected repository state changed or could not be revalidated.", "source_ids": [], "target_ids": [], "claim_ids": [], "check_ids": [], "material": True, "next_action": "manual"})
    try:
        for target in plan["targets"]:
            _revalidate_target(Path(plan["target"]["repository_root"]), target)
    except (PlanError, SafetyError, OSError) as exc:
        limitations.append({"limitation_id": f"L{len(limitations) + 1:03d}", "code": "target_drift", "message": f"Target state changed during verification: {exc}", "source_ids": [], "target_ids": [item["target_id"] for item in plan["targets"]], "claim_ids": [], "check_ids": [], "material": True, "next_action": "retry"})
        target_match = False
    _, required_guidance_claims = _guidance_interpretations(
        plan["guidance_interpretations"],
        source_map={item["source_id"]: item for item in plan["guidance"]["sources"]},
        target_ids={item["target_id"] for item in plan["targets"]},
        chain_map={item["chain_id"]: item for item in plan["guidance"]["chains"]},
        targets=plan["targets"],
        claim_ids=set(claim_map),
    )
    guidance_satisfied = (
        all(chain["complete"] for chain in plan["guidance"]["chains"])
        and required_guidance_claims.issubset(supported)
        and not any(
            value["code"] in {"guidance_drift", "semantic_ambiguity"}
            and value["material"]
            for value in limitations
        )
    )
    material_limitations = [value for value in limitations if value["material"]]
    material_disproved = bool(material_claims & set(disproved))
    if material_limitations:
        completion = "incomplete"
        outcome = "unknown"
        next_action = _next_action(material_limitations, "manual")
    elif material_disproved:
        completion = "complete"
        outcome = "fail"
        next_action = "triage"
    elif material_claims - set(supported) or not guidance_satisfied:
        completion = "complete"
        outcome = "unknown"
        next_action = "plan"
    else:
        completion = "complete"
        outcome = "pass"
        next_action = "none"
    sufficient = completion == "complete" and outcome == "pass"
    check_counts = {name: sum(1 for value in check_results if value["status"] == name) for name in ("passed", "failed", "timed_out", "unavailable", "skipped", "not_run")}
    result = {
        "schema_version": SCHEMA_VERSION,
        "context_sha256": plan["context_sha256"],
        "plan_sha256": plan_sha,
        "target": plan["target"],
        "target_sha256": plan["target_sha256"],
        "targets": plan["targets"],
        "repository_state": plan["repository_state"],
        "policy": plan["policy"],
        "guidance": plan["guidance"],
        "guidance_interpretations": plan["guidance_interpretations"],
        "discovery": plan["discovery"],
        "verifier": {
            "name": plan["invocation"]["freshness"]["producer"],
            "version": plan["invocation"]["freshness"]["producer_version"],
            "context_kind": plan["invocation"]["freshness"]["context_kind"],
            "consumer": plan["invocation"]["freshness"]["consumer"],
            "target_matched": target_match,
            "context_unchanged": context_match,
            "plan_unchanged": plan_match,
        },
        "completion": completion,
        "outcome": outcome,
        "next_action": next_action,
        "summary": {
            "conclusion": text(draft["conclusion"], "result conclusion", maximum=4000),
            "claim_counts": {"supported": len(supported), "disproved": len(disproved), "unresolved": len(unresolved)},
            "check_counts": check_counts,
            "observation_count": len(observations),
            "material_limitation_count": len(material_limitations),
        },
        "claims": claim_results,
        "checks": check_results,
        "plan_adherence": {"exact": not deviation_drafts, "deviations": deviation_drafts},
        "coverage": {
            "material_claim_ids": sorted(material_claims),
            "supported_claim_ids": supported,
            "disproved_claim_ids": disproved,
            "unresolved_claim_ids": unresolved,
            "attempted_tiers": sorted({check["tier"] for check in check_results if check["status"] not in {"not_run", "skipped"}}, key=("focused", "subsystem", "project").index),
            "completed_tiers": sorted({check["tier"] for check in check_results if check["status"] in {"passed", "failed"}}, key=("focused", "subsystem", "project").index),
            "required_guidance_satisfied": guidance_satisfied,
            "sufficient": sufficient,
        },
        "mutation": {
            "before_sha256": run["protected_before_sha256"],
            "after_sha256": recorded_after,
            "protected_state_unchanged": protected_unchanged,
            "run_temp": ({
                "root_identity_sha256": run_temp_identity,
                "before_sha256": run_temp_before,
                "after_sha256": run_temp_after_recorded,
                "state_unchanged": run_temp_unchanged,
            } if run_temp_root is not None else None),
            "allowed_effects": allowed_effects,
            "unexpected_effects": unexpected_effects,
        },
        "observations": observations,
        "limitations": limitations,
    }
    validate_result(result)
    return result


@_fail_closed
def validate_result(result: Any) -> dict[str, Any]:
    keys = {"schema_version", "context_sha256", "plan_sha256", "target", "target_sha256", "targets", "repository_state", "policy", "guidance", "guidance_interpretations", "discovery", "verifier", "completion", "outcome", "next_action", "summary", "claims", "checks", "plan_adherence", "coverage", "mutation", "observations", "limitations"}
    item = _exact(result, keys, "result")
    if item["schema_version"] != SCHEMA_VERSION:
        raise ResultError("unsupported result schema version")
    _digest(item["context_sha256"], "context digest")
    _digest(item["plan_sha256"], "plan digest")
    try:
        target = _validate_target(item["target"])
        targets = [_validate_target_record(value) for value in _array(item["targets"], "targets", 20000, minimum=1)]
    except PlanError as exc:
        raise ResultError(str(exc)) from exc
    target_ids = [value["target_id"] for value in targets]
    if target_ids != [f"T{index:03d}" for index in range(1, len(targets) + 1)]:
        raise ResultError("target ids are not canonical and sequential")
    target_digest = _digest(item["target_sha256"], "target digest")
    target_payload = [
        {key: value for key, value in record.items() if key not in {"guidance_chain_id", "old_guidance_chain_id"}}
        for record in targets
    ]
    if target_digest != _sha256(_canonical_json(target_payload)):
        raise ResultError("target digest does not match target inventory")
    target_id_set = set(target_ids)

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
        raise ResultError("protected path hashes are not canonical")
    if repository_identity != _sha256(os.path.normcase(target["repository_root"]).encode("utf-8")) or target["base_revision"] != repository["head_revision"]:
        raise ResultError("repository state does not match target")

    policy_ids: list[str] = []
    policy_labels: list[str] = []
    for value in _array(item["policy"], "policy", 64, minimum=1):
        policy = _exact(value, {"policy_id", "kind", "label", "sha256"}, "policy source")
        if policy["kind"] not in {"caller", "user_global", "project"}:
            raise ResultError("policy kind is invalid")
        policy_ids.append(text(policy["policy_id"], "policy id", maximum=16))
        policy_labels.append(text(policy["label"], "policy label", maximum=512))
        _digest(policy["sha256"], "policy digest")
    if policy_ids != [f"P{index:03d}" for index in range(1, len(policy_ids) + 1)] or item["policy"][0]["kind"] != "caller" or len(policy_labels) != len(set(policy_labels)):
        raise ResultError("policy identities or labels are not canonical")

    guidance = _exact(item["guidance"], {"sources", "chains"}, "guidance")
    source_ids: list[str] = []
    source_map: dict[str, dict[str, Any]] = {}
    for value in _array(guidance["sources"], "guidance sources", 5000, minimum=1):
        source = _exact(value, {"source_id", "kind", "path", "provenance", "revision", "sha256"}, "guidance source")
        source_id = text(source["source_id"], "source id", maximum=16)
        source_ids.append(source_id)
        source_map[source_id] = source
        canonical_path(source["path"])
        if source["kind"] not in {"skill", "repository"} or source["provenance"] not in {"locked_skill", "git_head", "current_filesystem"}:
            raise ResultError("guidance source classification is invalid")
        if source["revision"] is not None:
            text(source["revision"], "guidance revision", maximum=512)
        _digest(source["sha256"], "guidance digest")
        if source["kind"] == "skill":
            if source_id != "S001" or source["provenance"] != "locked_skill" or source["revision"] is None:
                raise ResultError("locked skill guidance provenance is invalid")
        elif repository["git_repository"]:
            if source["provenance"] != "git_head" or source["revision"] != repository["head_revision"]:
                raise ResultError("repository guidance is not bound to Git HEAD")
        elif source["provenance"] != "current_filesystem" or source["revision"] is not None:
            raise ResultError("non-Git repository guidance provenance is invalid")
    if source_ids != [f"S{index:03d}" for index in range(1, len(source_ids) + 1)]:
        raise ResultError("guidance source identities are not canonical")
    chain_ids: list[str] = []
    chain_map: dict[str, dict[str, Any]] = {}
    for value in _array(guidance["chains"], "guidance chains", 20000, minimum=1):
        chain = _exact(value, {"chain_id", "target_ids", "source_ids", "complete"}, "guidance chain")
        chain_id = text(chain["chain_id"], "chain id", maximum=16)
        chain_ids.append(chain_id)
        chain_map[chain_id] = chain
        chain_targets = _string_array(chain["target_ids"], "chain targets", 20000, minimum=1)
        chain_sources = _string_array(chain["source_ids"], "chain sources", 256, minimum=1)
        if any(value not in target_id_set for value in chain_targets) or any(value not in source_map for value in chain_sources) or chain_sources[0] != "S001":
            raise ResultError("guidance chain cites an unknown or invalid record")
        _boolean(chain["complete"], "guidance chain completeness")
    if chain_ids != [f"G{index:03d}" for index in range(1, len(chain_ids) + 1)]:
        raise ResultError("guidance chain identities are not canonical")
    for record in targets:
        for field in ("guidance_chain_id", "old_guidance_chain_id"):
            chain_id = record[field]
            if chain_id is not None and (chain_id not in chain_map or record["target_id"] not in chain_map[chain_id]["target_ids"]):
                raise ResultError("target guidance binding is invalid")
    for chain_id, chain in chain_map.items():
        for target_id in chain["target_ids"]:
            record = next(value for value in targets if value["target_id"] == target_id)
            if chain_id not in {record["guidance_chain_id"], record["old_guidance_chain_id"]}:
                raise ResultError("guidance chain contains an unbound target")
    try:
        _validate_guidance_bindings(targets, chain_map, source_map)
    except PlanError as exc:
        raise ResultError(str(exc)) from exc

    discovery_ids: list[str] = []
    for value in _array(item["discovery"], "discovery", 5000):
        source = _exact(value, {"discovery_id", "kind", "path", "sha256", "inspection_kind", "provenance"}, "discovery source")
        discovery_ids.append(text(source["discovery_id"], "discovery id", maximum=16))
        canonical_path(source["path"])
        if source["kind"] not in DISCOVERY_KINDS or source["provenance"] not in DISCOVERY_PROVENANCE or source["inspection_kind"] not in {"text", "binary", "metadata_only", "unreadable", "oversized", "unsupported"}:
            raise ResultError("discovery source classification is invalid")
        if source["sha256"] is not None:
            _digest(source["sha256"], "discovery digest")
        if (source["inspection_kind"] in {"text", "binary"}) != (source["sha256"] is not None):
            raise ResultError("discovery digest and inspection state are inconsistent")
    if discovery_ids != [f"D{index:03d}" for index in range(1, len(discovery_ids) + 1)]:
        raise ResultError("discovery identities are not canonical")

    verifier = _exact(item["verifier"], {"name", "version", "context_kind", "consumer", "target_matched", "context_unchanged", "plan_unchanged"}, "verifier")
    text(verifier["name"], "verifier name", maximum=128)
    for field in ("version", "consumer"):
        if verifier[field] is not None:
            text(verifier[field], f"verifier {field}", maximum=128)
    if verifier["context_kind"] not in {"fresh", "existing"}:
        raise ResultError("verifier context kind is invalid")
    for field in ("target_matched", "context_unchanged", "plan_unchanged"):
        _boolean(verifier[field], f"verifier {field.replace('_', ' ')}")

    checks = _array(item["checks"], "checks", 128)
    check_ids: list[str] = []
    candidate_ids: set[str] = set()
    check_map: dict[str, dict[str, Any]] = {}
    attempt_map: dict[str, dict[str, Any]] = {}
    encountered_attempt_ids: list[str] = []
    owned_effects: dict[tuple[str, str], str | None] = {}
    allowed_effects: list[dict[str, Any]] = []
    unexpected_effects: list[dict[str, Any]] = []
    terminal_effect_seen = False
    attempt_target_drift = False
    attempt_protected_drift = False
    attempt_run_temp_drift = False
    prior_failed: set[str] = set()
    tier_order = {"focused": 0, "subsystem": 1, "project": 2}
    for check in checks:
        required = {"check_id", "fingerprint", "candidate_id", "argv", "cwd", "tier", "claim_ids", "timeout_seconds", "repetitions", "depends_on", "useful_after_failure", "expected_effects", "artifact_boundaries", "authority", "decision", "status", "attempts", "reason"}
        check = _exact(check, required, "check result")
        check_id = text(check["check_id"], "check id", maximum=16)
        check_ids.append(check_id)
        candidate_id = text(check["candidate_id"], "candidate id", maximum=16)
        if not re.fullmatch(r"Q[0-9]{3,6}", candidate_id) or candidate_id in candidate_ids:
            raise ResultError("candidate id is invalid or duplicated")
        candidate_ids.add(candidate_id)
        argv = _array(check["argv"], "check argv", 128, minimum=1)
        for argument in argv:
            text(argument, "check argument", maximum=4096)
        cwd = canonical_path(check["cwd"], allow_root=True)
        if check["tier"] not in tier_order:
            raise ResultError("check tier is invalid")
        selected_claims = _string_array(check["claim_ids"], "check claims", 20000, minimum=1)
        dependencies = _string_array(check["depends_on"], "check dependencies", 127)
        if any(value not in check_ids[:-1] for value in dependencies):
            raise ResultError("check claims or dependencies are invalid")
        timeout = _integer(check["timeout_seconds"], "check timeout", 1, 3600)
        repetitions = _integer(check["repetitions"], "check repetitions", 1, 32)
        useful = _boolean(check["useful_after_failure"], "useful after failure")
        effects = _string_array(check["expected_effects"], "check effects", 14, minimum=1, item_maximum=64)
        if any(value not in ALL_EFFECTS for value in effects):
            raise ResultError("check effects are invalid")
        boundaries = []
        for value in _array(check["artifact_boundaries"], "artifact boundaries", 64):
            boundary = _exact(value, {"root_kind", "path"}, "artifact boundary")
            if boundary["root_kind"] not in {"repository", "run_temp"}:
                raise ResultError("artifact boundary root kind is invalid")
            boundaries.append({"root_kind": boundary["root_kind"], "path": canonical_path(boundary["path"])})
        boundary_kinds = {value["root_kind"] for value in boundaries}
        if "disposable_repository_write" in effects and "repository" not in boundary_kinds or "bounded_temporary_write" in effects and "run_temp" not in boundary_kinds:
            raise ResultError("check write effect lacks a matching artifact boundary")
        authority = _exact(check["authority"], {"source_kind", "source", "authorized"}, "check authority")
        if authority["source_kind"] not in {"caller", "user_global", "none"}:
            raise ResultError("check authority kind is invalid")
        text(authority["source"], "check authority source", maximum=4000)
        authorized = _boolean(authority["authorized"], "check authorized")
        if authorized != (authority["source_kind"] != "none") or authorized and not set(effects).issubset(ORDINARY_EFFECTS):
            raise ResultError("check authority is inconsistent")
        if check["decision"] not in {"run", "plan_only", "authorization_required", "unsupported"}:
            raise ResultError("check decision is invalid")
        if check["decision"] == "run" and not authorized or check["decision"] == "unsupported" and set(effects).issubset(ORDINARY_EFFECTS):
            raise ResultError("check decision contradicts authority or effects")
        reason = text(check["reason"], "check reason", maximum=4000)
        semantic = {"candidate_id": candidate_id, "tier": check["tier"], "reason": reason, "claim_ids": selected_claims, "depends_on": dependencies, "useful_after_failure": useful}
        fingerprint_payload = {**semantic, "argv": argv, "cwd": cwd, "expected_effects": effects, "artifact_boundaries": boundaries}
        if _digest(check["fingerprint"], "check fingerprint") != _sha256(_canonical_json(fingerprint_payload)):
            raise ResultError("check fingerprint is not derived")
        attempts_for_check: list[dict[str, Any]] = []
        repetitions_seen: set[int] = set()
        terminal_status_seen = False
        for value in _array(check["attempts"], "check attempts", 32):
            if terminal_effect_seen:
                raise ResultError("execution continued after an unexpected effect")
            attempt = _exact(value, {
                "attempt_id", "repetition", "status", "exit_code", "duration_ms",
                "cwd", "argv_sha256", "target_before_sha256",
                "target_after_sha256", "protected_before_sha256",
                "protected_after_sha256", "protected_before_excluded_paths",
                "protected_after_excluded_paths", "run_temp_before_sha256",
                "run_temp_after_sha256", "run_temp_before_path_hashes",
                "run_temp_after_path_hashes", "run_temp_before_excluded_paths",
                "run_temp_after_excluded_paths", "stdout", "stderr", "observed_effects",
            }, "attempt")
            attempt_id = text(attempt["attempt_id"], "attempt id", maximum=16)
            if not re.fullmatch(r"A[0-9]{3,6}", attempt_id) or attempt_id in attempt_map:
                raise ResultError("attempt id is invalid or duplicated")
            encountered_attempt_ids.append(attempt_id)
            repetition = _integer(attempt["repetition"], "attempt repetition", 1, repetitions)
            if repetition in repetitions_seen or terminal_status_seen:
                raise ResultError("attempt repeats work after a terminal result")
            repetitions_seen.add(repetition)
            if attempt["status"] not in ATTEMPT_STATUSES:
                raise ResultError("attempt status is invalid")
            if attempt["exit_code"] is not None:
                _integer(attempt["exit_code"], "attempt exit code", -2147483648, 2147483647)
            if attempt["status"] == "passed" and attempt["exit_code"] != 0 or attempt["status"] in {"unavailable", "skipped"} and attempt["exit_code"] is not None:
                raise ResultError("attempt status contradicts its exit code")
            if attempt["duration_ms"] is not None:
                _integer(attempt["duration_ms"], "attempt duration", 0, 86400000)
            if attempt["cwd"] != cwd or _digest(attempt["argv_sha256"], "attempt argv digest") != _sha256(_canonical_json(argv)):
                raise ResultError("attempt command differs from the canonical check")
            target_before = _digest(attempt["target_before_sha256"], "attempt target-before digest")
            target_after = _digest(attempt["target_after_sha256"], "attempt target-after digest")
            protected_before = _digest(attempt["protected_before_sha256"], "attempt protected-before digest")
            protected_after = _digest(attempt["protected_after_sha256"], "attempt protected-after digest")
            before_excluded = [canonical_path(value) for value in _string_array(attempt["protected_before_excluded_paths"], "protected-before exclusions", 5000, item_maximum=4096)]
            if before_excluded != sorted(path for root_kind, path in owned_effects if root_kind == "repository"):
                raise ResultError("attempt protected-before exclusions are not derived")
            run_temp_planned = any(
                "bounded_temporary_write" in value["expected_effects"]
                for value in checks
            )
            run_temp_before = attempt["run_temp_before_sha256"]
            run_temp_after = attempt["run_temp_after_sha256"]
            run_temp_before_paths = _string_array(attempt["run_temp_before_path_hashes"], "run-temp-before path hashes", 100000, item_maximum=64)
            run_temp_after_paths = _string_array(attempt["run_temp_after_path_hashes"], "run-temp-after path hashes", 100000, item_maximum=64)
            run_temp_before_excluded = [canonical_path(value) for value in _string_array(attempt["run_temp_before_excluded_paths"], "run-temp-before exclusions", 5000, item_maximum=4096)]
            if run_temp_before_excluded != sorted(path for root_kind, path in owned_effects if root_kind == "run_temp"):
                raise ResultError("attempt run-temp-before exclusions are not derived")
            if run_temp_planned:
                run_temp_before = _digest(run_temp_before, "attempt run-temp-before digest")
                run_temp_after = _digest(run_temp_after, "attempt run-temp-after digest")
                for path_hash in run_temp_before_paths + run_temp_after_paths:
                    _digest(path_hash, "attempt run-temp path hash")
                if run_temp_before_paths != [_sha256(b".")] or run_temp_after_paths != [_sha256(b".")]:
                    raise ResultError("run-temp snapshot contains undeclared paths")
            elif run_temp_before is not None or run_temp_after is not None or run_temp_before_paths or run_temp_after_paths or run_temp_before_excluded or attempt["run_temp_after_excluded_paths"]:
                raise ResultError("attempt records unplanned run-temp state")
            _stream(attempt["stdout"], "stdout")
            _stream(attempt["stderr"], "stderr")
            observed = [_effect(effect) for effect in _array(attempt["observed_effects"], "observed effects", 5000)]
            observed, unexpected = _validate_effects(
                check,
                observed,
                owned_effects,
                set(repository["protected_path_hashes"]),
            )
            after_excluded = [canonical_path(value) for value in _string_array(attempt["protected_after_excluded_paths"], "protected-after exclusions", 5000, item_maximum=4096)]
            if after_excluded != sorted(path for root_kind, path in owned_effects if root_kind == "repository"):
                raise ResultError("attempt protected-after exclusions are not derived")
            run_temp_after_excluded = [canonical_path(value) for value in _string_array(attempt["run_temp_after_excluded_paths"], "run-temp-after exclusions", 5000, item_maximum=4096)]
            if run_temp_after_excluded != sorted(path for root_kind, path in owned_effects if root_kind == "run_temp"):
                raise ResultError("attempt run-temp-after exclusions are not derived")
            allowed_effects.extend(effect for effect in observed if effect["classification"] == "allowed")
            unexpected_effects.extend(effect for effect in observed if effect["classification"] == "unexpected")
            terminal_effect_seen = terminal_effect_seen or unexpected
            attempt_target_drift = attempt_target_drift or target_before != target_digest or target_after != target_digest
            attempt_protected_drift = attempt_protected_drift or protected_before != repository["protected_state_sha256"] or protected_after != repository["protected_state_sha256"]
            if run_temp_planned:
                attempt_run_temp_drift = attempt_run_temp_drift or run_temp_before != run_temp_after
            terminal_effect_seen = terminal_effect_seen or attempt_target_drift or attempt_protected_drift or attempt_run_temp_drift
            if attempt["status"] != "passed":
                terminal_status_seen = True
            canonical_attempt = {**attempt, "observed_effects": observed}
            attempt_map[attempt_id] = {**canonical_attempt, "check_id": check_id}
            attempts_for_check.append({**canonical_attempt, "check_id": check_id})
        check_for_status = {**check, "repetitions": repetitions, "depends_on": dependencies, "useful_after_failure": useful}
        expected_status = _derive_check_status(check_for_status, attempts_for_check, prior_failed)
        if check["status"] != expected_status:
            raise ResultError("check status is not derived")
        if expected_status in {"failed", "timed_out", "unavailable"}:
            prior_failed.add(check_id)
        check_map[check_id] = check
    if check_ids != [f"K{index:03d}" for index in range(1, len(check_ids) + 1)]:
        raise ResultError("check ids are not canonical and sequential")
    attempt_ids = encountered_attempt_ids
    if attempt_ids != [f"A{index:03d}" for index in range(1, len(attempt_ids) + 1)]:
        raise ResultError("attempt ids are not canonical and sequential")

    static_sources = {
        **{value: "target" for value in target_ids},
        **{value: "policy" for value in policy_ids},
        **{value: "guidance" for value in source_ids},
        **{value: "discovery" for value in discovery_ids},
    }
    claims = _array(item["claims"], "claims", 20000)
    claim_ids: list[str] = []
    supported: list[str] = []
    disproved: list[str] = []
    unresolved: list[str] = []
    material_claims: list[str] = []
    for claim in claims:
        claim = _exact(claim, {"claim_id", "fingerprint", "material", "outcome", "evidence", "reason"}, "claim result")
        claim_id = text(claim["claim_id"], "claim id", maximum=16)
        claim_ids.append(claim_id)
        _digest(claim["fingerprint"], "claim fingerprint")
        material = _boolean(claim["material"], "claim material")
        if material:
            material_claims.append(claim_id)
        if claim["outcome"] not in {"supported", "disproved", "unresolved"}:
            raise ResultError("claim outcome is invalid")
        evidence = [_evidence(value, static_sources, check_map, attempt_map) for value in _array(claim["evidence"], "claim evidence", 64)]
        attempt_statuses = [attempt_map[value["attempt_id"]]["status"] for value in evidence if value["kind"] == "attempt"]
        has_static = any(value["kind"] in {"target", "guidance", "discovery"} for value in evidence)
        if claim["outcome"] == "supported" and not ((attempt_statuses and all(value == "passed" for value in attempt_statuses)) or has_static):
            raise ResultError("supported claim lacks compatible evidence")
        if claim["outcome"] == "disproved" and not any(value in {"failed", "timed_out"} for value in attempt_statuses):
            raise ResultError("disproved claim lacks failed command evidence")
        text(claim["reason"], "claim reason", maximum=4000)
        {"supported": supported, "disproved": disproved, "unresolved": unresolved}[claim["outcome"]].append(claim_id)
    if claim_ids != [f"C{index:03d}" for index in range(1, len(claim_ids) + 1)]:
        raise ResultError("claim ids are not canonical and sequential")
    claim_id_set = set(claim_ids)
    if any(value not in claim_id_set for check in checks for value in check["claim_ids"]):
        raise ResultError("check cites an unknown claim")
    _, required_guidance_claims = _guidance_interpretations(
        item["guidance_interpretations"],
        source_map=source_map,
        target_ids=target_id_set,
        chain_map=chain_map,
        targets=targets,
        claim_ids=claim_id_set,
    )

    adherence = _exact(item["plan_adherence"], {"exact", "deviations"}, "plan adherence")
    deviations = _array(adherence["deviations"], "plan deviations", 256)
    for deviation in deviations:
        deviation = _exact(deviation, {"kind", "check_id", "message", "material"}, "plan deviation")
        if deviation["kind"] not in {"unplanned_check", "changed_command", "changed_effect", "missing_attempt", "extra_attempt", "order_change", "other"} or deviation["check_id"] is not None and deviation["check_id"] not in check_map:
            raise ResultError("plan deviation is invalid")
        text(deviation["message"], "plan deviation message", maximum=4000)
        _boolean(deviation["material"], "plan deviation material")
    if _boolean(adherence["exact"], "plan adherence exact") != (not deviations):
        raise ResultError("plan adherence exactness is not derived")

    observations = _array(item["observations"], "observations", 1000)
    observation_ids: list[str] = []
    for observation in observations:
        observation = _exact(observation, {"observation_id", "fingerprint", "category", "strength", "confidence", "title", "reason", "current_run_impact", "evidence", "safe_direction"}, "observation")
        observation_ids.append(text(observation["observation_id"], "observation id", maximum=16))
        if observation["category"] not in OBSERVATION_CATEGORIES or observation["strength"] not in {"essential", "strong", "moderate", "optional"} or observation["confidence"] not in {"high", "medium", "low"} or observation["current_run_impact"] not in {"affected", "not_affected", "unknown"}:
            raise ResultError("observation classification is invalid")
        semantic = {
            "category": observation["category"],
            "strength": observation["strength"],
            "confidence": observation["confidence"],
            "title": text(observation["title"], "observation title", maximum=300),
            "reason": text(observation["reason"], "observation reason", maximum=4000),
            "current_run_impact": observation["current_run_impact"],
            "evidence": [_evidence(value, static_sources, check_map, attempt_map) for value in _array(observation["evidence"], "observation evidence", 64, minimum=1)],
            "safe_direction": text(observation["safe_direction"], "observation safe direction", maximum=4000),
        }
        if _digest(observation["fingerprint"], "observation fingerprint") != _sha256(_canonical_json(semantic)):
            raise ResultError("observation fingerprint is not derived")
    if observation_ids != [f"O{index:03d}" for index in range(1, len(observation_ids) + 1)]:
        raise ResultError("observation ids are not canonical and sequential")

    limitation_values = _array(item["limitations"], "limitations", 256)
    known_limitation_sources = target_id_set | set(policy_ids) | set(source_ids) | set(discovery_ids) | set(check_ids) | set(attempt_map)
    for index, value in enumerate(limitation_values, start=1):
        normalized = _limitation(value, derived_id=f"L{index:03d}")
        if normalized != value:
            raise ResultError("limitation arrays are not canonical")
        if any(source not in known_limitation_sources for source in value["source_ids"]) or any(target_id not in target_id_set for target_id in value["target_ids"]) or any(claim_id not in claim_id_set for claim_id in value["claim_ids"]) or any(check_id not in check_map for check_id in value["check_ids"]):
            raise ResultError("limitation cites an unknown record")
    material_limitations = [value for value in limitation_values if value["material"]]
    if not all((verifier["target_matched"], verifier["context_unchanged"], verifier["plan_unchanged"])) and not any(value["code"] in {"target_drift", "plan_drift"} and value["material"] for value in limitation_values):
        raise ResultError("verifier drift lacks a material limitation")
    if any(check["status"] == "unavailable" for check in checks) and not any(value["code"] == "check_unavailable" and value["material"] for value in limitation_values):
        raise ResultError("unavailable check lacks a material limitation")
    if any(check["status"] == "timed_out" for check in checks) and not any(value["code"] == "check_timeout" and value["material"] for value in limitation_values):
        raise ResultError("timed-out check lacks a material limitation")
    if any(value["material"] for value in deviations) and not any(value["code"] == "plan_drift" and value["material"] for value in limitation_values):
        raise ResultError("material plan deviation lacks a material limitation")
    if attempt_target_drift and not any(value["code"] == "target_drift" and value["material"] for value in limitation_values):
        raise ResultError("per-attempt target drift lacks a material limitation")
    if attempt_protected_drift and not any(value["code"] == "protected_state_changed" and value["material"] for value in limitation_values):
        raise ResultError("per-attempt protected-state drift lacks a material limitation")

    mutation = _exact(item["mutation"], {"before_sha256", "after_sha256", "protected_state_unchanged", "run_temp", "allowed_effects", "unexpected_effects"}, "mutation")
    before = _digest(mutation["before_sha256"], "mutation before digest")
    after = _digest(mutation["after_sha256"], "mutation after digest")
    if mutation["allowed_effects"] != allowed_effects or mutation["unexpected_effects"] != unexpected_effects:
        raise ResultError("mutation effects are not derived from attempts")
    protected_unchanged = _boolean(mutation["protected_state_unchanged"], "protected state unchanged")
    if protected_unchanged and (before != after or after != repository["protected_state_sha256"] or unexpected_effects):
        raise ResultError("protected-state success contradicts its evidence")
    if not protected_unchanged and not any(value["code"] == "protected_state_changed" and value["material"] for value in limitation_values):
        raise ResultError("protected-state change lacks a material limitation")
    temp_planned = any("bounded_temporary_write" in check["expected_effects"] for check in checks)
    if temp_planned:
        temp = _exact(mutation["run_temp"], {"root_identity_sha256", "before_sha256", "after_sha256", "state_unchanged"}, "run-temp mutation")
        _digest(temp["root_identity_sha256"], "run-temp root identity")
        temp_before = _digest(temp["before_sha256"], "run-temp before digest")
        temp_after = _digest(temp["after_sha256"], "run-temp after digest")
        temp_unchanged = _boolean(temp["state_unchanged"], "run-temp state unchanged")
        temp_attempts = [attempt for check in checks for attempt in check["attempts"]]
        attempt_run_temp_drift = attempt_run_temp_drift or any(
            attempt["run_temp_before_sha256"] != temp_before
            or attempt["run_temp_after_sha256"] != temp_before
            for attempt in temp_attempts
        )
        if temp_unchanged and (
            temp_before != temp_after
            or attempt_run_temp_drift
            or any(value["root_kind"] in {"run_temp", "outside"} for value in unexpected_effects)
        ):
            raise ResultError("run-temp success contradicts its evidence")
        if not temp_unchanged and not any(value["code"] == "protected_state_changed" and value["material"] for value in limitation_values):
            raise ResultError("run-temp change lacks a material limitation")
    elif mutation["run_temp"] is not None:
        raise ResultError("result records unplanned run-temp state")

    coverage = _exact(item["coverage"], {"material_claim_ids", "supported_claim_ids", "disproved_claim_ids", "unresolved_claim_ids", "attempted_tiers", "completed_tiers", "required_guidance_satisfied", "sufficient"}, "coverage")
    attempted_tiers = sorted({check["tier"] for check in checks if check["status"] not in {"not_run", "skipped"}}, key=tier_order.get)
    completed_tiers = sorted({check["tier"] for check in checks if check["status"] in {"passed", "failed"}}, key=tier_order.get)
    guidance_satisfied = (
        all(chain["complete"] for chain in guidance["chains"])
        and required_guidance_claims.issubset(supported)
        and not any(
            value["code"] in {"guidance_drift", "semantic_ambiguity"}
            and value["material"]
            for value in limitation_values
        )
    )
    if coverage["material_claim_ids"] != sorted(material_claims) or coverage["supported_claim_ids"] != sorted(supported) or coverage["disproved_claim_ids"] != sorted(disproved) or coverage["unresolved_claim_ids"] != sorted(unresolved) or coverage["attempted_tiers"] != attempted_tiers or coverage["completed_tiers"] != completed_tiers or _boolean(coverage["required_guidance_satisfied"], "required guidance satisfied") != guidance_satisfied:
        raise ResultError("result coverage is not derived")

    if item["completion"] not in {"complete", "incomplete"} or item["outcome"] not in {"pass", "fail", "unknown"} or item["next_action"] not in NEXT_ACTIONS:
        raise ResultError("result state is invalid")
    material_disproved = bool(set(material_claims) & set(disproved))
    if material_limitations:
        expected_state = ("incomplete", "unknown", _next_action(material_limitations, "manual"))
    elif material_disproved:
        expected_state = ("complete", "fail", "triage")
    elif set(material_claims) - set(supported) or not guidance_satisfied:
        expected_state = ("complete", "unknown", "plan")
    else:
        expected_state = ("complete", "pass", "none")
    if (item["completion"], item["outcome"], item["next_action"]) != expected_state:
        raise ResultError("result state is not derived")
    sufficient = expected_state == ("complete", "pass", "none")
    if _boolean(coverage["sufficient"], "coverage sufficient") != sufficient:
        raise ResultError("coverage sufficiency is not derived")

    summary = _exact(item["summary"], {"conclusion", "claim_counts", "check_counts", "observation_count", "material_limitation_count"}, "summary")
    text(summary["conclusion"], "summary conclusion", maximum=4000)
    claim_counts = _exact(summary["claim_counts"], {"supported", "disproved", "unresolved"}, "claim counts")
    check_counts = _exact(summary["check_counts"], {"passed", "failed", "timed_out", "unavailable", "skipped", "not_run"}, "check counts")
    expected_claim_counts = {"supported": len(supported), "disproved": len(disproved), "unresolved": len(unresolved)}
    expected_check_counts = {name: sum(1 for value in checks if value["status"] == name) for name in check_counts}
    if claim_counts != expected_claim_counts or check_counts != expected_check_counts or summary["observation_count"] != len(observations) or summary["material_limitation_count"] != len(material_limitations):
        raise ResultError("result summary is not derived")
    for value in list(claim_counts.values()) + list(check_counts.values()) + [summary["observation_count"], summary["material_limitation_count"]]:
        _integer(value, "summary count", 0, 20000)
    encoded = _canonical_json(item)
    if len(encoded) > MAX_JSON_BYTES:
        raise ResultError("canonical result exceeds the JSON ceiling")
    return item


def render(result: dict[str, Any]) -> str:
    result = validate_result(result)
    lines = [
        f"Verification: {result['completion']} / {result['outcome']} / next {result['next_action']}",
        result["summary"]["conclusion"],
        f"Target: {result['target']['kind']} ({len(result['targets'])} records, {result['target_sha256'][:12]})",
        f"Claims: {result['summary']['claim_counts']['supported']} supported, {result['summary']['claim_counts']['disproved']} disproved, {result['summary']['claim_counts']['unresolved']} unresolved",
        f"Checks: {result['summary']['check_counts']['passed']} passed, {result['summary']['check_counts']['failed']} failed, {result['summary']['check_counts']['timed_out']} timed out, {result['summary']['check_counts']['unavailable']} unavailable",
    ]
    for check in result["checks"]:
        lines.append(f"- {check['check_id']} [{check['tier']}]: {check['status']} — {check['reason']}")
    if result["limitations"]:
        lines.append("Limitations:")
        for limitation in result["limitations"]:
            marker = "material" if limitation["material"] else "non-material"
            lines.append(f"- {limitation['limitation_id']} [{marker}; next {limitation['next_action']}]: {limitation['message']}")
    if result["observations"]:
        lines.append("Workflow observations:")
        for observation in result["observations"]:
            lines.append(f"- {observation['observation_id']} [{observation['strength']}]: {observation['title']} — {observation['reason']}")
    return "\n".join(lines) + "\n"


def _emit(value: dict[str, Any], output_format: str, destination: str | None) -> None:
    if output_format == "human":
        data = render(value).encode("utf-8")
    elif output_format == "json":
        data = _canonical_json(value, pretty=True)
    else:
        data = (render(value) + _canonical_json(value, pretty=True).decode("utf-8")).encode("utf-8")
    if len(data) > MAX_JSON_BYTES:
        raise ResultError("rendered result exceeds the output ceiling")
    if destination is None:
        sys.stdout.buffer.write(data)
    else:
        write_created_output(filesystem_path(destination, "output path", expand_user=True).absolute(), data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    finalize_command = commands.add_parser("finalize")
    finalize_command.add_argument("--plan", required=True)
    finalize_command.add_argument("--run", required=True)
    finalize_command.add_argument("--input", required=True)
    finalize_command.add_argument("--format", choices=("human", "json", "both"), default="human")
    finalize_command.add_argument("--output")
    validate_command = commands.add_parser("validate")
    validate_command.add_argument("--input", required=True)
    render_command = commands.add_parser("render")
    render_command.add_argument("--input", required=True)
    render_command.add_argument("--format", choices=("human", "json", "both"), default="human")
    render_command.add_argument("--output")
    snapshot_command = commands.add_parser("snapshot")
    snapshot_command.add_argument("--plan", required=True)
    snapshot_command.add_argument("--exclude-repository", action="append", default=[])
    snapshot_command.add_argument("--run-temp-root")
    snapshot_command.add_argument("--exclude-run-temp", action="append", default=[])
    snapshot_command.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "finalize":
            value = finalize(_read_json(args.plan), _read_json(args.run), _read_json(args.input))
            _emit(value, args.format, args.output)
        elif args.command == "validate":
            validate_result(_read_json(args.input))
        elif args.command == "render":
            _emit(validate_result(_read_json(args.input)), args.format, args.output)
        else:
            value = capture_snapshot(
                _read_json(args.plan),
                args.exclude_repository,
                run_temp_root=args.run_temp_root,
                excluded_run_temp_paths=args.exclude_run_temp,
            )
            data = _canonical_json(value, pretty=True)
            if len(data) > MAX_JSON_BYTES:
                raise ResultError("rendered snapshot exceeds the output ceiling")
            if args.output:
                write_created_output(filesystem_path(args.output, "output path", expand_user=True).absolute(), data)
            else:
                sys.stdout.buffer.write(data)
        return 0
    except (ResultError, PlanError, SafetyError, OSError, UnicodeError, ValueError) as exc:
        print(f"verify-project result: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
