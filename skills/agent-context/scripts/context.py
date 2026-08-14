#!/usr/bin/env python3
"""Resolve explicitly registered, layered agent context without mutating it."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Mapping, Sequence


SKILL_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_CONTEXT = SKILL_ROOT / "references" / "default-context.toml"
SCHEMA_VERSION = 1
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
CONTEXT_KEY = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
SECRET_REFERENCE = re.compile(r"^(?:env|file|keychain):[A-Za-z0-9_./:\\-]{1,255}$")
LAYERS = ("public", "user", "profile", "domain", "repository", "session")
REGISTERED_LAYERS = {"user", "profile", "domain", "repository"}
PROJECT_LAYERS = {"profile", "domain", "repository"}
CATEGORIES = ("invariants", "preferences", "facts", "resources", "secret_refs")
CONTEXT_KEYS = {"schema_version", "id", "layer", *CATEGORIES}
REGISTRY_KEYS = {"schema_version", "always", "sources", "projects"}


class ContextError(RuntimeError):
    """Raised when context configuration is unsafe or invalid."""


def config_path(
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform_id: str | None = None,
) -> Path:
    environment = os.environ if environment is None else environment
    override = environment.get("AGENT_KIT_CONTEXT_CONFIG")
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_absolute():
            raise ContextError("AGENT_KIT_CONTEXT_CONFIG must be an absolute path")
        return candidate

    home = Path.home() if home is None else home
    platform_id = sys.platform if platform_id is None else platform_id
    if platform_id == "win32":
        base = Path(environment.get("APPDATA", home / "AppData" / "Roaming"))
    elif platform_id == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(environment.get("XDG_CONFIG_HOME", home / ".config"))
    return base / "agent-kit" / "context.toml"


def _load_toml(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise ContextError(f"{label} may not be a symlink: {path}")
    if not path.is_file():
        raise ContextError(f"{label} does not exist or is not a file: {path}")
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ContextError(f"cannot load {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContextError(f"{label} must be a TOML table: {path}")
    return value


def _require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ContextError(f"{label} must be lower-case hyphen-case and at most 64 characters")
    return value


def _valid_scalar(value: Any) -> bool:
    if isinstance(value, (str, bool, int)):
        return not isinstance(value, str) or "\x00" not in value
    return isinstance(value, float) and math.isfinite(value)


def _validate_category(name: str, value: Any, source: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ContextError(f"{source}: {name} must be a TOML table")
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not CONTEXT_KEY.fullmatch(key):
            raise ContextError(f"{source}: invalid {name} key {key!r}")
        if name == "secret_refs":
            if not isinstance(item, str) or not SECRET_REFERENCE.fullmatch(item):
                raise ContextError(
                    f"{source}: secret_refs.{key} must be a symbolic reference"
                )
        elif isinstance(item, list):
            if not all(_valid_scalar(element) for element in item):
                raise ContextError(
                    f"{source}: {name}.{key} arrays may contain only scalar values"
                )
        elif not _valid_scalar(item):
            raise ContextError(
                f"{source}: {name}.{key} must be a scalar or scalar array"
            )
        result[key] = item
    return result


def validate_context(
    value: dict[str, Any],
    source: str,
    allowed_layers: set[str],
    expected_id: str | None = None,
) -> dict[str, Any]:
    unknown = set(value) - CONTEXT_KEYS
    if unknown:
        raise ContextError(f"{source}: unsupported context keys {sorted(unknown)}")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContextError(f"{source}: schema_version must be {SCHEMA_VERSION}")
    context_id = _require_id(value.get("id"), f"{source} id")
    if expected_id is not None and context_id != expected_id:
        raise ContextError(
            f"{source}: context id {context_id!r} does not match registry id {expected_id!r}"
        )
    layer = value.get("layer")
    if layer not in allowed_layers:
        raise ContextError(
            f"{source}: layer must be one of {sorted(allowed_layers)}, got {layer!r}"
        )
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "id": context_id,
        "layer": layer,
    }
    for category in CATEGORIES:
        result[category] = _validate_category(category, value.get(category), source)
    if layer != "public" and result["invariants"]:
        raise ContextError(f"{source}: only public context may define invariants")
    return result


def load_context_file(
    path: Path,
    allowed_layers: set[str],
    expected_id: str | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    if source_root is not None:
        if source_root.is_symlink() or not source_root.is_dir():
            raise ContextError(
                f"registered source must be a real directory, not a symlink: {source_root}"
            )
        if path.is_symlink():
            raise ContextError(f"context file may not be a symlink: {path}")
        try:
            path.resolve(strict=True).relative_to(source_root.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise ContextError(
                f"context file escapes or is missing from source {source_root}: {path}"
            ) from exc
    value = _load_toml(path, "context file")
    return validate_context(value, str(path), allowed_layers, expected_id)


def load_registry(path: Path | None = None) -> dict[str, Any]:
    path = config_path() if path is None else path
    value = _load_toml(path, "context registry")
    unknown = set(value) - REGISTRY_KEYS
    if unknown:
        raise ContextError(f"context registry has unsupported keys {sorted(unknown)}")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContextError(f"context registry schema_version must be {SCHEMA_VERSION}")

    always = value.get("always", [])
    if not isinstance(always, list) or not all(isinstance(item, str) for item in always):
        raise ContextError("context registry always must be an array of source IDs")
    if len(always) != len(set(always)):
        raise ContextError("context registry always contains duplicate source IDs")

    sources = value.get("sources", [])
    if not isinstance(sources, list):
        raise ContextError("context registry sources must be an array of tables")
    source_map: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(sources, 1):
        if not isinstance(source, dict) or set(source) != {"id", "path"}:
            raise ContextError(
                f"context registry source {index} must contain only id and path"
            )
        source_id = _require_id(source.get("id"), f"context registry source {index} id")
        if source_id in source_map:
            raise ContextError(f"duplicate context registry source id: {source_id}")
        raw_path = source.get("path")
        if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
            raise ContextError(
                f"context registry source {source_id} path must be absolute"
            )
        source_map[source_id] = {"id": source_id, "path": raw_path}

    projects = value.get("projects", [])
    if not isinstance(projects, list):
        raise ContextError("context registry projects must be an array of tables")
    normalized_projects: list[dict[str, Any]] = []
    for index, project in enumerate(projects, 1):
        if not isinstance(project, dict):
            raise ContextError(f"context registry project {index} must be a table")
        unknown_project = set(project) - {"path", "remotes", "use"}
        if unknown_project:
            raise ContextError(
                f"context registry project {index} has unsupported keys "
                f"{sorted(unknown_project)}"
            )
        raw_path = project.get("path")
        if raw_path is not None and (
            not isinstance(raw_path, str) or not Path(raw_path).is_absolute()
        ):
            raise ContextError(
                f"context registry project {index} path must be absolute"
            )
        remotes = project.get("remotes", [])
        if (
            not isinstance(remotes, list)
            or not all(isinstance(item, str) and item for item in remotes)
            or len(remotes) != len(set(remotes))
        ):
            raise ContextError(
                f"context registry project {index} remotes must be unique strings"
            )
        use = project.get("use", [])
        if (
            not isinstance(use, list)
            or not all(isinstance(item, str) for item in use)
            or len(use) != len(set(use))
        ):
            raise ContextError(
                f"context registry project {index} use must be unique source IDs"
            )
        if raw_path is None and not remotes:
            raise ContextError(
                f"context registry project {index} needs a path or remote"
            )
        normalized_projects.append(
            {"path": raw_path, "remotes": remotes, "use": use, "index": index}
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "path": path,
        "always": always,
        "sources": source_map,
        "projects": normalized_projects,
    }


def load_context_sources(
    registry: dict[str, Any], source_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    unknown = [source_id for source_id in source_ids if source_id not in registry["sources"]]
    if unknown:
        raise ContextError(f"unknown context source IDs: {unknown}")
    loaded: dict[str, dict[str, Any]] = {}
    for source_id in source_ids:
        registration = registry["sources"][source_id]
        root = Path(registration["path"])
        loaded[source_id] = load_context_file(
            root / "context.toml",
            REGISTERED_LAYERS,
            expected_id=source_id,
            source_root=root,
        )
    return loaded


def load_registered_sources(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    loaded = load_context_sources(registry, registry["sources"])

    for source_id in registry["always"]:
        if source_id not in loaded:
            raise ContextError(f"unknown always source id: {source_id}")
        if loaded[source_id]["layer"] != "user":
            raise ContextError(f"always source {source_id} must use the user layer")

    for project in registry["projects"]:
        for source_id in project["use"]:
            if source_id not in loaded:
                raise ContextError(
                    f"context registry project {project['index']} uses unknown source "
                    f"{source_id}"
                )
            if loaded[source_id]["layer"] not in PROJECT_LAYERS:
                raise ContextError(
                    f"context registry project {project['index']} source {source_id} "
                    "must use profile, domain, or repository layer"
                )
    return loaded


def project_remotes(project: Path) -> set[str]:
    git = shutil.which("git")
    if git is None or not (project / ".git").exists():
        return set()
    names = subprocess.run(
        [git, "-C", str(project), "remote"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=5,
        check=False,
    )
    if names.returncode != 0:
        return set()
    result: set[str] = set()
    for name in names.stdout.splitlines():
        if not name:
            continue
        values = subprocess.run(
            [git, "-C", str(project), "remote", "get-url", "--all", name],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        if values.returncode == 0:
            result.update(item for item in values.stdout.splitlines() if item)
    return result


def select_project_sources(
    registry: dict[str, Any],
    project: Path,
    remotes: set[str] | None = None,
) -> list[str]:
    if project.is_symlink() or not project.is_dir():
        raise ContextError(f"project must be a real directory, not a symlink: {project}")
    resolved = project.resolve(strict=True)
    remotes = project_remotes(resolved) if remotes is None else remotes
    matches: list[dict[str, Any]] = []
    for mapping in registry["projects"]:
        path_match = False
        if mapping["path"] is not None:
            configured = Path(mapping["path"])
            if configured.is_symlink():
                raise ContextError(
                    f"context registry project path may not be a symlink: {configured}"
                )
            try:
                path_match = configured.resolve(strict=True) == resolved
            except OSError as exc:
                raise ContextError(
                    f"context registry project path does not exist: {configured}"
                ) from exc
        remote_match = bool(set(mapping["remotes"]) & remotes)
        if path_match or remote_match:
            matches.append(mapping)
    if len(matches) > 1:
        indexes = [mapping["index"] for mapping in matches]
        raise ContextError(f"multiple context project mappings match: {indexes}")
    return [] if not matches else list(matches[0]["use"])


def resolve_context(
    registry_path: Path | None = None,
    project: Path | None = None,
    use_override: Sequence[str] | None = None,
    session: Path | None = None,
    remotes: set[str] | None = None,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    project = Path.cwd() if project is None else project
    mapped = select_project_sources(registry, project, remotes)
    selected = list(mapped if use_override is None else use_override)
    ordered_ids = list(registry["always"]) + selected
    if len(ordered_ids) != len(set(ordered_ids)):
        raise ContextError("selected context source IDs contain duplicates")

    registered = load_context_sources(registry, ordered_ids)
    invalid_always = [
        source_id
        for source_id in registry["always"]
        if registered[source_id]["layer"] != "user"
    ]
    if invalid_always:
        raise ContextError(f"always sources must use the user layer: {invalid_always}")
    invalid = [
        source_id
        for source_id in selected
        if registered[source_id]["layer"] not in PROJECT_LAYERS
    ]
    if invalid:
        raise ContextError(
            f"--use and project mappings accept only profile, domain, or repository "
            f"sources: {invalid}"
        )

    public = load_context_file(PUBLIC_CONTEXT, {"public"})
    private_sources = [registered[source_id] for source_id in ordered_ids]
    private_sources.sort(key=lambda item: LAYERS.index(item["layer"]))
    sources = [public, *private_sources]
    if session is not None:
        sources.append(load_context_file(session, {"session"}))

    context = {category: {} for category in CATEGORIES}
    provenance = {category: {} for category in CATEGORIES}
    for source in sources:
        for category in CATEGORIES:
            for key, value in source[category].items():
                context[category][key] = value
                provenance[category][key] = source["id"]

    return {
        "schema_version": SCHEMA_VERSION,
        "project": str(project.resolve(strict=True)),
        "sources": [
            {"id": source["id"], "layer": source["layer"]} for source in sources
        ],
        "context": context,
        "provenance": provenance,
    }


def doctor_context(registry_path: Path | None = None) -> dict[str, Any]:
    registry = load_registry(registry_path)
    sources = load_registered_sources(registry)
    return {
        "schema_version": SCHEMA_VERSION,
        "healthy": True,
        "registry": str(registry["path"]),
        "sources": [
            {"id": source_id, "layer": sources[source_id]["layer"]}
            for source_id in sorted(sources)
        ],
        "project_mappings": len(registry["projects"]),
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Resolved agent context",
        "",
        f"Project: `{result['project']}`",
        "",
        "Sources: "
        + ", ".join(
            f"`{item['id']}` ({item['layer']})" for item in result["sources"]
        ),
    ]
    headings = {
        "invariants": "Invariants",
        "preferences": "Preferences",
        "facts": "Facts",
        "resources": "Resources",
        "secret_refs": "Secret references",
    }
    for category in CATEGORIES:
        values = result["context"][category]
        if not values:
            continue
        lines.extend(["", f"## {headings[category]}", ""])
        for key in sorted(values):
            rendered = json.dumps(values[key], ensure_ascii=False, sort_keys=True)
            source = result["provenance"][category][key]
            lines.append(f"- `{key}` ({source}): {rendered}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser(
        "doctor", help="validate the registry without printing context values"
    )
    doctor.add_argument("--json", action="store_true")

    resolve = subparsers.add_parser(
        "resolve", help="resolve the exact registered context for a project"
    )
    resolve.add_argument("--project", type=Path, default=Path.cwd())
    resolve.add_argument("--use", action="append", default=None, metavar="SOURCE_ID")
    resolve.add_argument("--session", type=Path)
    resolve.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor_context()
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print("agent-context doctor: healthy")
                print(f"  registry: {result['registry']}")
                print(f"  sources: {len(result['sources'])}")
                print(f"  project mappings: {result['project_mappings']}")
            return 0

        result = resolve_context(
            project=args.project,
            use_override=args.use,
            session=args.session,
        )
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        else:
            print(render_markdown(result), end="")
        return 0
    except (ContextError, OSError, subprocess.SubprocessError) as exc:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {"schema_version": SCHEMA_VERSION, "healthy": False, "error": str(exc)},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            print(f"agent-context: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
