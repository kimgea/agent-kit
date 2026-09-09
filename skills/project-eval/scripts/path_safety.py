#!/usr/bin/env python3
"""No-follow filesystem primitives bundled with project-eval helpers."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Iterator, NamedTuple


CONTROL = re.compile(r"[\x00-\x1f\x7f]")
SAFE_POSIX_DIR_FD = (
    os.name == "posix"
    and hasattr(os, "O_NOFOLLOW")
    and hasattr(os, "O_DIRECTORY")
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
)


class SafetyError(ValueError):
    """Raised when a filesystem boundary cannot be proven safe."""


class BoundDirectoryEntry(NamedTuple):
    """Metadata captured while a directory is held by an OS handle."""

    name: str
    path: Path
    is_directory: bool
    is_regular: bool
    link_like: bool
    identity: tuple[Any, ...]


def text(value: Any, label: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise SafetyError(
            f"{label} must be a non-empty string of at most {maximum} characters"
        )
    if CONTROL.search(value):
        raise SafetyError(f"{label} must not contain control characters")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise SafetyError(f"{label} must be valid UTF-8") from exc
    return value


def filesystem_path(value: Any, label: str, *, expand_user: bool = False) -> Path:
    value_text = text(value, label, maximum=8192)
    path = Path(value_text)
    return path.expanduser() if expand_user else path


def canonical_path(value: Any, *, allow_root: bool = False) -> str:
    value_text = text(value, "repository path")
    if "\\" in value_text or value_text.startswith("/") or re.match(
        r"^[A-Za-z]:", value_text
    ):
        raise SafetyError(f"repository path is not canonical: {value_text!r}")
    if value_text == ".":
        if allow_root:
            return value_text
        raise SafetyError("the repository root is not valid in this field")
    if value_text.endswith("/") or "//" in value_text:
        raise SafetyError(f"repository path is not canonical: {value_text!r}")
    parts = PurePosixPath(value_text).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise SafetyError(f"repository path is not canonical: {value_text!r}")
    canonical = PurePosixPath(*parts).as_posix()
    if canonical != value_text:
        raise SafetyError(f"repository path is not canonical: {value_text!r}")
    return canonical


def is_link_like(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    return bool(flag and attributes & flag)


def assert_no_link_components(path: Path, *, include_final: bool) -> None:
    absolute = path.absolute()
    parts = absolute.parts[1:] if include_final else absolute.parts[1:-1]
    current = Path(absolute.anchor)
    for part in parts:
        current /= part
        if is_link_like(current):
            raise SafetyError(f"refusing link-like path component: {current}")


def ensure_private_directory(path: Path) -> None:
    """Create or bind one absolute private directory without following links."""
    absolute = path.absolute()
    if not absolute.name:
        raise SafetyError("the filesystem root cannot be a private state directory")
    if os.name == "nt":
        current = Path(absolute.anchor)
        handles: list[int] = []
        try:
            handle = _windows_create_handle(
                current,
                access=0x00000080,
                creation=3,
                flags=0x02000000 | 0x00200000,
            )
            handles.append(handle)
            for part in absolute.parts[1:]:
                current /= part
                try:
                    child = _windows_relative_handle(
                        handles[-1],
                        part,
                        access=0x00000080,
                        creation=1,
                        display_path=current,
                        directory=True,
                    )
                except OSError:
                    child = _windows_relative_handle(
                        handles[-1],
                        part,
                        access=0x00000080,
                        creation=3,
                        display_path=current,
                        directory=True,
                    )
                attributes, _, _, _ = _windows_handle_attributes(child)
                if attributes & 0x00000400 or not attributes & 0x00000010:
                    _windows_close_handle(child)
                    raise SafetyError(f"refusing link-like or non-directory state path: {current}")
                handles.append(child)
            return
        finally:
            for handle in reversed(handles):
                _windows_close_handle(handle)
    if not SAFE_POSIX_DIR_FD:
        raise SafetyError("safe descriptor-relative directory creation is unavailable")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = -1
    try:
        descriptor = os.open(absolute.anchor, flags)
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current /= part
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=descriptor)
            except OSError as exc:
                raise SafetyError(f"cannot bind private state directory {current}: {exc}") from exc
            os.close(descriptor)
            descriptor = child
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise SafetyError(f"private state path is not a directory: {current}")
        metadata = os.fstat(descriptor)
        if metadata.st_mode & 0o077:
            raise SafetyError(f"private state directory permissions are too broad: {absolute}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)


@contextlib.contextmanager
def _posix_bound_parent(path: Path) -> Iterator[tuple[int, str, Path]]:
    if not SAFE_POSIX_DIR_FD:
        raise SafetyError("safe descriptor-relative path handling is unavailable")
    absolute = path.absolute()
    if not absolute.name:
        raise SafetyError(f"path must name a file: {path}")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = -1
    try:
        descriptor = os.open(absolute.anchor, flags)
        current = Path(absolute.anchor)
        for part in absolute.parent.parts[1:]:
            current /= part
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except OSError as exc:
                raise SafetyError(f"cannot bind safe parent directory {current}: {exc}") from exc
            os.close(descriptor)
            descriptor = child
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise SafetyError(f"input/output parent is not a directory: {current}")
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


def _windows_create_handle(path: Path, *, access: int, creation: int, flags: int) -> int:
    if os.name != "nt":
        raise SafetyError("Windows handle operation requested on another platform")
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
        _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_void_p)]

    disposition = {1: 2, 3: 1}.get(creation)
    if disposition is None:
        raise SafetyError(f"unsupported Windows create disposition: {creation}")
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
        0x00000020 | (0x00000001 if directory else 0x00000040) | 0x00200000,
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
def _windows_locked_parent(
    path: Path, *, final_parent_access: int = 0x00000080
) -> Iterator[tuple[Path, int]]:
    absolute = Path(os.path.normpath(str(path.absolute())))
    assert_no_link_components(absolute, include_final=False)
    if not absolute.name:
        raise SafetyError(f"path must name a file: {path}")
    current = Path(absolute.anchor)
    parent_parts = absolute.parent.parts[1:]
    handles: list[int] = []
    try:
        handle = _windows_create_handle(
            current,
            access=final_parent_access if not parent_parts else 0x00000080,
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
            raise SafetyError(f"refusing link-like or non-directory parent: {current}")
        handles.append(handle)
        for index, part in enumerate(parent_parts):
            current /= part
            child = _windows_relative_handle(
                handles[-1],
                part,
                access=(
                    final_parent_access
                    if index == len(parent_parts) - 1
                    else 0x00000080
                ),
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
                raise SafetyError(f"refusing link-like or non-directory parent: {current}")
            handles.append(child)
        yield _windows_handle_path(handles[-1]) / absolute.name, handles[-1]
    finally:
        for handle in reversed(handles):
            _windows_close_handle(handle)


def _windows_file_descriptor(
    path: Path,
    *,
    parent_handle: int,
    access: int = 0x80000000,
    creation: int = 3,
    descriptor_flags: int | None = None,
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
            raise SafetyError(f"refusing link-like or non-file path: {path}")
        flags = descriptor_flags
        if flags is None:
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        return msvcrt.open_osfhandle(handle, flags)
    except Exception:
        _windows_close_handle(handle)
        raise


@contextlib.contextmanager
def bound_read_descriptor(path: Path) -> Iterator[tuple[int, Path]]:
    if os.name == "nt":
        with _windows_locked_parent(path) as (absolute, parent_handle):
            try:
                descriptor = _windows_file_descriptor(absolute, parent_handle=parent_handle)
            except OSError as exc:
                raise SafetyError(f"cannot open {path}: {exc}") from exc
            try:
                yield descriptor, absolute
            finally:
                os.close(descriptor)
        return
    with _posix_bound_parent(path) as (parent, name, absolute):
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(name, flags, dir_fd=parent)
        except OSError as exc:
            raise SafetyError(f"cannot open {absolute}: {exc}") from exc
        try:
            yield descriptor, absolute
        finally:
            os.close(descriptor)


def _windows_directory_entries(
    directory: Path, handle: int, maximum: int
) -> tuple[list[BoundDirectoryEntry], int, bool]:
    import ctypes
    from ctypes import wintypes

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_size_t)]

    class FileIdBothDirectoryInformation(ctypes.Structure):
        _fields_ = [
            ("next_entry_offset", wintypes.ULONG),
            ("file_index", wintypes.ULONG),
            ("creation_time", ctypes.c_longlong),
            ("last_access_time", ctypes.c_longlong),
            ("last_write_time", ctypes.c_longlong),
            ("change_time", ctypes.c_longlong),
            ("end_of_file", ctypes.c_longlong),
            ("allocation_size", ctypes.c_longlong),
            ("file_attributes", wintypes.ULONG),
            ("file_name_length", wintypes.ULONG),
            ("ea_size", wintypes.ULONG),
            ("short_name_length", ctypes.c_ubyte),
            ("short_name", wintypes.WCHAR * 12),
            ("file_id", ctypes.c_longlong),
            ("file_name", wintypes.WCHAR * 1),
        ]

    ntdll = ctypes.WinDLL("ntdll")
    query = ntdll.NtQueryDirectoryFile
    query.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(IoStatusBlock),
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.BOOLEAN,
        ctypes.c_void_p,
        wintypes.BOOLEAN,
    ]
    query.restype = ctypes.c_long
    rtl_error = ntdll.RtlNtStatusToDosError
    rtl_error.argtypes = [ctypes.c_long]
    rtl_error.restype = wintypes.ULONG
    no_more_files = ctypes.c_long(0x80000006).value
    buffer = ctypes.create_string_buffer(65536)
    fallback_volume = _windows_handle_attributes(handle)[2]
    entries: list[BoundDirectoryEntry] = []
    consumed = 0
    restart = True
    while True:
        status_block = IoStatusBlock()
        status = int(
            query(
                handle,
                None,
                None,
                None,
                ctypes.byref(status_block),
                buffer,
                len(buffer),
                37,
                False,
                None,
                restart,
            )
        )
        restart = False
        if status == no_more_files:
            return sorted(entries, key=lambda item: item.name), consumed, True
        if status < 0:
            error = int(rtl_error(status))
            raise SafetyError(
                f"cannot enumerate bound directory {directory}: {ctypes.FormatError(error)}"
            )
        returned = int(status_block.information)
        if returned <= 0 or returned > len(buffer):
            raise SafetyError(f"invalid directory enumeration response for {directory}")
        offset = 0
        while offset < returned:
            header = FileIdBothDirectoryInformation.from_buffer_copy(buffer, offset)
            name_start = offset + FileIdBothDirectoryInformation.file_name.offset
            name_end = name_start + int(header.file_name_length)
            if name_end > returned or header.file_name_length % 2:
                raise SafetyError(f"invalid directory entry returned for {directory}")
            name = bytes(buffer[name_start:name_end]).decode("utf-16-le", "strict")
            if name not in {".", ".."}:
                consumed += 1
                if consumed > maximum:
                    return [], maximum, False
                child_path = directory / name
                child = _windows_relative_handle(
                    handle,
                    name,
                    access=0x00000080,
                    creation=3,
                    display_path=child_path,
                    directory=bool(int(header.file_attributes) & 0x00000010),
                )
                try:
                    attributes, _, volume, file_index = _windows_handle_attributes(child)
                finally:
                    _windows_close_handle(child)
                link = bool(attributes & 0x00000400)
                is_directory = bool(attributes & 0x00000010)
                entries.append(
                    BoundDirectoryEntry(
                        name=name,
                        path=child_path,
                        is_directory=is_directory,
                        is_regular=not is_directory and not link,
                        link_like=link,
                        identity=("windows_file", volume or fallback_volume, file_index),
                    )
                )
            next_offset = int(header.next_entry_offset)
            if next_offset == 0:
                break
            if (
                next_offset < FileIdBothDirectoryInformation.file_name.offset
                or offset + next_offset <= offset
                or offset + next_offset >= returned
            ):
                raise SafetyError(f"invalid directory entry chain returned for {directory}")
            offset += next_offset


def bound_directory_entries(
    path: Path, maximum: int
) -> tuple[list[BoundDirectoryEntry], int, bool]:
    """Enumerate a directory through a retained handle, never a mutable path lookup."""
    if maximum <= 0:
        return [], 0, False
    absolute = path.absolute()
    if os.name == "nt":
        sentinel = absolute / ".verify-project-directory-enumeration"
        # NtQueryDirectoryFile requires FILE_LIST_DIRECTORY on the directory
        # being enumerated. Keep traversal handles narrower and add that right
        # only to the retained final parent handle.
        with _windows_locked_parent(
            sentinel, final_parent_access=0x00000080 | 0x00000001
        ) as (_, handle):
            return _windows_directory_entries(absolute, handle, maximum)
    if not SAFE_POSIX_DIR_FD:
        raise SafetyError("safe descriptor-relative directory enumeration is unavailable")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    with _posix_bound_parent(absolute) as (parent, name, bound_path):
        descriptor = os.open(name, flags, dir_fd=parent)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise SafetyError(f"not a directory: {bound_path}")
            entries: list[BoundDirectoryEntry] = []
            consumed = 0
            with os.scandir(descriptor) as iterator:
                for entry in iterator:
                    consumed += 1
                    if consumed > maximum:
                        return [], maximum, False
                    child_metadata = os.stat(
                        entry.name, dir_fd=descriptor, follow_symlinks=False
                    )
                    entries.append(
                        BoundDirectoryEntry(
                            name=entry.name,
                            path=absolute / entry.name,
                            is_directory=stat.S_ISDIR(child_metadata.st_mode),
                            is_regular=stat.S_ISREG(child_metadata.st_mode),
                            link_like=stat.S_ISLNK(child_metadata.st_mode),
                            identity=filesystem_identity(absolute / entry.name, child_metadata),
                        )
                    )
            return sorted(entries, key=lambda item: item.name), consumed, True
        finally:
            os.close(descriptor)


def filesystem_identity(path: Path, metadata: os.stat_result | None = None) -> tuple[Any, ...]:
    try:
        value = metadata if metadata is not None else path.stat()
    except OSError as exc:
        raise SafetyError(f"cannot identify filesystem path {path}: {exc}") from exc
    device = int(getattr(value, "st_dev", 0))
    inode = int(getattr(value, "st_ino", 0))
    if inode:
        return ("inode", device, inode)
    try:
        return ("path", os.path.normcase(str(path.resolve(strict=True))))
    except OSError as exc:
        raise SafetyError(f"cannot identify filesystem path {path}: {exc}") from exc


def filesystem_alias_identity(
    path: Path, metadata: os.stat_result | None = None
) -> tuple[Any, ...]:
    """Return an identity stable across Windows hard-link path aliases."""
    if os.name != "nt":
        return filesystem_identity(path, metadata)
    path_metadata = metadata if metadata is not None else path.lstat()
    with _windows_locked_parent(path) as (absolute, parent_handle):
        handle = _windows_relative_handle(
            parent_handle,
            absolute.name,
            access=0x00000080,
            creation=3,
            display_path=absolute,
            directory=stat.S_ISDIR(path_metadata.st_mode),
        )
        try:
            attributes, _, volume, file_index = _windows_handle_attributes(handle)
            if attributes & 0x00000400:
                raise SafetyError(f"refusing link-like filesystem alias: {path}")
            return ("windows_file", volume, file_index)
        finally:
            _windows_close_handle(handle)


def filesystem_snapshot(path: Path, metadata: os.stat_result | None = None) -> tuple[Any, ...]:
    try:
        value = metadata if metadata is not None else path.stat()
    except OSError as exc:
        raise SafetyError(f"cannot snapshot filesystem path {path}: {exc}") from exc
    return (
        filesystem_identity(path, value),
        int(value.st_size),
        int(getattr(value, "st_mtime_ns", int(value.st_mtime * 1_000_000_000))),
        int(getattr(value, "st_ctime_ns", int(value.st_ctime * 1_000_000_000))),
    )


def read_regular(
    path: Path,
    maximum: int,
    *,
    expected_snapshot: tuple[Any, ...] | None = None,
    require_single_link: bool = False,
) -> tuple[os.stat_result, bytes]:
    with bound_read_descriptor(path) as (descriptor, bound_path):
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SafetyError(f"not a regular file: {bound_path}")
        identity = filesystem_identity(bound_path, metadata)
        if expected_snapshot is not None and (
            identity != expected_snapshot[0] or int(metadata.st_size) != expected_snapshot[1]
        ):
            raise SafetyError(f"file snapshot changed before inspection: {bound_path}")
        if require_single_link and metadata.st_nlink != 1:
            raise SafetyError(f"authority input is hard-linked: {bound_path}")
        if metadata.st_size > maximum:
            raise SafetyError(f"file exceeds {maximum} bytes: {bound_path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise SafetyError(f"file exceeds {maximum} bytes: {bound_path}")
        final = os.fstat(descriptor)
        initial_signature = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            getattr(metadata, "st_mtime_ns", metadata.st_mtime),
            getattr(metadata, "st_ctime_ns", metadata.st_ctime),
        )
        final_signature = (
            final.st_dev,
            final.st_ino,
            final.st_size,
            getattr(final, "st_mtime_ns", final.st_mtime),
            getattr(final, "st_ctime_ns", final.st_ctime),
        )
        if final_signature != initial_signature:
            raise SafetyError(f"file changed during inspection: {bound_path}")
        if expected_snapshot is not None:
            try:
                current = bound_path.lstat()
            except OSError as exc:
                raise SafetyError(f"file snapshot changed during inspection: {bound_path}") from exc
            if is_link_like(bound_path) or filesystem_snapshot(bound_path, current) != expected_snapshot:
                raise SafetyError(f"file snapshot changed during inspection: {bound_path}")
        return final, b"".join(chunks)


def canonical_text(data: bytes, label: str) -> tuple[str, bytes]:
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SafetyError(f"{label} is not UTF-8 text") from exc
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized, normalized.encode("utf-8")


def safe_repo_path(root: Path, relative: str, *, allow_absent_final: bool = False) -> Path:
    canonical = canonical_path(relative, allow_root=True)
    if canonical == ".":
        if is_link_like(root):
            raise SafetyError("repository root is link-like")
        return root
    current = root
    parts = PurePosixPath(canonical).parts
    for index, part in enumerate(parts):
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if allow_absent_final:
                return root.joinpath(*parts)
            raise SafetyError(f"cannot inspect repository path: {canonical}")
        except OSError as exc:
            raise SafetyError(f"cannot inspect {canonical}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode) or is_link_like(current):
            raise SafetyError(f"refusing link-like repository path: {canonical}")
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise SafetyError(f"non-directory path component in {canonical}")
    return current


def _write_descriptor(descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise SafetyError("output write made no progress")
        remaining = remaining[written:]
    os.fsync(descriptor)


def _read_descriptor(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(65536, maximum + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            raise SafetyError(f"file exceeds {maximum} bytes")
    return b"".join(chunks)


def _windows_create_hard_link(source: Path, destination: Path) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = kernel32.CreateHardLinkW
    operation.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID]
    operation.restype = wintypes.BOOL
    if not operation(str(destination), str(source), None):
        error = ctypes.get_last_error()
        raise OSError(error, ctypes.FormatError(error), str(destination))


def _windows_delete_handle(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    class FileDispositionInfo(ctypes.Structure):
        _fields_ = [("delete_file", wintypes.BOOL)]

    information = FileDispositionInfo(True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = kernel32.SetFileInformationByHandle
    operation.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    operation.restype = wintypes.BOOL
    if not operation(wintypes.HANDLE(handle), 4, ctypes.byref(information), ctypes.sizeof(information)):
        error = ctypes.get_last_error()
        raise OSError(error, ctypes.FormatError(error))


def publish_immutable_output(
    path: Path,
    data: bytes,
    temporary_name: str,
    *,
    require_identical: bool = True,
) -> bool:
    """Atomically create immutable content, accepting an identical race winner."""
    if not temporary_name or "/" in temporary_name or "\\" in temporary_name:
        raise SafetyError("temporary output name must be one plain path component")
    if os.name == "nt":
        import msvcrt

        with _windows_locked_parent(path) as (absolute, parent_handle):
            temporary = absolute.with_name(temporary_name)
            descriptor = _windows_file_descriptor(
                temporary,
                parent_handle=parent_handle,
                access=0x40000000 | 0x00010000 | 0x00000080,
                creation=1,
                descriptor_flags=os.O_RDWR | getattr(os, "O_BINARY", 0),
            )
            renamed = False
            rename_error: OSError | None = None
            try:
                _write_descriptor(descriptor, data)
                try:
                    _windows_create_hard_link(temporary, absolute)
                    renamed = True
                except OSError as exc:
                    rename_error = exc
                finally:
                    _windows_delete_handle(msvcrt.get_osfhandle(descriptor))
            finally:
                os.close(descriptor)
            try:
                verification = _windows_file_descriptor(
                    absolute,
                    parent_handle=parent_handle,
                    # FILE_READ_DATA is required by _read_descriptor();
                    # FILE_READ_ATTRIBUTES alone cannot verify the winner.
                    access=0x00000001 | 0x00000080,
                    creation=3,
                    descriptor_flags=os.O_RDONLY | getattr(os, "O_BINARY", 0),
                )
            except OSError:
                if rename_error is not None:
                    raise SafetyError(f"cannot publish immutable output {absolute}: {rename_error}") from rename_error
                raise
            try:
                metadata = os.fstat(verification)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise SafetyError(f"refusing unsafe immutable output: {absolute}")
                if require_identical and metadata.st_size != len(data):
                    raise SafetyError(f"immutable output race has different content: {absolute}")
                if require_identical and _read_descriptor(verification, len(data)) != data:
                    raise SafetyError(f"immutable output race has different content: {absolute}")
            finally:
                os.close(verification)
            return renamed
    if not SAFE_POSIX_DIR_FD:
        raise SafetyError("safe immutable publication is unavailable")
    with _posix_bound_parent(path) as (parent, name, absolute):
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        temporary = os.open(temporary_name, flags, 0o600, dir_fd=parent)
        linked = False
        try:
            _write_descriptor(temporary, data)
            try:
                os.link(
                    temporary_name,
                    name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                    follow_symlinks=False,
                )
                linked = True
            except FileExistsError:
                pass
        finally:
            os.close(temporary)
            try:
                os.unlink(temporary_name, dir_fd=parent)
            except FileNotFoundError:
                pass
        verification = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent,
        )
        try:
            metadata = os.fstat(verification)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise SafetyError(f"refusing unsafe immutable output: {absolute}")
            if require_identical and metadata.st_size != len(data):
                raise SafetyError(f"immutable output race has different content: {absolute}")
            if require_identical and _read_descriptor(verification, len(data)) != data:
                raise SafetyError(f"immutable output race has different content: {absolute}")
        finally:
            os.close(verification)
        return linked


def write_created_output(path: Path, data: bytes) -> None:
    """Create one new regular output without following any path component."""
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
                raise SafetyError(f"cannot create output {absolute}: {exc}") from exc
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise SafetyError(f"refusing unsafe new output: {absolute}")
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
                    or filesystem_identity(absolute, final_entry)
                    != filesystem_identity(absolute, final_metadata)
                ):
                    raise SafetyError(f"output entry changed while being written: {absolute}")
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
            raise SafetyError(f"cannot create output {absolute}: {exc}") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise SafetyError(f"refusing unsafe new output: {absolute}")
            _write_descriptor(descriptor, data)
            final_metadata = os.fstat(descriptor)
            final_entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISREG(final_entry.st_mode)
                or final_entry.st_nlink != 1
                or final_metadata.st_nlink != 1
                or filesystem_identity(absolute, final_entry)
                != filesystem_identity(absolute, final_metadata)
            ):
                raise SafetyError(f"output entry changed while being written: {absolute}")
        finally:
            os.close(descriptor)
