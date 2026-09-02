#!/usr/bin/env python3
"""Finalize, validate, and render verification-harness audit results."""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import unicodedata
from typing import Any


SCHEMA_VERSION = "1.0.0"
SKILL_REVISION = "verification-harness-audit@1.0.0"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 100
MAX_RECOMMENDATIONS = 2000
SAFE_POSIX_DIR_FD = (
    os.name == "posix"
    and hasattr(os, "O_NOFOLLOW")
    and hasattr(os, "O_DIRECTORY")
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
)

CONTROL = re.compile(r"[\x00-\x1f\x7f]")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RFC3339 = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?:\.[0-9]+)?(?P<zone>Z|(?P<sign>[+-])(?P<offset_hour>[0-9]{2}):(?P<offset_minute>[0-9]{2}))$"
)
TARGET_ID = re.compile(r"^T[0-9]{3,6}$")
CHAIN_ID = re.compile(r"^G[0-9]{3,6}$")
COMMAND_ID = re.compile(r"^C[0-9]{3,6}$")
SOURCE_ID = re.compile(r"^S[0-9]{3,6}$")
RECOMMENDATION_ID = re.compile(r"^R[0-9]{3,6}$")

TARGET_KINDS = {"part", "file", "directory", "project"}
FOCUS_KINDS = {
    "line_range",
    "symbol",
    "test_case",
    "ci_job",
    "configuration_section",
    "command",
    "other",
}
INSPECTION_KINDS = {
    "text",
    "binary",
    "non_utf8",
    "oversized",
    "unreadable",
    "not_inspected",
}
TRACKING_KINDS = {"tracked", "untracked", "ignored", "unknown"}
SOURCE_KINDS = {"skill", "user_global", "repository"}
AUTHORITY_KINDS = {"not_requested", "denied", "caller", "user_global"}
COMMAND_OUTCOMES = {"not_run", "passed", "failed", "timed_out", "refused"}
EVIDENCE_SOURCE_KINDS = {"timing", "failure", "history", "other"}
FRESHNESS = {"fresh", "stale", "unknown"}
STRENGTHS = ("essential", "strong", "moderate", "optional")
IMPACTS = ("critical", "high", "medium", "low")
CONFIDENCES = {"high", "medium", "low"}
DECISIONS = {"ready", "decision_required"}
CLAIMS = {"observed_defect", "inferred_risk", "improvement_opportunity"}
BASES = {
    "specification",
    "supported_behavior",
    "public_contract",
    "compatibility_promise",
    "safety_boundary",
    "required_workflow",
    "new_policy",
    "uncertain",
}
EXISTING_BASES = BASES - {"new_policy", "uncertain"}
RECOMMENDATION_KINDS = {
    "missing_coverage",
    "weak_assertion",
    "disconnected_check",
    "late_feedback",
    "slow_feedback",
    "flakiness",
    "nondeterminism",
    "unsafe_mutation",
    "isolation",
    "redundancy",
    "platform_gap",
    "failure_visibility",
    "discoverability",
    "local_ci_drift",
    "maintenance",
    "other",
}
ACTIONS = {
    "add",
    "strengthen",
    "wire",
    "move_tier",
    "stabilize",
    "isolate",
    "deduplicate",
    "remove",
    "document",
    "other",
}
EVIDENCE_KINDS = {
    "harness",
    "test",
    "code",
    "specification",
    "documentation",
    "configuration",
    "guidance",
    "command",
    "history",
    "caller_supplied",
    "reasoning",
}
CURRENT_TIERS = {
    "routine",
    "pre_merge",
    "integration",
    "release",
    "manual",
    "unknown",
    "absent",
}
RECOMMENDED_TIERS = {
    "routine",
    "pre_merge",
    "integration",
    "release",
    "manual",
    "none",
    "unknown",
}
LIMITATION_CODES = {
    "scope_truncated",
    "ignored_path",
    "link_skipped",
    "target_unreadable",
    "part_unreadable",
    "inventory_incomplete",
    "guidance_unreadable",
    "guidance_budget",
    "context_unavailable",
    "evidence_missing",
    "conflicting_evidence",
    "verification_not_authorized",
    "verification_unavailable",
    "verification_failed",
    "delegation_unavailable",
    "budget_exhausted",
    "other",
}
RESOLVER_LIMITATION_CODES = {
    "scope_truncated",
    "ignored_path",
    "link_skipped",
    "target_unreadable",
    "part_unreadable",
    "inventory_incomplete",
    "guidance_unreadable",
    "guidance_budget",
    "context_unavailable",
}
INVENTORY_LIMITATION_CODES = {
    "scope_truncated",
    "target_unreadable",
    "part_unreadable",
    "inventory_incomplete",
}


class ResultError(ValueError):
    """Raised when context, draft, result, or I/O violates the contract."""


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResultError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _assert_bounded_json(value: Any, label: str) -> None:
    pending: list[tuple[Any, int, bool]] = [(value, 0, False)]
    active: set[int] = set()
    while pending:
        current, depth, leaving = pending.pop()
        if not isinstance(current, (dict, list)):
            continue
        identity = id(current)
        if leaving:
            active.remove(identity)
            continue
        if identity in active:
            raise ResultError(f"{label} contains a circular value")
        if depth >= MAX_JSON_DEPTH:
            raise ResultError(
                f"{label} exceeds the {MAX_JSON_DEPTH}-level nesting limit"
            )
        active.add(identity)
        pending.append((current, depth, True))
        children = current.values() if isinstance(current, dict) else current
        pending.extend((child, depth + 1, False) for child in children)


def _canonical_json(value: Any) -> bytes:
    _assert_bounded_json(value, "canonical value")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (RecursionError, UnicodeEncodeError, ValueError) as exc:
        raise ResultError(f"canonical value is not bounded UTF-8 JSON: {exc}") from exc
    if len(encoded) > MAX_JSON_BYTES:
        raise ResultError("canonical value exceeds the JSON size ceiling")
    return encoded


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _filesystem_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or len(value) > 8192:
        raise ResultError(f"{label} must be a non-empty path of at most 8192 characters")
    if CONTROL.search(value):
        raise ResultError(f"{label} must not contain control characters")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ResultError(f"{label} must be valid UTF-8") from exc
    return Path(value)


def _is_link_like(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    return bool(flag and attributes & flag)


def _assert_no_link_components(path: Path, *, include_final: bool) -> None:
    absolute = path.absolute()
    parts = absolute.parts[1:] if include_final else absolute.parts[1:-1]
    current = Path(absolute.anchor)
    for part in parts:
        current /= part
        if _is_link_like(current):
            raise ResultError(f"refusing link-like path component: {current}")


def _file_signature(metadata: os.stat_result) -> tuple[Any, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        getattr(metadata, "st_mtime_ns", metadata.st_mtime),
        getattr(metadata, "st_ctime_ns", metadata.st_ctime),
    )


def _file_open_binding_signature(metadata: os.stat_result) -> tuple[Any, ...]:
    """Return metadata that must agree between path and handle stat APIs."""
    return (
        stat.S_IFMT(metadata.st_mode),
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
    )


def _file_identity(metadata: os.stat_result) -> tuple[int, int]:
    return (metadata.st_dev, metadata.st_ino)


@contextlib.contextmanager
def _posix_bound_parent(path: Path):
    """Yield a directory fd and basename without following ancestor links."""
    if not SAFE_POSIX_DIR_FD:
        raise ResultError("safe descriptor-relative path handling is unavailable")
    absolute = path.absolute()
    if not absolute.name:
        raise ResultError(f"path must name a file: {path}")
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(absolute.anchor, flags)
        current = Path(absolute.anchor)
        for part in absolute.parent.parts[1:]:
            current /= part
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except OSError as exc:
                raise ResultError(f"cannot bind safe parent directory {current}: {exc}") from exc
            os.close(descriptor)
            descriptor = child
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise ResultError(f"output/input parent is not a directory: {current}")
        yield descriptor, absolute.name, absolute
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _windows_extended_path(path: Path) -> str:
    value = str(path.absolute())
    if value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def _windows_create_handle(
    path: Path,
    *,
    access: int,
    creation: int,
    flags: int,
) -> int:
    if os.name != "nt":
        raise ResultError("Windows handle operation requested on another platform")
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        _windows_extended_path(path),
        access,
        0x00000001 | 0x00000002,
        None,
        creation,
        flags,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        error = ctypes.get_last_error()
        raise OSError(error, ctypes.FormatError(error), str(path))
    return int(handle)


def _windows_close_handle(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    close_handle(handle)


def _windows_handle_path(handle: int) -> Path:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    get_final_path.restype = wintypes.DWORD
    required = get_final_path(handle, None, 0, 0)
    if required == 0:
        error = ctypes.get_last_error()
        raise OSError(error, ctypes.FormatError(error))
    buffer = ctypes.create_unicode_buffer(required + 1)
    written = get_final_path(handle, buffer, len(buffer), 0)
    if written == 0 or written >= len(buffer):
        error = ctypes.get_last_error()
        raise OSError(error, ctypes.FormatError(error))
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _windows_path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path.absolute())))


def _windows_relative_handle(
    parent_handle: int,
    name: str,
    *,
    access: int,
    creation: int,
    display_path: Path,
) -> int:
    """Open or create one non-link file relative to a bound parent handle."""
    import ctypes
    from ctypes import wintypes

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.USHORT),
            ("maximum_length", wintypes.USHORT),
            ("buffer", wintypes.LPWSTR),
        ]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.ULONG),
            ("root_directory", wintypes.HANDLE),
            ("object_name", ctypes.POINTER(UnicodeString)),
            ("attributes", wintypes.ULONG),
            ("security_descriptor", wintypes.LPVOID),
            ("security_quality_of_service", wintypes.LPVOID),
        ]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [
            ("status", ctypes.c_void_p),
            ("information", ctypes.c_void_p),
        ]

    disposition = {1: 2, 3: 1}.get(creation)
    if disposition is None:
        raise ResultError(f"unsupported Windows create disposition: {creation}")
    encoded_length = len(name.encode("utf-16-le"))
    name_buffer = ctypes.create_unicode_buffer(name)
    object_name = UnicodeString(
        encoded_length,
        encoded_length + 2,
        ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = ObjectAttributes(
        ctypes.sizeof(ObjectAttributes),
        wintypes.HANDLE(parent_handle),
        ctypes.pointer(object_name),
        0x00000040,
        None,
        None,
    )
    status_block = IoStatusBlock()
    handle = wintypes.HANDLE()
    ntdll = ctypes.WinDLL("ntdll")
    nt_create_file = ntdll.NtCreateFile
    nt_create_file.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.ULONG,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatusBlock),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]
    nt_create_file.restype = wintypes.LONG
    status = nt_create_file(
        ctypes.byref(handle),
        access | 0x00100000,
        ctypes.byref(attributes),
        ctypes.byref(status_block),
        None,
        0x00000080,
        0x00000001 | 0x00000002,
        disposition,
        0x00000020 | 0x00000040 | 0x00200000,
        None,
        0,
    )
    if status < 0:
        rtl_error = ntdll.RtlNtStatusToDosError
        rtl_error.argtypes = [wintypes.LONG]
        rtl_error.restype = wintypes.ULONG
        error = int(rtl_error(status))
        raise OSError(error, ctypes.FormatError(error), str(display_path))
    return int(handle.value)


