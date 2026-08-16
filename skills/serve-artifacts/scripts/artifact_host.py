#!/usr/bin/env python3
"""Publish and serve transient interactive web artifacts safely.

The server is deliberately a data plane. Artifact creation, framework builds,
and application process management remain the producer's responsibility.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import errno
import hmac
import html
import http.server
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any, Iterator


SCHEMA_VERSION = 1
DEFAULT_BIND_ADDRESS = "127.0.0.1"
DEFAULT_PORT = 4177
DEFAULT_TTL = "24h"
COMMAND_TIMEOUT_SECONDS = 15
NETWORK_APPLY_TIMEOUT_SECONDS = 60
MAX_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_FILES = 1000
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_PROXY_BYTES = 10 * 1024 * 1024
PUBLIC_PREFIX = "/agent-artifacts"
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
PATH_PATTERN = re.compile(r"^/[a-z0-9][a-z0-9/-]*$")
BLOCKED_SUFFIXES = {
    ".bat",
    ".cgi",
    ".class",
    ".cmd",
    ".com",
    ".dll",
    ".dylib",
    ".exe",
    ".jar",
    ".php",
    ".pl",
    ".ps1",
    ".py",
    ".rb",
    ".sh",
    ".so",
}
SAFE_REQUEST_HEADERS = {"accept", "accept-encoding", "accept-language", "user-agent"}
SAFE_RESPONSE_HEADERS = {
    "cache-control",
    "content-encoding",
    "content-language",
    "content-type",
    "etag",
    "last-modified",
    "location",
    "vary",
}
CONTENT_SECURITY_POLICY = (
    "default-src 'self' data: blob:; "
    "script-src 'self' 'unsafe-inline' blob:; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "media-src 'self' data: blob:; "
    "worker-src 'self' blob:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'self'"
)


class ArtifactError(RuntimeError):
    """A safe, user-facing artifact operation failure."""


def normalize_bind_address(value: str, allow_remote: bool = False) -> str:
    """Accept one explicit IPv4 interface and require confirmation for remote access."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ArtifactError("bind address must be an explicit IPv4 address") from exc
    if not isinstance(address, ipaddress.IPv4Address):
        raise ArtifactError("bind address must be an explicit IPv4 address")
    if address.is_unspecified:
        raise ArtifactError("wildcard bind addresses are not allowed; select one interface address")
    if address.is_multicast or address.is_reserved:
        raise ArtifactError("multicast and reserved bind addresses are not allowed")
    if not address.is_loopback and address.is_global:
        raise ArtifactError("public-interface binding is not supported by this transient host")
    if not address.is_loopback and not allow_remote:
        raise ArtifactError("non-loopback binding requires --allow-remote after reviewing reachability")
    return address.compressed


