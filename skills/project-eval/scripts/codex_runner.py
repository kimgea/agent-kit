#!/usr/bin/env python3
"""Fixed, bounded Codex execution adapter for project-eval."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from typing import Any


MAX_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_PROMPT_BYTES = 64 * 1024
MAX_TIMEOUT_SECONDS = 86_400
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REASONING = {"low", "medium", "high", "xhigh", "max", "ultra"}
VERSION = re.compile(r"(?<![0-9])([0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?)")
MINIMUM_PERMISSION_PROFILE_VERSION = (0, 138, 0)


class RunnerError(ValueError):
    """Raised when runner authority, containment, or evidence is invalid."""


def _load_sibling(name: str):
    path = Path(__file__).with_name(name)
    module_name = f"_project_eval_runner_{path.stem}_{hashlib.sha256(str(path).encode()).hexdigest()[:12]}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load bundled helper {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SAFETY = _load_sibling("path_safety.py")
_CASE = _load_sibling("case_engine.py")
SafetyError = _SAFETY.SafetyError
assert_no_link_components = _SAFETY.assert_no_link_components
ensure_private_directory = _SAFETY.ensure_private_directory
read_regular = _SAFETY.read_regular


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def adapter_sha256() -> str:
    """Bind the installed adapter and every runtime helper it directly trusts."""
    files: dict[str, str] = {}
    for name in ("codex_runner.py", "case_engine.py", "fixed_check.py", "path_safety.py"):
        path = Path(__file__).with_name(name)
        try:
            _, raw = read_regular(path, 8 * 1024 * 1024, require_single_link=True)
        except SafetyError as exc:
            raise RunnerError(f"cannot bind runner adapter {name}: {exc}") from exc
        files[name] = _sha(raw)
    return _sha(_canonical(files))


def _fixed_text(raw: bytes, label: str, maximum: int = 1000) -> str:
    try:
        text = raw.decode("utf-8", "strict").strip()
    except UnicodeDecodeError as exc:
        raise RunnerError(f"{label} is not UTF-8") from exc
    if not text or len(text.encode("utf-8")) > maximum or any(ord(char) < 32 for char in text):
        raise RunnerError(f"{label} is malformed")
    return text


def _version_value(text: str) -> str:
    match = VERSION.search(text)
    if match is None:
        raise RunnerError("Codex version output has no supported semantic version")
    return match.group(1)


def _version_tuple(value: str) -> tuple[int, int, int]:
    core = value.split("-", 1)[0].split("+", 1)[0]
    return tuple(int(item) for item in core.split("."))  # type: ignore[return-value]


def _command_prefix(launcher: Path) -> list[str]:
    if os.name == "nt" and launcher.suffix.casefold() not in {".exe", ".com"}:
        raise RunnerError("Codex launcher must be a native Windows executable")
    return [str(launcher)]


def discover_codex() -> dict[str, Any]:
    names = ("codex.exe", "codex") if os.name == "nt" else ("codex",)
    discovered = next((candidate for name in names if (candidate := shutil.which(name))), None)
    if discovered is None:
        raise RunnerError("Codex CLI is not installed")
    try:
        launcher = Path(discovered).resolve(strict=True)
        assert_no_link_components(launcher, include_final=True)
        _, launcher_raw = read_regular(launcher, 256 * 1024 * 1024)
    except (OSError, SafetyError) as exc:
        raise RunnerError(f"cannot bind Codex launcher: {exc}") from exc
    command = _command_prefix(launcher)
    observations: dict[str, bytes] = {}
    for label, suffix in (("version", ["--version"]), ("help", ["exec", "--help"])):
        try:
            completed = subprocess.run(
                [*command, *suffix],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RunnerError(f"cannot inspect Codex {label}: {exc}") from exc
        if completed.returncode != 0 or len(completed.stdout) > 256 * 1024:
            raise RunnerError(f"Codex {label} command failed")
        observations[label] = completed.stdout
    version_text = _fixed_text(observations["version"], "Codex version")
    version = _version_value(version_text)
    if _version_tuple(version) < MINIMUM_PERMISSION_PROFILE_VERSION:
        raise RunnerError("Codex is too old to enforce restricted filesystem reads")
    return {
        "command": command,
        "launcher_sha256": _sha(launcher_raw),
        "help_sha256": _sha(observations["help"]),
        "version": version,
        "identity_sha256": _sha(
            _canonical(
                {
                    "launcher_sha256": _sha(launcher_raw),
                    "help_sha256": _sha(observations["help"]),
                    "version": version_text,
                }
            )
        ),
    }


def _instruction_digest(workspace: Path) -> str:
    records, _ = _CASE._tree_records(workspace)
    selected = [
        record
        for record in records
        if Path(record[0]).name.casefold() in {"agents.md", "claude.md", "skill.md"}
        or record[0].casefold().startswith((".agents/", ".codex/skills/", "skills/"))
    ]
    return _sha(_canonical(selected))


def _environment_digest(runner: dict[str, Any]) -> str:
    present_credentials = [
        name for name in ("CODEX_API_KEY", "OPENAI_API_KEY") if bool(os.environ.get(name))
    ]
    relevant = {
        name: _sha(os.environ[name].encode("utf-8"))
        for name in ("CODEX_HOME", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")
        if name in os.environ
    }
    return _sha(
        _canonical(
            {
                "system": platform.system().casefold(),
                "release": platform.release(),
                "machine": platform.machine().casefold(),
                "python": platform.python_version(),
                "runner_sha256": runner["identity_sha256"],
                "credential_names_present": present_credentials,
                "relevant_value_digests": relevant,
            }
        )
    )


def build_codex_command(
    runner: dict[str, Any],
    workspace: Path,
    result_path: Path,
    model: str,
    reasoning: str,
    *,
    workspace_edit: bool,
    network: bool,
) -> list[str]:
    if not isinstance(model, str) or MODEL_ID.fullmatch(model) is None:
        raise RunnerError("model id contains unsupported characters")
    if reasoning not in REASONING:
        raise RunnerError("unsupported reasoning effort")
    launcher_path = Path(runner["command"][0]).absolute()
    workspace_access = "write" if workspace_edit else "read"
    workspace_rules = {
        ".": workspace_access,
        ".git": "read",
        ".agents": "read",
        ".codex": "read",
    }
    filesystem_items: list[tuple[str, str | dict[str, str]]] = [
        (":root", "deny"),
        (":minimal", "read"),
        (":tmpdir", "deny"),
        (":slash_tmp", "deny"),
        (":workspace_roots", workspace_rules),
        (str(launcher_path), "read"),
    ]

    def toml_value(value: str | dict[str, str]) -> str:
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=True)
        return "{" + ",".join(
            f"{json.dumps(key, ensure_ascii=True)}={json.dumps(item, ensure_ascii=True)}"
            for key, item in value.items()
        ) + "}"

    filesystem_value = "{" + ",".join(
        f"{json.dumps(key, ensure_ascii=True)}={toml_value(value)}"
        for key, value in filesystem_items
    ) + "}"
    return [
        *runner["command"],
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--config",
        'approval_policy="never"',
        "--config",
        'default_permissions="project-eval"',
        "--config",
        f"permissions.project-eval.filesystem={filesystem_value}",
        "--config",
        f"permissions.project-eval.network.enabled={'true' if network else 'false'}",
        "--config",
        'web_search="disabled"',
        "--config",
        'shell_environment_policy.inherit="core"',
        "--config",
        "shell_environment_policy.ignore_default_excludes=false",
        "--config",
        "agents.enabled=false",
        "--cd",
        str(workspace),
        "--skip-git-repo-check",
        "--json",
        "--color",
        "never",
        "--output-last-message",
        str(result_path),
        "--model",
        model,
        "--config",
        f'model_reasoning_effort="{reasoning}"',
        "-",
    ]


def _runner_environment() -> dict[str, str]:
    """Keep only host settings required for Codex startup and authentication."""
    allowed = {
        "PATH",
        "HOME",
        "USERPROFILE",
        "CODEX_HOME",
        "CODEX_API_KEY",
        "OPENAI_API_KEY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "LANG",
        "LC_ALL",
        "TERM",
    }
    environment = {name: value for name, value in os.environ.items() if name in allowed}
    environment.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
    )
    return environment


@dataclass
class BudgetLedger:
    max_invocations: int
    max_seconds: int
    max_tokens: int | None
    max_cost_usd: float | None
    invocations: int = 0
    duration_ms: int = 0
    tokens: int | None = 0
    cost_usd: float | None = None
    exhausted_reason: str | None = None

    @classmethod
    def from_profile(cls, profile: dict[str, Any]) -> "BudgetLedger":
        return cls(
            max_invocations=profile["max_invocations"],
            max_seconds=profile["max_seconds"],
            max_tokens=profile["max_tokens"],
            max_cost_usd=profile["max_cost_usd"],
        )

    def claim(self) -> int:
        if self.exhausted_reason is not None:
            raise RunnerError(f"run budget exhausted: {self.exhausted_reason}")
        if self.invocations >= self.max_invocations:
            self.exhausted_reason = "invocations"
            raise RunnerError("run budget exhausted: invocations")
        remaining_ms = self.max_seconds * 1000 - self.duration_ms
        if remaining_ms <= 0:
            self.exhausted_reason = "time"
            raise RunnerError("run budget exhausted: time")
        self.invocations += 1
        return max(1, (remaining_ms + 999) // 1000)

    def record(self, *, duration_ms: int, tokens: int | None, cost_usd: float | None) -> None:
        self.duration_ms += max(0, duration_ms)
        if self.duration_ms > self.max_seconds * 1000:
            self.exhausted_reason = "time"
        if self.tokens is not None and tokens is not None:
            self.tokens += tokens
        else:
            self.tokens = None
        if self.max_tokens is not None and self.tokens is not None and self.tokens > self.max_tokens:
            self.exhausted_reason = "tokens"
        if cost_usd is not None:
            self.cost_usd = (self.cost_usd or 0.0) + cost_usd
        if (
            self.max_cost_usd is not None
            and self.cost_usd is not None
            and self.cost_usd > self.max_cost_usd
        ):
            self.exhausted_reason = "cost"


def build_profile_schedule(
    suite: dict[str, Any], profile_name: str, capabilities: set[str]
) -> dict[str, Any]:
    """Build the complete bounded case/repetition plan before any model call."""
    profiles = suite.get("profiles")
    if not isinstance(profiles, dict) or profile_name not in profiles:
        raise RunnerError(f"suite does not contain profile {profile_name!r}")
    profile = profiles[profile_name]
    cases = suite.get("cases")
    if not isinstance(cases, list):
        raise RunnerError("suite cases are malformed")
    by_id = {
        item.get("case_id"): item
        for item in cases
        if isinstance(item, dict) and isinstance(item.get("case_id"), str)
    }
    planned: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for case_id in profile["case_ids"]:
        case = by_id.get(case_id)
        if case is None:
            raise RunnerError(f"profile names unknown case {case_id!r}")
        eligibility = _CASE.platform_eligibility(case, capabilities)
        if eligibility["status"] != "eligible":
            excluded.append(
                {
                    "case_id": case_id,
                    "status": eligibility["status"],
                    "missing_capabilities": eligibility["missing_capabilities"],
                }
            )
            continue
        for repetition in range(1, profile["repetitions"] + 1):
            planned.append({"case_id": case_id, "repetition": repetition})
    if len(planned) > profile["max_invocations"]:
        raise RunnerError("profile invocation budget cannot cover its eligible schedule")
    return {
        "profile": profile_name,
        "planned": planned,
        "excluded": excluded,
        "max_invocations": profile["max_invocations"],
        "retry_capacity": profile["max_invocations"] - len(planned),
    }


class _WindowsJob:
    _KILL_ON_CLOSE = 0x00002000
    _EXTENDED_LIMIT_INFORMATION = 9
    _BASIC_ACCOUNTING_INFORMATION = 1

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_ulonglong), ("WriteOperationCount", ctypes.c_ulonglong), ("OtherOperationCount", ctypes.c_ulonglong), ("ReadTransferCount", ctypes.c_ulonglong), ("WriteTransferCount", ctypes.c_ulonglong), ("OtherTransferCount", ctypes.c_ulonglong)]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimitInformation), ("IoInfo", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        class BasicAccountingInformation(ctypes.Structure):
            _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong), ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong), ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD), ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._accounting_type = BasicAccountingInformation
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        self._kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._kernel32.TerminateJobObject.restype = wintypes.BOOL
        self._kernel32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID]
        self._kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._handle = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise RunnerError(f"cannot create Windows job: {ctypes.WinError(ctypes.get_last_error())}")
        limits = ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = self._KILL_ON_CLOSE
        if not self._kernel32.SetInformationJobObject(self._handle, self._EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise RunnerError(f"cannot configure Windows job: {error}")

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        raw_handle = getattr(process, "_handle", None)
        if raw_handle is None or not self._kernel32.AssignProcessToJobObject(self._handle, self._wintypes.HANDLE(int(raw_handle))):
            raise RunnerError(f"cannot assign Codex to Windows job: {self._ctypes.WinError(self._ctypes.get_last_error())}")

    def _active_processes(self) -> int:
        accounting = self._accounting_type()
        if not self._kernel32.QueryInformationJobObject(self._handle, self._BASIC_ACCOUNTING_INFORMATION, self._ctypes.byref(accounting), self._ctypes.sizeof(accounting), None):
            raise RunnerError(f"cannot query Windows job: {self._ctypes.WinError(self._ctypes.get_last_error())}")
        return accounting.ActiveProcesses

    def terminate_and_wait(self) -> None:
        if not self._handle or self._active_processes() == 0:
            return
        if not self._kernel32.TerminateJobObject(self._handle, 1):
            raise RunnerError(f"cannot terminate Windows job: {self._ctypes.WinError(self._ctypes.get_last_error())}")
        deadline = time.monotonic() + 30
        while self._active_processes() != 0:
            if time.monotonic() >= deadline:
                raise RunnerError("Windows job still has active processes after termination")
            time.sleep(0.05)

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


_WINDOWS_GATE = (
    "import os,subprocess,sys; gate=os.read(0,3); gate==b'GO\\n' or sys.exit(125); "
    "completed=subprocess.run(sys.argv[1:]); sys.exit(completed.returncode)"
)


def _terminate_posix(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        try:
            process.kill()
            process.wait(timeout=30)
        finally:
            raise RunnerError(f"cannot terminate Codex process group: {exc}") from exc
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise RunnerError("Codex process tree did not exit after termination") from exc


def _read_capture(path: Path, label: str) -> bytes:
    try:
        _, raw = read_regular(path, MAX_CAPTURE_BYTES, require_single_link=True)
    except SafetyError as exc:
        raise RunnerError(f"cannot read {label}: {exc}") from exc
    return raw


def _parse_events(raw: bytes) -> dict[str, Any]:
    total_tokens: int | None = None
    command_ids: set[str] = set()
    commands = 0
    network_observed = False
    failure_observed = False
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line.decode("utf-8", "strict"), object_pairs_hook=_CASE._duplicate_object)
            _CASE._bounded_json(event, f"Codex event line {line_number}")
        except (UnicodeDecodeError, json.JSONDecodeError, _CASE.CaseError, RecursionError) as exc:
            raise RunnerError(f"invalid Codex JSONL event at line {line_number}: {exc}") from exc
        if not isinstance(event, dict):
            raise RunnerError(f"Codex JSONL event at line {line_number} is not an object")
        event_type = event.get("type")
        if event_type in {"error", "turn.failed"}:
            failure_observed = True
        if event_type == "turn.completed":
            usage = event.get("usage")
            if isinstance(usage, dict):
                value = usage.get("total_tokens")
                if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1_000_000_000:
                    total_tokens = (total_tokens or 0) + value
                    if total_tokens > 1_000_000_000:
                        raise RunnerError("Codex token measurement exceeds its supported range")
        item = event.get("item") if event_type in {"item.started", "item.updated", "item.completed"} else event
        if isinstance(item, dict):
            item_type = item.get("type")
            if item_type == "command_execution":
                identity = item.get("id")
                key = identity if isinstance(identity, str) and identity else _sha(_canonical(item))
                if key not in command_ids:
                    command_ids.add(key)
                    commands += 1
            if item_type in {"web_search", "web_search_call", "browser", "mcp_tool_call"}:
                network_observed = True
    return {
        "tokens": {"value": total_tokens, "provenance": "runner_reported" if total_tokens is not None else "unavailable"},
        "commands": commands,
        "network_observed": network_observed,
        "failure_observed": failure_observed,
    }


def _open_capture(path: Path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(path, flags, 0o600)
    return os.fdopen(descriptor, "wb", closefd=True)


def _run_process(
    command: list[str],
    prompt: bytes,
    workspace: Path,
    events_path: Path,
    errors_path: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise RunnerError("attempt timeout is outside the supported range")
    started = time.monotonic()
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    timed_out = False
    capture_exceeded = False
    process: subprocess.Popen[bytes] | None = None
    windows_job = _WindowsJob() if os.name == "nt" else None
    try:
        with _open_capture(events_path) as events, _open_capture(errors_path) as errors:
            if windows_job is not None:
                launched = [sys.executable, "-I", "-S", "-c", _WINDOWS_GATE, *command]
                input_bytes = b"GO\n" + prompt
                isolation: dict[str, Any] = {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
            else:
                launched = command
                input_bytes = prompt
                isolation = {"start_new_session": True}
            process = subprocess.Popen(
                launched,
                cwd=workspace,
                env=_runner_environment(),
                stdin=subprocess.PIPE,
                stdout=events,
                stderr=errors,
                **isolation,
            )
            if windows_job is not None:
                try:
                    windows_job.assign(process)
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
            if process.stdin is None:
                raise RunnerError("Codex process has no stdin")
            try:
                process.stdin.write(input_bytes)
                process.stdin.close()
            except BrokenPipeError:
                pass
            deadline = started + timeout_seconds
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                if os.fstat(events.fileno()).st_size > MAX_CAPTURE_BYTES or os.fstat(errors.fileno()).st_size > MAX_CAPTURE_BYTES:
                    capture_exceeded = True
                    break
                time.sleep(0.05)
            if windows_job is not None:
                windows_job.terminate_and_wait()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired as exc:
                    raise RunnerError("Codex process did not exit after job termination") from exc
            else:
                _terminate_posix(process)
    except BaseException:
        if process is not None and process.poll() is None:
            if windows_job is not None:
                windows_job.terminate_and_wait()
            else:
                _terminate_posix(process)
        raise
    finally:
        if windows_job is not None:
            windows_job.close()
    duration_ms = max(0, round((time.monotonic() - started) * 1000))
    if capture_exceeded:
        raise RunnerError("Codex event or error capture exceeded its size limit")
    return {
        "exit_code": process.returncode if process is not None else None,
        "timed_out": timed_out,
        "started_at": started_at,
        "duration_ms": duration_ms,
    }


def _prompt(task: str, *, network: bool) -> bytes:
    if not isinstance(task, str) or not task.strip():
        raise RunnerError("case task must be nonempty text")
    policy = "Network access is explicitly available for this case." if network else "Do not use network, web search, remote tools, apps, or external services."
    text = f"""Work only in the current disposable evaluation workspace.