def _windows_handle_attributes(handle: int) -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    class FileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation_time", FileTime),
            ("access_time", FileTime),
            ("write_time", FileTime),
            ("volume_serial", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    information = FileInformation()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInformation)]
    get_information.restype = wintypes.BOOL
    if not get_information(handle, ctypes.byref(information)):
        error = ctypes.get_last_error()
        raise OSError(error, ctypes.FormatError(error))
    return int(information.attributes), int(information.links)


@contextlib.contextmanager
def _windows_locked_parent(path: Path):
    """Verify the parent chain and yield its bound final directory handle."""
    supplied = path.absolute()
    _assert_no_link_components(supplied, include_final=False)
    try:
        absolute = supplied.parent.resolve(strict=True) / supplied.name
    except OSError as exc:
        raise ResultError(f"cannot resolve safe Windows parent for {path}: {exc}") from exc
    if not absolute.name:
        raise ResultError(f"path must name a file: {path}")
    current = Path(absolute.anchor)
    directories = [current]
    for part in absolute.parent.parts[1:]:
        current /= part
        directories.append(current)
    handles: list[int] = []
    try:
        for directory in directories:
            handle = _windows_create_handle(
                directory,
                access=0x00000080,
                creation=3,
                flags=0x02000000 | 0x00200000,
            )
            try:
                attributes, _ = _windows_handle_attributes(handle)
            except Exception:
                _windows_close_handle(handle)
                raise
            if attributes & 0x00000400 or not attributes & 0x00000010:
                _windows_close_handle(handle)
                raise ResultError(f"refusing link-like or non-directory parent: {directory}")
            handles.append(handle)
        bound_parent = _windows_handle_path(handles[-1])
        if _windows_path_key(bound_parent) != _windows_path_key(absolute.parent):
            raise ResultError(
                f"Windows parent changed while being bound: {absolute.parent}"
            )
        yield absolute, handles[-1]
    finally:
        for handle in reversed(handles):
            _windows_close_handle(handle)


def _windows_file_descriptor(
    path: Path,
    *,
    parent_handle: int,
    access: int,
    creation: int,
    descriptor_flags: int,
) -> int:
    import msvcrt

    handle = _windows_relative_handle(
        parent_handle,
        path.name,
        access=access,
        creation=creation,
        display_path=path,
    )
    try:
        attributes, _ = _windows_handle_attributes(handle)
        if attributes & 0x00000400 or attributes & 0x00000010:
            raise ResultError(f"refusing link-like or non-file path: {path}")
        return msvcrt.open_osfhandle(handle, descriptor_flags)
    except Exception:
        _windows_close_handle(handle)
        raise