def normalize_advertise_url(value: str | None) -> str | None:
    """Validate an optional browser-facing origin or reviewed artifact proxy base."""
    if value is None:
        return None
    if any(character.isspace() for character in value):
        raise ArtifactError("advertise URL cannot contain whitespace")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ArtifactError("advertise URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ArtifactError("advertise URL must use http or https with a host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ArtifactError("advertise URL cannot contain credentials, a query, or a fragment")
    if port is not None and not 1 <= port <= 65535:
        raise ArtifactError("advertise URL has an invalid port")
    path = parsed.path.rstrip("/")
    if path not in {"", PUBLIC_PREFIX}:
        raise ArtifactError(f"advertise URL path must be empty or {PUBLIC_PREFIX}")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def runtime_bind_address(runtime: dict[str, Any]) -> str:
    """Read new runtime state while remaining compatible with loopback-only v1 state."""
    return normalize_bind_address(str(runtime.get("bind_address", DEFAULT_BIND_ADDRESS)), True)


def bound_base_url(runtime: dict[str, Any]) -> str:
    return f"http://{runtime_bind_address(runtime)}:{int(runtime['port'])}"


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def isoformat(value: dt.datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ArtifactError(f"invalid stored timestamp: {value!r}") from exc


def parse_ttl(value: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)([smhd])", value.strip().lower())
    if not match:
        raise ArtifactError("TTL must be a positive integer followed by s, m, h, or d")
    factors = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    seconds = int(match.group(1)) * factors[match.group(2)]
    if seconds > MAX_TTL_SECONDS:
        raise ArtifactError("TTL cannot exceed 30d")
    return seconds


def state_root(explicit: str | None = None) -> Path:
    override = explicit or os.environ.get("ARTIFACT_HOST_STATE_DIR")
    if override:
        candidate = Path(os.path.expandvars(os.path.expanduser(override)))
        if not candidate.is_absolute():
            raise ArtifactError("ARTIFACT_HOST_STATE_DIR must be an absolute path")
        return candidate.resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "AgentKit" / "artifacts"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AgentKit" / "artifacts"
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "agent-kit" / "artifacts"


def path_is_link(path: Path) -> bool:
    try:
        information = path.lstat()
    except FileNotFoundError:
        return False
    attributes = int(getattr(information, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return stat.S_ISLNK(information.st_mode) or bool(attributes & reparse_flag)


def ensure_private_dir(path: Path) -> None:
    if path_is_link(path):
        raise ArtifactError(f"refusing symlinked state directory: {path}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise ArtifactError(f"expected directory: {path}")
    if os.name != "nt":
        path.chmod(0o700)


def contained(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def atomic_write_json(path: Path, value: Any) -> None:
    ensure_private_dir(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=".artifact-host-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        last_error: PermissionError | None = None
        for attempt in range(8):
            try:
                os.replace(temporary_path, path)
                break
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.05 * (attempt + 1))
        else:
            raise last_error or PermissionError(f"cannot replace {path}")
        if os.name != "nt":
            path.chmod(0o600)
    except Exception:
        with contextlib.suppress(OSError):
            temporary_path.unlink()
        raise


def _try_lock(handle: Any) -> bool:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _unlock(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def store_lock(root: Path, timeout: float = 10.0) -> Iterator[None]:
    ensure_private_dir(root)
    lock_path = root / ".lock"
    if path_is_link(lock_path):
        raise ArtifactError(f"refusing symlinked state lock: {lock_path}")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    if os.name != "nt":
        os.chmod(lock_path, 0o600)
    with os.fdopen(descriptor, "r+b", buffering=0) as handle:
        if lock_path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                raise ArtifactError(f"artifact store is busy: {root}")
            time.sleep(0.05)
        try:
            yield
        finally:
            _unlock(handle)


def registry_path(root: Path) -> Path:
    return root / "registry.json"


def runtime_path(root: Path) -> Path:
    return root / "runtime.json"


def tailscale_path(root: Path) -> Path:
    return root / "tailscale.json"


def empty_registry() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "artifacts": {}}


def load_json_object(path: Path) -> dict[str, Any]:
    if path_is_link(path):
        raise ArtifactError(f"refusing symlinked state file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactError(f"expected a JSON object in {path}")
    return value


def load_registry(root: Path) -> dict[str, Any]:
    value = load_json_object(registry_path(root))
    if not value:
        return empty_registry()
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ArtifactError("unsupported artifact registry schema")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ArtifactError("artifact registry has invalid artifacts table")
    for artifact_id, record in artifacts.items():
        if not ID_PATTERN.fullmatch(artifact_id) or not isinstance(record, dict):
            raise ArtifactError("artifact registry contains an invalid record")
    return value


def new_id() -> str:
    return secrets.token_urlsafe(24)


def validate_id(value: str) -> str:
    if not ID_PATTERN.fullmatch(value):
        raise ArtifactError("invalid artifact ID")
    return value


def content_root_path(root: Path, create: bool = False) -> Path:
    content_root = root / "content"
    if path_is_link(content_root):
        raise ArtifactError(f"refusing symlinked artifact content directory: {content_root}")
    if create:
        ensure_private_dir(content_root)
    elif content_root.exists() and not content_root.is_dir():
        raise ArtifactError(f"expected artifact content directory: {content_root}")
    return content_root


def artifact_content_path(root: Path, artifact_id: str) -> Path:
    validate_id(artifact_id)
    content = content_root_path(root) / artifact_id
    if path_is_link(content):
        raise ArtifactError(f"refusing symlinked artifact content: {content}")
    return content


def remove_artifact_content(root: Path, artifact_id: str) -> None:
    content = artifact_content_path(root, artifact_id)
    if not content.exists():
        return
    if not content.is_dir():
        raise ArtifactError(f"expected artifact content directory: {content}")
    try:
        shutil.rmtree(content)
    except OSError as exc:
        raise ArtifactError(f"cannot remove artifact content {artifact_id}: {exc}") from exc


def safe_relative(value: str, label: str = "path") -> PurePosixPath:
    decoded = urllib.parse.unquote(value)
    if "\x00" in decoded or "\\" in decoded or decoded.startswith("/"):
        raise ArtifactError(f"unsafe {label}: {value}")
    path = PurePosixPath(decoded)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ArtifactError(f"unsafe {label}: {value}")
    return path


def artifact_expired(record: dict[str, Any], now: dt.datetime | None = None) -> bool:
    return parse_time(str(record.get("expires_at"))) <= (now or utc_now())


def cleanup_expired(root: Path, now: dt.datetime | None = None) -> list[str]:
    removed: list[str] = []
    with store_lock(root):
        registry = load_registry(root)
        for artifact_id, record in list(registry["artifacts"].items()):
            if not artifact_expired(record, now):
                continue
            remove_artifact_content(root, artifact_id)
            del registry["artifacts"][artifact_id]
            atomic_write_json(registry_path(root), registry)
            removed.append(artifact_id)
    return removed


def reserve_artifact(root: Path, ttl: str, title: str) -> dict[str, Any]:
    seconds = parse_ttl(ttl)
    now = utc_now()
    with store_lock(root):
        registry = load_registry(root)
        artifact_id = new_id()
        while artifact_id in registry["artifacts"]:
            artifact_id = new_id()
        record = {
            "kind": "reserved",
            "title": title.strip()[:160] or "Untitled artifact",
            "created_at": isoformat(now),
            "expires_at": isoformat(now + dt.timedelta(seconds=seconds)),
        }
        registry["artifacts"][artifact_id] = record
        atomic_write_json(registry_path(root), registry)
    return {"id": artifact_id, **record}


def inspect_bundle(source: Path, entry: str) -> tuple[list[tuple[Path, PurePosixPath]], int]:
    existing_parts = [source]
    existing_parts.extend(parent for parent in source.parents if parent != parent.parent)
    if any(path_is_link(candidate) for candidate in existing_parts):
        raise ArtifactError(f"refusing symlinked artifact source: {source}")
    if source.is_file():
        if source.suffix.lower() not in {".html", ".htm"}:
            raise ArtifactError("a single-file artifact must be HTML")
        files = [(source, PurePosixPath("index.html"))]
        normalized_entry = "index.html"
    elif source.is_dir():
        files = []
        for directory, directory_names, file_names in os.walk(source, followlinks=False):
            base = Path(directory)
            if path_is_link(base):
                raise ArtifactError(f"refusing symlinked artifact directory: {base}")
            for name in directory_names:
                candidate = base / name
                if path_is_link(candidate):
                    raise ArtifactError(f"refusing symlinked artifact directory: {candidate}")
                if name.startswith("."):
                    raise ArtifactError(f"refusing hidden artifact directory: {candidate}")
            for name in file_names:
                candidate = base / name
                if path_is_link(candidate) or not candidate.is_file():
                    raise ArtifactError(f"refusing linked or special artifact file: {candidate}")
                if name.startswith("."):
                    raise ArtifactError(f"refusing hidden artifact file: {candidate}")
                relative = PurePosixPath(candidate.relative_to(source).as_posix())
                files.append((candidate, relative))
        normalized_entry = safe_relative(entry, "entry file").as_posix()
    else:
        raise ArtifactError(f"artifact source does not exist: {source}")

    if not files:
        raise ArtifactError("artifact bundle is empty")
    if len(files) > MAX_FILES:
        raise ArtifactError(f"artifact bundle exceeds {MAX_FILES} files")
    total = 0
    names: set[str] = set()
    for candidate, relative in files:
        suffix = candidate.suffix.lower()
        if suffix in BLOCKED_SUFFIXES:
            raise ArtifactError(f"blocked executable artifact type: {relative}")
        size = candidate.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ArtifactError(f"artifact file exceeds {MAX_FILE_BYTES} bytes: {relative}")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ArtifactError(f"artifact bundle exceeds {MAX_TOTAL_BYTES} bytes")
        names.add(relative.as_posix())
    if normalized_entry not in names:
        raise ArtifactError(f"artifact entry file does not exist: {normalized_entry}")
    return sorted(files, key=lambda item: item[1].as_posix()), total


def _copy_bundle(files: list[tuple[Path, PurePosixPath]], destination: Path) -> None:
    destination.mkdir(mode=0o700)
    for source, relative in files:
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path_is_link(source):
            raise ArtifactError(f"artifact source changed into a symlink: {source}")
        shutil.copyfile(source, target)
        if os.name != "nt":
            target.chmod(0o600)


def _claim_record(
    registry: dict[str, Any], artifact_id: str | None, record: dict[str, Any]
) -> str:
    if artifact_id is None:
        artifact_id = new_id()
        while artifact_id in registry["artifacts"]:
            artifact_id = new_id()
    else:
        validate_id(artifact_id)
        existing = registry["artifacts"].get(artifact_id)
        if not existing or existing.get("kind") != "reserved":
            raise ArtifactError("--id must refer to an unexpired reserved artifact")
        if artifact_expired(existing):
            raise ArtifactError("reserved artifact has expired")
        record["created_at"] = existing["created_at"]
        if parse_time(record["expires_at"]) > parse_time(existing["expires_at"]):
            record["expires_at"] = existing["expires_at"]
        if not record.get("title"):
            record["title"] = existing.get("title", "Untitled artifact")
    registry["artifacts"][artifact_id] = record
    return artifact_id


def publish_static(
    root: Path,
    source: Path,
    ttl: str,
    title: str,
    entry: str,
    spa: bool,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    source = Path(os.path.abspath(os.path.expanduser(source)))
    files, total = inspect_bundle(source, entry)
    seconds = parse_ttl(ttl)
    now = utc_now()
    ensure_private_dir(root)
    content_root = content_root_path(root, create=True)
    stage = Path(tempfile.mkdtemp(prefix=".publish-", dir=content_root))
    if os.name != "nt":
        stage.chmod(0o700)
    try:
        _copy_bundle(files, stage / "bundle")
        with store_lock(root):
            registry = load_registry(root)
            record = {
                "kind": "static",
                "title": title.strip()[:160] or "Untitled artifact",
                "created_at": isoformat(now),
                "expires_at": isoformat(now + dt.timedelta(seconds=seconds)),
                "entry": "index.html" if source.is_file() else safe_relative(entry, "entry file").as_posix(),
                "spa": bool(spa),
                "files": len(files),
                "bytes": total,
            }
            selected_id = _claim_record(registry, artifact_id, record)
            destination = content_root / selected_id
            if destination.exists() or path_is_link(destination):
                raise ArtifactError("artifact content destination already exists")
            os.replace(stage / "bundle", destination)
            try:
                atomic_write_json(registry_path(root), registry)
            except Exception:
                shutil.rmtree(destination, ignore_errors=True)
                raise
        return {"id": selected_id, **record}
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def normalize_proxy_target(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError as exc:
        raise ArtifactError(f"invalid proxy target: {value}") from exc
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ArtifactError("proxy target must use http://127.0.0.1 or http://localhost")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ArtifactError("proxy target cannot contain credentials, a query, or a fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ArtifactError("proxy target has an invalid port") from exc
    if port is None or not 1 <= port <= 65535:
        raise ArtifactError("proxy target must include a valid explicit port")
    path = parsed.path.rstrip("/")
    if path and (".." in PurePosixPath(path).parts or "\\" in path):
        raise ArtifactError("proxy target has an unsafe base path")
    return f"http://127.0.0.1:{port}{path}"


def publish_proxy(
    root: Path,
    target: str,
    ttl: str,
    title: str,
    preserve_prefix: bool,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_proxy_target(target)
    seconds = parse_ttl(ttl)
    now = utc_now()
    with store_lock(root):
        registry = load_registry(root)
        record = {
            "kind": "proxy",
            "title": title.strip()[:160] or "Proxied artifact",
            "created_at": isoformat(now),
            "expires_at": isoformat(now + dt.timedelta(seconds=seconds)),
            "target": normalized,
            "preserve_prefix": bool(preserve_prefix),
        }
        selected_id = _claim_record(registry, artifact_id, record)
        atomic_write_json(registry_path(root), registry)
    return {"id": selected_id, **record}


def revoke_artifact(root: Path, artifact_id: str) -> bool:
    validate_id(artifact_id)
    with store_lock(root):
        registry = load_registry(root)
        if artifact_id not in registry["artifacts"]:
            return False
        remove_artifact_content(root, artifact_id)
        del registry["artifacts"][artifact_id]
        atomic_write_json(registry_path(root), registry)
    return True


def list_artifacts(root: Path) -> list[dict[str, Any]]:
    cleanup_expired(root)
    registry = load_registry(root)
    return [
        {"id": artifact_id, **record}
        for artifact_id, record in sorted(
            registry["artifacts"].items(), key=lambda item: item[1]["created_at"], reverse=True
        )
    ]


def common_security_headers(handler: http.server.BaseHTTPRequestHandler) -> None:
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("X-Frame-Options", "SAMEORIGIN")
    handler.send_header(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=()",
    )
    handler.send_header("Cross-Origin-Resource-Policy", "same-origin")


def content_security_headers(handler: http.server.BaseHTTPRequestHandler) -> None:
    common_security_headers(handler)
    handler.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


class ArtifactServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], root: Path, token: str, instance_id: str):
        self.root = root
        self.token = token
        self.instance_id = instance_id
        super().__init__(address, ArtifactRequestHandler)


class ArtifactRequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = "AgentArtifactHost/1"

    @property
    def artifact_server(self) -> ArtifactServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        self._dispatch(head=False)

    def do_HEAD(self) -> None:
        self._dispatch(head=True)

    def do_POST(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path != "/_control/stop":
            self._error(404, "not found")
            return
        supplied = self.headers.get("X-Artifact-Host-Token", "")
        if not hmac.compare_digest(supplied, self.artifact_server.token):
            self._error(404, "not found")
            return
        payload = b'{"status":"stopping"}\n'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        common_security_headers(self)
        self.end_headers()
        self.wfile.write(payload)
        threading.Thread(target=self.artifact_server.shutdown, daemon=True).start()

    def _dispatch(self, head: bool) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path == "/_health":
            authorized = hmac.compare_digest(
                self.headers.get("X-Artifact-Host-Token", ""), self.artifact_server.token
            )
            payload = {"status": "ok"}
            if authorized:
                payload["instance_id"] = self.artifact_server.instance_id
            self._json(200, payload, head)
            return
        if path == PUBLIC_PREFIX:
            self.send_response(308)
            self.send_header("Location", PUBLIC_PREFIX + "/")
            common_security_headers(self)
            self.end_headers()
            return
        if path.startswith(PUBLIC_PREFIX + "/"):
            path = path[len(PUBLIC_PREFIX) :]
        parts = [urllib.parse.unquote(part) for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"a", "c"}:
            artifact_id = parts[1]
            if not ID_PATTERN.fullmatch(artifact_id):
                self._error(404, "artifact not found")
                return
            record = self._record(artifact_id)
            if record is None:
                self._error(404, "artifact not found")
                return
            if parts[0] == "a":
                self._viewer(artifact_id, record, head)
                return
            subpath = "/".join(parts[2:])
            if record.get("kind") == "static":
                self._static(artifact_id, record, subpath, head)
                return
            if record.get("kind") == "proxy":
                self._proxy(artifact_id, record, subpath, parsed.query, head)
                return
        self._error(404, "not found")

    def _record(self, artifact_id: str) -> dict[str, Any] | None:
        try:
            registry = load_registry(self.artifact_server.root)
            record = registry["artifacts"].get(artifact_id)
            if record and artifact_expired(record):
                cleanup_expired(self.artifact_server.root)
                return None
            return record
        except ArtifactError:
            return None

    def _viewer(self, artifact_id: str, record: dict[str, Any], head: bool) -> None:
        if record.get("kind") == "reserved":
            self._error(404, "artifact is not published")
            return
        entry = record.get("entry", "") if record.get("kind") == "static" else ""
        encoded_entry = "/".join(urllib.parse.quote(part) for part in entry.split("/"))
        source = f"../../c/{artifact_id}/" + encoded_entry
        title = html.escape(str(record.get("title", "Artifact")))
        document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
html,body,iframe{{width:100%;height:100%;margin:0;border:0;background:#0b1020}}
iframe{{display:block}}
</style></head><body>
<iframe title="{title}" src="{source}" sandbox="allow-scripts allow-same-origin allow-downloads allow-forms"></iframe>
</body></html>""".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(document)))
        self.send_header("Cache-Control", "no-store")
        common_security_headers(self)
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; frame-src 'self'; style-src 'unsafe-inline'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        if not head:
            self.wfile.write(document)

    def _static(
        self, artifact_id: str, record: dict[str, Any], value: str, head: bool
    ) -> None:
        try:
            relative = safe_relative(value, "request path") if value else PurePosixPath(record["entry"])
        except ArtifactError:
            self._error(404, "not found")
            return
        try:
            bundle = artifact_content_path(self.artifact_server.root, artifact_id)
        except ArtifactError:
            self._error(404, "not found")
            return
        candidate = bundle.joinpath(*relative.parts)
        if not contained(bundle, candidate):
            self._error(404, "not found")
            return
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_file() and record.get("spa"):
            candidate = bundle.joinpath(*PurePosixPath(record["entry"]).parts)
        if path_is_link(candidate) or not candidate.is_file() or not contained(bundle, candidate):
            self._error(404, "not found")
            return
        try:
            handle = candidate.open("rb")
        except OSError:
            self._error(404, "artifact not found")
            return
        with handle:
            try:
                size = os.fstat(handle.fileno()).st_size
                content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
                if content_type.startswith("text/") or candidate.suffix.lower() in {
                    ".js",
                    ".mjs",
                    ".json",
                    ".svg",
                }:
                    content_type += "; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                content_security_headers(self)
                self.end_headers()
                if not head:
                    shutil.copyfileobj(handle, self.wfile)
            except OSError:
                self.close_connection = True

    def _proxy(
        self,
        artifact_id: str,
        record: dict[str, Any],
        value: str,
        query: str,
        head: bool,
    ) -> None:
        try:
            relative = safe_relative(value, "proxy path").as_posix() if value else ""
        except ArtifactError:
            self._error(404, "not found")
            return
        target = record["target"]
        if record.get("preserve_prefix"):
            upstream_path = f"{PUBLIC_PREFIX}/c/{artifact_id}/" + relative
        else:
            upstream_path = "/" + relative
        url = target.rstrip("/") + upstream_path
        if query:
            url += "?" + query
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() in SAFE_REQUEST_HEADERS
        }
        request = urllib.request.Request(url, headers=headers, method="HEAD" if head else "GET")
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirect,
        )
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        except (urllib.error.URLError, TimeoutError, OSError):
            self._error(502, "loopback artifact service unavailable")
            return
        try:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_PROXY_BYTES:
                self._error(502, "proxied response exceeds size limit")
                return
            body = b"" if head else response.read(MAX_PROXY_BYTES + 1)
            if len(body) > MAX_PROXY_BYTES:
                self._error(502, "proxied response exceeds size limit")
                return
            self.send_response(response.status)
            for key, header_value in response.headers.items():
                if key.lower() in SAFE_RESPONSE_HEADERS and key.lower() != "content-length":
                    self.send_header(key, header_value)
            self.send_header("Content-Length", str(len(body) if not head else int(length or 0)))
            self.send_header("Cache-Control", "no-store")
            content_security_headers(self)
            self.end_headers()
            if not head:
                self.wfile.write(body)
        finally:
            response.close()

    def _json(self, status: int, value: Any, head: bool = False) -> None:
        payload = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        common_security_headers(self)
        self.end_headers()
        if not head:
            self.wfile.write(payload)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})


def read_runtime(root: Path) -> dict[str, Any]:
    return load_json_object(runtime_path(root))


def health(runtime: dict[str, Any], timeout: float = 0.5) -> bool:
    try:
        port = int(runtime["port"])
        token = str(runtime["token"])
        instance_id = str(runtime["instance_id"])
        base_url = bound_base_url(runtime)
    except (ArtifactError, KeyError, TypeError, ValueError):
        return False
    request = urllib.request.Request(
        f"{base_url}/_health",
        headers={"X-Artifact-Host-Token": token},
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            value = json.load(response)
        return value.get("instance_id") == instance_id
    except (OSError, ValueError, urllib.error.URLError):
        return False


def server_status(root: Path) -> dict[str, Any]:
    runtime = read_runtime(root)
    running = bool(runtime and health(runtime))
    result: dict[str, Any] = {"running": running, "state_dir": str(root)}
    if runtime:
        for key in ("pid", "port", "started_at", "instance_id", "bind_address"):
            if key in runtime:
                result[key] = runtime[key]
    if running:
        bind_address = runtime_bind_address(runtime)
        result["bind_address"] = bind_address
        bound_url = bound_base_url(runtime)
        if ipaddress.ip_address(bind_address).is_loopback:
            result["local_base_url"] = bound_url
        else:
            result["direct_base_url"] = bound_url
        advertised = normalize_advertise_url(runtime.get("advertise_url"))
        if advertised:
            result["shared_base_url"] = advertised
    tailnet = load_json_object(tailscale_path(root))
    if tailnet:
        result["tailnet_base_url"] = tailnet.get("base_url")
    if running:
        result["browser_base_url"] = (
            result.get("shared_base_url")
            or result.get("tailnet_base_url")
            or result.get("direct_base_url")
            or result.get("local_base_url")
        )
    return result


def require_owned_adapter_compatibility(root: Path, bind_address: str, port: int) -> None:
    tailnet = load_json_object(tailscale_path(root))
    if not tailnet:
        return
    expected_target = f"http://{bind_address}:{port}"
    if tailnet.get("target") != expected_target:
        raise ArtifactError(
            "owned Tailscale Serve route uses different network settings; remove it before restarting"
        )


def run_server(
    root: Path,
    port: int,
    bind_address: str = DEFAULT_BIND_ADDRESS,
    allow_remote: bool = False,
    advertise_url: str | None = None,
) -> None:
    if not 1 <= port <= 65535:
        raise ArtifactError("port must be between 1 and 65535")
    bind_address = normalize_bind_address(bind_address, allow_remote)
    advertise_url = normalize_advertise_url(advertise_url)
    require_owned_adapter_compatibility(root, bind_address, port)
    ensure_private_dir(root)
    cleanup_expired(root)
    token = secrets.token_urlsafe(32)
    instance_id = secrets.token_hex(16)
    try:
        server = ArtifactServer((bind_address, port), root, token, instance_id)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            raise ArtifactError(f"artifact host address {bind_address}:{port} is already in use") from exc
        raise
    runtime = {
        "pid": os.getpid(),
        "port": server.server_address[1],
        "bind_address": bind_address,
        "token": token,
        "instance_id": instance_id,
        "started_at": isoformat(utc_now()),
    }
    if advertise_url:
        runtime["advertise_url"] = advertise_url
    atomic_write_json(runtime_path(root), runtime)

    stop_event = threading.Event()

    def stop_signal(_signum: int, _frame: Any) -> None:
        if not stop_event.is_set():
            stop_event.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, stop_signal)
        if hasattr(signal, "SIGINT"):
            signal.signal(signal.SIGINT, stop_signal)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        current = read_runtime(root)
        if current.get("instance_id") == instance_id:
            with contextlib.suppress(OSError):
                runtime_path(root).unlink()


def start_server(
    root: Path,
    port: int = DEFAULT_PORT,
    bind_address: str = DEFAULT_BIND_ADDRESS,
    allow_remote: bool = False,
    advertise_url: str | None = None,
) -> dict[str, Any]:
    bind_address = normalize_bind_address(bind_address, allow_remote)
    advertise_url = normalize_advertise_url(advertise_url)
    require_owned_adapter_compatibility(root, bind_address, port)
    current = read_runtime(root)
    if current and health(current):
        current_bind = runtime_bind_address(current)
        current_advertise = normalize_advertise_url(current.get("advertise_url"))
        if (
            int(current["port"]) != port
            or current_bind != bind_address
            or current_advertise != advertise_url
        ):
            raise ArtifactError(
                "artifact host already runs with different network settings; stop it before changing them"
            )
        return server_status(root)
    with contextlib.suppress(OSError):
        runtime_path(root).unlink()
    command = [sys.executable, str(Path(__file__).resolve())]
    command.extend(
        [
            "--state-dir",
            str(root),
            "serve",
            "--port",
            str(port),
            "--bind-address",
            bind_address,
        ]
    )
    if not ipaddress.ip_address(bind_address).is_loopback:
        command.append("--allow-remote")
    if advertise_url:
        command.extend(["--advertise-url", advertise_url])
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        runtime = read_runtime(root)
        if runtime and health(runtime):
            status = server_status(root)
            threading.Thread(target=process.wait, daemon=True).start()
            return status
        time.sleep(0.05)
    if process.poll() is None:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2)
    raise ArtifactError(f"artifact host failed to start on {bind_address}:{port}")


def stop_server(root: Path) -> bool:
    runtime = read_runtime(root)
    if not runtime or not health(runtime):
        with contextlib.suppress(OSError):
            runtime_path(root).unlink()
        return False
    request = urllib.request.Request(
        f"{bound_base_url(runtime)}/_control/stop",
        data=b"",
        method="POST",
        headers={"X-Artifact-Host-Token": str(runtime["token"])},
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=2):
            pass
    except urllib.error.URLError as exc:
        raise ArtifactError("artifact host did not accept the stop request") from exc
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not health(runtime):
            with contextlib.suppress(OSError):
                runtime_path(root).unlink()
            return True
        time.sleep(0.05)
    raise ArtifactError("artifact host did not stop within five seconds")


def ensure_server(root: Path, port: int) -> dict[str, Any]:
    current = read_runtime(root)
    if current and health(current):
        if int(current["port"]) != port:
            raise ArtifactError(
                f"artifact host already runs on port {current['port']}; use that port or stop it first"
            )
        return server_status(root)
    return start_server(root, port)


def artifact_urls(root: Path, record: dict[str, Any], port: int) -> dict[str, str]:
    artifact_id = record["id"]
    runtime = read_runtime(root)
    if not runtime or int(runtime.get("port", 0)) != port:
        runtime = {"port": port, "bind_address": DEFAULT_BIND_ADDRESS}
    bind_address = runtime_bind_address(runtime)
    bound_url = bound_base_url(runtime)
    result: dict[str, str] = {}
    if ipaddress.ip_address(bind_address).is_loopback:
        result["local_url"] = f"{bound_url}/a/{artifact_id}/"
    else:
        result["shared_url"] = f"{bound_url}/a/{artifact_id}/"
    advertised = normalize_advertise_url(runtime.get("advertise_url"))
    if advertised:
        result["shared_url"] = f"{advertised.rstrip('/')}/a/{artifact_id}/"
    tailnet = load_json_object(tailscale_path(root))
    if tailnet.get("base_url"):
        result["tailnet_url"] = f"{tailnet['base_url'].rstrip('/')}/a/{artifact_id}/"
    result["browser_url"] = (
        result.get("shared_url") or result.get("tailnet_url") or result.get("local_url", "")
    )
    result["content_base_path"] = f"{PUBLIC_PREFIX}/c/{artifact_id}"
    return result


def run_command(
    command: list[str], timeout: int = COMMAND_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        details = exc.stderr or exc.stdout or ""
        if isinstance(details, bytes):
            details = details.decode(errors="replace")
        suffix = f": {details.strip()}" if details.strip() else ""
        raise ArtifactError(
            f"{Path(command[0]).name} command timed out after {timeout} seconds{suffix}"
        ) from exc


def tailscale_binary() -> str:
    binary = shutil.which("tailscale")
    if not binary:
        raise ArtifactError("Tailscale CLI is not installed")
    return binary


def tailscale_status(binary: str) -> dict[str, Any]:
    result = run_command([binary, "status", "--json"])
    if result.returncode != 0:
        raise ArtifactError(f"cannot inspect Tailscale status: {result.stderr.strip()}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ArtifactError("Tailscale status did not return JSON") from exc
    if not isinstance(value, dict):
        raise ArtifactError("Tailscale status returned an invalid value")
    return value


def tailscale_serve_status(binary: str) -> dict[str, Any]:
    result = run_command([binary, "serve", "status", "--json"])
    if result.returncode != 0:
        raise ArtifactError(f"cannot inspect Tailscale Serve: {result.stderr.strip()}")
    try:
        value = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ArtifactError("Tailscale Serve status did not return JSON") from exc
    if not isinstance(value, dict):
        raise ArtifactError("Tailscale Serve status returned an invalid value")
    return value


def nested_path_values(value: Any, path: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for current_key, current_value in value.items():
            if isinstance(current_key, str) and current_key.rstrip("/") == path.rstrip("/"):
                found.append(current_value)
            found.extend(nested_path_values(current_value, path))
    elif isinstance(value, list):
        for item in value:
            found.extend(nested_path_values(item, path))
    return found


def validate_public_path(value: str) -> str:
    value = "/" + value.strip("/")
    if not PATH_PATTERN.fullmatch(value) or "//" in value or ".." in value.split("/"):
        raise ArtifactError("Tailscale path must contain lower-case letters, digits, /, and -")
    return value


def validate_live_tailscale_ownership(
    serve: dict[str, Any], state: dict[str, Any]
) -> tuple[str, int, str]:
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ArtifactError("unsupported Tailscale ownership schema")
    public_path = validate_public_path(str(state.get("path", "")))
    try:
        https_port = int(state.get("https_port", 0))
    except (TypeError, ValueError) as exc:
        raise ArtifactError("invalid Tailscale ownership HTTPS port") from exc
    if not 1 <= https_port <= 65535:
        raise ArtifactError("invalid Tailscale ownership HTTPS port")
    target = normalize_proxy_target(str(state.get("target", "")))

    try:
        base_url = urllib.parse.urlsplit(str(state.get("base_url", "")))
        base_port = base_url.port or 443
    except ValueError as exc:
        raise ArtifactError("invalid Tailscale ownership base URL") from exc
    if (
        base_url.scheme != "https"
        or not base_url.hostname
        or base_url.username
        or base_url.password
        or base_url.query
        or base_url.fragment
        or (base_url.path.rstrip("/") or "/") != public_path
        or base_port != https_port
    ):
        raise ArtifactError("invalid Tailscale ownership base URL")

    authority = f"{base_url.hostname.lower()}:{https_port}"
    web = serve.get("Web")
    site = None
    if isinstance(web, dict):
        site = next(
            (
                value
                for key, value in web.items()
                if isinstance(key, str) and key.lower() == authority
            ),
            None,
        )
    handlers = site.get("Handlers") if isinstance(site, dict) else None
    matches = []
    if isinstance(handlers, dict):
        matches = [
            value
            for key, value in handlers.items()
            if isinstance(key, str)
            and (key.rstrip("/") or "/") == public_path
        ]
    if len(matches) != 1 or not isinstance(matches[0], dict):
        raise ArtifactError(
            "live Tailscale Serve handler no longer matches recorded ownership; refusing removal"
        )
    try:
        live_target = normalize_proxy_target(str(matches[0].get("Proxy", "")))
    except ArtifactError as exc:
        raise ArtifactError(
            "live Tailscale Serve handler no longer matches recorded ownership; refusing removal"
        ) from exc
    if live_target != target:
        raise ArtifactError(
            "live Tailscale Serve handler no longer matches recorded ownership; refusing removal"
        )
    return public_path, https_port, target


def tailscale_plan(root: Path, port: int, https_port: int, public_path: str) -> dict[str, Any]:
    binary = tailscale_binary()
    public_path = validate_public_path(public_path)
    if not 1 <= https_port <= 65535:
        raise ArtifactError("HTTPS port must be between 1 and 65535")
    runtime = read_runtime(root)
    if not health(runtime):
        raise ArtifactError("start the local artifact host before configuring Tailscale")
    if int(runtime.get("port", 0)) != port:
        raise ArtifactError(
            f"artifact host runs on port {runtime.get('port')}; use that port for Tailscale setup"
        )
    bind_address = runtime_bind_address(runtime)
    if not ipaddress.ip_address(bind_address).is_loopback:
        raise ArtifactError("Tailscale Serve requires a loopback-bound artifact host")
    target = f"http://{bind_address}:{port}"
    serve = tailscale_serve_status(binary)
    existing = nested_path_values(serve, public_path)
    owned = load_json_object(tailscale_path(root))
    if existing and not owned:
        raise ArtifactError(f"Tailscale Serve path {public_path} already exists and is not owned by this host")
    if existing and target not in json.dumps(existing, sort_keys=True):
        raise ArtifactError(f"Tailscale Serve path {public_path} points to another target")
    if owned and any(
        owned.get(key) != expected
        for key, expected in {"path": public_path, "https_port": https_port, "target": target}.items()
    ):
        raise ArtifactError("existing artifact-host Tailscale ownership uses different settings")
    status = tailscale_status(binary)
    dns_name = str(status.get("Self", {}).get("DNSName", "")).rstrip(".")
    if not dns_name:
        raise ArtifactError("Tailscale status does not report a MagicDNS name")
    authority = dns_name if https_port == 443 else f"{dns_name}:{https_port}"
    base_url = f"https://{authority}{public_path}"
    command = [
        binary,
        "serve",
        "--bg",
        "--yes",
        f"--https={https_port}",
        f"--set-path={public_path}",
        target,
    ]
    return {
        "action": "configure",
        "command": command,
        "path": public_path,
        "https_port": https_port,
        "target": target,
        "base_url": base_url,
        "certificate_notice": "The machine MagicDNS name may appear in public certificate-transparency logs.",
    }


def tailscale_setup(
    root: Path,
    port: int,
    https_port: int,
    public_path: str,
    apply: bool,
    yes: bool,
) -> dict[str, Any]:
    if yes and not apply:
        raise ArtifactError("--yes requires --apply")
    plan = tailscale_plan(root, port, https_port, public_path)
    plan["applied"] = False
    if not apply:
        return plan
    if not yes:
        raise ArtifactError("Tailscale setup requires --apply --yes after reviewing the plan")
    result = run_command(plan["command"], timeout=NETWORK_APPLY_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise ArtifactError(f"Tailscale Serve setup failed: {result.stderr.strip() or result.stdout.strip()}")
    state = {
        "schema_version": SCHEMA_VERSION,
        "path": plan["path"],
        "https_port": plan["https_port"],
        "target": plan["target"],
        "base_url": plan["base_url"],
        "applied_at": isoformat(utc_now()),
    }
    try:
        atomic_write_json(tailscale_path(root), state)
    except Exception:
        rollback = [
            plan["command"][0],
            "serve",
            "--yes",
            f"--https={plan['https_port']}",
            f"--set-path={plan['path']}",
            plan["target"],
            "off",
        ]
        rollback_result = run_command(rollback, timeout=NETWORK_APPLY_TIMEOUT_SECONDS)
        if rollback_result.returncode != 0:
            raise ArtifactError(
                "Tailscale route was configured but ownership state and automatic rollback failed; "
                "remove the exact previewed path manually"
            )
        raise
    plan["applied"] = True
    return plan


def tailscale_remove(root: Path, apply: bool, yes: bool) -> dict[str, Any]:
    if yes and not apply:
        raise ArtifactError("--yes requires --apply")
    state = load_json_object(tailscale_path(root))
    if not state:
        return {"action": "remove", "configured": False, "applied": False}
    binary = tailscale_binary()
    serve = tailscale_serve_status(binary)
    public_path, https_port, target = validate_live_tailscale_ownership(serve, state)
    command = [
        binary,
        "serve",
        "--yes",
        f"--https={https_port}",
        f"--set-path={public_path}",
        target,
        "off",
    ]
    plan = {"action": "remove", "configured": True, "command": command, "applied": False}
    if not apply:
        return plan
    if not yes:
        raise ArtifactError("Tailscale removal requires --apply --yes after reviewing the plan")
    result = run_command(command, timeout=NETWORK_APPLY_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise ArtifactError(f"Tailscale Serve removal failed: {result.stderr.strip() or result.stdout.strip()}")
    tailscale_path(root).unlink()
    plan["applied"] = True
    return plan


def output(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "command" and isinstance(item, list):
                item = subprocess.list2cmdline(item) if os.name == "nt" else shlex.join(item)
            print(f"{key}: {item}")
    elif isinstance(value, list):
        for item in value:
            print(json.dumps(item, sort_keys=True, ensure_ascii=False))
    else:
        print(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("serve", help="run the artifact server in the foreground")
    command.add_argument("--port", type=int, default=DEFAULT_PORT)
    command.add_argument("--bind-address", default=DEFAULT_BIND_ADDRESS)
    command.add_argument("--allow-remote", action="store_true")
    command.add_argument("--advertise-url")

    for name, help_text in (
        ("start", "start the local artifact server in the background"),
        ("status", "show server and sharing state"),
        ("stop", "stop the owned background server"),
        ("list", "list active artifacts"),
        ("cleanup", "remove expired artifact copies"),
        ("doctor", "inspect the host and optional network adapters"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--json", action="store_true")
        if name == "start":
            command.add_argument("--port", type=int, default=DEFAULT_PORT)
            command.add_argument("--bind-address", default=DEFAULT_BIND_ADDRESS)
            command.add_argument("--allow-remote", action="store_true")
            command.add_argument("--advertise-url")

    command = subparsers.add_parser("reserve", help="reserve an ID before a framework build")
    command.add_argument("--ttl", default=DEFAULT_TTL)
    command.add_argument("--title", default="Reserved artifact")
    command.add_argument("--port", type=int, default=DEFAULT_PORT)
    command.add_argument("--json", action="store_true")

    command = subparsers.add_parser("publish", help="copy and publish a static web bundle")
    command.add_argument("path")
    command.add_argument("--ttl", default=DEFAULT_TTL)
    command.add_argument("--title", default="Web artifact")
    command.add_argument("--entry", default="index.html")
    command.add_argument("--spa", action="store_true")
    command.add_argument("--id")
    command.add_argument("--port", type=int, default=DEFAULT_PORT)
    command.add_argument("--json", action="store_true")

    command = subparsers.add_parser("proxy", help="publish an already-running loopback HTTP app")
    command.add_argument("url")
    command.add_argument("--ttl", default=DEFAULT_TTL)
    command.add_argument("--title", default="Loopback app")
    command.add_argument("--preserve-prefix", action="store_true")
    command.add_argument("--id")
    command.add_argument("--port", type=int, default=DEFAULT_PORT)
    command.add_argument("--json", action="store_true")

    command = subparsers.add_parser("revoke", help="remove one artifact copy or proxy record")
    command.add_argument("id")
    command.add_argument("--json", action="store_true")

    command = subparsers.add_parser("tailscale-setup", help="preview or configure tailnet-only HTTPS")
    command.add_argument("--port", type=int, default=DEFAULT_PORT)
    command.add_argument("--https-port", type=int, default=443)
    command.add_argument("--path", default=PUBLIC_PREFIX)
    command.add_argument("--apply", action="store_true")
    command.add_argument("--yes", action="store_true")
    command.add_argument("--json", action="store_true")

    command = subparsers.add_parser("tailscale-remove", help="preview or remove the owned Serve path")
    command.add_argument("--apply", action="store_true")
    command.add_argument("--yes", action="store_true")
    command.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = state_root(args.state_dir)
    try:
        if args.command == "serve":
            run_server(
                root,
                args.port,
                args.bind_address,
                args.allow_remote,
                args.advertise_url,
            )
            return 0
        if args.command == "start":
            output(
                start_server(
                    root,
                    args.port,
                    args.bind_address,
                    args.allow_remote,
                    args.advertise_url,
                ),
                args.json,
            )
        elif args.command == "status":
            output(server_status(root), args.json)
        elif args.command == "stop":
            output({"stopped": stop_server(root)}, args.json)
        elif args.command == "list":
            output(list_artifacts(root), args.json)
        elif args.command == "cleanup":
            removed = cleanup_expired(root)
            output({"removed": removed, "count": len(removed)}, args.json)
        elif args.command == "doctor":
            status = server_status(root)
            status.update(
                {
                    "python": platform_python(),
                    "tailscale_cli": shutil.which("tailscale"),
                    "limits": {
                        "max_files": MAX_FILES,
                        "max_total_bytes": MAX_TOTAL_BYTES,
                        "max_file_bytes": MAX_FILE_BYTES,
                        "max_ttl": "30d",
                    },
                }
            )
            output(status, args.json)
        elif args.command == "reserve":
            parse_ttl(args.ttl)
            runtime = ensure_server(root, args.port)
            record = reserve_artifact(root, args.ttl, args.title)
            record.update(artifact_urls(root, record, int(runtime["port"])))
            output(record, args.json)
        elif args.command == "publish":
            source = Path(os.path.abspath(os.path.expanduser(args.path)))
            inspect_bundle(source, args.entry)
            parse_ttl(args.ttl)
            if args.id:
                validate_id(args.id)
            runtime = ensure_server(root, args.port)
            record = publish_static(
                root,
                source,
                args.ttl,
                args.title,
                args.entry,
                args.spa,
                args.id,
            )
            record.update(artifact_urls(root, record, int(runtime["port"])))
            output(record, args.json)
        elif args.command == "proxy":
            normalize_proxy_target(args.url)
            parse_ttl(args.ttl)
            if args.id:
                validate_id(args.id)
            runtime = ensure_server(root, args.port)
            record = publish_proxy(
                root, args.url, args.ttl, args.title, args.preserve_prefix, args.id
            )
            record.update(artifact_urls(root, record, int(runtime["port"])))
            output(record, args.json)
        elif args.command == "revoke":
            output({"id": args.id, "revoked": revoke_artifact(root, args.id)}, args.json)
        elif args.command == "tailscale-setup":
            value = tailscale_setup(
                root, args.port, args.https_port, args.path, args.apply, args.yes
            )
            output(value, args.json)
        elif args.command == "tailscale-remove":
            output(tailscale_remove(root, args.apply, args.yes), args.json)
        return 0
    except (ArtifactError, OSError, ValueError) as exc:
        print(f"artifact-host: {exc}", file=sys.stderr)
        return 2


def platform_python() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


if __name__ == "__main__":
    raise SystemExit(main())
