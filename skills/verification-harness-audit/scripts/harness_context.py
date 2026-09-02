#!/usr/bin/env python3
"""Resolve a bounded local verification-harness audit context."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from typing import Any


SCHEMA_VERSION = "1.0.0"
SKILL_VERSION = "1.0.0"

DEFAULT_MAX_FILES = 5000
DEFAULT_MAX_FILE_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_TRAVERSAL_ENTRIES = 50000
DEFAULT_MAX_CONTEXT_FILES = 256
DEFAULT_MAX_CONTEXT_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_GUIDANCE_BYTES = 128 * 1024

MAX_FILES = 20000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_TRAVERSAL_ENTRIES = 1000000
MAX_CONTEXT_FILES = 5000
MAX_CONTEXT_BYTES = 64 * 1024 * 1024
MAX_GUIDANCE_BYTES = 1024 * 1024
MAX_GUIDANCE_SOURCE_BYTES = 1024 * 1024
MAX_GUIDANCE_SOURCES_PER_CHAIN = 256
MAX_REQUESTED_TARGETS = 1000
MAX_GUIDANCE_CHAINS = MAX_FILES + MAX_REQUESTED_TARGETS
MAX_GUIDANCE_PATHS_PER_CHAIN = MAX_FILES + MAX_REQUESTED_TARGETS
MAX_PATH_BYTES = 4 * 1024 * 1024
MAX_CONTEXT_JSON_BYTES = 16 * 1024 * 1024
MAX_INPUT_JSON_BYTES = 1024 * 1024
MAX_LIMITATIONS = 128
SAFE_POSIX_DIR_FD = (
    os.name == "posix"
    and hasattr(os, "O_NOFOLLOW")
    and hasattr(os, "O_DIRECTORY")
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
)
MAX_LIMITATION_PATHS = 20000

CONTROL = re.compile(r"[\x00-\x1f\x7f]")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RFC3339 = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?:\.[0-9]+)?(?P<zone>Z|(?P<sign>[+-])(?P<offset_hour>[0-9]{2}):(?P<offset_minute>[0-9]{2}))$"
)
FOCUS_KINDS = {
    "line_range",
    "symbol",
    "test_case",
    "ci_job",
    "configuration_section",
    "command",
    "other",
}


class ContextError(ValueError):
    """Raised when a context cannot be resolved safely."""


def _text(value: Any, label: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ContextError(f"{label} must be a non-empty string of at most {maximum} characters")
    if CONTROL.search(value):
        raise ContextError(f"{label} must not contain control characters")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ContextError(f"{label} must be valid UTF-8") from exc
    return value


def _filesystem_path(value: Any, label: str, *, expand_user: bool = False) -> Path:
    text = _text(value, label, maximum=8192)
    path = Path(text)
    return path.expanduser() if expand_user else path


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
            raise ContextError(f"refusing link-like path component: {current}")


@contextlib.contextmanager
def _posix_bound_parent(path: Path):
    """Yield a directory fd and basename without following ancestor links."""
    if not SAFE_POSIX_DIR_FD:
        raise ContextError("safe descriptor-relative path handling is unavailable")
    absolute = path.absolute()
    if not absolute.name:
        raise ContextError(f"path must name a file: {path}")
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
                raise ContextError(
                    f"cannot bind safe parent directory {current}: {exc}"
                ) from exc
            os.close(descriptor)
            descriptor = child
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise ContextError(f"input/output parent is not a directory: {current}")
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
        raise ContextError("Windows handle operation requested on another platform")
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


def _windows_relative_handle(
    parent_handle: int,
    name: str,
    *,
    access: int,
    creation: int,
    display_path: Path,
    directory: bool = False,
) -> int:
    """Open or create one non-link entry relative to a bound parent handle."""
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
        raise ContextError(f"unsupported Windows create disposition: {creation}")
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
        0x00000020
        | (0x00000001 if directory else 0x00000040)
        | 0x00200000,
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


def _windows_handle_attributes(handle: int) -> tuple[int, int, int, int]:
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
    return (
        int(information.attributes),
        int(information.links),
        int(information.volume_serial),
        (int(information.file_index_high) << 32) | int(information.file_index_low),
    )


@contextlib.contextmanager
def _windows_locked_parent(path: Path):
    """Verify the parent chain and yield its bound final directory handle."""
    absolute = path.absolute()
    _assert_no_link_components(absolute, include_final=False)
    if not absolute.name:
        raise ContextError(f"path must name a file: {path}")
    current = Path(absolute.anchor)
    handles: list[int] = []
    try:
        handle = _windows_create_handle(
            current,
            access=0x00000080,
            creation=3,
            flags=0x02000000 | 0x00200000,
        )
        try:
            attributes, _, _, _ = _windows_handle_attributes(handle)
        except Exception:
            _windows_close_handle(handle)
            raise
        if attributes & 0x00000400 or not attributes & 0x00000010:
            _windows_close_handle(handle)
            raise ContextError(
                f"refusing link-like or non-directory parent: {current}"
            )
        handles.append(handle)
        for part in absolute.parent.parts[1:]:
            current /= part
            child = _windows_relative_handle(
                handles[-1],
                part,
                access=0x00000080,
                creation=3,
                display_path=current,
                directory=True,
            )
            try:
                attributes, _, _, _ = _windows_handle_attributes(child)
            except Exception:
                _windows_close_handle(child)
                raise
            if attributes & 0x00000400 or not attributes & 0x00000010:
                _windows_close_handle(child)
                raise ContextError(
                    f"refusing link-like or non-directory parent: {current}"
                )
            handles.append(child)
        bound_parent = _windows_handle_path(handles[-1])
        yield bound_parent / absolute.name, handles[-1]
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
        attributes, _, _, _ = _windows_handle_attributes(handle)
        if attributes & 0x00000400 or attributes & 0x00000010:
            raise ContextError(f"refusing link-like or non-file path: {path}")
        return msvcrt.open_osfhandle(handle, descriptor_flags)
    except Exception:
        _windows_close_handle(handle)
        raise


def _filesystem_alias_identity(
    path: Path, metadata: os.stat_result | None = None
) -> tuple[Any, ...]:
    """Return an identity stable across Windows hard-link path aliases."""
    if os.name != "nt":
        return _filesystem_identity(path, metadata)
    path_metadata = metadata if metadata is not None else path.lstat()
    with _windows_locked_parent(path) as (absolute, parent_handle):
        try:
            handle = _windows_relative_handle(
                parent_handle,
                absolute.name,
                access=0x00000080,
                creation=3,
                display_path=absolute,
                directory=stat.S_ISDIR(path_metadata.st_mode),
            )
        except OSError as exc:
            raise ContextError(f"cannot identify filesystem path {path}: {exc}") from exc
        try:
            attributes, _, volume, file_index = _windows_handle_attributes(handle)
            if attributes & 0x00000400:
                raise ContextError(f"refusing link-like filesystem alias: {path}")
            return ("windows_file", volume, file_index)
        finally:
            _windows_close_handle(handle)


@contextlib.contextmanager
def _bound_read_descriptor(path: Path):
    """Open one regular file while binding all ancestors to trusted objects."""
    if os.name == "nt":
        with _windows_locked_parent(path) as (absolute, parent_handle):
            try:
                descriptor = _windows_file_descriptor(
                    absolute,
                    parent_handle=parent_handle,
                    access=0x80000000,
                    creation=3,
                    descriptor_flags=os.O_RDONLY | getattr(os, "O_BINARY", 0),
                )
            except OSError as exc:
                raise ContextError(f"cannot open {path}: {exc}") from exc
            try:
                yield descriptor, absolute
            finally:
                os.close(descriptor)
        return
    with _posix_bound_parent(path) as (parent, name, absolute):
        flags = (
            os.O_RDONLY
            | os.O_NOFOLLOW
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            descriptor = os.open(name, flags, dir_fd=parent)
        except OSError as exc:
            raise ContextError(f"cannot open {absolute}: {exc}") from exc
        try:
            yield descriptor, absolute
        finally:
            os.close(descriptor)


def _canonical_path(value: Any, *, allow_root: bool = False) -> str:
    text = _text(value, "repository path")
    if "\\" in text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise ContextError(f"repository path is not canonical: {text!r}")
    if text == ".":
        if allow_root:
            return text
        raise ContextError("the repository root is not valid in this field")
    if text.endswith("/") or "//" in text:
        raise ContextError(f"repository path is not canonical: {text!r}")
    parts = PurePosixPath(text).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ContextError(f"repository path is not canonical: {text!r}")
    canonical = PurePosixPath(*parts).as_posix()
    if canonical != text:
        raise ContextError(f"repository path is not canonical: {text!r}")
    return canonical


def _safe_repo_path(root: Path, relative: str) -> Path:
    canonical = _canonical_path(relative, allow_root=True)
    current = root
    if canonical == ".":
        return current
    parts = PurePosixPath(canonical).parts
    for index, part in enumerate(parts):
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ContextError(f"cannot inspect {canonical}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode) or _is_link_like(current):
            raise ContextError(f"refusing link-like repository path: {canonical}")
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise ContextError(f"non-directory path component in {canonical}")
    return current


def _relative(root: Path, path: Path) -> str:
    try:
        value = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ContextError(f"path escaped the repository root: {path}") from exc
    return _canonical_path(value, allow_root=True)


def _filesystem_identity(path: Path, metadata: os.stat_result | None = None) -> tuple[Any, ...]:
    try:
        value = metadata if metadata is not None else path.stat()
    except OSError as exc:
        raise ContextError(f"cannot identify filesystem path {path}: {exc}") from exc
    device = int(getattr(value, "st_dev", 0))
    inode = int(getattr(value, "st_ino", 0))
    if inode:
        return ("inode", device, inode)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ContextError(f"cannot identify filesystem path {path}: {exc}") from exc
    return (
        "path",
        os.path.normcase(str(resolved)),
    )


def _filesystem_snapshot(
    path: Path, metadata: os.stat_result | None = None
) -> tuple[Any, ...]:
    try:
        value = metadata if metadata is not None else path.stat()
    except OSError as exc:
        raise ContextError(f"cannot snapshot filesystem path {path}: {exc}") from exc
    return (
        _filesystem_identity(path, value),
        int(value.st_size),
        int(getattr(value, "st_mtime_ns", int(value.st_mtime * 1_000_000_000))),
        int(getattr(value, "st_ctime_ns", int(value.st_ctime * 1_000_000_000))),
    )


def _filesystem_open_binding(
    path: Path, metadata: os.stat_result
) -> tuple[Any, ...]:
    """Return the portable identity shared by path and descriptor stat APIs."""
    return (
        _filesystem_identity(path, metadata),
        stat.S_IFMT(metadata.st_mode),
        int(metadata.st_size),
    )


def _path_within(candidate: Path, boundary: Path) -> bool:
    try:
        candidate_text = os.path.normcase(str(candidate.resolve(strict=True)))
        boundary_text = os.path.normcase(str(boundary.resolve(strict=True)))
        return os.path.commonpath([candidate_text, boundary_text]) == boundary_text
    except (OSError, ValueError):
        return False


def _read_regular(
    path: Path,
    maximum: int,
    *,
    expected_snapshot: tuple[Any, ...] | None = None,
    require_single_link: bool = False,
) -> tuple[os.stat_result, bytes]:
    with _bound_read_descriptor(path) as (descriptor, bound_path):
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ContextError(f"not a regular file: {bound_path}")
        if expected_snapshot is not None:
            expected_binding = (
                expected_snapshot[0],
                stat.S_IFREG,
                expected_snapshot[1],
            )
            if _filesystem_open_binding(bound_path, metadata) != expected_binding:
                raise ContextError(f"file snapshot changed before inspection: {bound_path}")
        if require_single_link and metadata.st_nlink != 1:
            raise ContextError(
                f"authority input became hard-linked before inspection: {bound_path}"
            )
        if metadata.st_size > maximum:
            raise ContextError(f"file exceeds {maximum} bytes: {bound_path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise ContextError(f"file exceeds {maximum} bytes: {bound_path}")
        final_metadata = os.fstat(descriptor)
        initial_signature = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            getattr(metadata, "st_mtime_ns", metadata.st_mtime),
            getattr(metadata, "st_ctime_ns", metadata.st_ctime),
        )
        final_signature = (
            final_metadata.st_dev,
            final_metadata.st_ino,
            final_metadata.st_size,
            getattr(final_metadata, "st_mtime_ns", final_metadata.st_mtime),
            getattr(final_metadata, "st_ctime_ns", final_metadata.st_ctime),
        )
        if final_signature != initial_signature:
            raise ContextError(f"file changed during inspection: {bound_path}")
        if expected_snapshot is not None:
            try:
                path_metadata = bound_path.lstat()
            except OSError as exc:
                raise ContextError(
                    f"file snapshot changed during inspection: {bound_path}"
                ) from exc
            if _is_link_like(bound_path) or (
                _filesystem_snapshot(bound_path, path_metadata) != expected_snapshot
            ):
                raise ContextError(
                    f"file snapshot changed during inspection: {bound_path}"
                )
        return final_metadata, b"".join(chunks)


def _canonical_text(data: bytes, label: str) -> tuple[str, bytes]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContextError(f"{label} is not UTF-8 text") from exc
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized, normalized.encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _limitation(code: str, message: str, paths: list[str], material: bool) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "affected_paths": sorted(set(paths))[:MAX_LIMITATION_PATHS],
        "material": material,
    }


def _dedupe_limitations(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        key = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            result.append(value)
    if len(result) <= MAX_LIMITATIONS:
        return result
    omitted = result[MAX_LIMITATIONS - 1 :]
    return [
        *result[: MAX_LIMITATIONS - 1],
        _limitation(
            "scope_truncated",
            f"Resolver collapsed {len(omitted)} additional limitation records at the canonical ceiling.",
            [],
            any(item["material"] for item in omitted),
        ),
    ]


def _git_root(root: Path) -> bool:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0:
        return False
    try:
        discovered = Path(completed.stdout.decode("utf-8", "strict").strip()).resolve()
    except (UnicodeDecodeError, OSError):
        return False
    return discovered == root


def _decode_git_paths(data: bytes) -> set[str]:
    result: set[str] = set()
    for raw in data.split(b"\0"):
        if not raw:
            continue
        try:
            result.add(_canonical_path(raw.decode("utf-8", "strict")))
        except (UnicodeDecodeError, ContextError) as exc:
            raise ContextError("Git returned a non-UTF-8 or non-canonical path") from exc
    return result


def _git_ignored(root: Path, paths: list[str]) -> set[str]:
    ignored: set[str] = set()
    for offset in range(0, len(paths), 512):
        chunk = paths[offset : offset + 512]
        payload = b"\0".join(item.encode("utf-8") for item in chunk) + b"\0"
        try:
            completed = subprocess.run(
                ["git", "-C", str(root), "check-ignore", "-z", "--stdin"],
                input=payload,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ContextError(f"Git ignore classification failed: {exc}") from exc
        if completed.returncode not in {0, 1}:
            detail = completed.stderr.decode("utf-8", "replace").strip()
            raise ContextError(f"Git ignore classification failed: {detail or completed.returncode}")
        ignored.update(_decode_git_paths(completed.stdout))
    return ignored


def _git_tracked(root: Path, paths: list[str]) -> set[str]:
    tracked: set[str] = set()
    chunks: list[list[str]] = []
    current: list[str] = []
    current_bytes = 0
    for path in paths:
        size = len(path.encode("utf-8")) + 1
        if current and (len(current) >= 256 or current_bytes + size > 16384):
            chunks.append(current)
            current = []
            current_bytes = 0
        current.append(path)
        current_bytes += size
    if current:
        chunks.append(current)
    environment = dict(os.environ)
    environment["GIT_LITERAL_PATHSPECS"] = "1"
    for chunk in chunks:
        try:
            completed = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z", "--", *chunk],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ContextError(f"Git tracking classification failed: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip()
            raise ContextError(f"Git tracking classification failed: {detail or completed.returncode}")
        tracked.update(_decode_git_paths(completed.stdout))
    return tracked


def _minimal_roots(paths: list[str]) -> list[str]:
    result: list[str] = []
    for candidate in sorted(set(paths), key=lambda item: (item.count("/"), item)):
        if candidate == ".":
            return ["."]
        if any(candidate == root or candidate.startswith(f"{root}/") for root in result):
            continue
        result.append(candidate)
    return result


def _bounded_directory_entries(
    directory: Path, maximum_entries: int
) -> tuple[list[os.DirEntry[str]], int, bool]:
    if maximum_entries <= 0:
        return [], 0, False
    entries: list[os.DirEntry[str]] = []
    with os.scandir(directory) as iterator:
        for entry in iterator:
            entries.append(entry)
            if len(entries) == maximum_entries:
                # Proving exhaustion would require consuming one more entry.
                # Stop at the hard ceiling and do not return an arbitrary
                # filesystem-order subset from this directory.
                return [], len(entries), False
    return sorted(entries, key=lambda item: item.name), len(entries), True


def _enumerate_broad(
    root: Path,
    roots: list[str],
    *,
    maximum_entries: int,
    maximum_candidates: int,
    git_enabled: bool,
    excluded_candidates: set[str],
    excluded_identities: dict[tuple[Any, ...], str],
) -> tuple[list[str], int, list[dict[str, Any]], bool]:
    pending = _minimal_roots(roots)
    files: list[str] = []
    ignored_paths: list[str] = []
    link_paths: list[str] = []
    special_paths: list[str] = []
    limitations: list[dict[str, Any]] = []
    seen_file_identities = dict(excluded_identities)
    traversed = 0
    path_bytes = 0
    complete = True
    git_active = git_enabled

    while pending and complete:
        current = pending.pop(0)
        directory = root if current == "." else _safe_repo_path(root, current)
        remaining = maximum_entries - traversed
        try:
            entries, consumed_entries, exhausted = _bounded_directory_entries(
                directory,
                remaining,
            )
        except OSError as exc:
            limitations.append(
                _limitation(
                    "target_unreadable",
                    f"Cannot enumerate selected directory {current}: {exc}",
                    [] if current == "." else [current],
                    True,
                )
            )
            continue
        traversed += consumed_entries
        if not exhausted:
            complete = False
            break
        relative_entries: list[tuple[os.DirEntry[str], str]] = []
        for entry in entries:
            relative = _relative(root, Path(entry.path))
            encoded = len(relative.encode("utf-8"))
            if path_bytes + encoded > MAX_PATH_BYTES:
                complete = False
                break
            path_bytes += encoded
            relative_entries.append((entry, relative))

        ignored: set[str] = set()
        if git_active and relative_entries:
            try:
                ignored = _git_ignored(root, [item[1] for item in relative_entries])
            except ContextError as exc:
                git_active = False
                limitations.append(_limitation("inventory_incomplete", str(exc), [], True))

        next_directories: list[str] = []
        for entry, relative in relative_entries:
            if entry.name == ".git":
                ignored_paths.append(relative)
                continue
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                limitations.append(
                    _limitation("target_unreadable", f"Cannot inspect {relative}: {exc}", [relative], True)
                )
                continue
            if stat.S_ISLNK(metadata.st_mode) or _is_link_like(Path(entry.path)):
                link_paths.append(relative)
                continue
            if relative in ignored:
                ignored_paths.append(relative)
                continue
            if stat.S_ISDIR(metadata.st_mode):
                next_directories.append(relative)
            elif stat.S_ISREG(metadata.st_mode):
                identity = _filesystem_alias_identity(Path(entry.path), metadata)
                if relative in excluded_candidates:
                    continue
                if identity in excluded_identities:
                    prior = excluded_identities[identity]
                    limitations.append(
                        _limitation(
                            "inventory_incomplete",
                            f"Explicit and broad filesystem aliases resolve to the same file: {prior} and {relative}.",
                            [prior, relative],
                            True,
                        )
                    )
                    continue
                if identity in seen_file_identities:
                    limitations.append(
                        _limitation(
                            "inventory_incomplete",
                            f"Filesystem aliases resolve to the same file: {seen_file_identities[identity]} and {relative}.",
                            [seen_file_identities[identity], relative],
                            True,
                        )
                    )
                    continue
                if len(files) >= maximum_candidates:
                    complete = False
                    break
                files.append(relative)
                seen_file_identities[identity] = relative
            else:
                special_paths.append(relative)
        pending.extend(next_directories)
        pending = sorted(set(pending))

    if not complete:
        limitations.append(
            _limitation(
                "scope_truncated",
                "Deterministic discovery reached a file, path-byte, or traversal ceiling before exhaustive enumeration.",
                [],
                True,
            )
        )
    if ignored_paths:
        limitations.append(
            _limitation(
                "ignored_path",
                f"Excluded {len(set(ignored_paths))} ignored or repository-metadata paths from broad discovery.",
                sorted(set(ignored_paths)),
                False,
            )
        )
    if link_paths:
        limitations.append(
            _limitation(
                "link_skipped",
                f"Skipped {len(set(link_paths))} link-like paths under the no-follow inventory policy.",
                sorted(set(link_paths)),
                False,
            )
        )
    if special_paths:
        limitations.append(
            _limitation(
                "target_unreadable",
                f"Skipped {len(set(special_paths))} non-regular filesystem entries.",
                sorted(set(special_paths)),
                False,
            )
        )
    return sorted(set(files)), traversed, limitations, git_active


def _tracking(
    root: Path, paths: list[str], git_enabled: bool
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if not git_enabled or not paths:
        return {path: "unknown" for path in paths}, []
    try:
        ignored = _git_ignored(root, paths)
        tracked = _git_tracked(root, paths)
    except ContextError as exc:
        return (
            {path: "unknown" for path in paths},
            [_limitation("inventory_incomplete", str(exc), [], True)],
        )
    return {
        path: "ignored" if path in ignored else "tracked" if path in tracked else "untracked"
        for path in paths
    }, []


def _file_record(
    root: Path,
    relative: str,
    tracking: str,
    *,
    inspect: bool,
    maximum_file_bytes: int,
    remaining_bytes: int,
) -> tuple[dict[str, Any], int, str | None, int | None]:
    path = _safe_repo_path(root, relative)
    try:
        metadata = path.lstat()
    except OSError as exc:
        return (
            {"path": relative, "bytes": 0, "sha256": None, "inspection_kind": "unreadable", "tracking": tracking},
            0,
            f"Cannot inspect {relative}: {exc}",
            None,
        )
    if not stat.S_ISREG(metadata.st_mode):
        return (
            {"path": relative, "bytes": 0, "sha256": None, "inspection_kind": "unreadable", "tracking": tracking},
            0,
            f"Target is not a regular file: {relative}",
            None,
        )
    if not inspect:
        oversized = metadata.st_size > maximum_file_bytes
        return (
            {
                "path": relative,
                "bytes": metadata.st_size,
                "sha256": None,
                "inspection_kind": "oversized" if oversized else "not_inspected",
                "tracking": tracking,
            },
            0,
            f"File exceeds the per-file inspection ceiling: {relative}" if oversized else None,
            None,
        )
    if metadata.st_size > maximum_file_bytes:
        return (
            {"path": relative, "bytes": metadata.st_size, "sha256": None, "inspection_kind": "oversized", "tracking": tracking},
            0,
            f"File exceeds the per-file inspection ceiling: {relative}",
            None,
        )
    if metadata.st_size > remaining_bytes:
        return (
            {"path": relative, "bytes": metadata.st_size, "sha256": None, "inspection_kind": "not_inspected", "tracking": tracking},
            0,
            f"Aggregate byte ceiling prevented inspection of {relative}",
            None,
        )
    try:
        _, data = _read_regular(
            path,
            min(maximum_file_bytes, remaining_bytes),
            expected_snapshot=_filesystem_snapshot(path, metadata),
        )
    except ContextError as exc:
        return (
            {"path": relative, "bytes": metadata.st_size, "sha256": None, "inspection_kind": "unreadable", "tracking": tracking},
            0,
            str(exc),
            None,
        )
    if b"\0" in data:
        return (
            {"path": relative, "bytes": len(data), "sha256": _sha256(data), "inspection_kind": "binary", "tracking": tracking},
            len(data),
            None,
            None,
        )
    try:
        text, canonical = _canonical_text(data, relative)
    except ContextError:
        return (
            {"path": relative, "bytes": len(data), "sha256": _sha256(data), "inspection_kind": "non_utf8", "tracking": tracking},
            len(data),
            None,
            None,
        )
    return (
        {"path": relative, "bytes": len(canonical), "sha256": _sha256(canonical), "inspection_kind": "text", "tracking": tracking},
        len(data),
        None,
        len(text.splitlines()),
    )


def _parse_part(value: str) -> dict[str, Any]:
    try:
        path, start, end = value.rsplit(":", 2)
        start_line = int(start)
        end_line = int(end)
    except (TypeError, ValueError) as exc:
        raise ContextError("parts must use PATH:START_LINE:END_LINE") from exc
    canonical = _canonical_path(path)
    if start_line < 1 or end_line < start_line or end_line > 100000000:
        raise ContextError("part line ranges must be positive, ordered, and representable")
    return {
        "kind": "part",
        "path": canonical,
        "start_line": start_line,
        "end_line": end_line,
        "focus": {"kind": "line_range", "value": f"{start_line}:{end_line}"},
    }


def _requested(args: argparse.Namespace, root: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for raw in args.paths or []:
        relative = _canonical_path(raw, allow_root=True)
        path = _safe_repo_path(root, relative)
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            kind = "project" if relative == "." else "directory"
        elif stat.S_ISREG(metadata.st_mode):
            kind = "file"
        else:
            raise ContextError(f"target is not a regular file or directory: {relative}")
        values.append(
            {"kind": kind, "path": relative, "start_line": None, "end_line": None, "focus": None}
        )
    for raw in args.parts or []:
        item = _parse_part(raw)
        path = _safe_repo_path(root, item["path"])
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ContextError(f"part target is not a regular file: {item['path']}")
        values.append(item)
    if not values:
        raise ContextError("select at least one --path or --part")
    if (args.focus_kind is None) != (args.focus_value is None):
        raise ContextError("--focus-kind and --focus-value must be supplied together")
    if args.focus_kind is not None:
        if len(values) != 1:
            raise ContextError("an explicit focus requires exactly one selected target")
        if args.focus_kind not in FOCUS_KINDS:
            raise ContextError(f"unsupported focus kind: {args.focus_kind}")
        values[0]["focus"] = {
            "kind": args.focus_kind,
            "value": _text(args.focus_value, "focus value", maximum=2000),
        }
    identities: dict[tuple[Any, ...], str] = {}
    for item in values:
        identity = _filesystem_alias_identity(_safe_repo_path(root, item["path"]))
        prior = identities.get(identity)
        if prior is not None and prior != item["path"]:
            raise ContextError(
                f"requested target aliases resolve to the same filesystem object: {prior} and {item['path']}"
            )
        identities[identity] = item["path"]
    unique: dict[str, dict[str, Any]] = {}
    for item in values:
        key = json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if key in unique:
            raise ContextError(f"duplicate requested target: {item['path']}")
        unique[key] = item
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            item["path"],
            item["kind"],
            item["start_line"] or 0,
            item["end_line"] or 0,
            json.dumps(item["focus"], sort_keys=True),
        ),
    )
    if len(ordered) > MAX_REQUESTED_TARGETS:
        raise ContextError(f"target selection exceeds {MAX_REQUESTED_TARGETS} entries")
    if sum(len(item["path"].encode("utf-8")) for item in ordered) > MAX_PATH_BYTES:
        raise ContextError("requested paths exceed the canonical path budget")
    return [{"target_id": f"T{index:03d}", **item} for index, item in enumerate(ordered, 1)]


def _owners(root: Path, requested: list[dict[str, Any]], path: str) -> list[str]:
    owners: list[str] = []
    candidate = _safe_repo_path(root, path)
    candidate_identity: tuple[Any, ...] | None = None
    for item in requested:
        if item["kind"] == "project":
            owners.append(item["target_id"])
        elif item["kind"] == "directory" and (
            path == item["path"] or path.startswith(f"{item['path']}/")
        ):
            owners.append(item["target_id"])
        elif item["kind"] == "directory":
            if _path_within(candidate, _safe_repo_path(root, item["path"])):
                owners.append(item["target_id"])
        elif item["kind"] in {"file", "part"}:
            if path == item["path"]:
                owners.append(item["target_id"])
            else:
                if candidate_identity is None:
                    candidate_identity = _filesystem_alias_identity(candidate)
                if candidate_identity == _filesystem_alias_identity(
                    _safe_repo_path(root, item["path"])
                ):
                    owners.append(item["target_id"])
    return owners


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


def _guidance_source(
    *, source_kind: str, path: str, revision: str | None, data: bytes
) -> dict[str, Any]:
    text, canonical = _canonical_text(data, path)
    return {
        "source_kind": source_kind,
        "path": path,
        "revision": revision,
        "sha256": _sha256(canonical),
        "bytes": len(canonical),
        "lines": len(text.splitlines()),
        "loaded": True,
        "content": text,
    }


def _read_guidance(root: Path, relative: str) -> dict[str, Any] | None:
    path = root / PurePosixPath(relative)
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ContextError(f"cannot inspect guidance {relative}: {exc}") from exc
    safe = _safe_repo_path(root, relative)
    try:
        metadata = safe.lstat()
    except OSError as exc:
        raise ContextError(f"cannot inspect guidance {relative}: {exc}") from exc
    _, data = _read_regular(
        safe,
        MAX_GUIDANCE_SOURCE_BYTES,
        expected_snapshot=_filesystem_snapshot(safe, metadata),
    )
    return _guidance_source(source_kind="repository", path=relative, revision=None, data=data)


def _external_file(
    root: Path, value: str, label: str
) -> tuple[Path, tuple[Any, ...]]:
    path = _filesystem_path(value, label, expand_user=True)
    if not path.is_absolute():
        raise ContextError(f"{label} must be an absolute path")
    _assert_no_link_components(path, include_final=True)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ContextError(f"cannot resolve {label}: {exc}") from exc
    try:
        resolved.relative_to(root)
    except ValueError:
        try:
            metadata = resolved.stat()
        except OSError as exc:
            raise ContextError(f"cannot inspect {label}: {exc}") from exc
        if metadata.st_nlink != 1:
            raise ContextError(f"{label} must not be a hard-linked authority input")
        return resolved, _filesystem_snapshot(resolved, metadata)
    raise ContextError(f"{label} must be outside the repository trust boundary")


def _global_source(root: Path, value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    path, snapshot = _external_file(root, value, "global review file")
    _, data = _read_regular(
        path,
        MAX_GUIDANCE_SOURCE_BYTES,
        expected_snapshot=snapshot,
        require_single_link=True,
    )
    return _guidance_source(source_kind="user_global", path=str(path), revision=None, data=data)


def _skill_source() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "SKILL.md"
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ContextError(f"cannot inspect skill guidance: {exc}") from exc
    _, data = _read_regular(
        path,
        MAX_GUIDANCE_SOURCE_BYTES,
        expected_snapshot=_filesystem_snapshot(path, metadata),
    )
    return _guidance_source(
        source_kind="skill",
        path="SKILL.md",
        revision=f"verification-harness-audit@{SKILL_VERSION}",
        data=data,
    )


def _guidance(
    root: Path,
    requested: list[dict[str, Any]],
    inventory_paths: list[str],
    global_source: dict[str, Any] | None,
    maximum_bytes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    work: dict[tuple[str, bool], list[str]] = {}
    for path in inventory_paths:
        work[(path, False)] = _owners(root, requested, path)
    for item in requested:
        if item["kind"] not in {"directory", "project"}:
            continue
        if not any(item["target_id"] in owners for owners in work.values()):
            work[(item["path"], True)] = [item["target_id"]]

    skill = _skill_source()
    cache: dict[str, dict[str, Any] | None] = {}
    failures: dict[str, str] = {}
    limitations: list[dict[str, Any]] = []
    grouped: dict[str, dict[str, Any]] = {}
    for (path, directory), target_ids in sorted(work.items()):
        sources = [dict(skill)]
        if global_source is not None:
            sources.append(dict(global_source))
        complete = True
        for guidance_path in _guidance_paths(path, directory=directory):
            if len(sources) >= MAX_GUIDANCE_SOURCES_PER_CHAIN:
                complete = False
                limitations.append(
                    _limitation("guidance_budget", f"Guidance source ceiling reached for {path}.", [] if path == "." else [path], True)
                )
                break
            if guidance_path not in cache:
                try:
                    cache[guidance_path] = _read_guidance(root, guidance_path)
                except ContextError as exc:
                    cache[guidance_path] = None
                    failures[guidance_path] = str(exc)
            if guidance_path in failures:
                complete = False
                limitations.append(
                    _limitation("guidance_unreadable", failures[guidance_path], [] if path == "." else [path], True)
                )
            elif cache[guidance_path] is not None:
                sources.append(dict(cache[guidance_path]))

        loaded = 0
        for source in sources:
            if source["source_kind"] == "skill":
                continue
            if loaded + source["bytes"] > maximum_bytes:
                source["loaded"] = False
                source["content"] = None
                complete = False
                limitations.append(
                    _limitation("guidance_budget", f"Guidance byte ceiling omitted {source['path']} for {path}.", [] if path == "." else [path], True)
                )
            else:
                loaded += source["bytes"]
        identity = json.dumps(
            [complete, [(source["source_kind"], source["path"], source["sha256"], source["loaded"]) for source in sources]],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        if identity not in grouped:
            grouped[identity] = {
                "chain_id": "",
                "target_ids": [],
                "paths": [],
                "sources": sources,
                "complete": complete,
            }
        grouped[identity]["target_ids"].extend(target_ids)
        grouped[identity]["paths"].append(path)

    chains = sorted(grouped.values(), key=lambda item: (item["paths"][0], item["target_ids"]))
    if len(chains) > MAX_GUIDANCE_CHAINS:
        raise ContextError("resolved guidance exceeds the guidance-chain ceiling")
    for index, chain in enumerate(chains, 1):
        chain["chain_id"] = f"G{index:03d}"
        chain["target_ids"] = sorted(set(chain["target_ids"]))
        chain["paths"] = sorted(set(chain["paths"]))
        if len(chain["paths"]) > MAX_GUIDANCE_PATHS_PER_CHAIN:
            raise ContextError("resolved guidance exceeds the per-chain path ceiling")
    return chains, limitations


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContextError(f"JSON input contains duplicate member {key!r}")
        result[key] = value
    return result


def _load_external_json(root: Path, value: str, label: str) -> Any:
    path, snapshot = _external_file(root, value, label)
    _, data = _read_regular(
        path,
        MAX_INPUT_JSON_BYTES,
        expected_snapshot=snapshot,
        require_single_link=True,
    )
    try:
        return json.loads(data.decode("utf-8", "strict"), object_pairs_hook=_json_pairs)
    except UnicodeDecodeError as exc:
        raise ContextError(f"{label} must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ContextError(f"invalid {label} JSON: {exc}") from exc


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ContextError(f"{label} must contain exactly {sorted(expected)}")


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ContextError(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def _command_plan(
    root: Path, value: str | None, global_source: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if value is None:
        return []
    raw = _load_external_json(root, value, "command plan")
    if not isinstance(raw, list) or len(raw) > 256:
        raise ContextError("command plan must be an array of at most 256 entries")
    records: list[dict[str, Any]] = []
    expected = {
        "argv",
        "cwd",
        "reason",
        "expected_effects",
        "timeout_seconds",
        "repetitions",
        "authorization_kind",
        "authorization_source",
    }
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ContextError(f"command plan entry {index} must be an object")
        _exact_keys(item, expected, f"command plan entry {index}")
        argv = item["argv"]
        if not isinstance(argv, list) or not 1 <= len(argv) <= 128:
            raise ContextError(f"command plan entry {index}.argv must contain 1-128 arguments")
        argv = [_text(arg, f"command plan entry {index}.argv", maximum=4096) for arg in argv]
        cwd = _canonical_path(item["cwd"], allow_root=True)
        cwd_path = _safe_repo_path(root, cwd)
        if not cwd_path.is_dir():
            raise ContextError(f"command plan entry {index}.cwd is not a directory")
        effects = item["expected_effects"]
        if not isinstance(effects, list) or not 1 <= len(effects) <= 32:
            raise ContextError(f"command plan entry {index}.expected_effects must contain 1-32 values")
        effects = [_text(effect, f"command plan entry {index}.expected_effects", maximum=2000) for effect in effects]
        kind = item["authorization_kind"]
        if kind not in {"caller", "user_global"}:
            raise ContextError(f"command plan entry {index} has invalid authorization_kind")
        if kind == "user_global":
            if global_source is None:
                raise ContextError("user_global command authority requires --global-review-file")
            source = global_source["path"]
            source_sha256 = global_source["sha256"]
            supplied_source = _filesystem_path(
                item["authorization_source"],
                f"command plan entry {index}.authorization_source",
                expand_user=True,
            )
            _assert_no_link_components(supplied_source, include_final=True)
            try:
                resolved_source = supplied_source.resolve(strict=True)
            except OSError as exc:
                raise ContextError(
                    "user_global command authority must reference the resolved global source path"
                ) from exc
            if os.path.normcase(str(resolved_source)) != os.path.normcase(source):
                raise ContextError("user_global command authority must reference the resolved global source path")
        else:
            source = _text(item["authorization_source"], f"command plan entry {index}.authorization_source", maximum=2000)
            source_sha256 = _sha256(source.encode("utf-8"))
        records.append(
            {
                "command_id": f"C{index:03d}",
                "argv": argv,
                "cwd": cwd,
                "reason": _text(item["reason"], f"command plan entry {index}.reason", maximum=4000),
                "expected_effects": effects,
                "timeout_seconds": _integer(item["timeout_seconds"], "timeout_seconds", 1, 86400),
                "repetitions": _integer(item["repetitions"], "repetitions", 1, 100),
                "authorization": {"kind": kind, "source": source, "source_sha256": source_sha256},
                "outcome": "not_run",
                "exit_code": None,
                "duration_ms": None,
                "output_sha256": None,
                "summary": "Exact command plan was authorized but has not been executed.",
            }
        )
    return records


def _date_time(value: Any, label: str, *, nullable: bool) -> str | None:
    if value is None and nullable:
        return None
    text = _text(value, label, maximum=64)
    match = RFC3339.fullmatch(text)
    if match is None:
        raise ContextError(f"{label} must use canonical RFC 3339 date-time syntax")
    try:
        dt.date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError as exc:
        raise ContextError(f"{label} must be an RFC 3339 date-time") from exc
    if (
        int(match.group("hour")) > 23
        or int(match.group("minute")) > 59
        or int(match.group("second")) > 59
    ):
        raise ContextError(f"{label} has an out-of-range RFC 3339 time")
    if match.group("zone") != "Z" and (
        int(match.group("offset_hour")) > 23
        or int(match.group("offset_minute")) > 59
    ):
        raise ContextError(f"{label} has an out-of-range RFC 3339 offset")
    return text


def _evidence_sources(root: Path, value: str | None) -> list[dict[str, Any]]:
    if value is None:
        return []
    raw = _load_external_json(root, value, "evidence metadata")
    if not isinstance(raw, list) or len(raw) > 256:
        raise ContextError("evidence metadata must be an array of at most 256 entries")
    expected = {
        "kind",
        "source_label",
        "source_sha256",
        "observed_at",
        "supplied_at",
        "freshness",
        "freshness_basis",
    }
    result: list[dict[str, Any]] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ContextError(f"evidence metadata entry {index} must be an object")
        _exact_keys(item, expected, f"evidence metadata entry {index}")
        if item["kind"] not in {"timing", "failure", "history", "other"}:
            raise ContextError(f"evidence metadata entry {index} has invalid kind")
        if item["freshness"] not in {"fresh", "stale", "unknown"}:
            raise ContextError(f"evidence metadata entry {index} has invalid freshness")
        digest = item["source_sha256"]
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ContextError(f"evidence metadata entry {index} has invalid source_sha256")
        result.append(
            {
                "evidence_source_id": f"S{index:03d}",
                "kind": item["kind"],
                "source_label": _text(item["source_label"], f"evidence metadata entry {index}.source_label", maximum=1000),
                "source_sha256": digest,
                "observed_at": _date_time(item["observed_at"], "observed_at", nullable=True),
                "supplied_at": _date_time(item["supplied_at"], "supplied_at", nullable=False),
                "freshness": item["freshness"],
                "freshness_basis": _text(item["freshness_basis"], f"evidence metadata entry {index}.freshness_basis", maximum=2000),
            }
        )
    return result


def _validate_limits(args: argparse.Namespace) -> None:
    pairs = [
        ("max-files", args.max_files, 1, MAX_FILES),
        ("max-file-bytes", args.max_file_bytes, 1, MAX_FILE_BYTES),
        ("max-total-bytes", args.max_total_bytes, 1, MAX_TOTAL_BYTES),
        ("max-traversal-entries", args.max_traversal_entries, 1, MAX_TRAVERSAL_ENTRIES),
        ("max-context-files", args.max_context_files, 0, MAX_CONTEXT_FILES),
        ("max-context-bytes", args.max_context_bytes, 0, MAX_CONTEXT_BYTES),
        ("max-guidance-bytes", args.max_guidance_bytes, 1024, MAX_GUIDANCE_BYTES),
    ]
    for label, value, minimum, maximum in pairs:
        _integer(value, label, minimum, maximum)


def resolve(args: argparse.Namespace) -> dict[str, Any]:
    _validate_limits(args)
    root_input = _filesystem_path(args.repo, "repository root", expand_user=True)
    _assert_no_link_components(root_input, include_final=True)
    try:
        root = root_input.resolve(strict=True)
    except OSError as exc:
        raise ContextError(f"cannot resolve repository root: {exc}") from exc
    if not root.is_dir():
        raise ContextError("repository root must be a non-link directory")
    requested = _requested(args, root)
    git_enabled = _git_root(root)

    explicit = sorted({item["path"] for item in requested if item["kind"] in {"file", "part"}})
    explicit_identities = {
        _filesystem_alias_identity(_safe_repo_path(root, path)): path
        for path in explicit
    }
    broad_roots = [item["path"] for item in requested if item["kind"] in {"directory", "project"}]
    if len(explicit) > args.max_files:
        raise ContextError("max-files is smaller than the explicit target selection")
    broad, traversed, limitations, git_after_walk = _enumerate_broad(
        root,
        broad_roots,
        maximum_entries=args.max_traversal_entries,
        maximum_candidates=args.max_files - len(explicit),
        git_enabled=git_enabled,
        excluded_candidates=set(explicit),
        excluded_identities=explicit_identities,
    ) if broad_roots else ([], 0, [], git_enabled)
    selected_paths = sorted(set(explicit) | set(broad))
    if len(selected_paths) > args.max_files:
        selected_paths = selected_paths[: args.max_files]
        limitations.append(_limitation("scope_truncated", "File ceiling omitted part of the selected harness inventory.", [], True))

    inspection_set = set(explicit)
    for value in args.inspections or []:
        relative = _canonical_path(value)
        if relative in inspection_set:
            raise ContextError(f"duplicate inspection path: {relative}")
        if relative not in selected_paths:
            raise ContextError(f"inspection path is outside the resolved harness inventory: {relative}")
        inspection_set.add(relative)

    tracking, tracking_limits = _tracking(root, selected_paths, git_after_walk)
    limitations.extend(tracking_limits)
    records: list[dict[str, Any]] = []
    line_counts: dict[str, int] = {}
    read_bytes = 0
    for relative in selected_paths:
        record, consumed, error, line_count = _file_record(
            root,
            relative,
            tracking[relative],
            inspect=relative in inspection_set,
            maximum_file_bytes=args.max_file_bytes,
            remaining_bytes=max(0, args.max_total_bytes - read_bytes),
        )
        records.append(record)
        read_bytes += consumed
        if line_count is not None:
            line_counts[relative] = line_count
        if error is not None:
            limitations.append(_limitation("target_unreadable", error, [relative], True))
        elif record["inspection_kind"] in {"binary", "non_utf8"}:
            limitations.append(
                _limitation(
                    "target_unreadable",
                    f"Recorded {record['inspection_kind']} target without semantic text inspection: {relative}",
                    [relative],
                    relative in inspection_set,
                )
            )

    by_path = {record["path"]: record for record in records}
    for item in requested:
        if item["kind"] != "part":
            continue
        record = by_path.get(item["path"])
        if record is None or record["inspection_kind"] != "text":
            limitations.append(_limitation("part_unreadable", f"Part target is not readable UTF-8 text: {item['path']}", [item["path"]], True))
            continue
        line_count = line_counts[item["path"]]
        if line_count == 0 or item["end_line"] > line_count:
            raise ContextError(f"part range exceeds the readable lines in {item['path']}")

    inventory_complete = not any(item["material"] for item in limitations)

    context_paths: list[str] = []
    seen_context_paths: set[str] = set()
    for value in args.contexts or []:
        relative = _canonical_path(value)
        if relative in seen_context_paths:
            raise ContextError(f"duplicate context path: {relative}")
        seen_context_paths.add(relative)
        context_paths.append(relative)
    context_paths.sort()
    if len(context_paths) > args.max_context_files:
        raise ContextError("context selection exceeds max-context-files")
    inventory_identities = {
        _filesystem_alias_identity(_safe_repo_path(root, path)): path
        for path in selected_paths
    }
    context_identities: dict[tuple[Any, ...], str] = {}
    for path in context_paths:
        identity = _filesystem_alias_identity(_safe_repo_path(root, path))
        if identity in inventory_identities and inventory_identities[identity] != path:
            raise ContextError(
                "harness and context aliases resolve to the same filesystem object: "
                f"{inventory_identities[identity]} and {path}"
            )
        prior = context_identities.get(identity)
        if prior is not None:
            raise ContextError(
                f"context path aliases resolve to the same filesystem object: {prior} and {path}"
            )
        context_identities[identity] = path
    overlap = {path for path in context_paths if _owners(root, requested, path)}
    if overlap:
        raise ContextError(f"context paths duplicate harness inventory: {sorted(overlap)}")
    context_tracking, context_tracking_limits = _tracking(root, context_paths, git_after_walk)
    limitations.extend(context_tracking_limits)
    context_records: list[dict[str, Any]] = []
    context_read_bytes = 0
    for relative in context_paths:
        path = _safe_repo_path(root, relative)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ContextError(f"context target is not a regular file: {relative}")
        record, consumed, error, _ = _file_record(
            root,
            relative,
            context_tracking[relative],
            inspect=True,
            maximum_file_bytes=args.max_file_bytes,
            remaining_bytes=max(0, args.max_context_bytes - context_read_bytes),
        )
        context_records.append(record)
        context_read_bytes += consumed
        if error is not None or record["inspection_kind"] != "text":
            limitations.append(
                _limitation(
                    "context_unavailable",
                    error or f"Context is not readable UTF-8 text: {relative}",
                    [relative],
                    True,
                )
            )

    global_source = _global_source(root, args.global_review_file)
    chains, guidance_limits = _guidance(
        root,
        requested,
        [record["path"] for record in records],
        global_source,
        args.max_guidance_bytes,
    )
    limitations.extend(guidance_limits)
    execution = _command_plan(root, args.command_plan, global_source)
    evidence_sources = _evidence_sources(root, args.evidence_metadata)
    limitations = _dedupe_limitations(limitations)

    context = {
        "schema_version": SCHEMA_VERSION,
        "target": {
            "kind": "current_filesystem",
            "repository_root": str(root),
            "requested": requested,
        },
        "inventory": {
            "limits": {
                "maximum_files": args.max_files,
                "maximum_file_bytes": args.max_file_bytes,
                "maximum_total_bytes": args.max_total_bytes,
                "maximum_traversal_entries": args.max_traversal_entries,
                "maximum_context_files": args.max_context_files,
                "maximum_context_bytes": args.max_context_bytes,
            },
            "traversed_entries": traversed,
            "read_bytes": read_bytes,
            "context_read_bytes": context_read_bytes,
            "files": records,
            "complete": inventory_complete,
        },
        "context_inventory": context_records,
        "guidance": chains,
        "execution": execution,
        "evidence_sources": evidence_sources,
        "limitations": limitations,
    }
    data = _serialized(context)
    if len(data) > MAX_CONTEXT_JSON_BYTES:
        raise ContextError("resolved context exceeds the canonical JSON ceiling")
    return context


def _serialized(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_descriptor(descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise ContextError("output write made no progress")
        remaining = remaining[written:]
    os.fsync(descriptor)


def _write_created_output(path: Path, data: bytes) -> None:
    if os.name == "nt":
        with _windows_locked_parent(path) as (absolute, parent_handle):
            try:
                descriptor = _windows_file_descriptor(
                    absolute,
                    parent_handle=parent_handle,
                    access=0x40000000 | 0x00000080,
                    creation=1,
                    descriptor_flags=os.O_WRONLY | getattr(os, "O_BINARY", 0),
                )
            except OSError as exc:
                raise ContextError(f"cannot create output {absolute}: {exc}") from exc
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise ContextError(f"refusing unsafe new output: {absolute}")
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
                    not stat.S_ISREG(final_metadata.st_mode)
                    or final_metadata.st_nlink != 1
                    or _filesystem_open_binding(absolute, final_entry)
                    != _filesystem_open_binding(absolute, final_metadata)
                ):
                    raise ContextError(
                        f"output entry changed while being written: {absolute}"
                    )
            finally:
                os.close(descriptor)
        return
    with _posix_bound_parent(path) as (parent, name, absolute):
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
            raise ContextError(f"cannot create output {absolute}: {exc}") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ContextError(f"refusing unsafe new output: {absolute}")
            _write_descriptor(descriptor, data)
            final_metadata = os.fstat(descriptor)
            final = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISREG(final.st_mode)
                or final.st_nlink != 1
                or final_metadata.st_nlink != 1
                or _filesystem_identity(absolute, final)
                != _filesystem_identity(absolute, final_metadata)
            ):
                raise ContextError(f"output entry changed while being written: {absolute}")
        finally:
            os.close(descriptor)


def _write(value: dict[str, Any], destination: str | None) -> None:
    data = _serialized(value)
    if len(data) > MAX_CONTEXT_JSON_BYTES:
        raise ContextError("resolved context exceeds the canonical JSON ceiling")
    if destination is None:
        sys.stdout.write(data.decode("utf-8"))
        return
    path = _filesystem_path(destination, "output path", expand_user=True)
    _assert_no_link_components(path, include_final=False)
    if not path.parent.is_dir():
        raise ContextError(f"output parent does not exist: {path.parent}")
    _write_created_output(path, data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="repository root")
    parser.add_argument("--path", dest="paths", action="append", help="selected file, directory, or .")
    parser.add_argument("--part", dest="parts", action="append", help="selected PATH:START_LINE:END_LINE")
    parser.add_argument("--focus-kind", choices=sorted(FOCUS_KINDS))
    parser.add_argument("--focus-value")
    parser.add_argument("--context", dest="contexts", action="append", help="related read-only repository file")
    parser.add_argument("--inspect", dest="inspections", action="append", help="exact broad-inventory file to read and hash")
    parser.add_argument("--global-review-file", help="absolute active-agent user REVIEW.md")
    parser.add_argument("--command-plan", help="absolute external JSON plan authorized by the caller or user guidance")
    parser.add_argument("--evidence-metadata", help="absolute external JSON metadata for caller-supplied evidence")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    parser.add_argument("--max-traversal-entries", type=int, default=DEFAULT_MAX_TRAVERSAL_ENTRIES)
    parser.add_argument("--max-context-files", type=int, default=DEFAULT_MAX_CONTEXT_FILES)
    parser.add_argument("--max-context-bytes", type=int, default=DEFAULT_MAX_CONTEXT_BYTES)
    parser.add_argument("--max-guidance-bytes", type=int, default=DEFAULT_MAX_GUIDANCE_BYTES)
    parser.add_argument("--output", help="create a new context JSON file instead of stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = resolve(args)
        _write(result, args.output)
        return 0
    except ContextError as exc:
        print(f"verification-harness context: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
