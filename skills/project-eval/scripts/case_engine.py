#!/usr/bin/env python3
"""Prepare and deterministically grade isolated project-eval cases."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from typing import Any


MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_TREE_BYTES = 64 * 1024 * 1024
MAX_TREE_ENTRIES = 10_000
MAX_TEXT = 20_000
ID = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CONTROL_NAME = "control.json"
FORBIDDEN_VISIBLE_NAMES = {
    ".git",
    ".agent-kit",
    ".eval-results",
    "evals",
    "control.json",
    "hidden",
    "holdout",
    "holdouts",
    "expected",
    "expected-results",
    "golden",
    "alternatives",
    "grader.py",
    "graders",
}
FORBIDDEN_VISIBLE_CASEFOLDED = {name.casefold() for name in FORBIDDEN_VISIBLE_NAMES}
PHASES = {
    "intake",
    "clarification",
    "specification",
    "planning",
    "implementation",
    "verification",
    "reporting",
}
CHECKS = {
    "python-compile": "python-compile",
}


class CaseError(ValueError):
    """Raised when a case cannot be safely prepared or graded."""


def _load_safety():
    path = Path(__file__).with_name("path_safety.py")
    name = f"_project_eval_case_safety_{hashlib.sha256(str(path).encode()).hexdigest()[:12]}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load bundled path safety helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SAFETY = _load_safety()
SafetyError = _SAFETY.SafetyError
assert_no_link_components = _SAFETY.assert_no_link_components
bound_directory_entries = _SAFETY.bound_directory_entries
canonical_path = _SAFETY.canonical_path
ensure_private_directory = _SAFETY.ensure_private_directory
filesystem_alias_identity = _SAFETY.filesystem_alias_identity
read_regular = _SAFETY.read_regular
safe_repo_path = _SAFETY.safe_repo_path
write_created_output = _SAFETY.write_created_output


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def engine_sha256() -> str:
    files: dict[str, str] = {}
    for name in ("case_engine.py", "fixed_check.py", "path_safety.py"):
        path = Path(__file__).with_name(name)
        try:
            _, raw = read_regular(path, MAX_JSON_BYTES, require_single_link=True)
        except SafetyError as exc:
            raise CaseError(f"cannot bind evaluator runtime {name}: {exc}") from exc
        files[name] = _sha(raw)
    return _sha(_canonical(files))


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CaseError(f"{label} must be an object")
    return value


def _array(value: Any, label: str, *, maximum: int, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise CaseError(f"{label} must contain from {minimum} through {maximum} items")
    return value


def _text(value: Any, label: str, *, maximum: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise CaseError(f"{label} must be a non-empty string of at most {maximum} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise CaseError(f"{label} contains control characters")
    return value


def _identifier(value: Any, label: str) -> str:
    value = _text(value, label, maximum=64)
    if not ID.fullmatch(value):
        raise CaseError(f"{label} is not a canonical identifier")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise CaseError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise CaseError(f"{label} must be an integer from {minimum} through {maximum}")
    return value


def _exact(value: dict[str, Any], label: str, fields: tuple[str, ...]) -> None:
    missing = sorted(set(fields) - set(value))
    extra = sorted(set(value) - set(fields))
    if missing or extra:
        raise CaseError(f"{label} fields do not match its contract; missing={missing}, extra={extra}")


def _duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CaseError(f"duplicate JSON member: {key!r}")
        result[key] = value
    return result


def _bounded_json(value: Any, label: str) -> None:
    pending: list[tuple[Any, int]] = [(value, 0)]
    count = 0
    while pending:
        current, depth = pending.pop()
        count += 1
        if count > 100_000:
            raise CaseError(f"{label} contains too many JSON values")
        if depth > 64:
            raise CaseError(f"{label} exceeds the JSON depth limit")
        if isinstance(current, dict):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)


def _relative(value: Any, label: str) -> str:
    try:
        return canonical_path(_text(value, label, maximum=4096))
    except SafetyError as exc:
        raise CaseError(f"{label}: {exc}") from exc


def _unique_ids(value: Any, label: str, *, maximum: int, minimum: int = 0) -> list[str]:
    items = _array(value, label, maximum=maximum, minimum=minimum)
    result: list[str] = []
    for index, item in enumerate(items):
        current = _identifier(item, f"{label}[{index}]")
        if current in result:
            raise CaseError(f"{label} contains duplicate {current!r}")
        result.append(current)
    return result


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        _, raw = read_regular(path, MAX_JSON_BYTES, require_single_link=True)
    except SafetyError as exc:
        raise CaseError(f"cannot read {label}: {exc}") from exc
    try:
        text = raw.decode("utf-8", "strict")
        value = json.loads(text, object_pairs_hook=_duplicate_object)
        _bounded_json(value, label)
    except (UnicodeDecodeError, json.JSONDecodeError, CaseError) as exc:
        raise CaseError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    return _mapping(value, label), raw


def validate_control(value: Any) -> dict[str, Any]:
    control = _mapping(value, "case control")
    fields = (
        "schema_version",
        "case_id",
        "materialization",
        "assertions",
        "checks",
        "hidden_grader",
        "trajectory",
        "reconstruction",
    )
    _exact(control, "case control", fields)
    if control["schema_version"] != "project-eval-case-control/v1":
        raise CaseError("unsupported case control schema_version")
    _identifier(control["case_id"], "case control.case_id")

    materialization = _mapping(control["materialization"], "case control.materialization")
    _exact(materialization, "case control.materialization", ("mode", "source", "remove_paths", "history"))
    mode = materialization["mode"]
    if mode not in {"copy", "reconstruction", "history"}:
        raise CaseError("case control.materialization.mode is unsupported")
    source = materialization["source"]
    if source is not None:
        _relative(source, "case control.materialization.source")
    removals = _array(materialization["remove_paths"], "case control.materialization.remove_paths", maximum=256)
    for index, item in enumerate(removals):
        _relative(item, f"case control.materialization.remove_paths[{index}]")
    history = _array(materialization["history"], "case control.materialization.history", maximum=64)
    for index, item in enumerate(history):
        snapshot = _mapping(item, f"case control.materialization.history[{index}]")
        _exact(snapshot, f"case control.materialization.history[{index}]", ("source", "message"))
        _relative(snapshot["source"], f"case control.materialization.history[{index}].source")
        _text(snapshot["message"], f"case control.materialization.history[{index}].message", maximum=200)
    if mode in {"copy", "reconstruction"} and (source is None or history):
        raise CaseError(f"{mode} materialization requires source and no history")
    if mode == "copy" and source != "visible":
        raise CaseError("copy materialization source must be the visible directory")
    if mode == "copy" and removals:
        raise CaseError("copy materialization cannot remove paths")
    if mode == "reconstruction" and not removals:
        raise CaseError("reconstruction materialization requires a removal transform")
    if mode == "history" and (source is not None or removals or not history):
        raise CaseError("history materialization requires only explicit sanitized snapshots")
    if mode == "history" and any(
        not snapshot["source"].startswith("history/") for snapshot in history
    ):
        raise CaseError("history snapshots must remain beneath the history directory")

    assertions = _array(control["assertions"], "case control.assertions", maximum=256, minimum=1)
    assertion_ids: set[str] = set()
    for index, item in enumerate(assertions):
        label = f"case control.assertions[{index}]"
        assertion = _mapping(item, label)
        _exact(assertion, label, ("assertion_id", "kind", "path", "expected"))
        assertion_id = _identifier(assertion["assertion_id"], f"{label}.assertion_id")
        if assertion_id in assertion_ids:
            raise CaseError(f"duplicate assertion_id: {assertion_id}")
        assertion_ids.add(assertion_id)
        kind = assertion["kind"]
        if kind not in {"file_exists", "file_absent", "file_contains", "file_not_contains", "text_equals", "json_equals"}:
            raise CaseError(f"{label}.kind is unsupported")
        _relative(assertion["path"], f"{label}.path")
        expected = assertion["expected"]
        if kind in {"file_exists", "file_absent"}:
            if expected is not None:
                raise CaseError(f"{label}.expected must be null for {kind}")
        elif kind in {"file_contains", "file_not_contains", "text_equals"}:
            _text(expected, f"{label}.expected")
        else:
            if len(_canonical(expected)) > MAX_JSON_BYTES:
                raise CaseError(f"{label}.expected is too large")

    checks = _array(control["checks"], "case control.checks", maximum=32)
    check_ids: set[str] = set()
    for index, item in enumerate(checks):
        label = f"case control.checks[{index}]"
        check = _mapping(item, label)
        _exact(check, label, ("check_id", "kind", "timeout_seconds"))
        check_id = _identifier(check["check_id"], f"{label}.check_id")
        if check_id in check_ids:
            raise CaseError(f"duplicate check_id: {check_id}")
        check_ids.add(check_id)
        if check["kind"] not in CHECKS:
            raise CaseError(f"{label}.kind is not a fixed project check")
        _integer(check["timeout_seconds"], f"{label}.timeout_seconds", 1, 600)

    grader = control["hidden_grader"]
    if grader is not None:
        grader = _mapping(grader, "case control.hidden_grader")
        _exact(grader, "case control.hidden_grader", ("grader_id", "kind", "timeout_seconds"))
        _identifier(grader["grader_id"], "case control.hidden_grader.grader_id")
        if grader["kind"] not in CHECKS:
            raise CaseError("case control.hidden_grader.kind is not an evaluator-owned fixed grader")
        _integer(grader["timeout_seconds"], "case control.hidden_grader.timeout_seconds", 1, 600)

    trajectory = control["trajectory"]
    if trajectory is not None:
        trajectory = _mapping(trajectory, "case control.trajectory")
        _exact(trajectory, "case control.trajectory", ("phases", "facts"))
        phases = _unique_ids(trajectory["phases"], "case control.trajectory.phases", maximum=7, minimum=1)
        if any(item not in PHASES for item in phases):
            raise CaseError("case control.trajectory.phases contains an unsupported phase")
        facts = _array(trajectory["facts"], "case control.trajectory.facts", maximum=256, minimum=1)
        fact_ids: set[str] = set()
        for index, item in enumerate(facts):
            label = f"case control.trajectory.facts[{index}]"
            fact = _mapping(item, label)
            _exact(fact, label, ("fact_id", "keywords", "answer", "phases"))
            fact_id = _identifier(fact["fact_id"], f"{label}.fact_id")
            if fact_id in fact_ids:
                raise CaseError(f"duplicate fact_id: {fact_id}")
            fact_ids.add(fact_id)
            keywords = _array(fact["keywords"], f"{label}.keywords", maximum=16, minimum=1)
            normalized: set[str] = set()
            for keyword_index, keyword in enumerate(keywords):
                keyword = _text(keyword, f"{label}.keywords[{keyword_index}]", maximum=64).casefold()
                if not re.fullmatch(r"[\w-]+", keyword, flags=re.UNICODE):
                    raise CaseError(f"{label}.keywords must contain single normalized terms")
                if keyword in normalized:
                    raise CaseError(f"{label}.keywords contains a duplicate")
                normalized.add(keyword)
            _text(fact["answer"], f"{label}.answer", maximum=2000)
            fact_phases = _unique_ids(fact["phases"], f"{label}.phases", maximum=7, minimum=1)
            if not set(fact_phases) <= set(phases):
                raise CaseError(f"{label}.phases names a phase outside the trajectory")

    reconstruction = control["reconstruction"]
    if reconstruction is not None:
        reconstruction = _mapping(reconstruction, "case control.reconstruction")
        _exact(reconstruction, "case control.reconstruction", ("golden_source", "alternative_sources", "protected_paths"))
        golden = _relative(reconstruction["golden_source"], "case control.reconstruction.golden_source")
        alternatives = _array(reconstruction["alternative_sources"], "case control.reconstruction.alternative_sources", maximum=16, minimum=1)
        for index, item in enumerate(alternatives):
            alternative = _relative(item, f"case control.reconstruction.alternative_sources[{index}]")
            if not alternative.startswith("alternatives/"):
                raise CaseError("reconstruction alternatives must remain beneath alternatives")
        protected = _array(reconstruction["protected_paths"], "case control.reconstruction.protected_paths", maximum=256, minimum=1)
        for index, item in enumerate(protected):
            _relative(item, f"case control.reconstruction.protected_paths[{index}]")
        if mode != "reconstruction" or source != golden or golden != "golden":
            raise CaseError("reconstruction metadata must bind the reconstruction source")
    elif mode == "reconstruction":
        raise CaseError("reconstruction materialization requires reconstruction metadata")
    return control


def load_control(fixture: Path) -> tuple[dict[str, Any], bytes]:
    try:
        control_path = safe_repo_path(fixture, CONTROL_NAME)
    except SafetyError as exc:
        raise CaseError(f"cannot bind case control: {exc}") from exc
    control, raw = _load_json(control_path, "case control")
    return validate_control(control), raw


def validate_case_fixture(fixture: Path, case: dict[str, Any]) -> tuple[dict[str, Any], bytes, str]:
    fixture_digest = tree_digest(fixture)
    control, raw = load_control(fixture)
    if control["case_id"] != case["case_id"]:
        raise CaseError("case control does not match the selected suite case")
    declared = set(case["assertion_ids"])
    actual = {item["assertion_id"] for item in control["assertions"]}
    if declared != actual:
        raise CaseError("case control assertions do not match the suite declaration")
    if (case["kind"] == "trajectory") != (control["trajectory"] is not None):
        raise CaseError("trajectory control does not match the selected case kind")
    materialization = control["materialization"]
    if materialization["mode"] == "history":
        if "sanitized-history" not in case["required_capabilities"]:
            raise CaseError("history materialization requires the sanitized-history capability declaration")
        for snapshot in materialization["history"]:
            _resolve_source(fixture, snapshot["source"], "sanitized history snapshot")
    else:
        _resolve_source(fixture, materialization["source"], "materialization source")
    reconstruction = control["reconstruction"]
    if reconstruction is not None:
        _resolve_source(fixture, reconstruction["golden_source"], "golden source")
        for source in reconstruction["alternative_sources"]:
            _resolve_source(fixture, source, "alternative source")
        _protected_payloads(fixture, control)
    if tree_digest(fixture) != fixture_digest:
        raise CaseError("case fixture changed during validation")
    return control, raw, fixture_digest


def _tree_records(root: Path, *, include_git: bool = True) -> tuple[list[tuple[str, str, int, str]], int]:
    root = root.absolute()
    try:
        assert_no_link_components(root, include_final=True)
    except SafetyError as exc:
        raise CaseError(f"cannot bind tree: {exc}") from exc
    records: list[tuple[str, str, int, str]] = []
    total_bytes = 0
    pending: list[tuple[Path, str]] = [(root, "")]
    while pending:
        directory, prefix = pending.pop()
        try:
            entries, _, complete = bound_directory_entries(directory, MAX_TREE_ENTRIES - len(records))
        except SafetyError as exc:
            raise CaseError(f"cannot inspect tree: {exc}") from exc
        if not complete:
            raise CaseError("tree exceeds its entry limit")
        for entry in entries:
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            if not include_git and (relative == ".git" or relative.startswith(".git/")):
                continue
            if entry.link_like:
                raise CaseError(f"tree contains link-like entry: {relative}")
            if entry.is_directory:
                records.append((relative, "directory", 0, ""))
                pending.append((entry.path, relative))
            elif entry.is_regular:
                try:
                    metadata, raw = read_regular(entry.path, MAX_TREE_BYTES - total_bytes, require_single_link=True)
                except SafetyError as exc:
                    raise CaseError(f"cannot inspect tree file {relative}: {exc}") from exc
                total_bytes += len(raw)
                if total_bytes > MAX_TREE_BYTES:
                    raise CaseError("tree exceeds its byte limit")
                mode = 1 if metadata.st_mode & 0o111 else 0
                records.append((relative, "file", mode, _sha(raw)))
            else:
                raise CaseError(f"tree contains unsupported entry: {relative}")
            if len(records) > MAX_TREE_ENTRIES:
                raise CaseError("tree exceeds its entry limit")
    return sorted(records), total_bytes


def tree_digest(root: Path, *, include_git: bool = True) -> str:
    records, _ = _tree_records(root, include_git=include_git)
    return _sha(_canonical(records))


def _copy_tree(source: Path, destination: Path) -> None:
    ensure_private_directory(destination)
    pending: list[tuple[Path, Path, str]] = [(source, destination, "")]
    count = 0
    total = 0
    while pending:
        current_source, current_destination, prefix = pending.pop()
        try:
            entries, _, complete = bound_directory_entries(current_source, MAX_TREE_ENTRIES - count)
        except SafetyError as exc:
            raise CaseError(f"cannot inspect fixture source: {exc}") from exc
        if not complete:
            raise CaseError("fixture exceeds its entry limit")
        for entry in entries:
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            if entry.name.casefold() in FORBIDDEN_VISIBLE_CASEFOLDED:
                raise CaseError(f"fixture contains prohibited agent-visible entry: {relative}")
            if entry.link_like:
                raise CaseError(f"fixture contains link-like entry: {relative}")
            target = current_destination / entry.name
            count += 1
            if count > MAX_TREE_ENTRIES:
                raise CaseError("fixture exceeds its entry limit")
            if entry.is_directory:
                ensure_private_directory(target)
                pending.append((entry.path, target, relative))
            elif entry.is_regular:
                try:
                    metadata, raw = read_regular(entry.path, MAX_TREE_BYTES - total, require_single_link=True)
                except SafetyError as exc:
                    raise CaseError(f"cannot read fixture file {relative}: {exc}") from exc
                total += len(raw)
                if total > MAX_TREE_BYTES:
                    raise CaseError("fixture exceeds its byte limit")
                write_created_output(target, raw)
                if os.name == "posix" and metadata.st_mode & 0o111:
                    target.chmod(0o700)
            else:
                raise CaseError(f"fixture contains unsupported entry: {relative}")


def _safe_environment(home: Path) -> dict[str, str]:
    environment: dict[str, str] = {}
    for name in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    environment.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": os.devnull,
        }
    )
    return environment


def _remove_tree(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise CaseError(f"cannot remove disposable tree: {path}")


def _run_bounded(argv: list[str], cwd: Path, timeout: int, environment: dict[str, str]) -> tuple[int, bytes, bytes, bool]:
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        # Graders and project code are untrusted. Exit status is sufficient for
        # deterministic grading, so never retain or buffer their raw output.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        start_new_session=os.name == "posix",
    )
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            try:
                process.kill()
            except OSError:
                pass
        process.wait()
    return process.returncode, b"", b"", timed_out


def _git_history(workspace: Path, snapshots: list[dict[str, Any]], fixture: Path) -> None:
    home = workspace.parent / f".git-home-{secrets.token_hex(8)}"
    ensure_private_directory(home)
    environment = _safe_environment(home)
    try:
        operations = [
            ["git", "init", "--quiet", "--template="],
            ["git", "config", "user.name", "Project Eval"],
            ["git", "config", "user.email", "project-eval.invalid@example.invalid"],
        ]
        for argv in operations:
            code, _, _, timed_out = _run_bounded(argv, workspace, 30, environment)
            if timed_out or code != 0:
                raise CaseError("cannot initialize sanitized history")
        for index, snapshot in enumerate(snapshots):
            for entry in list(workspace.iterdir()):
                if entry.name == ".git":
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            source = safe_repo_path(fixture, snapshot["source"])
            if not source.is_dir():
                raise CaseError("sanitized history snapshot is not a directory")
            source_before = tree_digest(source)
            _copy_tree(source, workspace)
            if tree_digest(source) != source_before:
                raise CaseError("sanitized history snapshot changed during materialization")
            timestamp = f"{946684800 + index} +0000"
            commit_environment = dict(environment)
            commit_environment["GIT_AUTHOR_DATE"] = timestamp
            commit_environment["GIT_COMMITTER_DATE"] = timestamp
            for argv in (["git", "add", "-A"], ["git", "commit", "--quiet", "--allow-empty", "-m", snapshot["message"]]):
                code, _, _, timed_out = _run_bounded(argv, workspace, 30, commit_environment)
                if timed_out or code != 0:
                    raise CaseError("cannot construct sanitized history")
    finally:
        _remove_tree(home)


def _resolve_source(fixture: Path, relative: str, label: str) -> Path:
    try:
        source = safe_repo_path(fixture, relative)
    except SafetyError as exc:
        raise CaseError(f"cannot bind {label}: {exc}") from exc
    if not source.is_dir():
        raise CaseError(f"{label} is not a directory")
    return source


def materialize_case(fixture: Path, case: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    control, _, fixture_before = validate_case_fixture(fixture, case)
    ensure_private_directory(workspace_root)
    workspace = workspace_root / f"case-{case['case_id']}-{secrets.token_hex(12)}"
    ensure_private_directory(workspace)
    try:
        materialization = control["materialization"]
        mode = materialization["mode"]
        if mode == "history":
            _git_history(workspace, materialization["history"], fixture)
        else:
            source = _resolve_source(fixture, materialization["source"], "materialization source")
            before = tree_digest(source)
            _copy_tree(source, workspace)
            if tree_digest(source) != before:
                raise CaseError("fixture source changed during materialization")
            if mode == "reconstruction":
                for relative in materialization["remove_paths"]:
                    try:
                        target = safe_repo_path(workspace, relative, allow_absent_final=True)
                    except SafetyError as exc:
                        raise CaseError(f"unsafe reconstruction removal: {exc}") from exc
                    if not target.exists():
                        raise CaseError(f"reconstruction removal target is missing: {relative}")
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
        workspace_sha = tree_digest(workspace)
        fixture_after = tree_digest(fixture)
        if fixture_after != fixture_before:
            raise CaseError("case fixture changed during materialization")
        try:
            identity = list(filesystem_alias_identity(workspace, workspace.lstat()))
        except (OSError, SafetyError) as exc:
            raise CaseError(f"cannot bind prepared workspace identity: {exc}") from exc
        prepared = {
            "schema_version": "project-eval-prepared-case/v1",
            "case_id": case["case_id"],
            "kind": case["kind"],
            "coverage": case["coverage"],
            "workspace": str(workspace),
            "workspace_identity_sha256": _sha(_canonical(identity)),
            "workspace_initial_sha256": workspace_sha,
            "control_sha256": _sha(_canonical(control)),
            "fixture_sha256": fixture_after,
        }
        prepared["preparation_sha256"] = _sha(_canonical(prepared))
        return prepared
    except Exception:
        _remove_tree(workspace)
        raise


def _read_workspace_file(workspace: Path, relative: str, maximum: int = MAX_JSON_BYTES) -> bytes | None:
    try:
        path = safe_repo_path(workspace, relative, allow_absent_final=True)
    except SafetyError as exc:
        raise CaseError(f"cannot bind assertion path: {exc}") from exc
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CaseError(f"cannot inspect assertion path: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise CaseError(f"assertion path is not a regular file: {relative}")
    try:
        _, raw = read_regular(path, maximum, require_single_link=True)
    except SafetyError as exc:
        raise CaseError(f"cannot read assertion path: {exc}") from exc
    return raw


def _grade_assertion(workspace: Path, assertion: dict[str, Any]) -> tuple[bool, str]:
    kind = assertion["kind"]
    raw = _read_workspace_file(workspace, assertion["path"])
    if kind == "file_exists":
        return raw is not None, "required file presence"
    if kind == "file_absent":
        return raw is None, "required file absence"
    if raw is None:
        return False, "required file is missing"
    if kind in {"file_contains", "file_not_contains", "text_equals"}:
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeDecodeError:
            return False, "file is not UTF-8 text"
        expected = assertion["expected"]
        if kind == "file_contains":
            return expected in text, "required text presence"
        if kind == "file_not_contains":
            return expected not in text, "forbidden text absence"
        return text == expected, "exact text equality"
    try:
        value = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, "valid JSON and exact value"
    return value == assertion["expected"], "exact JSON equality"


def validate_prepared_case(
    fixture: Path,
    case: dict[str, Any],
    value: Any,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    prepared = _mapping(value, "prepared case")
    fields = (
        "schema_version",
        "case_id",
        "kind",
        "coverage",
        "workspace",
        "workspace_identity_sha256",
        "workspace_initial_sha256",
        "control_sha256",
        "fixture_sha256",
        "preparation_sha256",
    )
    _exact(prepared, "prepared case", fields)
    if prepared["schema_version"] != "project-eval-prepared-case/v1":
        raise CaseError("unsupported prepared case schema_version")
    _identifier(prepared["case_id"], "prepared case.case_id")
    if prepared["kind"] not in {"explanation", "implementation", "trajectory"}:
        raise CaseError("prepared case.kind is unsupported")
    if prepared["coverage"] not in {"development", "holdout", "regression"}:
        raise CaseError("prepared case.coverage is unsupported")
    for field in (
        "workspace_identity_sha256",
        "workspace_initial_sha256",
        "control_sha256",
        "fixture_sha256",
        "preparation_sha256",
    ):
        _digest(prepared[field], f"prepared case.{field}")
    workspace_value = prepared["workspace"]
    if not isinstance(workspace_value, str) or not workspace_value or "\x00" in workspace_value:
        raise CaseError("prepared case.workspace must be a nonempty absolute path")
    workspace = Path(workspace_value)
    if not workspace.is_absolute():
        raise CaseError("prepared case.workspace must be an absolute path")
    unsigned = dict(prepared)
    claimed_preparation = unsigned.pop("preparation_sha256")
    if _sha(_canonical(unsigned)) != claimed_preparation:
        raise CaseError("prepared case digest does not match its contents")

    control, _, fixture_sha = validate_case_fixture(fixture, case)
    if prepared["case_id"] != case["case_id"]:
        raise CaseError("prepared case does not match the selected case_id")
    if prepared["kind"] != case["kind"] or prepared["coverage"] != case["coverage"]:
        raise CaseError("prepared case metadata does not match the selected suite case")
    if prepared["control_sha256"] != _sha(_canonical(control)):
        raise CaseError("prepared case control digest does not match the selected fixture")
    if prepared["fixture_sha256"] != fixture_sha:
        raise CaseError("prepared case fixture digest does not match the selected fixture")
    try:
        assert_no_link_components(workspace, include_final=True)
        metadata = workspace.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise CaseError("prepared workspace is not a directory")
        identity = _sha(_canonical(list(filesystem_alias_identity(workspace, metadata))))
    except (OSError, SafetyError) as exc:
        raise CaseError(f"cannot bind prepared workspace: {exc}") from exc
    if identity != prepared["workspace_identity_sha256"]:
        raise CaseError("prepared workspace identity changed after materialization")
    return control, prepared, workspace


def _grade_control(
    workspace: Path,
    control: dict[str, Any],
    *,
    allow_hidden_grader: bool,
    allow_project_checks: bool,
) -> dict[str, Any]:
    before = tree_digest(workspace)
    evidence: list[dict[str, Any]] = []
    all_passed = True
    for assertion in control["assertions"]:
        passed, summary = _grade_assertion(workspace, assertion)
        all_passed &= passed
        evidence.append(
            {
                "evidence_id": assertion["assertion_id"],
                "kind": "assertion",
                "status": "pass" if passed else "fail",
                "sha256": _sha(_canonical({"assertion": assertion, "passed": passed})),
                "summary": summary,
                "redacted": True,
            }
        )

    with tempfile.TemporaryDirectory(prefix="project-eval-grader-") as temporary:
        home = Path(temporary)
        environment = _safe_environment(home)
        for check in control["checks"]:
            if not allow_project_checks:
                all_passed = False
                evidence.append(
                    {
                        "evidence_id": check["check_id"],
                        "kind": "check",
                        "status": "unknown",
                        "sha256": _sha(_canonical(check)),
                        "summary": "fixed project check requires explicit authorization",
                        "redacted": True,
                    }
                )
                continue
            check_helper = Path(__file__).with_name("fixed_check.py")
            code, stdout, stderr, timed_out = _run_bounded(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(check_helper),
                    CHECKS[check["kind"]],
                    "--workspace",
                    str(workspace),
                ],
                workspace,
                check["timeout_seconds"],
                environment,
            )
            passed = not timed_out and code == 0
            all_passed &= passed
            evidence.append(
                {
                    "evidence_id": check["check_id"],
                    "kind": "check",
                    "status": "pass" if passed else "fail",
                    "sha256": _sha(f"exit={code};timeout={timed_out}".encode("ascii")),
                    "summary": "fixed project check completed" if passed else ("fixed project check timed out" if timed_out else "fixed project check failed"),
                    "redacted": True,
                }
            )

        grader = control["hidden_grader"]
        if grader is not None:
            if not allow_hidden_grader:
                all_passed = False
                evidence.append(
                    {
                        "evidence_id": grader["grader_id"],
                        "kind": "check",
                        "status": "unknown",
                        "sha256": _sha(_canonical(grader)),
                        "summary": "fixed hidden grader requires explicit authorization",
                        "redacted": True,
                    }
                )
            else:
                check_helper = Path(__file__).with_name("fixed_check.py")
                code, stdout, stderr, timed_out = _run_bounded(
                    [
                        sys.executable,
                        "-I",
                        "-S",
                        str(check_helper),
                        CHECKS[grader["kind"]],
                        "--workspace",
                        str(workspace),
                    ],
                    workspace,
                    grader["timeout_seconds"],
                    environment,
                )
                passed = not timed_out and code == 0
                all_passed &= passed
                evidence.append(
                    {
                        "evidence_id": grader["grader_id"],
                        "kind": "check",
                        "status": "pass" if passed else "fail",
                        "sha256": _sha(f"exit={code};timeout={timed_out}".encode("ascii")),
                        "summary": "fixed hidden grader completed" if passed else ("fixed hidden grader timed out" if timed_out else "fixed hidden grader failed"),
                        "redacted": True,
                    }
                )

    after = tree_digest(workspace)
    mutation = after != before
    if mutation:
        all_passed = False
        evidence.append(
            {
                "evidence_id": "grader-mutation",
                "kind": "failure",
                "status": "fail",
                "sha256": _sha(f"{before}:{after}".encode("ascii")),
                "summary": "grading changed the evaluated workspace",
                "redacted": True,
            }
        )
    return {"passed": all_passed, "workspace_sha256": before, "evidence": evidence}


def grade_case(
    fixture: Path,
    case: dict[str, Any],
    prepared_value: Any,
    *,
    allow_hidden_grader: bool = False,
    allow_project_checks: bool = False,
) -> dict[str, Any]:
    control, prepared, workspace = validate_prepared_case(fixture, case, prepared_value)
    graded = _grade_control(
        workspace,
        control,
        allow_hidden_grader=allow_hidden_grader,
        allow_project_checks=allow_project_checks,
    )
    return {
        "schema_version": "project-eval-case-grade/v1",
        "case_id": case["case_id"],
        "status": "passed" if graded["passed"] else "failed",
        "workspace_initial_sha256": prepared["workspace_initial_sha256"],
        "workspace_sha256": graded["workspace_sha256"],
        "control_sha256": _sha(_canonical(control)),
        "fixture_sha256": prepared["fixture_sha256"],
        "preparation_sha256": prepared["preparation_sha256"],
        "grader_sha256": _sha(
            _canonical(
                {
                    "control_sha256": _sha(_canonical(control)),
                    "runtime_sha256": engine_sha256(),
                    "hidden_grader": control["hidden_grader"],
                    "hidden_grader_authorized": allow_hidden_grader,
                    "project_checks_authorized": allow_project_checks,
                }
            )
        ),
        "evidence": graded["evidence"],
    }


def _copy_source_for_calibration(fixture: Path, source_value: str, root: Path, label: str) -> Path:
    source = _resolve_source(fixture, source_value, label)
    destination = root / f"{label}-{secrets.token_hex(6)}"
    before = tree_digest(source)
    _copy_tree(source, destination)
    if tree_digest(source) != before:
        raise CaseError(f"{label} changed during calibration")
    return destination


def _payloads_beneath(root: Path, relative: str, label: str) -> list[tuple[str, bytes]]:
    try:
        path = safe_repo_path(root, relative)
        metadata = path.lstat()
    except (OSError, SafetyError) as exc:
        raise CaseError(f"cannot bind {label}: {exc}") from exc
    if stat.S_ISREG(metadata.st_mode):
        try:
            _, raw = read_regular(path, MAX_TREE_BYTES, require_single_link=True)
        except SafetyError as exc:
            raise CaseError(f"cannot read {label}: {exc}") from exc
        return [(relative, raw)] if raw else []
    if not stat.S_ISDIR(metadata.st_mode):
        raise CaseError(f"{label} is not a regular file or directory")
    result: list[tuple[str, bytes]] = []
    pending: list[tuple[Path, str]] = [(path, relative)]
    count = 0
    total = 0
    while pending:
        directory, prefix = pending.pop()
        try:
            entries, _, complete = bound_directory_entries(directory, MAX_TREE_ENTRIES - count)
        except SafetyError as exc:
            raise CaseError(f"cannot inspect {label}: {exc}") from exc
        if not complete:
            raise CaseError(f"{label} exceeds its entry limit")
        for entry in entries:
            count += 1
            child_relative = f"{prefix}/{entry.name}"
            if entry.link_like:
                raise CaseError(f"{label} contains a link-like entry")
            if entry.is_directory:
                pending.append((entry.path, child_relative))
            elif entry.is_regular:
                try:
                    _, raw = read_regular(entry.path, MAX_TREE_BYTES - total, require_single_link=True)
                except SafetyError as exc:
                    raise CaseError(f"cannot read {label}: {exc}") from exc
                total += len(raw)
                if total > MAX_TREE_BYTES:
                    raise CaseError(f"{label} exceeds its byte limit")
                if raw:
                    result.append((child_relative, raw))
            else:
                raise CaseError(f"{label} contains an unsupported entry")
    return result


def _protected_payloads(fixture: Path, control: dict[str, Any]) -> list[tuple[str, bytes]]:
    reconstruction = control["reconstruction"]
    golden = _resolve_source(fixture, reconstruction["golden_source"], "golden source")
    result: list[tuple[str, bytes]] = []
    seen: set[tuple[str, str]] = set()
    requested = [
        *(('protected', item) for item in reconstruction["protected_paths"]),
        *(('removed', item) for item in control["materialization"]["remove_paths"]),
    ]
    for source_kind, relative in requested:
        for payload_path, raw in _payloads_beneath(
            golden, relative, f"{source_kind} reconstruction source"
        ):
            key = (payload_path, _sha(raw))
            if key not in seen:
                seen.add(key)
                result.append((payload_path, raw))
    if not result:
        raise CaseError("reconstruction leakage calibration has no nonempty protected payload")
    return result


def _contains_payload(root: Path, payload: bytes) -> bool:
    pending = [root]
    count = 0
    total = 0
    while pending:
        directory = pending.pop()
        entries, _, complete = bound_directory_entries(directory, MAX_TREE_ENTRIES - count)
        if not complete:
            raise CaseError("calibration tree exceeds its entry limit")
        for entry in entries:
            count += 1
            if entry.link_like:
                raise CaseError("calibration tree contains a link-like entry")
            if entry.is_directory:
                pending.append(entry.path)
            elif entry.is_regular:
                _, raw = read_regular(entry.path, MAX_TREE_BYTES - total, require_single_link=True)
                total += len(raw)
                if payload and payload in raw:
                    return True
    return False


def calibrate_reconstruction(
    fixture: Path,
    case: dict[str, Any],
    workspace_root: Path,
    *,
    allow_hidden_grader: bool = False,
    allow_project_checks: bool = False,
) -> dict[str, Any]:
    control, _, _ = validate_case_fixture(fixture, case)
    if control["materialization"]["mode"] != "reconstruction":
        raise CaseError("selected case is not a matching reconstruction case")
    ensure_private_directory(workspace_root)
    prepared = materialize_case(fixture, case, workspace_root)
    start = Path(prepared["workspace"])
    calibration_root = workspace_root / f"calibration-{secrets.token_hex(12)}"
    ensure_private_directory(calibration_root)
    try:
        start_grade = _grade_control(
            start,
            control,
            allow_hidden_grader=allow_hidden_grader,
            allow_project_checks=allow_project_checks,
        )
        golden = _copy_source_for_calibration(
            fixture, control["reconstruction"]["golden_source"], calibration_root, "golden"
        )
        golden_grade = _grade_control(
            golden,
            control,
            allow_hidden_grader=allow_hidden_grader,
            allow_project_checks=allow_project_checks,
        )
        golden_digest = tree_digest(golden)
        alternatives: list[dict[str, Any]] = []
        for index, source in enumerate(control["reconstruction"]["alternative_sources"]):
            alternative = _copy_source_for_calibration(fixture, source, calibration_root, f"alternative-{index}")
            grade = _grade_control(
                alternative,
                control,
                allow_hidden_grader=allow_hidden_grader,
                allow_project_checks=allow_project_checks,
            )
            alternatives.append({"passed": grade["passed"], "distinct": tree_digest(alternative) != golden_digest})
        leaked: list[str] = []
        for relative, payload in _protected_payloads(fixture, control):
            if _contains_payload(start, payload):
                leaked.append(relative)
        passed = (
            not start_grade["passed"]
            and golden_grade["passed"]
            and all(item["passed"] and item["distinct"] for item in alternatives)
            and not leaked
        )
        return {
            "schema_version": "project-eval-reconstruction-calibration/v1",
            "case_id": case["case_id"],
            "status": "passed" if passed else "failed",
            "prepared_start_failed": not start_grade["passed"],
            "golden_passed": golden_grade["passed"],
            "alternatives": alternatives,
            "protected_source_leaked": bool(leaked),
            "evidence_sha256": _sha(_canonical({"start": start_grade, "golden": golden_grade, "alternatives": alternatives, "leaked": leaked})),
        }
    finally:
        _remove_tree(start)
        _remove_tree(calibration_root)


def respond_to_question(control: dict[str, Any], phase: str, question: str) -> dict[str, Any]:
    validate_control(control)
    trajectory = control["trajectory"]
    if trajectory is None:
        raise CaseError("case does not define a clarification trajectory")
    if phase not in trajectory["phases"]:
        raise CaseError("phase is not part of the selected trajectory")
    question = _text(question, "question", maximum=2000).casefold()
    words = set(re.findall(r"[\w-]+", question, flags=re.UNICODE))
    matches: list[dict[str, Any]] = []
    for fact in trajectory["facts"]:
        keywords = {keyword.casefold() for keyword in fact["keywords"]}
        if phase in fact["phases"] and keywords <= words:
            matches.append(fact)
    if len(matches) == 1:
        return {
            "schema_version": "project-eval-clarification-response/v1",
            "status": "answered",
            "fact_id": matches[0]["fact_id"],
            "answer": matches[0]["answer"],
        }
    return {
        "schema_version": "project-eval-clarification-response/v1",
        "status": "ambiguous" if matches else "unanswered",
        "fact_id": None,
        "answer": None,
    }


def platform_eligibility(case: dict[str, Any], capabilities: set[str]) -> dict[str, Any]:
    current = {"Linux": "linux", "Windows": "windows", "Darwin": "macos"}.get(platform.system())
    if current not in case["platforms"]:
        return {"status": "not_applicable", "missing_capabilities": []}
    missing = sorted(set(case["required_capabilities"]) - capabilities)
    if missing:
        return {"status": "unavailable", "missing_capabilities": missing}
    return {"status": "eligible", "missing_capabilities": []}
