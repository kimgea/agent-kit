"""Resolve and rank bounded paired project-eval harness experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable

import evidence_contracts
import path_safety


VERSION = "1.0.0"
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_CONTEXT_BYTES = 16 * 1024 * 1024
MAX_RESULT_BYTES = 4 * 1024 * 1024
MAX_CANDIDATES = 64
MAX_SUITES = 32
MAX_RUNS = 512
MAX_SURFACES = 256
MAX_PATCH_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 300_000
ID = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$")
HEAD_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CLASSIFICATION_ORDER = {
    "clear_improvement": 0,
    "tradeoff": 1,
    "inconclusive": 2,
    "no_improvement": 3,
    "incomplete": 4,
}


class ExperimentError(ValueError):
    """Raised when experiment authority or evidence is invalid."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ExperimentError(f"duplicate JSON member: {key}")
        value[key] = item
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path, label: str, *, maximum: int = MAX_INPUT_BYTES) -> tuple[Any, bytes]:
    try:
        _, raw = path_safety.read_regular(path, maximum, require_single_link=True)
    except path_safety.SafetyError as exc:
        raise ExperimentError(f"cannot read {label}: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=lambda token: (_ for _ in ()).throw(ExperimentError(f"invalid JSON constant: {token}")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExperimentError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    nodes = 0
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise ExperimentError(f"{label} exceeds JSON structure limits")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
    return value, raw


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExperimentError(f"{label} must be an object")
    return value


def _array(value: Any, label: str, *, minimum: int = 0, maximum: int) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ExperimentError(f"{label} must contain between {minimum} and {maximum} items")
    return value


def _exact(value: dict[str, Any], label: str, fields: Iterable[str]) -> None:
    expected = set(fields)
    if set(value) != expected:
        raise ExperimentError(f"{label} members differ")


def _text(value: Any, label: str, maximum: int = 4000) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ExperimentError(f"{label} must be non-empty bounded text")
    if any(unicodedata.category(char) in {"Cc", "Cs"} for char in value):
        raise ExperimentError(f"{label} contains unsupported control characters")
    return value


def _identifier(value: Any, label: str, pattern: re.Pattern[str] = ID) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ExperimentError(f"{label} must be a canonical identifier")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ExperimentError(f"{label} must be a lowercase SHA-256")
    return value


def _enum(value: Any, label: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ExperimentError(f"{label} must be one of {sorted(allowed)}")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ExperimentError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _number(value: Any, label: str, minimum: float, maximum: float, *, nullable: bool = False) -> float | int | None:
    if nullable and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        suffix = " or null" if nullable else ""
        raise ExperimentError(f"{label} must be a bounded number{suffix}")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ExperimentError(f"{label} must be boolean")
    return value


def _unique_ids(value: Any, label: str, *, maximum: int = 512) -> list[str]:
    items = [_identifier(item, label) for item in _array(value, label, maximum=maximum)]
    if len(set(items)) != len(items):
        raise ExperimentError(f"{label} must be unique")
    return items


def _git(root: Path, *arguments: str, maximum: int = MAX_INPUT_BYTES) -> bytes:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_LITERAL_PATHSPECS"] = "1"
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        environment.pop(key, None)
    command = ["git", "--no-pager", "-c", "core.fsmonitor=false", "-c", f"core.hooksPath={os.devnull}", *arguments]
    try:
        completed = subprocess.run(command, cwd=root, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExperimentError(f"cannot inspect repository: {exc}") from exc
    if completed.returncode:
        message = completed.stderr.decode("utf-8", "replace")[:500]
        raise ExperimentError(f"cannot inspect repository: {message}")
    if len(completed.stdout) > maximum:
        raise ExperimentError("Git metadata exceeds the supported limit")
    return completed.stdout


def _repository(root: Path) -> tuple[Path, str]:
    original = root.absolute()
    try:
        path_safety.assert_no_link_components(original, include_final=True)
    except path_safety.SafetyError as exc:
        raise ExperimentError(f"cannot bind repository root: {exc}") from exc
    if not original.is_dir():
        raise ExperimentError("repository root must be a directory")
    try:
        top = Path(_git(original, "rev-parse", "--show-toplevel").decode("utf-8").strip()).absolute()
    except UnicodeDecodeError as exc:
        raise ExperimentError("Git repository root is not UTF-8") from exc
    try:
        same = os.path.samefile(original, top)
    except OSError:
        same = os.path.normcase(str(original)) == os.path.normcase(str(top))
    if not same:
        raise ExperimentError("--repo must name the Git worktree root")
    head = _git(original, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
    if HEAD_RE.fullmatch(head) is None:
        raise ExperimentError("Git HEAD is not a supported object identifier")
    return original, head


def _is_within(path: Path, root: Path) -> bool:
    try:
        pairs = (
            (path.absolute(), root.absolute()),
            (path.resolve(strict=False), root.resolve(strict=False)),
        )
        return any(
            os.path.commonpath(
                (os.path.normcase(str(candidate)), os.path.normcase(str(boundary)))
            )
            == os.path.normcase(str(boundary))
            for candidate, boundary in pairs
        )
    except (OSError, ValueError):
        return False


def _reject_repository_output(path: Path, repository: Path) -> None:
    if _is_within(path, repository):
        raise ExperimentError("output must be outside the active checkout")


def _committed_surface(root: Path, path: str) -> dict[str, Any]:
    canonical = path_safety.canonical_path(path)
    raw_index = _git(root, "ls-files", "-s", "-z", "--", canonical)
    records = [record for record in raw_index.split(b"\0") if record]
    if len(records) != 1 or b"\t" not in records[0]:
        raise ExperimentError(f"editable surface must be one tracked file: {canonical}")
    header, raw_path = records[0].split(b"\t", 1)
    try:
        indexed_path = raw_path.decode("utf-8")
        fields = header.decode("ascii").split()
    except UnicodeDecodeError as exc:
        raise ExperimentError(f"editable surface index entry is not canonical UTF-8: {canonical}") from exc
    if len(fields) != 3 or indexed_path != canonical or fields[2] != "0":
        raise ExperimentError(f"editable surface has unsupported index state: {canonical}")
    mode, object_id = fields[0], fields[1]
    if mode not in {"100644", "100755"} or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", object_id):
        raise ExperimentError(f"editable surface is not a regular tracked file: {canonical}")
    committed = _git(root, "cat-file", "blob", object_id, maximum=MAX_PATCH_BYTES)
    live_path = path_safety.safe_repo_path(root, canonical)
    try:
        metadata, live = path_safety.read_regular(live_path, MAX_PATCH_BYTES, require_single_link=True)
    except path_safety.SafetyError as exc:
        raise ExperimentError(f"cannot bind editable surface {canonical}: {exc}") from exc
    executable = bool(metadata.st_mode & 0o111)
    if os.name != "nt" and executable != (mode == "100755"):
        raise ExperimentError(f"editable surface mode differs from committed HEAD: {canonical}")
    try:
        text, canonical_raw = path_safety.canonical_text(committed, f"editable surface {canonical}")
        _, canonical_live = path_safety.canonical_text(live, f"live editable surface {canonical}")
    except path_safety.SafetyError as exc:
        raise ExperimentError(str(exc)) from exc
    if canonical_live != canonical_raw:
        raise ExperimentError(f"editable surface differs from committed HEAD: {canonical}")
    return {"path": canonical, "sha256": _sha_bytes(committed), "mode": mode, "text": text}


def _repository_binding(head: str, surfaces: list[dict[str, Any]]) -> str:
    return _sha_bytes(_canonical_bytes({"revision": head, "surfaces": [{key: item[key] for key in ("path", "sha256", "mode")} for item in surfaces]}))


def _assert_target_current(root: Path, head: str, surfaces: list[dict[str, Any]]) -> None:
    if _repository(root)[1] != head:
        raise ExperimentError("repository revision changed during experiment resolution")
    refreshed = [_committed_surface(root, item["path"]) for item in surfaces]
    expected = [{key: item[key] for key in ("path", "sha256", "mode")} for item in surfaces]
    actual = [{key: item[key] for key in ("path", "sha256", "mode")} for item in refreshed]
    if actual != expected:
        raise ExperimentError("editable surfaces changed during experiment resolution")


def _validate_cost(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label)
    _exact(item, label, ("value", "provenance"))
    amount = _number(item["value"], f"{label}.value", 0, 1_000_000, nullable=True)
    provenance = _enum(item["provenance"], f"{label}.provenance", {"host_observed", "runner_reported", "unavailable"})
    if (provenance == "unavailable") != (amount is None):
        raise ExperimentError(f"{label} value and provenance disagree")
    return item


def _validate_run_refs(value: Any, label: str, suite_ids: list[str]) -> list[dict[str, Any]]:
    refs = _array(value, label, minimum=len(suite_ids), maximum=len(suite_ids))
    seen: set[str] = set()
    for index, raw in enumerate(refs):
        item = _object(raw, f"{label}[{index}]")
        _exact(item, f"{label}[{index}]", ("suite_id", "path"))
        suite_id = _identifier(item["suite_id"], f"{label}[{index}].suite_id")
        if suite_id in seen or suite_id not in suite_ids:
            raise ExperimentError(f"{label} must bind each selected suite exactly once")
        seen.add(suite_id)
        item["path"] = path_safety.canonical_path(item["path"])
    if seen != set(suite_ids):
        raise ExperimentError(f"{label} must bind each selected suite exactly once")
    return refs


def validate_request(value: Any) -> dict[str, Any]:
    request = _object(value, "request")
    _exact(request, "request", ("schema_version", "experiment_id", "objective", "editable_surfaces", "suites", "profile", "runner", "requirements", "guardrail_tolerances", "budget", "baseline", "candidates"))
    if request["schema_version"] != "eval-harness-experiment-request/v1":
        raise ExperimentError("unsupported request schema_version")
    _identifier(request["experiment_id"], "request.experiment_id")
    objective = _object(request["objective"], "request.objective")
    _exact(objective, "request.objective", ("metric", "direction", "tolerance", "target"))
    metric = _enum(objective["metric"], "request.objective.metric", {"correctness", "completion", "time", "tokens", "cost"})
    direction = _enum(objective["direction"], "request.objective.direction", {"increase", "decrease"})
    _number(objective["tolerance"], "request.objective.tolerance", 0, 1_000_000_000)
    _number(objective["target"], "request.objective.target", 0, 1_000_000_000, nullable=True)
    if metric in {"correctness", "completion"} and direction != "increase":
        raise ExperimentError("quality objectives must use increase direction")
    if metric in {"correctness", "completion"} and objective["target"] is not None and objective["target"] > 1:
        raise ExperimentError("quality objective target cannot exceed 1")
    surfaces = [path_safety.canonical_path(item) for item in _array(request["editable_surfaces"], "request.editable_surfaces", minimum=1, maximum=MAX_SURFACES)]
    if len(set(surfaces)) != len(surfaces):
        raise ExperimentError("request.editable_surfaces must be unique")
    request["editable_surfaces"] = surfaces
    suites = _array(request["suites"], "request.suites", minimum=1, maximum=MAX_SUITES)
    suite_ids: list[str] = []
    for index, raw_suite in enumerate(suites):
        label = f"request.suites[{index}]"
        suite = _object(raw_suite, label)
        _exact(suite, label, ("suite_id", "suite_sha256", "development_case_ids", "holdout_case_ids", "regression_case_ids"))
        suite_id = _identifier(suite["suite_id"], f"{label}.suite_id")
        if suite_id in suite_ids:
            raise ExperimentError("request contains duplicate suite_id")
        suite_ids.append(suite_id)
        _sha(suite["suite_sha256"], f"{label}.suite_sha256")
        roles = [_unique_ids(suite[field], f"{label}.{field}") for field in ("development_case_ids", "holdout_case_ids", "regression_case_ids")]
        if set(roles[0]) & set(roles[1]) or set(roles[0]) & set(roles[2]) or set(roles[1]) & set(roles[2]):
            raise ExperimentError(f"{label} case roles must be disjoint")
        if not roles[1] or not roles[2]:
            raise ExperimentError(f"{label} requires hidden holdout and protected regression cases")
    _identifier(request["profile"], "request.profile")
    runner = _object(request["runner"], "request.runner")
    runner_fields = ("runner", "runner_version", "agent", "model", "reasoning", "platform", "environment_sha256", "adapter_sha256", "launcher_sha256", "profile_sha256")
    _exact(runner, "request.runner", runner_fields)
    for field in ("runner", "agent"):
        _identifier(runner[field], f"request.runner.{field}")
    _identifier(runner["runner_version"], "request.runner.runner_version", SAFE_VALUE)
    for field in ("model", "reasoning"):
        if runner[field] is not None:
            _identifier(runner[field], f"request.runner.{field}")
    _enum(runner["platform"], "request.runner.platform", {"linux", "windows", "macos"})
    for field in ("environment_sha256", "adapter_sha256", "launcher_sha256", "profile_sha256"):
        _sha(runner[field], f"request.runner.{field}")
    requirements = _object(request["requirements"], "request.requirements")
    _exact(requirements, "request.requirements", ("minimum_repetitions", "no_progress_limit"))
    _integer(requirements["minimum_repetitions"], "request.requirements.minimum_repetitions", 2, 100)
    _integer(requirements["no_progress_limit"], "request.requirements.no_progress_limit", 1, MAX_CANDIDATES)
    tolerances = _object(request["guardrail_tolerances"], "request.guardrail_tolerances")
    _exact(tolerances, "request.guardrail_tolerances", ("correctness", "completion", "time", "tokens", "cost"))
    for field in tolerances:
        maximum = 1 if field in {"correctness", "completion"} else 1_000_000_000
        _number(tolerances[field], f"request.guardrail_tolerances.{field}", 0, maximum)
    budget = _object(request["budget"], "request.budget")
    _exact(budget, "request.budget", ("max_candidates", "max_run_receipts", "max_seconds", "max_tokens", "max_cost_usd"))
    max_candidates = _integer(budget["max_candidates"], "request.budget.max_candidates", 1, MAX_CANDIDATES)
    _integer(budget["max_run_receipts"], "request.budget.max_run_receipts", len(suite_ids), MAX_RUNS)
    _number(budget["max_seconds"], "request.budget.max_seconds", 1, 31_536_000)
    _number(budget["max_tokens"], "request.budget.max_tokens", 1, 1_000_000_000, nullable=True)
    _number(budget["max_cost_usd"], "request.budget.max_cost_usd", 0, 1_000_000, nullable=True)
    baseline = _object(request["baseline"], "request.baseline")
    _exact(baseline, "request.baseline", ("runs", "cost_usd"))
    _validate_run_refs(baseline["runs"], "request.baseline.runs", suite_ids)
    _validate_cost(baseline["cost_usd"], "request.baseline.cost_usd")
    candidates = _array(request["candidates"], "request.candidates", minimum=1, maximum=max_candidates)
    seen_candidates: set[str] = set()
    referenced = [item["path"] for item in baseline["runs"]]
    for index, raw_candidate in enumerate(candidates):
        label = f"request.candidates[{index}]"
        candidate = _object(raw_candidate, label)
        _exact(candidate, label, ("candidate_id", "variant_path", "runs", "cost_usd"))
        candidate_id = _identifier(candidate["candidate_id"], f"{label}.candidate_id")
        if candidate_id in seen_candidates:
            raise ExperimentError("request contains duplicate candidate_id")
        seen_candidates.add(candidate_id)
        candidate["variant_path"] = path_safety.canonical_path(candidate["variant_path"])
        _validate_run_refs(candidate["runs"], f"{label}.runs", suite_ids)
        _validate_cost(candidate["cost_usd"], f"{label}.cost_usd")
        referenced.append(candidate["variant_path"])
        referenced.extend(item["path"] for item in candidate["runs"])
    if len(referenced) != len(set(referenced)):
        raise ExperimentError("request input artifacts must use distinct paths")
    if len(suite_ids) * (1 + len(candidates)) > budget["max_run_receipts"]:
        raise ExperimentError("request exceeds the cumulative run-receipt budget")
    return request


def _validate_variant(
    value: Any,
    candidate_id: str,
    revision: str,
    repository_sha: str,
    surfaces: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    variant = _object(value, f"variant {candidate_id}")
    _exact(
        variant,
        f"variant {candidate_id}",
        (
            "schema_version",
            "candidate_id",
            "base_revision",
            "base_repository_sha256",
            "editable_surfaces",
            "rationale",
            "edits",
        ),
    )
    if variant["schema_version"] != "eval-harness-variant/v1" or variant["candidate_id"] != candidate_id:
        raise ExperimentError(f"variant identity mismatch for {candidate_id}")
    if _identifier(variant["base_revision"], f"variant {candidate_id}.base_revision", HEAD_RE) != revision:
        raise ExperimentError(f"variant {candidate_id} does not bind the selected revision")
    if _sha(variant["base_repository_sha256"], f"variant {candidate_id}.base_repository_sha256") != repository_sha:
        raise ExperimentError(f"variant {candidate_id} does not bind the selected starting content")
    declared_surfaces = _array(
        variant["editable_surfaces"],
        f"variant {candidate_id}.editable_surfaces",
        minimum=len(surfaces),
        maximum=len(surfaces),
    )
    normalized_surfaces: list[dict[str, Any]] = []
    for index, raw_surface in enumerate(declared_surfaces):
        label = f"variant {candidate_id}.editable_surfaces[{index}]"
        surface = _object(raw_surface, label)
        _exact(surface, label, ("path", "sha256", "mode"))
        normalized_surfaces.append(
            {
                "path": path_safety.canonical_path(surface["path"]),
                "sha256": _sha(surface["sha256"], f"{label}.sha256"),
                "mode": _enum(surface["mode"], f"{label}.mode", {"100644", "100755"}),
            }
        )
    expected_surfaces = [
        {key: surface[key] for key in ("path", "sha256", "mode")}
        for surface in surfaces.values()
    ]
    if normalized_surfaces != expected_surfaces:
        raise ExperimentError(f"variant {candidate_id} editable surfaces differ from caller selection")
    _text(variant["rationale"], f"variant {candidate_id}.rationale", 2000)
    edits = _array(variant["edits"], f"variant {candidate_id}.edits", minimum=1, maximum=MAX_SURFACES)
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    total = 0
    for index, raw_edit in enumerate(edits):
        label = f"variant {candidate_id}.edits[{index}]"
        edit = _object(raw_edit, label)
        _exact(edit, label, ("path", "before_sha256", "after_text"))
        path = path_safety.canonical_path(edit["path"])
        if path in seen or path not in surfaces:
            raise ExperimentError(f"{label}.path is duplicate or outside editable surfaces")
        seen.add(path)
        if _sha(edit["before_sha256"], f"{label}.before_sha256") != surfaces[path]["sha256"]:
            raise ExperimentError(f"{label} does not bind starting content")
        after_text = edit["after_text"]
        if not isinstance(after_text, str) or "\x00" in after_text or any(unicodedata.category(char) == "Cs" for char in after_text):
            raise ExperimentError(f"{label}.after_text must be UTF-8 text without NUL or surrogates")
        after_raw = after_text.encode("utf-8")
        total += len(after_raw)
        if total > MAX_PATCH_BYTES:
            raise ExperimentError(f"variant {candidate_id} exceeds the patch byte limit")
        after_sha = _sha_bytes(after_raw)
        if after_sha == surfaces[path]["sha256"]:
            raise ExperimentError(f"{label} does not change content")
        normalized.append({"path": path, "before_sha256": surfaces[path]["sha256"], "after_sha256": after_sha, "after_text": after_text})
    normalized.sort(key=lambda item: item["path"])
    patch = {"base_repository_sha256": repository_sha, "changes": normalized}
    return {"rationale": variant["rationale"], "patch_sha256": _sha_bytes(_canonical_bytes(patch)), **patch}


def _runner_condition(configuration: dict[str, Any]) -> dict[str, Any]:
    fields = ("runner", "runner_version", "agent", "model", "reasoning", "platform", "environment_sha256", "adapter_sha256", "launcher_sha256", "profile_sha256")
    return {field: configuration[field] for field in fields}


def _run_summary(result: dict[str, Any], raw_sha: str) -> dict[str, Any]:
    return {
        "run_id": result["run_id"],
        "run_sha256": raw_sha,
        "suite": result["suite"],
        "source": result["source"],
        "target": result["target"],
        "condition": _runner_condition(result["configuration"]),
        "instructions_sha256": result["configuration"]["instructions_sha256"],
        "configuration_sha256": result["configuration"]["configuration_sha256"],
        "completion": result["completion"],
        "outcome": result["outcome"],
        "cases": [
            {key: case[key] for key in ("case_id", "importance", "status", "stability", "repetitions", "passed", "failed", "forbidden_effect_failures", "duration_ms", "tokens", "target_sha256", "grader_sha256")}
            for case in result["cases"]
        ],
        "summary": result["summary"],
        "material_limitations": sum(bool(item["material"]) for item in result["limitations"]),
    }


def _validate_loaded_run(
    value: Any,
    reference: dict[str, Any],
    expected_suite: dict[str, Any],
    profile: str,
    runner: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    try:
        evidence_contracts.validate_project_eval_run(value)
    except evidence_contracts.ContractError as exc:
        raise ExperimentError(f"run receipt {reference['path']} is not canonical: {exc}") from exc
    if value["source"]["kind"] != "local":
        raise ExperimentError("imported run evidence cannot establish experiment authority")
    if value["suite"] != {"suite_id": expected_suite["suite_id"], "suite_sha256": expected_suite["suite_sha256"], "profile": profile}:
        raise ExperimentError(f"run receipt {reference['path']} does not match the selected suite/profile")
    if _runner_condition(value["configuration"]) != runner:
        raise ExperimentError(f"run receipt {reference['path']} does not match the selected runner conditions")
    canonical = _canonical_bytes(value)
    return value, _sha_bytes(canonical)


def _load_run(input_root: Path, reference: dict[str, Any], expected_suite: dict[str, Any], profile: str, runner: dict[str, Any]) -> dict[str, Any]:
    try:
        path = path_safety.safe_repo_path(input_root, reference["path"])
    except path_safety.SafetyError as exc:
        raise ExperimentError(f"unsafe run receipt path: {exc}") from exc
    value, _ = _read_json(path, f"run receipt {reference['path']}")
    value, run_sha = _validate_loaded_run(value, reference, expected_suite, profile, runner)
    return {"path": reference["path"], "source_sha256": run_sha, "run": _run_summary(value, run_sha)}


def _load_bound_candidate_run(
    input_root: Path,
    reference: dict[str, Any],
    expected_suite: dict[str, Any],
    profile: str,
    runner: dict[str, Any],
    *,
    candidate_id: str,
    revision: str,
    repository_sha256: str,
    patch_sha256: str,
    variant_sha256: str,
) -> dict[str, Any]:
    try:
        path = path_safety.safe_repo_path(input_root.absolute(), reference["path"])
    except path_safety.SafetyError as exc:
        raise ExperimentError(f"unsafe candidate binding path: {exc}") from exc
    binding, _ = _read_json(path, f"candidate binding {reference['path']}")
    binding = _object(binding, f"candidate binding {reference['path']}")
    _exact(
        binding,
        f"candidate binding {reference['path']}",
        (
            "schema_version",
            "producer",
            "candidate_id",
            "base_revision",
            "base_repository_sha256",
            "patch_sha256",
            "variant_sha256",
            "run_result_sha256",
            "run_result",
        ),
    )
    if binding["schema_version"] != "project-eval-experiment-binding/v1":
        raise ExperimentError("candidate run requires a project-eval experiment binding")
    producer = _object(binding["producer"], "candidate binding.producer")
    _exact(producer, "candidate binding.producer", ("name", "version"))
    if producer["name"] != "project-eval":
        raise ExperimentError("candidate binding must be produced by project-eval")
    _identifier(producer["version"], "candidate binding.producer.version", SAFE_VALUE)
    if binding["candidate_id"] != candidate_id:
        raise ExperimentError("candidate binding identity does not match the selected variant")
    if _identifier(binding["base_revision"], "candidate binding.base_revision", HEAD_RE) != revision:
        raise ExperimentError("candidate binding does not match the selected revision")
    if _sha(binding["base_repository_sha256"], "candidate binding.base_repository_sha256") != repository_sha256:
        raise ExperimentError("candidate binding does not match the selected starting content")
    if _sha(binding["patch_sha256"], "candidate binding.patch_sha256") != patch_sha256:
        raise ExperimentError("candidate run was not produced from the selected patch")
    if _sha(binding["variant_sha256"], "candidate binding.variant_sha256") != variant_sha256:
        raise ExperimentError("candidate binding does not bind the selected variant document")
    run, run_sha = _validate_loaded_run(binding["run_result"], reference, expected_suite, profile, runner)
    if _sha(binding["run_result_sha256"], "candidate binding.run_result_sha256") != run_sha:
        raise ExperimentError("candidate binding does not bind its run result")
    binding_sha = _sha_bytes(_canonical_bytes(binding))
    return {
        "path": reference["path"],
        "binding_sha256": binding_sha,
        "source_sha256": run_sha,
        "run": _run_summary(run, run_sha),
    }


def _materialize_selected_surfaces(surfaces: list[dict[str, Any]], variants: list[dict[str, Any]], repository: Path) -> None:
    temp_root = Path(tempfile.gettempdir()).absolute()
    if _is_within(temp_root, repository):
        raise ExperimentError("system temporary directory must be outside the active checkout")
    with tempfile.TemporaryDirectory(prefix="eval-harness-experiment-", dir=temp_root) as temporary:
        root = Path(temporary)
        workspaces: list[Path] = []
        for index in range(1 + len(variants)):
            workspace = root / f"workspace-{index:03d}"
            workspace.mkdir()
            workspaces.append(workspace)
            for surface in surfaces:
                target = workspace.joinpath(*surface["path"].split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(surface["text"].encode("utf-8"))
        for workspace, variant in zip(workspaces[1:], variants):
            for change in variant["patch"]["changes"]:
                workspace.joinpath(*change["path"].split("/" )).write_bytes(change["after_text"].encode("utf-8"))
        identities = {os.path.normcase(str(path.absolute())) for path in workspaces}
        if len(identities) != len(workspaces):
            raise ExperimentError("disposable experiment workspaces are not distinct")


def _context_without_digest(context: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in context.items() if key != "context_sha256"}


def resolve_context(root: Path, request_path: Path, input_root: Path) -> dict[str, Any]:
    repository, head = _repository(root)
    try:
        path_safety.assert_no_link_components(input_root.absolute(), include_final=True)
    except path_safety.SafetyError as exc:
        raise ExperimentError(f"cannot bind input root: {exc}") from exc
    if not input_root.absolute().is_dir():
        raise ExperimentError("--input-root must be a directory")
    request_value, _ = _read_json(request_path.absolute(), "experiment request")
    request = validate_request(request_value)
    surfaces = [_committed_surface(repository, path) for path in request["editable_surfaces"]]
    surface_by_path = {item["path"]: item for item in surfaces}
    repository_sha = _repository_binding(head, surfaces)
    suites = {item["suite_id"]: item for item in request["suites"]}

    def load_baseline_set(owner: dict[str, Any]) -> list[dict[str, Any]]:
        by_suite = {item["suite_id"]: item for item in owner["runs"]}
        return [_load_run(input_root.absolute(), by_suite[suite_id], suites[suite_id], request["profile"], request["runner"]) for suite_id in suites]

    baseline = {"runs": load_baseline_set(request["baseline"]), "cost_usd": request["baseline"]["cost_usd"]}
    candidates: list[dict[str, Any]] = []
    for selected in request["candidates"]:
        variant_path = path_safety.safe_repo_path(input_root.absolute(), selected["variant_path"])
        variant_value, _ = _read_json(variant_path, f"variant {selected['candidate_id']}")
        variant_sha = _sha_bytes(_canonical_bytes(variant_value))
        patch = _validate_variant(
            variant_value,
            selected["candidate_id"],
            head,
            repository_sha,
            surface_by_path,
        )
        by_suite = {item["suite_id"]: item for item in selected["runs"]}
        bound_runs = [
            _load_bound_candidate_run(
                input_root.absolute(),
                by_suite[suite_id],
                suites[suite_id],
                request["profile"],
                request["runner"],
                candidate_id=selected["candidate_id"],
                revision=head,
                repository_sha256=repository_sha,
                patch_sha256=patch["patch_sha256"],
                variant_sha256=variant_sha,
            )
            for suite_id in suites
        ]
        candidates.append({"candidate_id": selected["candidate_id"], "variant_source": {"path": selected["variant_path"], "sha256": variant_sha}, "patch": patch, "runs": bound_runs, "cost_usd": selected["cost_usd"]})
    all_run_sha = [item["source_sha256"] for item in baseline["runs"]] + [run["source_sha256"] for candidate in candidates for run in candidate["runs"]]
    if len(all_run_sha) != len(set(all_run_sha)):
        raise ExperimentError("baseline and candidates must use distinct run receipts")
    _materialize_selected_surfaces(surfaces, candidates, repository)
    _assert_target_current(repository, head, surfaces)
    context = {
        "schema_version": "eval-harness-experiment-context/v1",
        "repository_root": str(repository),
        "input_root": str(input_root.absolute()),
        "request_source": {"path": str(request_path.absolute()), "sha256": _sha_bytes(_canonical_bytes(request))},
        "target": {"revision": head, "repository_sha256": repository_sha, "editable_surfaces": [{key: item[key] for key in ("path", "sha256", "mode")} for item in surfaces]},
        "request": request,
        "baseline": baseline,
        "candidates": candidates,
        "limits": {"max_input_bytes": MAX_INPUT_BYTES, "max_context_bytes": MAX_CONTEXT_BYTES, "max_result_bytes": MAX_RESULT_BYTES, "max_patch_bytes": MAX_PATCH_BYTES, "max_candidates": MAX_CANDIDATES, "max_runs": MAX_RUNS, "max_surfaces": MAX_SURFACES},
    }
    context["context_sha256"] = _sha_bytes(_canonical_bytes(context))
    if len(_canonical_bytes(context)) > MAX_CONTEXT_BYTES:
        raise ExperimentError("canonical context exceeds the supported limit")
    return validate_context(context)


def _case_map(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["case_id"]: item for item in run["cases"]}


def _validate_pair(baseline: dict[str, Any], candidate: dict[str, Any], suite: dict[str, Any], minimum_repetitions: int) -> list[str]:
    reasons: list[str] = []
    if baseline["suite"] != candidate["suite"] or baseline["condition"] != candidate["condition"]:
        reasons.append("relevant run conditions differ")
    for field in ("definition_sha256", "fixture_set_sha256"):
        if baseline["target"][field] != candidate["target"][field]:
            reasons.append(f"target {field} differs")
    if baseline["target"]["repository_sha256"] == candidate["target"]["repository_sha256"] and baseline["instructions_sha256"] == candidate["instructions_sha256"]:
        reasons.append("candidate receipt does not reflect a harness or instruction variant")
    baseline_cases = _case_map(baseline)
    candidate_cases = _case_map(candidate)
    expected = set(suite["development_case_ids"] + suite["holdout_case_ids"] + suite["regression_case_ids"])
    if set(baseline_cases) != expected or set(candidate_cases) != expected:
        reasons.append("run cases do not exactly match the selected development/holdout/regression set")
        return reasons
    for case_id in sorted(expected):
        before, after = baseline_cases[case_id], candidate_cases[case_id]
        if before["importance"] != after["importance"] or before["grader_sha256"] != after["grader_sha256"]:
            reasons.append(f"case authority differs for {case_id}")
        if before["repetitions"] != after["repetitions"] or before["repetitions"] < minimum_repetitions:
            reasons.append(f"case repetitions are not paired and sufficient for {case_id}")
    return sorted(set(reasons))


def _aggregate(runs: list[dict[str, Any]], cost: dict[str, Any]) -> dict[str, Any]:
    cases = [case for run in runs for case in run["cases"]]
    total_repetitions = sum(item["repetitions"] for item in cases)
    passed_repetitions = sum(item["passed"] for item in cases)
    tokens = [run["summary"]["tokens"]["value"] for run in runs]
    return {
        "correctness": passed_repetitions / total_repetitions if total_repetitions else 0.0,
        "completion": sum(item["status"] == "passed" for item in cases) / len(cases) if cases else 0.0,
        "time": sum(run["summary"]["duration_ms"] for run in runs) / 1000.0,
        "tokens": None if any(value is None for value in tokens) else sum(tokens),
        "cost": cost["value"],
    }


def _quality(runs: list[dict[str, Any]], suites: list[dict[str, Any]], minimum: int) -> dict[str, Any]:
    required_passed = True
    repetitions_met = True
    effect_breach = False
    protected_passed = True
    for run, suite in zip(runs, suites):
        cases = _case_map(run)
        roles = set(suite["holdout_case_ids"] + suite["regression_case_ids"])
        for case in cases.values():
            required_passed &= case["importance"] != "required" or case["status"] == "passed"
            repetitions_met &= case["repetitions"] >= minimum
            effect_breach |= bool(case["forbidden_effect_failures"])
        protected_passed &= all(cases[case_id]["status"] == "passed" for case_id in roles if case_id in cases)
    complete = all(run["completion"] == "complete" and not run["material_limitations"] for run in runs)
    return {"complete": complete, "required_cases_passed": required_passed, "required_repetitions_met": repetitions_met, "protected_cases_passed": protected_passed, "effect_breach": effect_breach}


def _guardrail_regression(
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    suites: list[dict[str, Any]],
    tolerances: dict[str, Any],
    baseline_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
) -> bool:
    for before_run, after_run, suite in zip(baseline, candidate, suites):
        before, after = _case_map(before_run), _case_map(after_run)
        for case_id in suite["holdout_case_ids"] + suite["regression_case_ids"]:
            if case_id not in before or case_id not in after:
                return True
            if after[case_id]["passed"] / max(1, after[case_id]["repetitions"]) + tolerances["correctness"] < before[case_id]["passed"] / max(1, before[case_id]["repetitions"]):
                return True
    for metric in ("correctness", "completion"):
        if candidate_metrics[metric] + tolerances[metric] < baseline_metrics[metric]:
            return True
    for metric in ("time", "tokens", "cost"):
        before, after = baseline_metrics[metric], candidate_metrics[metric]
        if before is not None and after is not None and after > before + tolerances[metric]:
            return True
    return False


def _objective_delta(metric: str, direction: str, baseline: dict[str, Any], candidate: dict[str, Any]) -> float | None:
    before, after = baseline[metric], candidate[metric]
    if before is None or after is None:
        return None
    return float(after - before if direction == "increase" else before - after)


def _expected_classification(
    *,
    baseline: dict[str, Any],
    delta: float | None,
    tolerance: float,
    required_repetitions_met: bool,
    required_cases_passed: bool,
    protected_cases_passed: bool,
    guardrail_regression: bool,
    effect_breach: bool,
    budget_breach: bool,
    limitations: list[dict[str, Any]],
) -> str:
    if (
        delta is None
        or any(item["material"] for item in limitations)
        or not baseline["complete"]
        or not baseline["required_cases_passed"]
        or not baseline["protected_cases_passed"]
        or baseline["effect_breach"]
        or effect_breach
        or budget_breach
    ):
        return "incomplete"
    if (
        delta > tolerance
        and required_repetitions_met
        and required_cases_passed
        and protected_cases_passed
        and not guardrail_regression
    ):
        return "clear_improvement"
    if delta > tolerance and required_cases_passed:
        return "tradeoff"
    if not required_repetitions_met or (abs(delta) <= tolerance and delta != 0):
        return "inconclusive"
    return "no_improvement"


def _budget_breach(consumed: dict[str, Any], limits: dict[str, Any]) -> bool:
    if consumed["candidates"] > limits["max_candidates"] or consumed["run_receipts"] > limits["max_run_receipts"]:
        return True
    if consumed["seconds"] > limits["max_seconds"]:
        return True
    if limits["max_tokens"] is not None and (consumed["tokens"] is None or consumed["tokens"] > limits["max_tokens"]):
        return True
    if limits["max_cost_usd"] is not None and (consumed["cost_usd"] is None or consumed["cost_usd"] > limits["max_cost_usd"]):
        return True
    return False


def _add_consumed(consumed: dict[str, Any], metrics: dict[str, Any], runs: int) -> None:
    consumed["run_receipts"] += runs
    consumed["seconds"] += metrics["time"]
    consumed["tokens"] = None if consumed["tokens"] is None or metrics["tokens"] is None else consumed["tokens"] + metrics["tokens"]
    consumed["cost_usd"] = None if consumed["cost_usd"] is None or metrics["cost"] is None else consumed["cost_usd"] + metrics["cost"]


def _derive_result(context: dict[str, Any]) -> dict[str, Any]:
    request = context["request"]
    suites = request["suites"]
    baseline_runs = [item["run"] for item in context["baseline"]["runs"]]
    baseline_metrics = _aggregate(baseline_runs, context["baseline"]["cost_usd"])
    baseline_quality = _quality(baseline_runs, suites, request["requirements"]["minimum_repetitions"])
    consumed = {"candidates": 0, "run_receipts": 0, "seconds": 0.0, "tokens": 0, "cost_usd": 0.0}
    _add_consumed(consumed, baseline_metrics, len(baseline_runs))
    limitations: list[dict[str, Any]] = []
    if not baseline_quality["complete"] or not baseline_quality["required_cases_passed"] or not baseline_quality["protected_cases_passed"] or baseline_quality["effect_breach"]:
        limitations.append({"code": "invalid-baseline", "message": "Baseline evidence is incomplete or does not pass required and protected cases.", "material": True})
    candidates: list[dict[str, Any]] = []
    no_progress = 0
    stop_reason = "candidates_exhausted"
    stop_after: str | None = None
    for source in context["candidates"]:
        candidate_runs = [item["run"] for item in source["runs"]]
        pair_reasons: list[str] = []
        for before, after, suite in zip(baseline_runs, candidate_runs, suites):
            pair_reasons.extend(_validate_pair(before, after, suite, request["requirements"]["minimum_repetitions"]))
        candidate_metrics = _aggregate(candidate_runs, source["cost_usd"])
        candidate_quality = _quality(candidate_runs, suites, request["requirements"]["minimum_repetitions"])
        _add_consumed(consumed, candidate_metrics, len(candidate_runs))
        consumed["candidates"] += 1
        breach = _budget_breach(consumed, request["budget"])
        regression = _guardrail_regression(
            baseline_runs,
            candidate_runs,
            suites,
            request["guardrail_tolerances"],
            baseline_metrics,
            candidate_metrics,
        )
        delta = _objective_delta(request["objective"]["metric"], request["objective"]["direction"], baseline_metrics, candidate_metrics)
        item_limitations: list[dict[str, Any]] = []
        if pair_reasons:
            item_limitations.append({"code": "condition-mismatch", "message": "; ".join(sorted(set(pair_reasons))), "material": True})
        if delta is None:
            item_limitations.append({"code": "objective-unavailable", "message": "The selected objective is not available in both paired observations.", "material": True})
        if not candidate_quality["complete"]:
            item_limitations.append({"code": "incomplete-evidence", "message": "Candidate run evidence is incomplete or materially limited.", "material": True})
        classification = _expected_classification(
            baseline=baseline_quality,
            delta=delta,
            tolerance=request["objective"]["tolerance"],
            required_repetitions_met=candidate_quality["required_repetitions_met"],
            required_cases_passed=candidate_quality["required_cases_passed"],
            protected_cases_passed=candidate_quality["protected_cases_passed"],
            guardrail_regression=regression,
            effect_breach=candidate_quality["effect_breach"],
            budget_breach=breach,
            limitations=item_limitations,
        )
        evidence = []
        for before, after, suite in zip(context["baseline"]["runs"], source["runs"], suites):
            evidence.append({"evidence_id": f"paired-{suite['suite_id']}", "kind": "run_receipt", "baseline_sha256": before["source_sha256"], "candidate_sha256": after["source_sha256"], "case_ids": suite["development_case_ids"] + suite["holdout_case_ids"] + suite["regression_case_ids"], "summary": f"Paired {suite['suite_id']} baseline and candidate under the selected runner conditions.", "redacted": True})
        candidates.append({
            "sequence": consumed["candidates"],
            "rank": 0,
            "candidate_id": source["candidate_id"],
            "patch": source["patch"],
            "run_sha256s": [item["source_sha256"] for item in source["runs"]],
            "condition_sha256": _sha_bytes(_canonical_bytes([item["run"]["condition"] for item in source["runs"]])),
            "classification": classification,
            "objective_delta": delta,
            "required_repetitions_met": candidate_quality["required_repetitions_met"],
            "required_cases_passed": candidate_quality["required_cases_passed"],
            "protected_cases_passed": candidate_quality["protected_cases_passed"],
            "guardrail_regression": regression,
            "effect_breach": candidate_quality["effect_breach"],
            "budget_breach": breach,
            "metrics": candidate_metrics,
            "evidence": evidence,
            "limitations": item_limitations,
        })
        stop_after = source["candidate_id"]
        if candidate_quality["effect_breach"]:
            stop_reason = "forbidden_effect"
            break
        if breach:
            stop_reason = "budget_exhausted"
            break
        if classification == "clear_improvement":
            target = request["objective"]["target"]
            if target is None or delta >= target:
                stop_reason = "target_achieved"
                break
        if classification == "tradeoff":
            stop_reason = "decision_required"
            break
        no_progress = no_progress + 1 if classification in {"no_improvement", "inconclusive"} else 0
        if no_progress >= request["requirements"]["no_progress_limit"]:
            stop_reason = "no_progress"
            break
    ranked = sorted(candidates, key=lambda item: (CLASSIFICATION_ORDER[item["classification"]], -(item["objective_delta"] if item["objective_delta"] is not None else -1_000_000_001), item["candidate_id"]))
    for index, item in enumerate(ranked, 1):
        item["rank"] = index
    classes = [item["classification"] for item in ranked]
    if stop_reason == "decision_required":
        outcome, next_action = "tradeoff", "decision"
    elif stop_reason == "target_achieved":
        outcome, next_action = "clear_improvement", "review_candidate"
    elif "clear_improvement" in classes:
        outcome, next_action = "clear_improvement", "review_candidate"
    elif "tradeoff" in classes:
        outcome, next_action = "tradeoff", "decision"
    elif classes and all(item == "no_improvement" for item in classes):
        outcome, next_action = "no_improvement", "none"
    elif "inconclusive" in classes:
        outcome, next_action = "inconclusive", "retry"
    else:
        outcome, next_action = "incomplete", "manual"
    if limitations or stop_reason in {"forbidden_effect", "budget_exhausted", "source_drift"}:
        outcome, next_action = "incomplete", "manual"
    completion = "incomplete" if outcome == "incomplete" else "complete"
    result = {
        "schema_version": "eval-experiment-result/v1",
        "producer": {"name": "eval-harness-experiment", "version": VERSION},
        "context_sha256": context["context_sha256"],
        "completion": completion,
        "outcome": outcome,
        "next_action": next_action,
        "objective": request["objective"],
        "requirements": request["requirements"],
        "guardrail_tolerances": request["guardrail_tolerances"],
        "repository": {key: context["target"][key] for key in ("revision", "repository_sha256")},
        "baseline": {"run_sha256s": [item["source_sha256"] for item in context["baseline"]["runs"]], "condition_sha256": _sha_bytes(_canonical_bytes([item["run"]["condition"] for item in context["baseline"]["runs"]])), "metrics": baseline_metrics, **baseline_quality},
        "candidates": ranked,
        "budget": {"limits": request["budget"], "consumed": consumed},
        "stop": {"reason": stop_reason, "after_candidate_id": stop_after},
        "limitations": limitations,
    }
    return result


def evaluate(context_value: Any) -> dict[str, Any]:
    context = validate_context(context_value, current=True)
    return validate_result(_derive_result(context))


def validate_context(value: Any, *, current: bool = False) -> dict[str, Any]:
    context = _object(value, "context")
    _exact(context, "context", ("schema_version", "repository_root", "input_root", "request_source", "target", "request", "baseline", "candidates", "limits", "context_sha256"))
    if context["schema_version"] != "eval-harness-experiment-context/v1":
        raise ExperimentError("unsupported context schema_version")
    _text(context["repository_root"], "context.repository_root", 4096)
    _text(context["input_root"], "context.input_root", 4096)
    request_source = _object(context["request_source"], "context.request_source")
    _exact(request_source, "context.request_source", ("path", "sha256"))
    _text(request_source["path"], "context.request_source.path", 4096)
    _sha(request_source["sha256"], "context.request_source.sha256")
    request = validate_request(context["request"])
    target = _object(context["target"], "context.target")
    _exact(target, "context.target", ("revision", "repository_sha256", "editable_surfaces"))
    _identifier(target["revision"], "context.target.revision", HEAD_RE)
    _sha(target["repository_sha256"], "context.target.repository_sha256")
    surfaces = _array(target["editable_surfaces"], "context.target.editable_surfaces", minimum=1, maximum=MAX_SURFACES)
    for index, surface in enumerate(surfaces):
        label = f"context.target.editable_surfaces[{index}]"
        _exact(_object(surface, label), label, ("path", "sha256", "mode"))
        path_safety.canonical_path(surface["path"])
        _sha(surface["sha256"], f"{label}.sha256")
        _enum(surface["mode"], f"{label}.mode", {"100644", "100755"})
    if [item["path"] for item in surfaces] != request["editable_surfaces"]:
        raise ExperimentError("context surfaces do not match the request")
    limits = _object(context["limits"], "context.limits")
    expected_limits = {"max_input_bytes": MAX_INPUT_BYTES, "max_context_bytes": MAX_CONTEXT_BYTES, "max_result_bytes": MAX_RESULT_BYTES, "max_patch_bytes": MAX_PATCH_BYTES, "max_candidates": MAX_CANDIDATES, "max_runs": MAX_RUNS, "max_surfaces": MAX_SURFACES}
    if limits != expected_limits:
        raise ExperimentError("context limits are inconsistent")
    expected_digest = _sha_bytes(_canonical_bytes(_context_without_digest(context)))
    if _sha(context["context_sha256"], "context.context_sha256") != expected_digest:
        raise ExperimentError("context digest is inconsistent")
    if len(_canonical_bytes(context)) > MAX_CONTEXT_BYTES:
        raise ExperimentError("canonical context exceeds the supported limit")
    if current:
        refreshed = resolve_context(Path(context["repository_root"]), Path(context["request_source"]["path"]), Path(context["input_root"]))
        if refreshed != context:
            raise ExperimentError("experiment inputs changed after context resolution")
    return context


def validate_result(value: Any, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    result = _object(value, "result")
    _exact(result, "result", ("schema_version", "producer", "context_sha256", "completion", "outcome", "next_action", "objective", "requirements", "guardrail_tolerances", "repository", "baseline", "candidates", "budget", "stop", "limitations"))
    if result["schema_version"] != "eval-experiment-result/v1":
        raise ExperimentError("unsupported result schema_version")
    producer = _object(result["producer"], "result.producer")
    if producer != {"name": "eval-harness-experiment", "version": VERSION}:
        raise ExperimentError("result producer is inconsistent")
    _sha(result["context_sha256"], "result.context_sha256")
    completion = _enum(result["completion"], "result.completion", {"complete", "incomplete"})
    outcome = _enum(result["outcome"], "result.outcome", set(CLASSIFICATION_ORDER))
    next_action = _enum(result["next_action"], "result.next_action", {"none", "review_candidate", "decision", "retry", "manual"})
    objective = _object(result["objective"], "result.objective")
    _exact(objective, "result.objective", ("metric", "direction", "tolerance", "target"))
    metric = _enum(objective["metric"], "result.objective.metric", {"correctness", "completion", "time", "tokens", "cost"})
    direction = _enum(objective["direction"], "result.objective.direction", {"increase", "decrease"})
    tolerance = _number(objective["tolerance"], "result.objective.tolerance", 0, 1_000_000_000)
    _number(objective["target"], "result.objective.target", 0, 1_000_000_000, nullable=True)
    if metric in {"correctness", "completion"} and direction != "increase":
        raise ExperimentError("quality objectives must use increase direction")
    requirements = _object(result["requirements"], "result.requirements")
    _exact(requirements, "result.requirements", ("minimum_repetitions", "no_progress_limit"))
    _integer(requirements["minimum_repetitions"], "result.requirements.minimum_repetitions", 2, 100)
    no_progress_limit = _integer(requirements["no_progress_limit"], "result.requirements.no_progress_limit", 1, MAX_CANDIDATES)
    tolerances = _object(result["guardrail_tolerances"], "result.guardrail_tolerances")
    _exact(tolerances, "result.guardrail_tolerances", ("correctness", "completion", "time", "tokens", "cost"))
    for field in tolerances:
        maximum = 1 if field in {"correctness", "completion"} else 1_000_000_000
        _number(tolerances[field], f"result.guardrail_tolerances.{field}", 0, maximum)
    repository = _object(result["repository"], "result.repository")
    _exact(repository, "result.repository", ("revision", "repository_sha256"))
    _identifier(repository["revision"], "result.repository.revision", HEAD_RE)
    repository_sha = _sha(repository["repository_sha256"], "result.repository.repository_sha256")
    baseline = _object(result["baseline"], "result.baseline")
    baseline_fields = ("run_sha256s", "condition_sha256", "metrics", "complete", "required_cases_passed", "required_repetitions_met", "protected_cases_passed", "effect_breach")
    _exact(baseline, "result.baseline", baseline_fields)
    baseline_runs = _array(baseline["run_sha256s"], "result.baseline.run_sha256s", minimum=1, maximum=MAX_SUITES)
    for digest in baseline_runs:
        _sha(digest, "result.baseline.run_sha256s")
    if len(set(baseline_runs)) != len(baseline_runs):
        raise ExperimentError("baseline run digests must be unique")
    baseline_condition = _sha(baseline["condition_sha256"], "result.baseline.condition_sha256")
    for field in ("complete", "required_cases_passed", "required_repetitions_met", "protected_cases_passed", "effect_breach"):
        _boolean(baseline[field], f"result.baseline.{field}")
    baseline_metrics = _object(baseline["metrics"], "result.baseline.metrics")
    _exact(baseline_metrics, "result.baseline.metrics", ("correctness", "completion", "time", "tokens", "cost"))
    _number(baseline_metrics["correctness"], "result.baseline.metrics.correctness", 0, 1)
    _number(baseline_metrics["completion"], "result.baseline.metrics.completion", 0, 1)
    _number(baseline_metrics["time"], "result.baseline.metrics.time", 0, 31_536_000)
    _number(baseline_metrics["tokens"], "result.baseline.metrics.tokens", 0, 1_000_000_000, nullable=True)
    _number(baseline_metrics["cost"], "result.baseline.metrics.cost", 0, 1_000_000, nullable=True)
    candidates = _array(result["candidates"], "result.candidates", minimum=1, maximum=MAX_CANDIDATES)
    seen: set[str] = set()
    for index, raw in enumerate(candidates):
        item = _object(raw, f"result.candidates[{index}]")
        expected_fields = ("sequence", "rank", "candidate_id", "patch", "run_sha256s", "condition_sha256", "classification", "objective_delta", "required_repetitions_met", "required_cases_passed", "protected_cases_passed", "guardrail_regression", "effect_breach", "budget_breach", "metrics", "evidence", "limitations")
        _exact(item, f"result.candidates[{index}]", expected_fields)
        candidate_id = _identifier(item["candidate_id"], f"result.candidates[{index}].candidate_id")
        if candidate_id in seen:
            raise ExperimentError("result contains duplicate candidate_id")
        seen.add(candidate_id)
        _integer(item["sequence"], f"result.candidates[{index}].sequence", 1, len(candidates))
        _integer(item["rank"], f"result.candidates[{index}].rank", 1, max(1, len(candidates)))
        _enum(item["classification"], f"result.candidates[{index}].classification", set(CLASSIFICATION_ORDER))
        if item["objective_delta"] is not None:
            _number(item["objective_delta"], f"result.candidates[{index}].objective_delta", -1_000_000_000, 1_000_000_000)
        for field in ("required_repetitions_met", "required_cases_passed", "protected_cases_passed", "guardrail_regression", "effect_breach", "budget_breach"):
            _boolean(item[field], f"result.candidates[{index}].{field}")
        for digest in _array(item["run_sha256s"], f"result.candidates[{index}].run_sha256s", minimum=1, maximum=MAX_SUITES):
            _sha(digest, f"result.candidates[{index}].run_sha256s")
        _sha(item["condition_sha256"], f"result.candidates[{index}].condition_sha256")
        if item["condition_sha256"] != baseline_condition:
            raise ExperimentError("candidate runner conditions differ from baseline")
        if len(item["run_sha256s"]) != len(baseline_runs):
            raise ExperimentError("candidate does not bind one run per baseline suite")
        patch = _object(item["patch"], f"result.candidates[{index}].patch")
        _exact(patch, f"result.candidates[{index}].patch", ("rationale", "patch_sha256", "base_repository_sha256", "changes"))
        _text(patch["rationale"], f"result.candidates[{index}].patch.rationale", 2000)
        _sha(patch["patch_sha256"], f"result.candidates[{index}].patch.patch_sha256")
        _sha(patch["base_repository_sha256"], f"result.candidates[{index}].patch.base_repository_sha256")
        if patch["base_repository_sha256"] != repository_sha:
            raise ExperimentError("candidate patch does not bind the result repository")
        changes = _array(patch["changes"], f"result.candidates[{index}].patch.changes", minimum=1, maximum=MAX_SURFACES)
        changed_paths: set[str] = set()
        for change in changes:
            _exact(_object(change, "patch change"), "patch change", ("path", "before_sha256", "after_sha256", "after_text"))
            path = path_safety.canonical_path(change["path"])
            if path in changed_paths:
                raise ExperimentError("candidate patch contains duplicate paths")
            changed_paths.add(path)
            _sha(change["before_sha256"], "patch change.before_sha256")
            _sha(change["after_sha256"], "patch change.after_sha256")
            if not isinstance(change["after_text"], str) or "\x00" in change["after_text"] or any(unicodedata.category(char) == "Cs" for char in change["after_text"]) or _sha_bytes(change["after_text"].encode("utf-8")) != change["after_sha256"]:
                raise ExperimentError("patch change after_text digest is inconsistent")
        semantic_patch = {"base_repository_sha256": patch["base_repository_sha256"], "changes": changes}
        if patch["patch_sha256"] != _sha_bytes(_canonical_bytes(semantic_patch)):
            raise ExperimentError("candidate patch digest is inconsistent")
        metrics = _object(item["metrics"], "candidate metrics")
        _exact(metrics, "candidate metrics", ("correctness", "completion", "time", "tokens", "cost"))
        _number(metrics["correctness"], "candidate metrics.correctness", 0, 1)
        _number(metrics["completion"], "candidate metrics.completion", 0, 1)
        _number(metrics["time"], "candidate metrics.time", 0, 31_536_000)
        _number(metrics["tokens"], "candidate metrics.tokens", 0, 1_000_000_000, nullable=True)
        _number(metrics["cost"], "candidate metrics.cost", 0, 1_000_000, nullable=True)
        expected_delta = _objective_delta(metric, direction, baseline_metrics, metrics)
        if item["objective_delta"] != expected_delta:
            raise ExperimentError("candidate objective delta is inconsistent with recorded metrics")
        evidence_ids: set[str] = set()
        for raw_evidence in _array(item["evidence"], "candidate evidence", minimum=1, maximum=MAX_SUITES):
            evidence = _object(raw_evidence, "candidate evidence")
            _exact(evidence, "candidate evidence", ("evidence_id", "kind", "baseline_sha256", "candidate_sha256", "case_ids", "summary", "redacted"))
            evidence_id = _identifier(evidence["evidence_id"], "candidate evidence.evidence_id")
            if evidence_id in evidence_ids:
                raise ExperimentError("candidate evidence identities must be unique")
            evidence_ids.add(evidence_id)
            if evidence["kind"] != "run_receipt":
                raise ExperimentError("candidate evidence kind must be run_receipt")
            _sha(evidence["baseline_sha256"], "candidate evidence.baseline_sha256")
            _sha(evidence["candidate_sha256"], "candidate evidence.candidate_sha256")
            _unique_ids(evidence["case_ids"], "candidate evidence.case_ids")
            _text(evidence["summary"], "candidate evidence.summary", 500)
            if evidence["redacted"] is not True:
                raise ExperimentError("candidate evidence must be redacted")
        for raw_limitation in _array(item["limitations"], "candidate limitations", maximum=64):
            limitation = _object(raw_limitation, "candidate limitation")
            _exact(limitation, "candidate limitation", ("code", "message", "material"))
            _identifier(limitation["code"], "candidate limitation.code")
            _text(limitation["message"], "candidate limitation.message", 2000)
            _boolean(limitation["material"], "candidate limitation.material")
    if sorted(item["sequence"] for item in candidates) != list(range(1, len(candidates) + 1)):
        raise ExperimentError("candidate evaluation sequence is not contiguous")
    if sorted(item["rank"] for item in candidates) != list(range(1, len(candidates) + 1)):
        raise ExperimentError("candidate ranks are not contiguous")
    expected_order = sorted(candidates, key=lambda item: (CLASSIFICATION_ORDER[item["classification"]], -(item["objective_delta"] if item["objective_delta"] is not None else -1_000_000_001), item["candidate_id"]))
    if [item["candidate_id"] for item in candidates] != [item["candidate_id"] for item in expected_order]:
        raise ExperimentError("candidate ranking is inconsistent")
    budget = _object(result["budget"], "result.budget")
    _exact(budget, "result.budget", ("limits", "consumed"))
    limits = _object(budget["limits"], "result.budget.limits")
    _exact(limits, "result.budget.limits", ("max_candidates", "max_run_receipts", "max_seconds", "max_tokens", "max_cost_usd"))
    _integer(limits["max_candidates"], "result.budget.limits.max_candidates", 1, MAX_CANDIDATES)
    _integer(limits["max_run_receipts"], "result.budget.limits.max_run_receipts", 1, MAX_RUNS)
    _number(limits["max_seconds"], "result.budget.limits.max_seconds", 1, 31_536_000)
    _number(limits["max_tokens"], "result.budget.limits.max_tokens", 1, 1_000_000_000, nullable=True)
    _number(limits["max_cost_usd"], "result.budget.limits.max_cost_usd", 0, 1_000_000, nullable=True)
    consumed = _object(budget["consumed"], "result.budget.consumed")
    _exact(consumed, "result.budget.consumed", ("candidates", "run_receipts", "seconds", "tokens", "cost_usd"))
    _integer(consumed["candidates"], "result.budget.consumed.candidates", 0, MAX_CANDIDATES)
    _integer(consumed["run_receipts"], "result.budget.consumed.run_receipts", 0, MAX_RUNS)
    _number(consumed["seconds"], "result.budget.consumed.seconds", 0, 31_536_000)
    _number(consumed["tokens"], "result.budget.consumed.tokens", 0, 1_000_000_000, nullable=True)
    _number(consumed["cost_usd"], "result.budget.consumed.cost_usd", 0, 1_000_000, nullable=True)
    stop = _object(result["stop"], "result.stop")
    _exact(stop, "result.stop", ("reason", "after_candidate_id"))
    stop_reason = _enum(stop["reason"], "result.stop.reason", {"candidates_exhausted", "target_achieved", "no_progress", "budget_exhausted", "source_drift", "forbidden_effect", "decision_required"})
    if stop["after_candidate_id"] is not None and stop["after_candidate_id"] not in seen:
        raise ExperimentError("result.stop names an unknown candidate")
    limitations = []
    for raw_limitation in _array(result["limitations"], "result.limitations", maximum=64):
        limitation = _object(raw_limitation, "result limitation")
        _exact(limitation, "result limitation", ("code", "message", "material"))
        _identifier(limitation["code"], "result limitation.code")
        _text(limitation["message"], "result limitation.message", 2000)
        _boolean(limitation["material"], "result limitation.material")
        limitations.append(limitation)
    baseline_invalid = (
        not baseline["complete"]
        or not baseline["required_cases_passed"]
        or not baseline["protected_cases_passed"]
        or baseline["effect_breach"]
    )
    if baseline_invalid and not any(
        item["code"] == "invalid-baseline" and item["material"]
        for item in limitations
    ):
        raise ExperimentError("invalid baseline requires a material result limitation")

    expected_consumed = {
        "candidates": 0,
        "run_receipts": 0,
        "seconds": 0.0,
        "tokens": 0,
        "cost_usd": 0.0,
    }
    _add_consumed(expected_consumed, baseline_metrics, len(baseline_runs))
    ordered = sorted(candidates, key=lambda item: item["sequence"])
    no_progress = 0
    expected_stop_reason = "candidates_exhausted"
    expected_stop_after: str | None = None
    for sequence_index, item in enumerate(ordered):
        _add_consumed(expected_consumed, item["metrics"], len(item["run_sha256s"]))
        expected_consumed["candidates"] += 1
        expected_breach = _budget_breach(expected_consumed, limits)
        if item["budget_breach"] != expected_breach:
            raise ExperimentError("candidate budget_breach is inconsistent with cumulative evidence")
        expected_classification = _expected_classification(
            baseline=baseline,
            delta=item["objective_delta"],
            tolerance=tolerance,
            required_repetitions_met=item["required_repetitions_met"],
            required_cases_passed=item["required_cases_passed"],
            protected_cases_passed=item["protected_cases_passed"],
            guardrail_regression=item["guardrail_regression"],
            effect_breach=item["effect_breach"],
            budget_breach=item["budget_breach"],
            limitations=item["limitations"],
        )
        if item["classification"] != expected_classification:
            raise ExperimentError("candidate classification is inconsistent with its evidence and gates")
        expected_stop_after = item["candidate_id"]
        if item["effect_breach"]:
            expected_stop_reason = "forbidden_effect"
        elif item["budget_breach"]:
            expected_stop_reason = "budget_exhausted"
        elif item["classification"] == "clear_improvement" and (
            objective["target"] is None
            or item["objective_delta"] >= objective["target"]
        ):
            expected_stop_reason = "target_achieved"
        elif item["classification"] == "tradeoff":
            expected_stop_reason = "decision_required"
        else:
            no_progress = (
                no_progress + 1
                if item["classification"] in {"no_improvement", "inconclusive"}
                else 0
            )
            if no_progress >= no_progress_limit:
                expected_stop_reason = "no_progress"
        if expected_stop_reason != "candidates_exhausted":
            if sequence_index != len(ordered) - 1:
                raise ExperimentError("result includes candidates after the required stop condition")
            break
    if consumed != expected_consumed:
        raise ExperimentError("result cumulative budget consumption is inconsistent")
    if (stop_reason, stop["after_candidate_id"]) != (
        expected_stop_reason,
        expected_stop_after,
    ):
        raise ExperimentError("result stop condition is inconsistent with candidate sequence")

    classes = [item["classification"] for item in candidates]
    if stop_reason == "decision_required":
        expected_outcome = ("tradeoff", "decision")
    elif stop_reason == "target_achieved":
        expected_outcome = ("clear_improvement", "review_candidate")
    elif "clear_improvement" in classes:
        expected_outcome = ("clear_improvement", "review_candidate")
    elif "tradeoff" in classes:
        expected_outcome = ("tradeoff", "decision")
    elif classes and all(item == "no_improvement" for item in classes):
        expected_outcome = ("no_improvement", "none")
    elif "inconclusive" in classes:
        expected_outcome = ("inconclusive", "retry")
    else:
        expected_outcome = ("incomplete", "manual")
    if any(item["material"] for item in limitations) or stop_reason in {"forbidden_effect", "budget_exhausted", "source_drift"}:
        expected_outcome = ("incomplete", "manual")
    if (outcome, next_action) != expected_outcome:
        raise ExperimentError("result outcome or next_action is inconsistent")
    if completion != ("incomplete" if outcome == "incomplete" else "complete"):
        raise ExperimentError("result completion is inconsistent")
    if len(_canonical_bytes(result)) > MAX_RESULT_BYTES:
        raise ExperimentError("canonical result exceeds the supported limit")
    if context is not None:
        canonical_context = validate_context(context, current=True)
        if result["context_sha256"] != canonical_context["context_sha256"]:
            raise ExperimentError("result does not bind the selected context")
        expected = _derive_result(canonical_context)
        if result != expected:
            raise ExperimentError("result is not deterministically derived from the selected context")
    return result


def _display(value: str) -> str:
    pieces = []
    for char in value:
        category = unicodedata.category(char)
        if category in {"Cc", "Cf", "Cs"}:
            pieces.append(f"\\u{ord(char):04x}")
        elif char == "&":
            pieces.append("&amp;")
        elif char == "<":
            pieces.append("&lt;")
        elif char == ">":
            pieces.append("&gt;")
        else:
            pieces.append(char)
    return "".join(pieces)


def render(result: dict[str, Any]) -> str:
    validate_result(result)
    lines = [
        f"Experiment: {_display(result['outcome'])}",
        f"Completion: {_display(result['completion'])}",
        f"Next action: {_display(result['next_action'])}",
        f"Objective: {_display(result['objective']['direction'])} {_display(result['objective']['metric'])} beyond {result['objective']['tolerance']}",
        f"Stop: {_display(result['stop']['reason'])}",
        "",
    ]
    if not result["candidates"]:
        lines.append("No candidate was ranked.\n")
    for item in result["candidates"]:
        delta = "unavailable" if item["objective_delta"] is None else f"{item['objective_delta']:.6g}"
        lines.extend([
            f"{item['rank']}. {_display(item['candidate_id'])}: {_display(item['classification'])}",
            f"   objective delta: {delta}",
            f"   patch: {item['patch']['patch_sha256']}",
            f"   surfaces: {', '.join(_display(change['path']) for change in item['patch']['changes'])}",
            f"   gates: repetitions={item['required_repetitions_met']} required={item['required_cases_passed']} guardrail_regression={item['guardrail_regression']} effect_breach={item['effect_breach']} budget_breach={item['budget_breach']}",
        ])
    if result["limitations"]:
        lines.append("\nLimitations:")
        lines.extend(f"- {_display(item['code'])}: {_display(item['message'])}" for item in result["limitations"])
    return "\n".join(lines).rstrip() + "\n"


def _emit(value: dict[str, Any], output_format: str, output: Path | None, *, repository: Path | None = None) -> None:
    if output_format == "human":
        data = render(value).encode("utf-8")
    elif output_format == "json":
        data = _canonical_bytes(value) + b"\n"
    else:
        data = (render(value) + _canonical_bytes(value).decode("utf-8") + "\n").encode("utf-8")
    if len(data) > MAX_RESULT_BYTES:
        raise ExperimentError("rendered output exceeds the output limit")
    if output is None:
        sys.stdout.buffer.write(data)
    else:
        if repository is not None:
            _reject_repository_output(output, repository)
        path_safety.write_created_output(output, data)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("--repo", required=True)
    resolve.add_argument("--request", required=True)
    resolve.add_argument("--input-root", required=True)
    resolve.add_argument("--output", required=True)
    evaluate_command = commands.add_parser("evaluate")
    evaluate_command.add_argument("--context", required=True)
    evaluate_command.add_argument("--format", choices=("human", "json", "both"), default="human")
    evaluate_command.add_argument("--output")
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
            context = resolve_context(Path(args.repo), Path(args.request), Path(args.input_root))
            data = _canonical_bytes(context) + b"\n"
            if len(data) > MAX_CONTEXT_BYTES:
                raise ExperimentError("canonical context exceeds the supported limit")
            output = Path(args.output)
            _reject_repository_output(output, Path(context["repository_root"]))
            path_safety.write_created_output(output, data)
        elif args.command == "evaluate":
            context, _ = _read_json(Path(args.context), "experiment context", maximum=MAX_CONTEXT_BYTES)
            _emit(evaluate(context), args.format, Path(args.output) if args.output else None, repository=Path(context["repository_root"]))
        elif args.command == "validate":
            result, _ = _read_json(Path(args.input), "experiment result", maximum=MAX_RESULT_BYTES)
            context = None
            if args.context:
                context, _ = _read_json(Path(args.context), "experiment context", maximum=MAX_CONTEXT_BYTES)
            validate_result(result, context=context)
            sys.stdout.write('{"schema_version":"eval-experiment-result/v1","valid":true}\n')
        else:
            result, _ = _read_json(Path(args.input), "experiment result", maximum=MAX_RESULT_BYTES)
            value = validate_result(result)
            if args.format == "json":
                sys.stdout.buffer.write(_canonical_bytes(value) + b"\n")
            else:
                sys.stdout.write(render(value))
    except (ExperimentError, evidence_contracts.ContractError, path_safety.SafetyError, OSError) as exc:
        sys.stderr.write(f"eval-harness-experiment: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