Do not inspect paths outside it. Do not request approvals or extra permissions.
{policy}
Complete the following task. Keep your final response concise.

{task}
"""
    raw = text.encode("utf-8")
    if len(raw) > MAX_PROMPT_BYTES:
        raise RunnerError("runner prompt exceeds its size limit")
    return raw


def _configuration(
    runner: dict[str, Any],
    workspace: Path,
    command: list[str],
    model: str,
    reasoning: str,
    network: bool,
    effects: list[str],
) -> dict[str, Any]:
    instruction_sha = _instruction_digest(workspace)
    environment_sha = _environment_digest(runner)
    argv_template = [
        "<launcher>"
        if index == 0
        else "<workspace>"
        if value == str(workspace)
        else "<host-result>"
        if index and command[index - 1] == "--output-last-message"
        else value
        for index, value in enumerate(command)
    ]
    value = {
        "runner": "codex-exec",
        "runner_version": runner["version"],
        "agent": "codex",
        "model": model,
        "reasoning": reasoning,
        "platform": {"linux": "linux", "darwin": "macos", "windows": "windows"}.get(platform.system().casefold(), "linux"),
        "environment_sha256": environment_sha,
        "adapter_sha256": adapter_sha256(),
        "launcher_sha256": runner["identity_sha256"],
        "argv_sha256": _sha(_canonical(argv_template)),
        "instructions_sha256": instruction_sha,
        "network": network,
        "effects": sorted(effects),
    }
    value["configuration_sha256"] = _sha(_canonical(value))
    return value


def run_codex_attempt(
    fixture: Path,
    case: dict[str, Any],
    prepared_value: Any,
    profile: dict[str, Any],
    task: str,
    host_root: Path,
    model: str,
    reasoning: str,
    ledger: BudgetLedger,
    *,
    allow_network: bool = False,
    allow_hidden_grader: bool = False,
    allow_project_checks: bool = False,
    runner: dict[str, Any] | None = None,
) -> dict[str, Any]:
    control, prepared, workspace = _CASE.validate_prepared_case(fixture, case, prepared_value)
    if not host_root.is_absolute():
        raise RunnerError("host root must be absolute")
    host_root = host_root.absolute()
    workspace = workspace.absolute()
    if host_root == workspace or host_root in workspace.parents or workspace in host_root.parents:
        raise RunnerError("host root and evaluated workspace must be separate")
    if bool(profile["network"]) != bool(allow_network):
        if profile["network"]:
            raise RunnerError("networked profile requires explicit network authorization")
        raise RunnerError("network authorization cannot expand an offline profile")
    effects = list(profile["effects"])
    if "workspace_edit" not in effects and case["kind"] == "implementation":
        raise RunnerError("implementation case profile must permit workspace_edit")
    timeout = ledger.claim()
    ensure_private_directory(host_root)
    invocation = host_root / f"invocation-{os.getpid()}-{time.monotonic_ns()}"
    ensure_private_directory(invocation)
    try:
        events_path = invocation / "events.jsonl"
        errors_path = invocation / "stderr.bin"
        result_path = invocation / "last-message.txt"
        before = _CASE.tree_digest(workspace)
        if before != prepared["workspace_initial_sha256"]:
            raise RunnerError("prepared workspace changed before the Codex attempt")
        active_runner = runner or discover_codex()
        command = build_codex_command(
            active_runner,
            workspace,
            result_path,
            model,
            reasoning,
            workspace_edit="workspace_edit" in effects,
            network=allow_network,
        )
        configuration = _configuration(
            active_runner, workspace, command, model, reasoning, allow_network, effects
        )
        raw_prompt = _prompt(task, network=allow_network)
        execution = _run_process(command, raw_prompt, workspace, events_path, errors_path, timeout)
        events_raw = _read_capture(events_path, "Codex event capture")
        errors_raw = _read_capture(errors_path, "Codex error capture")
        event_summary = _parse_events(events_raw)
        final_raw: bytes | None = None
        if result_path.exists():
            try:
                _, final_raw = read_regular(result_path, MAX_CAPTURE_BYTES, require_single_link=True)
            except SafetyError as exc:
                raise RunnerError(f"cannot bind Codex final message: {exc}") from exc
        after = _CASE.tree_digest(workspace)
        final_instruction_sha = _instruction_digest(workspace)
        changed = after != before
        effect_errors: list[str] = []
        if changed and "workspace_edit" not in effects:
            effect_errors.append("workspace changed without workspace_edit authority")
        if event_summary["commands"] and "command_execution" not in effects:
            effect_errors.append("commands ran without command_execution authority")
        if event_summary["network_observed"] and not allow_network:
            effect_errors.append("network-capable tool activity was observed in an offline profile")
        if final_instruction_sha != configuration["instructions_sha256"]:
            effect_errors.append("frozen agent instructions changed during the attempt")
        runner_failed = bool(
            execution["timed_out"]
            or execution["exit_code"] != 0
            or event_summary["failure_observed"]
            or final_raw is None
        )
        ledger.record(
            duration_ms=execution["duration_ms"],
            tokens=event_summary["tokens"]["value"],
            cost_usd=None,
        )
        budget_error = ledger.exhausted_reason
        unobservable_budgets = []
        if profile["max_tokens"] is not None and event_summary["tokens"]["value"] is None:
            unobservable_budgets.append("tokens")
        if profile["max_cost_usd"] is not None:
            unobservable_budgets.append("cost")
        status = "completed"
        if execution["timed_out"]:
            status = "timed_out"
        elif runner_failed or effect_errors:
            status = "failed"
        elif budget_error is not None:
            status = "budget_exceeded"
        error_category = None
        if status == "timed_out":
            error_category = "timeout"
        elif effect_errors:
            error_category = "effect_violation"
        elif status == "budget_exceeded":
            error_category = "budget_exceeded"
        elif runner_failed:
            error_category = "runner_failure"
        result = {
            "schema_version": "project-eval-runner-attempt/v1",
            "case_id": case["case_id"],
            "status": status,
            "error_category": error_category,
            "exit_code": execution["exit_code"],
            "timed_out": execution["timed_out"],
            "duration_ms": {"value": execution["duration_ms"], "provenance": "host_observed"},
            "tokens": event_summary["tokens"],
            "cost_microusd": {"value": None, "provenance": "unavailable"},
            "commands": {"value": event_summary["commands"], "provenance": "host_observed"},
            "workspace_before_sha256": before,
            "workspace_after_sha256": after,
            "workspace_changed": changed,
            "preparation_sha256": prepared["preparation_sha256"],
            "fixture_sha256": prepared["fixture_sha256"],
            "control_sha256": prepared["control_sha256"],
            "configuration": configuration,
            "prompt_sha256": _sha(raw_prompt),
            "result_sha256": _sha(final_raw) if final_raw is not None else None,
            "events_sha256": _sha(events_raw),
            "errors_sha256": _sha(errors_raw),
            "effect_errors": effect_errors,
            "budget_exhausted": budget_error,
            "unobservable_budgets": unobservable_budgets,
        }
        result["attempt_sha256"] = _sha(_canonical(result))
        return result
    finally:
        shutil.rmtree(invocation, ignore_errors=False)


def grade_recorded_case(
    fixture: Path,
    case: dict[str, Any],
    prepared_value: Any,
    *,
    allow_hidden_grader: bool = False,
    allow_project_checks: bool = False,
) -> dict[str, Any]:
    """Agent-neutral grading path; validates actual files and claims no runner support."""
    result = _CASE.grade_case(
        fixture,
        case,
        prepared_value,
        allow_hidden_grader=allow_hidden_grader,
        allow_project_checks=allow_project_checks,
    )
    return {
        "schema_version": "project-eval-recorded-grade/v1",
        "runner": "recorded-output",
        "direct_runner_compatibility": [],
        "grade": result,
    }