@contextlib.contextmanager
def _bound_read_descriptor(path: Path, label: str):
    """Open a regular file while binding every path component to one identity."""
    if os.name == "nt":
        with _windows_locked_parent(path) as (absolute, parent_handle):
            try:
                preflight = absolute.lstat()
                descriptor = _windows_file_descriptor(
                    absolute,
                    parent_handle=parent_handle,
                    access=0x80000000,
                    creation=3,
                    descriptor_flags=os.O_RDONLY | getattr(os, "O_BINARY", 0),
                )
            except OSError as exc:
                raise ResultError(f"cannot open {label} {path}: {exc}") from exc
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise ResultError(f"{label} must be a regular file: {path}")
                if _file_open_binding_signature(metadata) != (
                    _file_open_binding_signature(preflight)
                ):
                    raise ResultError(f"{label} changed before being opened: {path}")
                yield descriptor, metadata
            finally:
                os.close(descriptor)
        return
    with _posix_bound_parent(path) as (parent, name, absolute):
        try:
            preflight = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except OSError as exc:
            raise ResultError(f"cannot inspect {label} {absolute}: {exc}") from exc
        if stat.S_ISLNK(preflight.st_mode):
            raise ResultError(f"refusing link-like {label}: {absolute}")
        if not stat.S_ISREG(preflight.st_mode):
            raise ResultError(f"{label} must be a regular file: {absolute}")
        flags = (
            os.O_RDONLY
            | os.O_NOFOLLOW
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            descriptor = os.open(name, flags, dir_fd=parent)
        except OSError as exc:
            raise ResultError(f"cannot open {label} {absolute}: {exc}") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ResultError(f"{label} must be a regular file: {absolute}")
            if _file_open_binding_signature(metadata) != (
                _file_open_binding_signature(preflight)
            ):
                raise ResultError(f"{label} changed before being opened: {absolute}")
            yield descriptor, metadata
        finally:
            os.close(descriptor)


def _read_json(source: str) -> Any:
    if source == "-":
        raw = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
        label = "stdin"
    else:
        path = _filesystem_path(source, "JSON input path")
        with _bound_read_descriptor(path, "JSON input") as (descriptor, metadata):
            if metadata.st_size > MAX_JSON_BYTES:
                raise ResultError(f"JSON input is too large: {source}")
            signature = _file_signature(metadata)
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, min(65536, MAX_JSON_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_JSON_BYTES:
                    raise ResultError(f"JSON input is too large: {source}")
            final = os.fstat(descriptor)
            final_signature = _file_signature(final)
            if signature != final_signature:
                raise ResultError(f"JSON input changed while being read: {source}")
            raw = b"".join(chunks)
            label = source
    if len(raw) > MAX_JSON_BYTES:
        raise ResultError(f"JSON input is too large: {label}")
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ResultError(f"JSON input is not UTF-8: {label}") from exc
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicates)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ResultError(f"invalid JSON: {exc}") from exc
    _assert_bounded_json(value, "JSON input")
    return value


def _object(value: Any, label: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ResultError(f"{label} must be an object")
    missing = keys - set(value)
    extra = set(value) - keys
    if missing:
        raise ResultError(f"{label} is missing fields: {sorted(missing)}")
    if extra:
        raise ResultError(f"{label} has unknown fields: {sorted(extra)}")
    return value


def _array(
    value: Any,
    label: str,
    maximum: int,
    *,
    minimum: int = 0,
) -> list[Any]:
    if not isinstance(value, list):
        raise ResultError(f"{label} must be an array")
    if not minimum <= len(value) <= maximum:
        raise ResultError(f"{label} must contain {minimum}-{maximum} entries")
    return value


def _string(
    value: Any,
    label: str,
    maximum: int,
    *,
    allow_empty: bool = False,
    safe: bool = False,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ResultError(f"{label} must be a non-empty string")
    if len(value) > maximum:
        raise ResultError(f"{label} exceeds {maximum} characters")
    if safe and CONTROL.search(value):
        raise ResultError(f"{label} must not contain control characters")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ResultError(f"{label} must be valid UTF-8") from exc
    return value


def _nullable_string(value: Any, label: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _string(value, label, maximum)


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ResultError(f"{label} must be an integer from {minimum} through {maximum}")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ResultError(f"{label} must be boolean")
    return value


def _enum(value: Any, label: str, choices: set[str] | tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ResultError(f"{label} must be one of {sorted(choices)}")
    return value


def _digest(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    text = _string(value, label, 64)
    if not HEX64.fullmatch(text):
        raise ResultError(f"{label} must be a lowercase SHA-256")
    return text


def _repository_path(value: Any, label: str, *, allow_root: bool = False) -> str:
    text = _string(value, label, 4096, safe=True)
    if "\\" in text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise ResultError(f"{label} must be a canonical repository-relative path")
    if text == ".":
        if allow_root:
            return text
        raise ResultError(f"{label} cannot be the repository root")
    if text.endswith("/") or "//" in text:
        raise ResultError(f"{label} must be a canonical repository-relative path")
    parts = PurePosixPath(text).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ResultError(f"{label} must be a canonical repository-relative path")
    if PurePosixPath(*parts).as_posix() != text:
        raise ResultError(f"{label} must be a canonical repository-relative path")
    return text


def _unique_strings(
    value: Any,
    label: str,
    maximum: int,
    *,
    item_maximum: int,
    minimum: int = 0,
    safe: bool = False,
) -> list[str]:
    result = [
        _string(item, f"{label}[{index}]", item_maximum, safe=safe)
        for index, item in enumerate(_array(value, label, maximum, minimum=minimum))
    ]
    if len(result) != len(set(result)):
        raise ResultError(f"{label} contains duplicate values")
    return result


def _strings(
    value: Any,
    label: str,
    maximum: int,
    *,
    item_maximum: int,
    minimum: int = 0,
    safe: bool = False,
) -> list[str]:
    return [
        _string(item, f"{label}[{index}]", item_maximum, safe=safe)
        for index, item in enumerate(_array(value, label, maximum, minimum=minimum))
    ]


def _unique_paths(
    value: Any,
    label: str,
    maximum: int,
    *,
    minimum: int = 0,
    allow_root: bool = False,
) -> list[str]:
    result = [
        _repository_path(item, f"{label}[{index}]", allow_root=allow_root)
        for index, item in enumerate(_array(value, label, maximum, minimum=minimum))
    ]
    if len(result) != len(set(result)):
        raise ResultError(f"{label} contains duplicate paths")
    return result


def _date_time(value: Any, label: str, *, nullable: bool) -> str | None:
    if value is None and nullable:
        return None
    text = _string(value, label, 64, safe=True)
    match = RFC3339.fullmatch(text)
    if match is None:
        raise ResultError(f"{label} must use canonical RFC 3339 syntax")
    try:
        dt.date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError as exc:
        raise ResultError(f"{label} must be an RFC 3339 date-time") from exc
    if (
        int(match.group("hour")) > 23
        or int(match.group("minute")) > 59
        or int(match.group("second")) > 59
    ):
        raise ResultError(f"{label} has an out-of-range RFC 3339 time")
    if match.group("zone") != "Z" and (
        int(match.group("offset_hour")) > 23
        or int(match.group("offset_minute")) > 59
    ):
        raise ResultError(f"{label} has an out-of-range RFC 3339 offset")
    return text


def _validate_location(value: Any, label: str, *, allow_root: bool = True) -> dict[str, Any]:
    item = _object(value, label, {"path", "start_line", "end_line"})
    _repository_path(item["path"], f"{label}.path", allow_root=allow_root)
    start = item["start_line"]
    end = item["end_line"]
    if start is None or end is None:
        if start is not None or end is not None:
            raise ResultError(f"{label} line range must be fully null or fully specified")
    else:
        _integer(start, f"{label}.start_line", 1, 100000000)
        _integer(end, f"{label}.end_line", start, 100000000)
    return item


def _validate_limitation(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label, {"code", "message", "affected_paths", "material"})
    _enum(item["code"], f"{label}.code", LIMITATION_CODES)
    _string(item["message"], f"{label}.message", 4000)
    _unique_paths(item["affected_paths"], f"{label}.affected_paths", 20000)
    _boolean(item["material"], f"{label}.material")
    return item


def _validate_target(value: Any, label: str = "target") -> dict[str, Any]:
    target = _object(value, label, {"kind", "repository_root", "requested"})
    if target["kind"] != "current_filesystem":
        raise ResultError(f"{label}.kind must be current_filesystem")
    root = _filesystem_path(target["repository_root"], f"{label}.repository_root")
    if not root.is_absolute():
        raise ResultError(f"{label}.repository_root must be absolute")
    requested = _array(target["requested"], f"{label}.requested", 1000, minimum=1)
    seen_paths_and_ranges: set[tuple[Any, ...]] = set()
    for index, raw in enumerate(requested, 1):
        item_label = f"{label}.requested[{index - 1}]"
        item = _object(
            raw,
            item_label,
            {"target_id", "kind", "path", "start_line", "end_line", "focus"},
        )
        expected_id = f"T{index:03d}"
        if item["target_id"] != expected_id or not TARGET_ID.fullmatch(item["target_id"]):
            raise ResultError(f"{item_label}.target_id must be {expected_id}")
        kind = _enum(item["kind"], f"{item_label}.kind", TARGET_KINDS)
        path = _repository_path(item["path"], f"{item_label}.path", allow_root=True)
        if kind == "project" and path != ".":
            raise ResultError(f"{item_label} project target must use path .")
        if kind != "project" and path == ".":
            raise ResultError(f"{item_label} root target must be kind project")
        if kind == "part":
            start = _integer(item["start_line"], f"{item_label}.start_line", 1, 100000000)
            _integer(item["end_line"], f"{item_label}.end_line", start, 100000000)
        elif item["start_line"] is not None or item["end_line"] is not None:
            raise ResultError(f"{item_label} non-part line range must be null")
        if item["focus"] is not None:
            focus = _object(item["focus"], f"{item_label}.focus", {"kind", "value"})
            _enum(focus["kind"], f"{item_label}.focus.kind", FOCUS_KINDS)
            _string(focus["value"], f"{item_label}.focus.value", 2000, safe=True)
        identity = (path, kind, item["start_line"], item["end_line"], json.dumps(item["focus"], sort_keys=True))
        if identity in seen_paths_and_ranges:
            raise ResultError(f"{label}.requested contains a duplicate target")
        seen_paths_and_ranges.add(identity)
    expected_order = sorted(
        requested,
        key=lambda item: (
            item["path"],
            item["kind"],
            item["start_line"] or 0,
            item["end_line"] or 0,
            json.dumps(item["focus"], sort_keys=True),
        ),
    )
    if requested != expected_order:
        raise ResultError(f"{label}.requested must be in canonical order")
    return target


def _validate_inventory_file(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label, {"path", "bytes", "sha256", "inspection_kind", "tracking"})
    _repository_path(item["path"], f"{label}.path")
    _integer(item["bytes"], f"{label}.bytes", 0, 9223372036854775807)
    kind = _enum(item["inspection_kind"], f"{label}.inspection_kind", INSPECTION_KINDS)
    _enum(item["tracking"], f"{label}.tracking", TRACKING_KINDS)
    digest = _digest(item["sha256"], f"{label}.sha256", nullable=True)
    if kind in {"text", "binary", "non_utf8"} and digest is None:
        raise ResultError(f"{label}.sha256 is required for inspected content")
    if kind in {"oversized", "unreadable", "not_inspected"} and digest is not None:
        raise ResultError(f"{label}.sha256 must be null when content was not read")
    return item


def _path_owned_by_target(path: str, target: dict[str, Any]) -> bool:
    for item in target["requested"]:
        if item["kind"] == "project":
            return True
        if item["kind"] == "directory" and (
            path == item["path"] or path.startswith(f"{item['path']}/")
        ):
            return True
        if item["kind"] in {"file", "part"} and path == item["path"]:
            return True
    return False


def _target_owners(path: str, target: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for item in target["requested"]:
        if item["kind"] == "project":
            result.add(item["target_id"])
        elif item["kind"] == "directory" and (
            path == item["path"] or path.startswith(f"{item['path']}/")
        ):
            result.add(item["target_id"])
        elif item["kind"] in {"file", "part"} and path == item["path"]:
            result.add(item["target_id"])
    return result


def _location_target_owners(
    location: dict[str, Any],
    target: dict[str, Any],
) -> set[str]:
    """Return targets that own this exact location, including part ranges."""
    result: set[str] = set()
    for item in target["requested"]:
        if item["kind"] == "project":
            result.add(item["target_id"])
        elif item["kind"] == "directory" and (
            location["path"] == item["path"]
            or location["path"].startswith(f"{item['path']}/")
        ):
            result.add(item["target_id"])
        elif item["kind"] == "file" and location["path"] == item["path"]:
            result.add(item["target_id"])
        elif (
            item["kind"] == "part"
            and location["path"] == item["path"]
            and location["start_line"] is not None
            and location["end_line"] is not None
            and location["start_line"] >= item["start_line"]
            and location["end_line"] <= item["end_line"]
        ):
            result.add(item["target_id"])
    return result


def _validate_inventory(
    value: Any,
    target: dict[str, Any],
    label: str = "inventory",
) -> dict[str, Any]:
    inventory = _object(
        value,
        label,
        {"limits", "traversed_entries", "read_bytes", "context_read_bytes", "files", "complete"},
    )
    limits = _object(
        inventory["limits"],
        f"{label}.limits",
        {
            "maximum_files",
            "maximum_file_bytes",
            "maximum_total_bytes",
            "maximum_traversal_entries",
            "maximum_context_files",
            "maximum_context_bytes",
        },
    )
    _integer(limits["maximum_files"], f"{label}.limits.maximum_files", 1, 20000)
    _integer(limits["maximum_file_bytes"], f"{label}.limits.maximum_file_bytes", 1, 16777216)
    _integer(limits["maximum_total_bytes"], f"{label}.limits.maximum_total_bytes", 1, 268435456)
    _integer(limits["maximum_traversal_entries"], f"{label}.limits.maximum_traversal_entries", 1, 1000000)
    _integer(limits["maximum_context_files"], f"{label}.limits.maximum_context_files", 0, 5000)
    _integer(limits["maximum_context_bytes"], f"{label}.limits.maximum_context_bytes", 0, 67108864)
    _integer(inventory["traversed_entries"], f"{label}.traversed_entries", 0, limits["maximum_traversal_entries"])
    _integer(inventory["read_bytes"], f"{label}.read_bytes", 0, limits["maximum_total_bytes"])
    _integer(inventory["context_read_bytes"], f"{label}.context_read_bytes", 0, limits["maximum_context_bytes"])
    files = _array(inventory["files"], f"{label}.files", limits["maximum_files"])
    paths: list[str] = []
    for index, raw in enumerate(files):
        item = _validate_inventory_file(raw, f"{label}.files[{index}]")
        paths.append(item["path"])
        if not _path_owned_by_target(item["path"], target):
            raise ResultError(f"{label}.files[{index}] is outside the selected harness boundary")
    if paths != sorted(set(paths)):
        raise ResultError(f"{label}.files paths must be unique and sorted")
    file_paths = set(paths)
    for item in target["requested"]:
        if item["kind"] in {"file", "part"} and item["path"] not in file_paths:
            raise ResultError(f"{label}.files is missing explicit target {item['path']}")
    _boolean(inventory["complete"], f"{label}.complete")
    return inventory


def _validate_context_inventory(
    value: Any,
    inventory: dict[str, Any],
    label: str = "context_inventory",
) -> list[dict[str, Any]]:
    records = _array(value, label, inventory["limits"]["maximum_context_files"])
    paths: list[str] = []
    target_paths = {item["path"] for item in inventory["files"]}
    for index, raw in enumerate(records):
        item = _validate_inventory_file(raw, f"{label}[{index}]")
        paths.append(item["path"])
        if item["path"] in target_paths:
            raise ResultError(f"{label} overlaps the harness inventory: {item['path']}")
    if paths != sorted(set(paths)):
        raise ResultError(f"{label} paths must be unique and sorted")
    return records


def _guidance_paths(path: str, *, directory: bool) -> list[str]:
    base = PurePosixPath(path) if directory and path != "." else PurePosixPath(path).parent
    result = ["REVIEW.md"]
    if base.as_posix() == ".":
        return result
    current = PurePosixPath()
    for part in base.parts:
        current /= part
        result.append((current / "REVIEW.md").as_posix())
    return result


def _validate_guidance_source(
    value: Any,
    label: str,
    *,
    resolver_context: bool,
) -> dict[str, Any]:
    keys = {"source_kind", "path", "revision", "sha256", "bytes", "lines", "loaded"}
    if resolver_context:
        keys.add("content")
    item = _object(value, label, keys)
    kind = _enum(item["source_kind"], f"{label}.source_kind", SOURCE_KINDS)
    path = _string(item["path"], f"{label}.path", 8192, safe=True)
    if kind == "repository":
        _repository_path(path, f"{label}.path")
    elif kind == "user_global":
        authority_path = _filesystem_path(path, f"{label}.path")
        if not authority_path.is_absolute():
            raise ResultError(f"{label}.path must be absolute for user-global guidance")
    elif path != "SKILL.md":
        raise ResultError(f"{label}.path must be SKILL.md for the skill source")
    _nullable_string(item["revision"], f"{label}.revision", 256)
    _digest(item["sha256"], f"{label}.sha256")
    _integer(item["bytes"], f"{label}.bytes", 0, 16777216)
    _integer(item["lines"], f"{label}.lines", 0, 1048576)
    _boolean(item["loaded"], f"{label}.loaded")
    if resolver_context:
        if item["loaded"]:
            content = _string(
                item["content"],
                f"{label}.content",
                1048576,
                allow_empty=True,
            )
            canonical = content.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
            if len(canonical) != item["bytes"]:
                raise ResultError(f"{label}.bytes does not match loaded content")
            if hashlib.sha256(canonical).hexdigest() != item["sha256"]:
                raise ResultError(f"{label}.sha256 does not match loaded content")
            if len(content.replace("\r\n", "\n").replace("\r", "\n").splitlines()) != item["lines"]:
                raise ResultError(f"{label}.lines does not match loaded content")
        elif item["content"] is not None:
            raise ResultError(f"{label}.content must be null when not loaded")
    return item


def _validate_guidance(
    value: Any,
    target: dict[str, Any],
    inventory: dict[str, Any],
    *,
    resolver_context: bool,
    label: str = "guidance",
) -> list[dict[str, Any]]:
    chains = _array(value, label, 21000)
    requested_ids = {item["target_id"] for item in target["requested"]}
    requested_by_path = {item["path"]: item for item in target["requested"]}
    inventory_paths = {item["path"] for item in inventory["files"]}
    allowed_paths = inventory_paths | {
        item["path"]
        for item in target["requested"]
        if item["kind"] in {"directory", "project"}
    }
    seen_paths: set[str] = set()
    seen_target_ids: set[str] = set()
    global_identities: set[tuple[str, str]] = set()
    for index, raw in enumerate(chains, 1):
        chain_label = f"{label}[{index - 1}]"
        chain = _object(raw, chain_label, {"chain_id", "target_ids", "paths", "sources", "complete"})
        expected_id = f"G{index:03d}"
        if chain["chain_id"] != expected_id or not CHAIN_ID.fullmatch(chain["chain_id"]):
            raise ResultError(f"{chain_label}.chain_id must be {expected_id}")
        target_ids = _unique_strings(
            chain["target_ids"],
            f"{chain_label}.target_ids",
            1000,
            item_maximum=16,
            minimum=1,
            safe=True,
        )
        if not set(target_ids) <= requested_ids or any(not TARGET_ID.fullmatch(item) for item in target_ids):
            raise ResultError(f"{chain_label}.target_ids contains an unknown target")
        paths = _unique_paths(
            chain["paths"],
            f"{chain_label}.paths",
            21000,
            minimum=1,
            allow_root=True,
        )
        if paths != sorted(paths):
            raise ResultError(f"{chain_label}.paths must be sorted")
        if not set(paths) <= allowed_paths:
            raise ResultError(f"{chain_label}.paths expands the resolved target")
        if seen_paths & set(paths):
            raise ResultError(f"{label} assigns a path to multiple chains")
        seen_paths.update(paths)
        expected_targets: set[str] = set()
        for path in paths:
            expected_targets.update(_target_owners(path, target))
        if set(target_ids) != expected_targets:
            raise ResultError(f"{chain_label}.target_ids does not match its paths")
        seen_target_ids.update(target_ids)
        sources = _array(chain["sources"], f"{chain_label}.sources", 256, minimum=1)
        validated_sources = [
            _validate_guidance_source(
                source,
                f"{chain_label}.sources[{source_index}]",
                resolver_context=resolver_context,
            )
            for source_index, source in enumerate(sources)
        ]
        if validated_sources[0]["source_kind"] != "skill":
            raise ResultError(f"{chain_label}.sources must begin with the skill contract")
        if validated_sources[0]["revision"] != SKILL_REVISION:
            raise ResultError(f"{chain_label}.sources has the wrong skill revision")
        seen_global = False
        seen_repository = False
        seen_sources: set[tuple[str, str, str]] = set()
        repository_depth = 0
        for source_index, source in enumerate(validated_sources):
            identity = (source["source_kind"], source["path"], source["sha256"])
            if identity in seen_sources:
                raise ResultError(f"{chain_label}.sources contains a duplicate source")
            seen_sources.add(identity)
            if source["source_kind"] == "skill":
                if source_index != 0:
                    raise ResultError(f"{chain_label}.sources contains misplaced skill guidance")
            elif source["source_kind"] == "user_global":
                if seen_global or seen_repository:
                    raise ResultError(f"{chain_label}.sources contains misplaced user-global guidance")
                seen_global = True
                global_identities.add((source["path"], source["sha256"]))
            else:
                seen_repository = True
                depth = len(PurePosixPath(source["path"]).parts)
                if depth < repository_depth:
                    raise ResultError(f"{chain_label}.repository guidance must be broad-to-specific")
                repository_depth = depth
                for path in paths:
                    directory = path not in inventory_paths and requested_by_path.get(path, {}).get("kind") in {"directory", "project"}
                    if source["path"] not in _guidance_paths(path, directory=directory):
                        raise ResultError(f"{chain_label}.sources contains non-applicable repository guidance")
        _boolean(chain["complete"], f"{chain_label}.complete")
        if chain["complete"] and any(
            source["source_kind"] != "skill" and not source["loaded"]
            for source in validated_sources
        ):
            raise ResultError(f"{chain_label}.complete hides unloaded guidance")
    expected_guided_paths = inventory_paths | {
        item["path"]
        for item in target["requested"]
        if item["kind"] in {"directory", "project"}
        and not any(
            item["target_id"] in _target_owners(path, target)
            for path in inventory_paths
        )
    }
    if seen_paths != expected_guided_paths:
        raise ResultError(f"{label} must associate every inventory and empty broad target path exactly once")
    if seen_target_ids != requested_ids:
        raise ResultError(f"{label} must associate every requested target")
    if len(global_identities) > 1:
        raise ResultError(f"{label} contains multiple user-global sources")
    return chains


def _validate_authorization(
    value: Any,
    label: str,
    global_sources: set[tuple[str, str]],
) -> dict[str, Any]:
    item = _object(value, label, {"kind", "source", "source_sha256"})
    kind = _enum(item["kind"], f"{label}.kind", AUTHORITY_KINDS)
    source = _nullable_string(item["source"], f"{label}.source", 2000)
    digest = _digest(item["source_sha256"], f"{label}.source_sha256", nullable=True)
    if kind in {"not_requested", "denied"}:
        if source is not None or digest is not None:
            raise ResultError(f"{label} without execution authority must not carry a source")
    else:
        if source is None or digest is None:
            raise ResultError(f"{label} execution authority requires source provenance")
        if kind == "user_global" and (source, digest) not in global_sources:
            raise ResultError(f"{label} user-global authority does not match resolved guidance")
        if kind == "caller" and hashlib.sha256(source.encode("utf-8")).hexdigest() != digest:
            raise ResultError(f"{label} caller authority digest is inconsistent")
    return item


def _validate_execution(
    value: Any,
    guidance: list[dict[str, Any]],
    label: str = "execution",
) -> list[dict[str, Any]]:
    records = _array(value, label, 256)
    global_sources = {
        (source["path"], source["sha256"])
        for chain in guidance
        for source in chain["sources"]
        if source["source_kind"] == "user_global"
    }
    for index, raw in enumerate(records, 1):
        item_label = f"{label}[{index - 1}]"
        item = _object(
            raw,
            item_label,
            {
                "command_id",
                "argv",
                "cwd",
                "reason",
                "expected_effects",
                "timeout_seconds",
                "repetitions",
                "authorization",
                "outcome",
                "exit_code",
                "duration_ms",
                "output_sha256",
                "summary",
            },
        )
        expected_id = f"C{index:03d}"
        if item["command_id"] != expected_id or not COMMAND_ID.fullmatch(item["command_id"]):
            raise ResultError(f"{item_label}.command_id must be {expected_id}")
        _strings(item["argv"], f"{item_label}.argv", 128, item_maximum=4096, minimum=1, safe=True)
        _repository_path(item["cwd"], f"{item_label}.cwd", allow_root=True)
        _string(item["reason"], f"{item_label}.reason", 4000)
        _strings(item["expected_effects"], f"{item_label}.expected_effects", 32, item_maximum=2000, minimum=1)
        _integer(item["timeout_seconds"], f"{item_label}.timeout_seconds", 1, 86400)
        _integer(item["repetitions"], f"{item_label}.repetitions", 1, 100)
        authorization = _validate_authorization(item["authorization"], f"{item_label}.authorization", global_sources)
        outcome = _enum(item["outcome"], f"{item_label}.outcome", COMMAND_OUTCOMES)
        if item["exit_code"] is not None:
            _integer(item["exit_code"], f"{item_label}.exit_code", -2147483648, 2147483647)
        if item["duration_ms"] is not None:
            _integer(item["duration_ms"], f"{item_label}.duration_ms", 0, 8640000000)
        _digest(item["output_sha256"], f"{item_label}.output_sha256", nullable=True)
        _string(item["summary"], f"{item_label}.summary", 4000)
        if outcome in {"not_run", "refused"}:
            if any(item[key] is not None for key in ("exit_code", "duration_ms", "output_sha256")):
                raise ResultError(f"{item_label} unexecuted outcome must not carry execution results")
        else:
            if authorization["kind"] not in {"caller", "user_global"}:
                raise ResultError(f"{item_label} executed without valid authority")
            if item["duration_ms"] is None or item["output_sha256"] is None:
                raise ResultError(f"{item_label} executed outcome requires duration and output digest")
            if outcome == "passed" and item["exit_code"] != 0:
                raise ResultError(f"{item_label} passed outcome requires exit code 0")
            if outcome == "failed" and (item["exit_code"] is None or item["exit_code"] == 0):
                raise ResultError(f"{item_label} failed outcome requires a nonzero exit code")
            if outcome == "timed_out" and item["exit_code"] is not None:
                raise ResultError(f"{item_label} timed-out outcome requires null exit code")
        if outcome == "refused" and authorization["kind"] not in {"denied", "not_requested"}:
            raise ResultError(f"{item_label} refused outcome requires absent or denied authority")
    return records


def _validate_evidence_sources(value: Any, label: str = "evidence_sources") -> list[dict[str, Any]]:
    records = _array(value, label, 256)
    for index, raw in enumerate(records, 1):
        item_label = f"{label}[{index - 1}]"
        item = _object(
            raw,
            item_label,
            {
                "evidence_source_id",
                "kind",
                "source_label",
                "source_sha256",
                "observed_at",
                "supplied_at",
                "freshness",
                "freshness_basis",
            },
        )
        expected_id = f"S{index:03d}"
        if item["evidence_source_id"] != expected_id or not SOURCE_ID.fullmatch(item["evidence_source_id"]):
            raise ResultError(f"{item_label}.evidence_source_id must be {expected_id}")
        _enum(item["kind"], f"{item_label}.kind", EVIDENCE_SOURCE_KINDS)
        _string(item["source_label"], f"{item_label}.source_label", 1000)
        _digest(item["source_sha256"], f"{item_label}.source_sha256")
        observed = _date_time(item["observed_at"], f"{item_label}.observed_at", nullable=True)
        supplied = _date_time(item["supplied_at"], f"{item_label}.supplied_at", nullable=False)
        if observed is not None and supplied is not None:
            observed_instant = dt.datetime.fromisoformat(observed.replace("Z", "+00:00"))
            supplied_instant = dt.datetime.fromisoformat(supplied.replace("Z", "+00:00"))
            if observed_instant > supplied_instant:
                raise ResultError(f"{item_label}.observed_at must not be after supplied_at")
        _enum(item["freshness"], f"{item_label}.freshness", FRESHNESS)
        _string(item["freshness_basis"], f"{item_label}.freshness_basis", 2000)
    return records


def _validate_context(value: Any) -> dict[str, Any]:
    context = _object(
        value,
        "context",
        {
            "schema_version",
            "target",
            "inventory",
            "context_inventory",
            "guidance",
            "execution",
            "evidence_sources",
            "limitations",
        },
    )
    if context["schema_version"] != SCHEMA_VERSION:
        raise ResultError(f"context.schema_version must be {SCHEMA_VERSION}")
    target = _validate_target(context["target"], "context.target")
    inventory = _validate_inventory(context["inventory"], target, "context.inventory")
    _validate_context_inventory(context["context_inventory"], inventory, "context.context_inventory")
    guidance = _validate_guidance(
        context["guidance"],
        target,
        inventory,
        resolver_context=True,
        label="context.guidance",
    )
    _validate_execution(context["execution"], guidance, "context.execution")
    _validate_evidence_sources(context["evidence_sources"], "context.evidence_sources")
    limitations = [
        _validate_limitation(item, f"context.limitations[{index}]")
        for index, item in enumerate(_array(context["limitations"], "context.limitations", 2000))
    ]
    material_inventory = any(
        item["material"] and item["code"] in INVENTORY_LIMITATION_CODES
        for item in limitations
    )
    if inventory["complete"] == material_inventory:
        raise ResultError("context.inventory.complete is inconsistent with resolver limitations")
    if any(not chain["complete"] for chain in guidance) and not any(
        item["material"] and item["code"] in {"guidance_unreadable", "guidance_budget"}
        for item in limitations
    ):
        raise ResultError("context incomplete guidance requires a material guidance limitation")
    _canonical_json(context)
    return context


def _result_guidance(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            **{key: copy.deepcopy(chain[key]) for key in ("chain_id", "target_ids", "paths", "complete")},
            "sources": [
                {
                    key: copy.deepcopy(source[key])
                    for key in ("source_kind", "path", "revision", "sha256", "bytes", "lines", "loaded")
                }
                for source in chain["sources"]
            ],
        }
        for chain in context["guidance"]
    ]


def _infer_guidance_limit(guidance: list[dict[str, Any]]) -> int:
    lower = 1024
    upper = 1024 * 1024 + 1
    for chain in guidance:
        loaded = 0
        for source in chain["sources"]:
            if source["source_kind"] == "skill":
                continue
            threshold = loaded + source["bytes"]
            if source["loaded"]:
                lower = max(lower, threshold)
                loaded = threshold
            else:
                upper = min(upper, threshold)
    if not 1024 <= lower <= 1024 * 1024 or lower >= upper:
        raise ResultError("context guidance loaded flags cannot come from one bounded byte ceiling")
    return lower


def _verify_context_fresh(context: dict[str, Any]) -> None:
    resolver_path = Path(__file__).resolve().with_name("harness_context.py")
    specification = importlib.util.spec_from_file_location(
        "verification_harness_context_fresh",
        resolver_path,
    )
    if specification is None or specification.loader is None:
        raise ResultError("cannot load the bundled context resolver")
    resolver = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(resolver)
    paths = [
        item["path"]
        for item in context["target"]["requested"]
        if item["kind"] != "part"
    ]
    parts = [
        f"{item['path']}:{item['start_line']}:{item['end_line']}"
        for item in context["target"]["requested"]
        if item["kind"] == "part"
    ]
    explicit = {
        item["path"]
        for item in context["target"]["requested"]
        if item["kind"] in {"file", "part"}
    }
    inspections = [
        item["path"]
        for item in context["inventory"]["files"]
        if item["path"] not in explicit and item["inspection_kind"] != "not_inspected"
    ]
    global_paths = {
        source["path"]
        for chain in context["guidance"]
        for source in chain["sources"]
        if source["source_kind"] == "user_global"
    }
    if len(global_paths) > 1:
        raise ResultError("context contains multiple user-global review files")
    limits = context["inventory"]["limits"]
    arguments = argparse.Namespace(
        repo=context["target"]["repository_root"],
        paths=paths,
        parts=parts,
        focus_kind=None,
        focus_value=None,
        contexts=[item["path"] for item in context["context_inventory"]],
        inspections=inspections,
        global_review_file=next(iter(global_paths), None),
        command_plan=None,
        evidence_metadata=None,
        max_files=limits["maximum_files"],
        max_file_bytes=limits["maximum_file_bytes"],
        max_total_bytes=limits["maximum_total_bytes"],
        max_traversal_entries=limits["maximum_traversal_entries"],
        max_context_files=limits["maximum_context_files"],
        max_context_bytes=limits["maximum_context_bytes"],
        max_guidance_bytes=_infer_guidance_limit(context["guidance"]),
        output=None,
    )
    focused = [
        item
        for item in context["target"]["requested"]
        if item["focus"] is not None
        and not (
            item["kind"] == "part"
            and item["focus"]
            == {
                "kind": "line_range",
                "value": f"{item['start_line']}:{item['end_line']}",
            }
        )
    ]
    if focused:
        if len(context["target"]["requested"]) != 1:
            raise ResultError("context focus is inconsistent with resolver rules")
        arguments.focus_kind = focused[0]["focus"]["kind"]
        arguments.focus_value = focused[0]["focus"]["value"]
    try:
        fresh = resolver.resolve(arguments)
    except Exception as exc:
        raise ResultError(f"cannot refresh resolver-owned context: {exc}") from exc
    for key in ("target", "inventory", "context_inventory", "guidance"):
        if _sha256_json(fresh[key]) != _sha256_json(context[key]):
            raise ResultError(f"resolver-owned {key} is stale; resolve the unchanged target again")
    original_limits = [
        item for item in context["limitations"] if item["code"] in RESOLVER_LIMITATION_CODES
    ]
    fresh_limits = [
        item for item in fresh["limitations"] if item["code"] in RESOLVER_LIMITATION_CODES
    ]
    if original_limits != fresh_limits:
        raise ResultError("resolver-owned limitations are stale; resolve the unchanged target again")


def _validate_coverage(
    value: Any,
    target: dict[str, Any],
    inventory: dict[str, Any],
    context_inventory: list[dict[str, Any]],
    limitations: list[dict[str, Any]],
    label: str = "coverage",
) -> dict[str, Any]:
    coverage = _object(
        value,
        label,
        {
            "complete",
            "inspected_targets",
            "inspected_harness_paths",
            "classified_non_harness_paths",
            "excluded",
            "context_paths",
        },
    )
    _boolean(coverage["complete"], f"{label}.complete")
    inspected_targets = _unique_strings(
        coverage["inspected_targets"],
        f"{label}.inspected_targets",
        1000,
        item_maximum=16,
        safe=True,
    )
    target_ids = {item["target_id"] for item in target["requested"]}
    if not set(inspected_targets) <= target_ids or any(not TARGET_ID.fullmatch(item) for item in inspected_targets):
        raise ResultError(f"{label}.inspected_targets contains an unknown target")
    inspected = _unique_paths(
        coverage["inspected_harness_paths"],
        f"{label}.inspected_harness_paths",
        20000,
    )
    non_harness = _unique_paths(
        coverage["classified_non_harness_paths"],
        f"{label}.classified_non_harness_paths",
        20000,
    )
    if set(inspected) & set(non_harness):
        raise ResultError(f"{label} classifies a path more than once")
    excluded_raw = _array(coverage["excluded"], f"{label}.excluded", 20000)
    excluded_paths: list[str] = []
    for index, raw in enumerate(excluded_raw):
        item_label = f"{label}.excluded[{index}]"
        item = _object(raw, item_label, {"path", "reason", "material"})
        excluded_paths.append(_repository_path(item["path"], f"{item_label}.path"))
        _string(item["reason"], f"{item_label}.reason", 2000)
        _boolean(item["material"], f"{item_label}.material")
    if len(excluded_paths) != len(set(excluded_paths)):
        raise ResultError(f"{label}.excluded contains duplicate paths")
    classified = set(inspected) | set(non_harness) | set(excluded_paths)
    inventory_by_path = {item["path"]: item for item in inventory["files"]}
    if classified != set(inventory_by_path):
        raise ResultError(f"{label} must classify every resolver-owned inventory path exactly once")
    for path in [*inspected, *non_harness]:
        if inventory_by_path[path]["inspection_kind"] != "text":
            raise ResultError(f"{label} cannot classify unread semantic content as inspected: {path}")
    context_paths = _unique_paths(
        coverage["context_paths"],
        f"{label}.context_paths",
        5000,
    )
    context_by_path = {item["path"]: item for item in context_inventory}
    if not set(context_paths) <= set(context_by_path):
        raise ResultError(f"{label}.context_paths expands the resolved context inventory")
    for path in context_paths:
        if context_by_path[path]["inspection_kind"] != "text":
            raise ResultError(f"{label}.context_paths includes unread semantic content: {path}")
    material_omission = (
        not inventory["complete"]
        or any(item["material"] for item in limitations)
        or any(item["material"] for item in excluded_raw)
    )
    if coverage["complete"] == material_omission:
        raise ResultError(f"{label}.complete is inconsistent with material omissions")
    if coverage["complete"] and set(inspected_targets) != target_ids:
        raise ResultError(f"{label}.complete requires every requested target to be inspected")
    inspected_semantic_paths = set(inspected) | set(non_harness)
    excluded_path_set = set(excluded_paths)
    requested_by_id = {item["target_id"]: item for item in target["requested"]}
    for target_id in inspected_targets:
        target_item = requested_by_id[target_id]
        if target_item["kind"] not in {"file", "part"}:
            continue
        if target_item["path"] in excluded_path_set:
            raise ResultError(f"{label} cannot mark an excluded target as inspected: {target_id}")
        if target_item["path"] not in inspected_semantic_paths:
            raise ResultError(
                f"{label} inspected target lacks inspected semantic content: {target_id}"
            )
    missing_targets = target_ids - set(inspected_targets)
    if missing_targets:
        global_material = any(
            item["material"] and not item["affected_paths"] for item in limitations
        )
        material_paths = {
            path
            for item in limitations
            if item["material"]
            for path in item["affected_paths"]
        } | {
            item["path"] for item in excluded_raw if item["material"]
        }
        for target_id in missing_targets:
            target_path = requested_by_id[target_id]["path"]
            covered = global_material or any(
                target_path == path
                or (target_path != "." and path.startswith(f"{target_path}/"))
                or (target_path == "." and path)
                for path in material_paths
            )
            if not covered:
                raise ResultError(f"{label} omits {target_id} without a material exclusion or limitation")
    return coverage


def _known_location_paths(
    inventory: dict[str, Any],
    context_inventory: list[dict[str, Any]],
    guidance: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> set[str]:
    del inventory, context_inventory
    result = set(coverage["inspected_harness_paths"])
    result.update(coverage["classified_non_harness_paths"])
    result.update(coverage["context_paths"])
    result.update(
        source["path"]
        for chain in guidance
        for source in chain["sources"]
        if source["source_kind"] == "repository" and source["loaded"]
    )
    return result


def _repository_guidance_targets(
    guidance: list[dict[str, Any]],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for chain in guidance:
        for source in chain["sources"]:
            if source["source_kind"] == "repository" and source["loaded"]:
                result.setdefault(source["path"], set()).update(chain["target_ids"])
    return result


def _validate_evidence(
    value: Any,
    label: str,
    *,
    known_paths: set[str],
    commands: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    item = _object(value, label, {"kind", "description", "location", "source_id"})
    kind = _enum(item["kind"], f"{label}.kind", EVIDENCE_KINDS)
    _string(item["description"], f"{label}.description", 4000)
    direct_artifact = kind not in {
        "command",
        "history",
        "caller_supplied",
        "reasoning",
    }
    if direct_artifact and item["location"] is None:
        raise ResultError(f"{label}.location is required for direct artifact evidence")
    if item["location"] is not None:
        location = _validate_location(item["location"], f"{label}.location")
        if location["path"] not in known_paths:
            raise ResultError(f"{label}.location expands the resolved evidence boundary")
    source_id = item["source_id"]
    if kind == "command":
        if not isinstance(source_id, str) or not COMMAND_ID.fullmatch(source_id) or source_id not in commands:
            raise ResultError(f"{label}.source_id must reference a lead-owned command")
        if commands[source_id]["outcome"] in {"not_run", "refused"}:
            raise ResultError(f"{label} cannot cite a command that did not run")
    elif kind in {"history", "caller_supplied"}:
        if not isinstance(source_id, str) or not SOURCE_ID.fullmatch(source_id) or source_id not in sources:
            raise ResultError(f"{label}.source_id must reference lead-owned supplied evidence")
        if kind == "history" and sources[source_id]["kind"] != "history":
            raise ResultError(f"{label} history evidence must reference a history source")
    elif source_id is not None:
        raise ResultError(f"{label}.source_id must be null for direct artifact evidence")
    return item


def _validate_safe_direction(
    value: Any,
    label: str,
    *,
    allowed_paths: set[str],
) -> dict[str, Any]:
    item = _object(
        value,
        label,
        {"outcome", "acceptance_evidence", "alternatives", "suggested_paths"},
    )
    _string(item["outcome"], f"{label}.outcome", 4000)
    _strings(
        item["acceptance_evidence"],
        f"{label}.acceptance_evidence",
        32,
        item_maximum=2000,
        minimum=1,
    )
    _strings(item["alternatives"], f"{label}.alternatives", 16, item_maximum=2000)
    paths = _unique_paths(item["suggested_paths"], f"{label}.suggested_paths", 64, allow_root=True)
    if not set(paths) <= allowed_paths:
        raise ResultError(f"{label}.suggested_paths expands the resolver-owned boundary")
    return item


def recommendation_fingerprint(item: dict[str, Any]) -> str:
    def location_key(location: dict[str, Any]) -> tuple[str, int, int]:
        return (
            location.get("path"),
            -1 if location.get("start_line") is None else location["start_line"],
            -1 if location.get("end_line") is None else location["end_line"],
        )

    value = {
        "kind": item.get("kind"),
        "action": item.get("action"),
        "basis": item.get("basis"),
        "title": " ".join(str(item.get("title", "")).casefold().split()),
        "affected_targets": sorted(item.get("affected_targets") or []),
        "affected_locations": sorted(
            (location_key(location) for location in item.get("affected_locations") or [])
        ),
        "outcome": " ".join(
            str((item.get("safe_direction") or {}).get("outcome", ""))
            .casefold()
            .split()
        ),
    }
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _validate_recommendations(
    value: Any,
    *,
    target: dict[str, Any],
    inventory: dict[str, Any],
    context_inventory: list[dict[str, Any]],
    guidance: list[dict[str, Any]],
    execution: list[dict[str, Any]],
    evidence_sources: list[dict[str, Any]],
    coverage: dict[str, Any],
    finalized: bool,
    label: str = "recommendations",
) -> list[dict[str, Any]]:
    recommendations = _array(value, label, MAX_RECOMMENDATIONS)
    target_ids = {item["target_id"] for item in target["requested"]}
    requested_by_id = {item["target_id"]: item for item in target["requested"]}
    inspected_paths = set(coverage["inspected_harness_paths"])
    boundary_paths = inspected_paths | {
        item["path"]
        for item in target["requested"]
        if item["kind"] in {"directory", "project"}
    }
    known_paths = _known_location_paths(inventory, context_inventory, guidance, coverage)
    guidance_targets = _repository_guidance_targets(guidance)
    allowed_suggested_paths = boundary_paths
    commands = {item["command_id"]: item for item in execution}
    sources = {item["evidence_source_id"]: item for item in evidence_sources}
    fingerprints: set[str] = set()
    for index, raw in enumerate(recommendations, 1):
        item_label = f"{label}[{index - 1}]"
        draft_keys = {
            "kind",
            "action",
            "strength",
            "impact",
            "confidence",
            "decision",
            "decision_reason",
            "claim",
            "basis",
            "basis_reference",
            "title",
            "problem",
            "reason",
            "impact_summary",
            "affected_targets",
            "affected_locations",
            "related_context",
            "evidence",
            "current_tier",
            "recommended_tier",
            "safe_direction",
        }
        keys = draft_keys | ({"recommendation_id", "fingerprint"} if finalized else set())
        item = _object(raw, item_label, keys)
        if finalized:
            expected_id = f"R{index:03d}"
            if item["recommendation_id"] != expected_id or not RECOMMENDATION_ID.fullmatch(item["recommendation_id"]):
                raise ResultError(f"{item_label}.recommendation_id must be {expected_id}")
            _digest(item["fingerprint"], f"{item_label}.fingerprint")
        _enum(item["kind"], f"{item_label}.kind", RECOMMENDATION_KINDS)
        _enum(item["action"], f"{item_label}.action", ACTIONS)
        strength = _enum(item["strength"], f"{item_label}.strength", STRENGTHS)
        _enum(item["impact"], f"{item_label}.impact", IMPACTS)
        _enum(item["confidence"], f"{item_label}.confidence", CONFIDENCES)
        decision = _enum(item["decision"], f"{item_label}.decision", DECISIONS)
        _string(item["decision_reason"], f"{item_label}.decision_reason", 3000)
        claim = _enum(item["claim"], f"{item_label}.claim", CLAIMS)
        basis = _enum(item["basis"], f"{item_label}.basis", BASES)
        _string(item["basis_reference"], f"{item_label}.basis_reference", 4000)
        _string(item["title"], f"{item_label}.title", 300)
        _string(item["problem"], f"{item_label}.problem", 6000)
        _string(item["reason"], f"{item_label}.reason", 6000)
        _string(item["impact_summary"], f"{item_label}.impact_summary", 4000)
        affected_targets = _unique_strings(
            item["affected_targets"],
            f"{item_label}.affected_targets",
            1000,
            item_maximum=16,
            minimum=1,
            safe=True,
        )
        if not set(affected_targets) <= target_ids or any(not TARGET_ID.fullmatch(value) for value in affected_targets):
            raise ResultError(f"{item_label}.affected_targets contains an unknown target")
        locations = [
            _validate_location(location, f"{item_label}.affected_locations[{location_index}]")
            for location_index, location in enumerate(
                _array(item["affected_locations"], f"{item_label}.affected_locations", 64, minimum=1)
            )
        ]
        for location in locations:
            if location["path"] not in boundary_paths:
                raise ResultError(f"{item_label}.affected_locations expands the harness boundary")
            owners = _location_target_owners(location, target)
            if not owners & set(affected_targets):
                raise ResultError(f"{item_label}.affected_locations does not match affected_targets")
            if location["path"] not in inspected_paths:
                target_item = next(
                    (entry for entry in target["requested"] if entry["path"] == location["path"]),
                    None,
                )
                if target_item is None or target_item["kind"] not in {"directory", "project"}:
                    raise ResultError(f"{item_label}.affected_locations must be inspected harness paths")
                if item["kind"] != "missing_coverage":
                    raise ResultError(f"{item_label} may use a broad target location only for missing coverage")
        for target_id in affected_targets:
            target_item = requested_by_id[target_id]
            if not any(
                target_id in _location_target_owners(location, target)
                for location in locations
            ):
                if not (item["kind"] == "missing_coverage" and target_item["kind"] in {"directory", "project"}):
                    raise ResultError(f"{item_label} has an affected target with no affected location")
        related = [
            _validate_location(location, f"{item_label}.related_context[{location_index}]")
            for location_index, location in enumerate(
                _array(item["related_context"], f"{item_label}.related_context", 64)
            )
        ]
        if any(location["path"] not in known_paths for location in related):
            raise ResultError(f"{item_label}.related_context expands the evidence boundary")
        affected_target_set = set(affected_targets)
        for location in related:
            applicable_targets = guidance_targets.get(location["path"])
            if (
                applicable_targets is not None
                and not affected_target_set & applicable_targets
            ):
                raise ResultError(
                    f"{item_label}.related_context cites guidance that does not apply to its affected targets"
                )
        evidence = [
            _validate_evidence(
                evidence_item,
                f"{item_label}.evidence[{evidence_index}]",
                known_paths=known_paths,
                commands=commands,
                sources=sources,
            )
            for evidence_index, evidence_item in enumerate(
                _array(item["evidence"], f"{item_label}.evidence", 64, minimum=1)
            )
        ]
        for evidence_item in evidence:
            if evidence_item["location"] is None:
                continue
            applicable_targets = guidance_targets.get(evidence_item["location"]["path"])
            if (
                applicable_targets is not None
                and not affected_target_set & applicable_targets
            ):
                raise ResultError(
                    f"{item_label}.evidence cites guidance that does not apply to its affected targets"
                )
        _enum(item["current_tier"], f"{item_label}.current_tier", CURRENT_TIERS)
        _enum(item["recommended_tier"], f"{item_label}.recommended_tier", RECOMMENDED_TIERS)
        _validate_safe_direction(
            item["safe_direction"],
            f"{item_label}.safe_direction",
            allowed_paths=allowed_suggested_paths,
        )
        if basis in {"new_policy", "uncertain"} and decision != "decision_required":
            raise ResultError(f"{item_label} new or uncertain policy requires a decision")
        if decision == "ready" and basis not in EXISTING_BASES:
            raise ResultError(f"{item_label} ready recommendation lacks fixed existing intent")
        if strength == "essential":
            if basis not in EXISTING_BASES or decision != "ready" or claim != "observed_defect":
                raise ResultError(f"{item_label} essential strength requires a verified existing-contract defect")
            if not any(evidence_item["kind"] != "reasoning" for evidence_item in evidence):
                raise ResultError(f"{item_label} essential strength requires non-reasoning evidence")
        if claim == "observed_defect" and not any(
            evidence_item["kind"] != "reasoning" for evidence_item in evidence
        ):
            raise ResultError(f"{item_label} observed defect requires direct evidence")
        if item["kind"] in {"slow_feedback", "flakiness"} and claim == "observed_defect":
            measured = False
            for evidence_item in evidence:
                source_id = evidence_item["source_id"]
                if evidence_item["kind"] == "command" and source_id is not None:
                    command = commands[source_id]
                    if item["kind"] != "flakiness" or command["repetitions"] > 1:
                        measured = True
                elif evidence_item["kind"] in {"history", "caller_supplied"} and source_id is not None:
                    source = sources[source_id]
                    compatible_source = (
                        source["kind"] == "timing"
                        if item["kind"] == "slow_feedback"
                        else source["kind"] in {"failure", "history"}
                    )
                    if (
                        compatible_source
                        and source["freshness"] == "fresh"
                        and source["observed_at"] is not None
                    ):
                        measured = True
            if not measured:
                raise ResultError(f"{item_label} observed {item['kind']} lacks fresh measured evidence")
        expected_fingerprint = recommendation_fingerprint(item)
        if finalized and item["fingerprint"] != expected_fingerprint:
            raise ResultError(f"{item_label}.fingerprint is inconsistent")
        if expected_fingerprint in fingerprints:
            raise ResultError(f"{label} contains duplicate semantic recommendations")
        fingerprints.add(expected_fingerprint)
    return recommendations


def _recommendation_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    strength_order = {value: index for index, value in enumerate(STRENGTHS)}
    impact_order = {value: index for index, value in enumerate(IMPACTS)}
    return (
        strength_order[item["strength"]],
        impact_order[item["impact"]],
        item["kind"],
        item["affected_locations"][0]["path"],
        item["title"].casefold(),
        recommendation_fingerprint(item),
    )


def _status(
    coverage: dict[str, Any],
    inventory: dict[str, Any],
    guidance: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    limitations: list[dict[str, Any]],
) -> str:
    if (
        not coverage["complete"]
        or not inventory["complete"]
        or any(not chain["complete"] for chain in guidance)
        or any(item["material"] for item in limitations)
        or any(item["material"] for item in coverage["excluded"])
    ):
        return "INCOMPLETE"
    if any(item["strength"] == "essential" for item in recommendations):
        return "IMPROVEMENTS"
    return "PASS"


def _summary(
    conclusion: str,
    recommendations: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "conclusion": conclusion,
        "recommendation_counts": {
            strength: sum(item["strength"] == strength for item in recommendations)
            for strength in STRENGTHS
        },
        "ready": sum(item["decision"] == "ready" for item in recommendations),
        "decision_required": sum(item["decision"] == "decision_required" for item in recommendations),
        "observed_defects": sum(item["claim"] == "observed_defect" for item in recommendations),
        "inferred_risks": sum(item["claim"] == "inferred_risk" for item in recommendations),
    }


def _validate_summary(
    value: Any,
    recommendations: list[dict[str, Any]],
    label: str = "summary",
) -> dict[str, Any]:
    item = _object(
        value,
        label,
        {
            "conclusion",
            "recommendation_counts",
            "ready",
            "decision_required",
            "observed_defects",
            "inferred_risks",
        },
    )
    conclusion = _string(item["conclusion"], f"{label}.conclusion", 4000)
    expected = _summary(conclusion, recommendations)
    counts = _object(
        item["recommendation_counts"],
        f"{label}.recommendation_counts",
        set(STRENGTHS),
    )
    for strength in STRENGTHS:
        _integer(counts[strength], f"{label}.recommendation_counts.{strength}", 0, MAX_RECOMMENDATIONS)
    for field in ("ready", "decision_required", "observed_defects", "inferred_risks"):
        _integer(item[field], f"{label}.{field}", 0, MAX_RECOMMENDATIONS)
    if item != expected:
        raise ResultError(f"{label} derived counts are inconsistent")
    return item


def _merge_limitations(
    context_limitations: list[dict[str, Any]],
    draft_limitations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*context_limitations, *draft_limitations]:
        key = json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            result.append(copy.deepcopy(item))
    if len(result) > 2000:
        raise ResultError("combined limitations exceed 2000 entries")
    return result


def _validate_result(value: Any) -> dict[str, Any]:
    result = _object(
        value,
        "result",
        {
            "schema_version",
            "context_sha256",
            "status",
            "target",
            "inventory",
            "context_inventory",
            "guidance",
            "execution",
            "evidence_sources",
            "summary",
            "coverage",
            "recommendations",
            "limitations",
        },
    )
    if result["schema_version"] != SCHEMA_VERSION:
        raise ResultError(f"schema_version must be {SCHEMA_VERSION}")
    _digest(result["context_sha256"], "context_sha256")
    _enum(result["status"], "status", {"PASS", "IMPROVEMENTS", "INCOMPLETE"})
    target = _validate_target(result["target"])
    inventory = _validate_inventory(result["inventory"], target)
    context_inventory = _validate_context_inventory(result["context_inventory"], inventory)
    guidance = _validate_guidance(
        result["guidance"],
        target,
        inventory,
        resolver_context=False,
    )
    execution = _validate_execution(result["execution"], guidance)
    evidence_sources = _validate_evidence_sources(result["evidence_sources"])
    limitations = [
        _validate_limitation(item, f"limitations[{index}]")
        for index, item in enumerate(_array(result["limitations"], "limitations", 2000))
    ]
    material_inventory = any(
        item["material"] and item["code"] in INVENTORY_LIMITATION_CODES
        for item in limitations
    )
    if inventory["complete"] == material_inventory:
        raise ResultError("inventory.complete is inconsistent with resolver limitations")
    coverage = _validate_coverage(
        result["coverage"],
        target,
        inventory,
        context_inventory,
        limitations,
    )
    if coverage["complete"] and any(not chain["complete"] for chain in guidance):
        raise ResultError("coverage.complete cannot hide incomplete guidance")
    recommendations = _validate_recommendations(
        result["recommendations"],
        target=target,
        inventory=inventory,
        context_inventory=context_inventory,
        guidance=guidance,
        execution=execution,
        evidence_sources=evidence_sources,
        coverage=coverage,
        finalized=True,
    )
    if recommendations != sorted(recommendations, key=_recommendation_sort_key):
        raise ResultError("recommendations are not in canonical order")
    expected_status = _status(coverage, inventory, guidance, recommendations, limitations)
    if result["status"] != expected_status:
        raise ResultError(f"status must be {expected_status}")
    _validate_summary(result["summary"], recommendations)
    _bounded_json_result_text(result)
    return result


def finalize(context_value: Any, draft_value: Any) -> dict[str, Any]:
    context = _validate_context(context_value)
    _verify_context_fresh(context)
    draft = _object(
        draft_value,
        "draft",
        {"summary", "coverage", "recommendations", "limitations"},
    )
    summary_draft = _object(draft["summary"], "draft.summary", {"conclusion"})
    conclusion = _string(summary_draft["conclusion"], "draft.summary.conclusion", 4000)
    draft_limitations = [
        _validate_limitation(item, f"draft.limitations[{index}]")
        for index, item in enumerate(_array(draft["limitations"], "draft.limitations", 2000))
    ]
    allowed_draft_paths = (
        {item["path"] for item in context["inventory"]["files"]}
        | {item["path"] for item in context["context_inventory"]}
        | {
            item["path"]
            for item in context["target"]["requested"]
            if item["kind"] in {"directory", "project"}
        }
    )
    for index, item in enumerate(draft_limitations):
        if not set(item["affected_paths"]) <= allowed_draft_paths:
            raise ResultError(f"draft.limitations[{index}] expands the resolver-owned boundary")
    limitations = _merge_limitations(context["limitations"], draft_limitations)
    coverage = copy.deepcopy(
        _validate_coverage(
            draft["coverage"],
            context["target"],
            context["inventory"],
            context["context_inventory"],
            limitations,
            "draft.coverage",
        )
    )
    guidance = _result_guidance(context)
    if coverage["complete"] and any(not chain["complete"] for chain in guidance):
        raise ResultError("draft.coverage.complete cannot hide incomplete guidance")
    recommendations = copy.deepcopy(
        _validate_recommendations(
            draft["recommendations"],
            target=context["target"],
            inventory=context["inventory"],
            context_inventory=context["context_inventory"],
            guidance=guidance,
            execution=context["execution"],
            evidence_sources=context["evidence_sources"],
            coverage=coverage,
            finalized=False,
            label="draft.recommendations",
        )
    )
    recommendations.sort(key=_recommendation_sort_key)
    for index, item in enumerate(recommendations, 1):
        item["recommendation_id"] = f"R{index:03d}"
        item["fingerprint"] = recommendation_fingerprint(item)
    result = {
        "schema_version": SCHEMA_VERSION,
        "context_sha256": _sha256_json(context),
        "status": _status(
            coverage,
            context["inventory"],
            guidance,
            recommendations,
            limitations,
        ),
        "target": copy.deepcopy(context["target"]),
        "inventory": copy.deepcopy(context["inventory"]),
        "context_inventory": copy.deepcopy(context["context_inventory"]),
        "guidance": guidance,
        "execution": copy.deepcopy(context["execution"]),
        "evidence_sources": copy.deepcopy(context["evidence_sources"]),
        "summary": _summary(conclusion, recommendations),
        "coverage": coverage,
        "recommendations": recommendations,
        "limitations": limitations,
    }
    return _validate_result(result)


def _display(value: str) -> str:
    pieces: list[str] = []
    for character in value:
        category = unicodedata.category(character)
        if character == "\\" or category.startswith("C") or category in {"Zl", "Zp"}:
            pieces.append(json.dumps(character, ensure_ascii=True)[1:-1])
        elif character in "`*_{}[]()#+-.!|":
            pieces.append(f"\\{character}")
        else:
            pieces.append(character)
    return (
        "".join(pieces)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _location_text(location: dict[str, Any]) -> str:
    path = _display(location["path"])
    if location["start_line"] is None:
        return path
    if location["start_line"] == location["end_line"]:
        return f"{path}:{location['start_line']}"
    return f"{path}:{location['start_line']}-{location['end_line']}"


def render_human(result: dict[str, Any]) -> str:
    result = _validate_result(result)
    summary = result["summary"]
    lines = [
        f"Verification harness audit: {result['status']}",
        "",
        _display(summary["conclusion"]),
        "",
        "Summary",
        f"- Essential: {summary['recommendation_counts']['essential']}",
        f"- Strong: {summary['recommendation_counts']['strong']}",
        f"- Moderate: {summary['recommendation_counts']['moderate']}",
        f"- Optional: {summary['recommendation_counts']['optional']}",
        f"- Ready: {summary['ready']}",
        f"- Decision required: {summary['decision_required']}",
        f"- Observed defects: {summary['observed_defects']}",
        f"- Inferred risks: {summary['inferred_risks']}",
    ]
    if result["recommendations"]:
        lines.extend(["", "Recommendations"])
        for item in result["recommendations"]:
            lines.extend(
                [
                    "",
                    f"{item['recommendation_id']} [{item['strength']}/{item['impact']}/{item['confidence']}] {_display(item['title'])}",
                    "- Affected locations:",
                ]
            )
            lines.extend(
                f"  - {_location_text(location)}"
                for location in item["affected_locations"]
            )
            lines.extend(
                [
                    f"- Decision: {item['decision']} — {_display(item['decision_reason'])}",
                    f"- Claim: {item['claim']}; basis: {item['basis']}",
                    f"- Basis reference: {_display(item['basis_reference'])}",
                    f"- Tier: {item['current_tier']} → {item['recommended_tier']}",
                    f"- Problem: {_display(item['problem'])}",
                    f"- Reason: {_display(item['reason'])}",
                    f"- Impact: {_display(item['impact_summary'])}",
                    "- Evidence:",
                ]
            )
            for evidence in item["evidence"]:
                evidence_origin = (
                    _location_text(evidence["location"])
                    if evidence["location"] is not None
                    else f"source {evidence['source_id']}"
                    if evidence["source_id"] is not None
                    else "reasoning"
                )
                lines.append(
                    f"  - [{evidence['kind']}; {evidence_origin}] {_display(evidence['description'])}"
                )
            lines.extend(
                [
                    f"- Safe direction: {_display(item['safe_direction']['outcome'])}",
                    "- Acceptance evidence:",
                ]
            )
            lines.extend(
                f"  - {_display(value)}"
                for value in item["safe_direction"]["acceptance_evidence"]
            )
            if item["safe_direction"]["alternatives"]:
                lines.append("- Alternatives:")
                lines.extend(
                    f"  - {_display(value)}"
                    for value in item["safe_direction"]["alternatives"]
                )
    lines.extend(
        [
            "",
            "Coverage",
            f"- Requested targets inspected: {len(result['coverage']['inspected_targets'])}/{len(result['target']['requested'])}",
            f"- Harness paths: {len(result['coverage']['inspected_harness_paths'])}",
            f"- Non-harness paths: {len(result['coverage']['classified_non_harness_paths'])}",
            f"- Excluded paths: {len(result['coverage']['excluded'])}",
            f"- Context paths inspected: {len(result['coverage']['context_paths'])}",
            f"- Complete: {'yes' if result['coverage']['complete'] else 'no'}",
        ]
    )
    for item in result["coverage"]["excluded"]:
        marker = "material" if item["material"] else "non-material"
        lines.append(
            f"- Excluded {_display(item['path'])} [{marker}]: {_display(item['reason'])}"
        )
    if result["limitations"]:
        lines.extend(["", "Limitations"])
        for item in result["limitations"]:
            marker = "material" if item["material"] else "non-material"
            lines.append(f"- [{marker}] {_display(item['message'])}")
    return "\n".join(lines)


def _json_result_text(result: dict[str, Any]) -> str:
    _assert_bounded_json(result, "canonical result")
    try:
        text = json.dumps(
            result,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (RecursionError, UnicodeEncodeError, ValueError) as exc:
        raise ResultError(f"canonical result cannot be rendered: {exc}") from exc
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("`", "\\u0060")
    )


def _bounded_json_result_text(result: dict[str, Any]) -> str:
    text = _json_result_text(result)
    if len((text + "\n").encode("utf-8")) > MAX_JSON_BYTES:
        raise ResultError("canonical result exceeds the machine-readable size ceiling")
    return text


def _format_result(result: dict[str, Any], output_format: str) -> str:
    json_text = _bounded_json_result_text(result)
    if output_format == "json":
        return json_text
    human = render_human(result)
    if output_format == "human":
        return human
    return f"{human}\n\nCanonical JSON\n```json\n{json_text}\n```"


def _input_file_identities(input_paths: list[Path]) -> set[tuple[int, int]]:
    identities: set[tuple[int, int]] = set()
    for path in input_paths:
        with _bound_read_descriptor(path, "input alias check") as (_, metadata):
            identities.add(_file_identity(metadata))
    return identities


def _write_descriptor(descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise ResultError("output write made no progress")
        remaining = remaining[written:]
    os.fsync(descriptor)


def _write_output_posix(
    path: Path,
    data: bytes,
    overwrite: bool,
    input_identities: set[tuple[int, int]],
) -> None:
    with _posix_bound_parent(path) as (parent, name, absolute):
        try:
            existing = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        except OSError as exc:
            raise ResultError(f"cannot inspect output {absolute}: {exc}") from exc
        if existing is not None:
            if not overwrite:
                raise ResultError(f"output already exists: {absolute}")
            if (
                not stat.S_ISREG(existing.st_mode)
                or existing.st_nlink != 1
                or _file_identity(existing) in input_identities
            ):
                raise ResultError(f"refusing unsafe output replacement: {absolute}")
            flags = (
                os.O_WRONLY
                | os.O_NOFOLLOW
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            try:
                descriptor = os.open(name, flags, dir_fd=parent)
            except OSError as exc:
                raise ResultError(f"cannot safely open output {absolute}: {exc}") from exc
            metadata = os.fstat(descriptor)
            if (
                _file_open_binding_signature(metadata)
                != _file_open_binding_signature(existing)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or _file_identity(metadata) in input_identities
            ):
                os.close(descriptor)
                raise ResultError(f"refusing unsafe output replacement: {absolute}")
            try:
                os.ftruncate(descriptor, 0)
                _write_descriptor(descriptor, data)
                final_metadata = os.fstat(descriptor)
                final_entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (
                    final_entry.st_nlink != 1
                    or final_metadata.st_nlink != 1
                    or _file_identity(final_entry) != _file_identity(final_metadata)
                ):
                    raise ResultError(f"output entry changed while being written: {absolute}")
            finally:
                os.close(descriptor)
            return
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=parent)
        except OSError as exc:
            raise ResultError(f"cannot create output {absolute}: {exc}") from exc
        metadata = os.fstat(descriptor)
        try:
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ResultError(f"refusing unsafe new output: {absolute}")
            _write_descriptor(descriptor, data)
            final_metadata = os.fstat(descriptor)
            final_entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (
                final_entry.st_nlink != 1
                or final_metadata.st_nlink != 1
                or _file_identity(final_entry) != _file_identity(final_metadata)
            ):
                raise ResultError(f"output entry changed while being written: {absolute}")
        finally:
            os.close(descriptor)


def _write_output_windows(
    path: Path,
    data: bytes,
    overwrite: bool,
    input_identities: set[tuple[int, int]],
) -> None:
    with _windows_locked_parent(path) as (absolute, parent_handle):
        try:
            preflight = absolute.lstat()
        except FileNotFoundError:
            preflight = None
        except OSError as exc:
            raise ResultError(f"cannot inspect output {absolute}: {exc}") from exc
        if preflight is not None and not overwrite:
            raise ResultError(f"output already exists: {absolute}")
        creation = 3 if preflight is not None else 1
        try:
            descriptor = _windows_file_descriptor(
                absolute,
                parent_handle=parent_handle,
                access=0x40000000 | 0x00000080,
                creation=creation,
                descriptor_flags=os.O_WRONLY | getattr(os, "O_BINARY", 0),
            )
        except OSError as exc:
            action = "open" if preflight is not None else "create"
            raise ResultError(f"cannot {action} output {absolute}: {exc}") from exc
        created = preflight is None
        try:
            metadata = os.fstat(descriptor)
            if preflight is not None and _file_open_binding_signature(metadata) != (
                _file_open_binding_signature(preflight)
            ):
                raise ResultError(f"output changed before being opened: {absolute}")
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or _file_identity(metadata) in input_identities
            ):
                raise ResultError(f"refusing unsafe output replacement: {absolute}")
            if not created:
                os.ftruncate(descriptor, 0)
            _write_descriptor(descriptor, data)
            final_metadata = os.fstat(descriptor)
            verification = _windows_file_descriptor(
                absolute,
                parent_handle=parent_handle,
                access=0x00000080,
                creation=3,
                descriptor_flags=os.O_RDONLY | getattr(os, "O_BINARY", 0),
            )
            try:
                final_entry = os.fstat(verification)
            finally:
                os.close(verification)
            if (
                final_metadata.st_nlink != 1
                or _file_open_binding_signature(final_entry)
                != _file_open_binding_signature(final_metadata)
            ):
                raise ResultError(f"output entry changed while being written: {absolute}")
        finally:
            os.close(descriptor)


def _write_stdout_utf8(text: str) -> None:
    data = (text + "\n").encode("utf-8")
    binary = getattr(sys.stdout, "buffer", None)
    if binary is not None:
        binary.write(data)
        binary.flush()
        return
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _write_output(
    text: str,
    destination: str | None,
    overwrite: bool,
    *,
    input_paths: list[Path],
) -> None:
    if destination is None:
        _write_stdout_utf8(text)
        return
    path = _filesystem_path(destination, "output path")
    if any(path.absolute() == source.absolute() for source in input_paths):
        raise ResultError("output must not replace or alias an input file")
    input_identities = _input_file_identities(input_paths)
    data = (text + "\n").encode("utf-8")
    if os.name == "nt":
        _write_output_windows(path, data, overwrite, input_identities)
    else:
        _write_output_posix(path, data, overwrite, input_identities)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    finalize_parser = commands.add_parser("finalize")
    finalize_parser.add_argument("--context", required=True)
    finalize_parser.add_argument("--draft", required=True)
    finalize_parser.add_argument("--format", choices=("human", "json", "both"), default="human")
    finalize_parser.add_argument("--output")
    finalize_parser.add_argument("--overwrite", action="store_true")
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("--input", default="-")
    render_parser = commands.add_parser("render")
    render_parser.add_argument("--input", default="-")
    render_parser.add_argument("--format", choices=("human", "json", "both"), default="human")
    render_parser.add_argument("--output")
    render_parser.add_argument("--overwrite", action="store_true")
    return parser


def _input_paths(*values: str) -> list[Path]:
    return [
        _filesystem_path(value, "input path")
        for value in values
        if value != "-"
    ]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "finalize":
            result = finalize(_read_json(args.context), _read_json(args.draft))
            _write_output(
                _format_result(result, args.format),
                args.output,
                args.overwrite,
                input_paths=_input_paths(args.context, args.draft),
            )
        elif args.command == "validate":
            _validate_result(_read_json(args.input))
            _write_stdout_utf8("valid verification-harness-audit result")
        else:
            result = _validate_result(_read_json(args.input))
            _write_output(
                _format_result(result, args.format),
                args.output,
                args.overwrite,
                input_paths=_input_paths(args.input),
            )
        return 0
    except (ResultError, OSError) as exc:
        print(f"verification-harness result: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
