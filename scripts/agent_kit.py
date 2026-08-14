#!/usr/bin/env python3
"""Validate, inspect, package, install, and remove agent-kit resources safely."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import platform
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "toolkit.toml"
RESOURCE_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
SUPPORTED_AGENTS = {"codex", "claude"}
SUPPORTED_PLATFORMS = {"linux", "windows", "macos"}
SUPPORTED_KINDS = {
    "skill",
    "instruction",
    "template",
    "policy",
    "tool",
    "hook",
    "adapter",
}
REQUIRED_RESOURCE_KEYS = {
    "id",
    "kind",
    "path",
    "version",
    "summary",
    "agents",
    "platforms",
    "maturity",
    "installable",
    "setup_requires_approval",
    "data_sensitivity",
}
GENERATED_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist"}
GENERATED_SUFFIXES = {".pyc", ".pyo", ".bak", ".tmp"}
STATE_SCHEMA = 1
PLUGIN_INSTALLATION = {"NOT_AVAILABLE", "AVAILABLE", "INSTALLED_BY_DEFAULT"}
PLUGIN_AUTHENTICATION = {"ON_INSTALL", "ON_USE"}
MARKETPLACE_KEYS = {
    "name",
    "display_name",
    "author_name",
    "author_url",
    "homepage",
    "repository",
    "license",
}
PLUGIN_REQUIRED_KEYS = {
    "id",
    "skills",
    "category",
    "installation",
    "authentication",
}
PLUGIN_OPTIONAL_KEYS = {
    "version",
    "description",
    "display_name",
    "short_description",
    "default_prompts",
}


class AgentKitError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def platform_name() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def contained(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def resolve_relative(root: Path, value: str, label: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise AgentKitError(f"{label} must be a contained relative path: {value}")
    candidate = root / path
    if not contained(root, candidate):
        raise AgentKitError(f"{label} escapes the repository: {value}")
    return candidate


def load_catalog(root: Path | None = None) -> dict[str, Any]:
    root = ROOT if root is None else root
    path = root / "toolkit.toml"
    try:
        with path.open("rb") as handle:
            catalog = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AgentKitError(f"cannot load {path}: {exc}") from exc
    if not isinstance(catalog, dict):
        raise AgentKitError("toolkit.toml must contain a TOML table")
    return catalog


def resource_map(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resources = catalog.get("resources")
    if not isinstance(resources, list):
        raise AgentKitError("toolkit.toml must contain [[resources]] entries")
    mapped: dict[str, dict[str, Any]] = {}
    for index, resource in enumerate(resources, 1):
        if not isinstance(resource, dict):
            raise AgentKitError(f"resource {index} must be a table")
        resource_id = resource.get("id")
        if not isinstance(resource_id, str) or not RESOURCE_ID.fullmatch(resource_id):
            raise AgentKitError(f"resource {index} has invalid id: {resource_id!r}")
        if resource_id in mapped:
            raise AgentKitError(f"duplicate resource id: {resource_id}")
        mapped[resource_id] = resource
    return mapped


def plugin_map(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    plugins = catalog.get("plugins")
    if not isinstance(plugins, list):
        raise AgentKitError("toolkit.toml must contain [[plugins]] entries")
    mapped: dict[str, dict[str, Any]] = {}
    for index, plugin in enumerate(plugins, 1):
        if not isinstance(plugin, dict):
            raise AgentKitError(f"plugin {index} must be a table")
        plugin_id = plugin.get("id")
        if not isinstance(plugin_id, str) or not RESOURCE_ID.fullmatch(plugin_id):
            raise AgentKitError(f"plugin {index} has invalid id: {plugin_id!r}")
        if plugin_id in mapped:
            raise AgentKitError(f"duplicate plugin id: {plugin_id}")
        mapped[plugin_id] = plugin
    return mapped


def parse_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentKitError(f"cannot read {path}: {exc}") from exc
    match = FRONTMATTER.match(text)
    if not match:
        raise AgentKitError(f"{path} has no valid YAML frontmatter block")
    values: dict[str, str] = {}
    for number, line in enumerate(match.group(1).splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise AgentKitError(f"{path} frontmatter line {number} is invalid")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or not value or key in values:
            raise AgentKitError(f"{path} frontmatter line {number} is invalid")
        values[key] = value
    return values


def validate_openai_yaml(path: Path, resource_id: str) -> list[str]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read {path}: {exc}"]
    if not re.search(r"(?m)^interface:\s*$", text):
        errors.append(f"{path}: missing interface table")
    for field in ("display_name", "short_description", "default_prompt"):
        match = re.search(rf'(?m)^  {field}:\s+"([^"]+)"\s*$', text)
        if not match:
            errors.append(f"{path}: {field} must be a quoted interface string")
        elif field == "short_description" and not 25 <= len(match.group(1)) <= 64:
            errors.append(f"{path}: short_description must contain 25-64 characters")
        elif field == "default_prompt" and f"${resource_id}" not in match.group(1):
            errors.append(f"{path}: default_prompt must mention ${resource_id}")
    return errors


def read_openai_interface(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentKitError(f"cannot read {path}: {exc}") from exc
    result: dict[str, str] = {}
    for field in ("display_name", "short_description", "default_prompt"):
        match = re.search(rf'(?m)^  {field}:\s+"([^"]+)"\s*$', text)
        if not match:
            raise AgentKitError(f"{path}: missing quoted interface field {field}")
        result[field] = match.group(1)
    return result


def validate_plugin_catalog(
    root: Path,
    catalog: dict[str, Any],
    resources: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    marketplace = catalog.get("plugin_marketplace")
    if not isinstance(marketplace, dict):
        errors.append("toolkit.toml must contain [plugin_marketplace]")
    else:
        missing = MARKETPLACE_KEYS - marketplace.keys()
        unknown = marketplace.keys() - MARKETPLACE_KEYS
        if missing:
            errors.append(f"plugin_marketplace missing keys {sorted(missing)}")
        if unknown:
            errors.append(f"plugin_marketplace has unsupported keys {sorted(unknown)}")
        for key in MARKETPLACE_KEYS:
            value = marketplace.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"plugin_marketplace.{key} must be a non-empty string")
        name = marketplace.get("name")
        if isinstance(name, str) and not RESOURCE_ID.fullmatch(name):
            errors.append("plugin_marketplace.name must be lower-case hyphen-case")

    try:
        plugins = plugin_map(catalog)
    except AgentKitError as exc:
        return [*errors, str(exc)]

    memberships: dict[str, list[str]] = {}
    for plugin_id, plugin in plugins.items():
        missing = PLUGIN_REQUIRED_KEYS - plugin.keys()
        unknown = plugin.keys() - PLUGIN_REQUIRED_KEYS - PLUGIN_OPTIONAL_KEYS
        if missing:
            errors.append(f"{plugin_id}: plugin missing keys {sorted(missing)}")
            continue
        if unknown:
            errors.append(f"{plugin_id}: plugin has unsupported keys {sorted(unknown)}")
        skills = plugin.get("skills")
        if (
            not isinstance(skills, list)
            or not skills
            or not all(isinstance(item, str) for item in skills)
            or len(skills) != len(set(skills))
        ):
            errors.append(f"{plugin_id}: skills must be a non-empty unique string array")
            continue
        for skill_id in skills:
            resource = resources.get(skill_id)
            if (
                resource is None
                or resource.get("kind") != "skill"
                or not resource.get("installable")
            ):
                errors.append(
                    f"{plugin_id}: plugin skill is not an installable resource: {skill_id}"
                )
            memberships.setdefault(skill_id, []).append(plugin_id)
        if not isinstance(plugin.get("category"), str) or not plugin["category"].strip():
            errors.append(f"{plugin_id}: category must be a non-empty string")
        if plugin.get("installation") not in PLUGIN_INSTALLATION:
            errors.append(f"{plugin_id}: invalid plugin installation policy")
        if plugin.get("authentication") not in PLUGIN_AUTHENTICATION:
            errors.append(f"{plugin_id}: invalid plugin authentication policy")

        if len(skills) > 1:
            required_overrides = {
                "version",
                "description",
                "display_name",
                "short_description",
                "default_prompts",
            }
            missing_overrides = required_overrides - plugin.keys()
            if missing_overrides:
                errors.append(
                    f"{plugin_id}: grouped plugin missing metadata "
                    f"{sorted(missing_overrides)}"
                )
        if "version" in plugin and (
            not isinstance(plugin["version"], str)
            or not VERSION.fullmatch(plugin["version"])
        ):
            errors.append(f"{plugin_id}: plugin version must be semantic x.y.z")
        for field in ("description", "display_name", "short_description"):
            if field in plugin and (
                not isinstance(plugin[field], str) or not plugin[field].strip()
            ):
                errors.append(f"{plugin_id}: {field} must be a non-empty string")
        if "default_prompts" in plugin:
            prompts = plugin["default_prompts"]
            if (
                not isinstance(prompts, list)
                or not 1 <= len(prompts) <= 3
                or not all(
                    isinstance(prompt, str) and 1 <= len(prompt) <= 128
                    for prompt in prompts
                )
            ):
                errors.append(
                    f"{plugin_id}: default_prompts must contain 1-3 strings "
                    "of at most 128 characters"
                )

    installable = {
        resource_id
        for resource_id, resource in resources.items()
        if resource.get("kind") == "skill" and resource.get("installable")
    }
    for skill_id in sorted(installable):
        owners = memberships.get(skill_id, [])
        if len(owners) != 1:
            errors.append(
                f"{skill_id}: installable skill must belong to exactly one plugin, "
                f"found {owners}"
            )
    extra = memberships.keys() - installable
    if extra:
        errors.append(f"plugins reference non-installable skills: {sorted(extra)}")
    return errors


def resolved_plugin_metadata(
    root: Path,
    catalog: dict[str, Any],
    plugin: dict[str, Any],
    resources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    marketplace = catalog["plugin_marketplace"]
    skill_ids = plugin["skills"]
    if len(skill_ids) == 1:
        resource = resources[skill_ids[0]]
        interface = read_openai_interface(
            resolve_relative(root, resource["path"], f"{resource['id']}.path")
            / "agents"
            / "openai.yaml"
        )
        version = resource["version"]
        description = resource["summary"]
        display_name = interface["display_name"]
        short_description = interface["short_description"]
        default_prompts = [interface["default_prompt"]]
    else:
        version = plugin["version"]
        description = plugin["description"]
        display_name = plugin["display_name"]
        short_description = plugin["short_description"]
        default_prompts = plugin["default_prompts"]
    return {
        "id": plugin["id"],
        "version": version,
        "description": description,
        "display_name": display_name,
        "short_description": short_description,
        "default_prompts": default_prompts,
        "category": plugin["category"],
        "author_name": marketplace["author_name"],
        "author_url": marketplace["author_url"],
        "homepage": marketplace["homepage"],
        "repository": marketplace["repository"],
        "license": marketplace["license"],
        "skills": list(skill_ids),
    }


def validate_evals(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load evaluation file {path}: {exc}"]
    if not isinstance(value, list) or not value:
        return [f"{path}: evaluation file must be a non-empty JSON array"]
    seen: set[str] = set()
    for index, case in enumerate(value, 1):
        if not isinstance(case, dict):
            errors.append(f"{path}: case {index} must be an object")
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str) or not RESOURCE_ID.fullmatch(case_id):
            errors.append(f"{path}: case {index} has an invalid id")
        elif case_id in seen:
            errors.append(f"{path}: duplicate case id {case_id}")
        else:
            seen.add(case_id)
        for field in ("prompt", "expected"):
            item = case.get(field)
            if not isinstance(item, str) or not item.strip():
                errors.append(f"{path}: case {index} requires non-empty {field}")
        forbidden = case.get("must_not")
        if forbidden is not None and not (
            isinstance(forbidden, list) and all(isinstance(item, str) for item in forbidden)
        ):
            errors.append(f"{path}: case {index} must_not must be a string array")
    return errors


def validate_markdown_links(root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(root.rglob("*.md")):
        if ".git" in path.parts or any(part in GENERATED_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"cannot read {path}: {exc}")
            continue
        for target in MARKDOWN_LINK.findall(text):
            target = target.strip().strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            candidate = path.parent / target
            if not contained(root, candidate):
                errors.append(f"{path}: link escapes repository: {target}")
            elif not candidate.exists():
                errors.append(f"{path}: broken local link: {target}")
    return errors


def validate_generated_artifacts(root: Path) -> list[str]:
    errors: list[str] = []
    git = shutil.which("git")
    tracked: list[Path] = []
    if git is not None and (root / ".git").exists():
        result = subprocess.run(
            [git, "ls-files", "-z"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            tracked = [root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]
    paths = tracked or [path for path in root.rglob("*") if ".git" not in path.parts]
    for path in paths:
        relative_parts = path.relative_to(root).parts
        if any(part in GENERATED_DIRS for part in relative_parts):
            errors.append(f"generated path must not be tracked: {path}")
        elif path.is_file() and path.suffix in GENERATED_SUFFIXES:
            errors.append(f"generated file must not be tracked: {path}")
    return errors


def validate_repository_controls(root: Path, catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = (
        "AGENTS.md",
        "CLAUDE.md",
        "LICENSE",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
        "CHANGELOG.md",
        ".github/CODEOWNERS",
        ".github/dependabot.yml",
        ".github/pull_request_template.md",
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
        "scripts/configure_github.py",
    )
    for item in required:
        if not (root / item).is_file():
            errors.append(f"missing repository control: {item}")

    version = str(catalog.get("toolkit_version", ""))
    changelog = root / "CHANGELOG.md"
    if changelog.is_file() and f"## {version} " not in changelog.read_text(encoding="utf-8"):
        errors.append(f"CHANGELOG.md has no release section for {version}")

    workflow_root = root / ".github" / "workflows"
    for path in sorted(workflow_root.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^permissions:\s*$", text):
            errors.append(f"{path}: workflow must declare top-level permissions")
        for action, reference in re.findall(r"(?m)^\s*uses:\s*([^@\s]+)@([^\s#]+)", text):
            if action.startswith("./"):
                continue
            if not re.fullmatch(r"[0-9a-f]{40}", reference):
                errors.append(f"{path}: action {action} must use a full immutable SHA")
    ci = workflow_root / "ci.yml"
    if ci.is_file():
        text = ci.read_text(encoding="utf-8")
        for required_text in (
            "ubuntu-latest",
            "windows-latest",
            '"3.11"',
            '"3.13"',
            "python scripts/agent_kit.py check",
        ):
            if required_text not in text:
                errors.append(f"{ci}: missing required matrix/gate value {required_text}")
    release = workflow_root / "release.yml"
    if release.is_file():
        text = release.read_text(encoding="utf-8")
        for required_text in (
            "python scripts/agent_kit.py check",
            "python scripts/agent_kit.py package --format all",
            "gh release create",
            "--verify-tag",
        ):
            if required_text not in text:
                errors.append(f"{release}: missing release boundary {required_text}")
    return errors


def validate_project_tracking(root: Path) -> list[str]:
    """Validate the small CCPM-compatible PRD/epic state committed with the repo."""
    errors: list[str] = []
    claude = root / ".claude"
    if not claude.exists():
        return errors

    def frontmatter(path: Path) -> dict[str, str] | None:
        try:
            return parse_frontmatter(path)
        except AgentKitError as exc:
            errors.append(str(exc))
            return None

    for path in sorted((claude / "prds").glob("*.md")):
        values = frontmatter(path)
        if values is None:
            continue
        if values.get("status") not in {"backlog", "active", "completed"}:
            errors.append(f"{path}: PRD status must be backlog, active, or completed")
        if values.get("name") != path.stem:
            errors.append(f"{path}: PRD name must match its filename")

    epic_root = claude / "epics"
    if not epic_root.is_dir():
        errors.append(f"{epic_root}: missing project tracking directory")
        return errors
    directories = [
        (path, False)
        for path in epic_root.iterdir()
        if path.is_dir() and path.name != "archived"
    ]
    archived_root = epic_root / "archived"
    if archived_root.is_dir():
        directories.extend(
            (path, True) for path in archived_root.iterdir() if path.is_dir()
        )
    for directory, archived in sorted(directories, key=lambda item: item[0].as_posix()):
        epic_path = directory / "epic.md"
        if not epic_path.is_file():
            errors.append(f"{directory}: missing epic.md")
            continue
        epic = frontmatter(epic_path)
        if epic is None:
            continue
        if epic.get("status") not in {"backlog", "in-progress", "completed"}:
            errors.append(
                f"{epic_path}: epic status must be backlog, in-progress, or completed"
            )
        elif archived and epic.get("status") != "completed":
            errors.append(f"{epic_path}: archived epic must be completed")
        elif not archived and epic.get("status") == "completed":
            errors.append(f"{epic_path}: completed epic must be archived")
        if epic.get("name") != directory.name:
            errors.append(f"{epic_path}: epic name must match its directory")
        progress = epic.get("progress", "")
        if not re.fullmatch(r"(?:0|[1-9][0-9]?|100)%", progress):
            errors.append(f"{epic_path}: progress must be an integer from 0% to 100%")

        tasks: list[tuple[Path, dict[str, str]]] = []
        for task_path in sorted(directory.glob("[0-9]*.md")):
            task = frontmatter(task_path)
            if task is None:
                continue
            tasks.append((task_path, task))
            if task.get("status") not in {"open", "in-progress", "closed"}:
                errors.append(
                    f"{task_path}: task status must be open, in-progress, or closed"
                )

        closed = sum(task.get("status") == "closed" for _, task in tasks)
        expected_progress = f"{closed * 100 // len(tasks)}%" if tasks else "0%"
        if progress != expected_progress:
            errors.append(
                f"{epic_path}: progress {progress!r} does not match task state "
                f"{expected_progress!r}"
            )
        if epic.get("status") == "completed" and any(
            task.get("status") != "closed" for _, task in tasks
        ):
            errors.append(f"{epic_path}: completed epic has non-closed tasks")
    return errors


def validate_catalog(root: Path, catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if catalog.get("schema_version") != 2:
        errors.append("toolkit.toml schema_version must be 2")
    if not isinstance(catalog.get("toolkit_version"), str) or not VERSION.fullmatch(
        catalog.get("toolkit_version", "")
    ):
        errors.append("toolkit.toml toolkit_version must be semantic x.y.z")
    if catalog.get("minimum_python") != "3.11":
        errors.append("toolkit.toml minimum_python must match the supported 3.11 baseline")
    try:
        resources = resource_map(catalog)
    except AgentKitError as exc:
        return [str(exc)]
    errors.extend(validate_plugin_catalog(root, catalog, resources))

    catalog_skills: set[str] = set()
    for resource_id, resource in resources.items():
        missing = REQUIRED_RESOURCE_KEYS - resource.keys()
        if missing:
            errors.append(f"{resource_id}: missing catalog keys {sorted(missing)}")
            continue
        kind = resource.get("kind")
        if kind not in SUPPORTED_KINDS:
            errors.append(f"{resource_id}: unsupported kind {kind!r}")
        version = resource.get("version")
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            errors.append(f"{resource_id}: version must be semantic x.y.z")
        agents = resource.get("agents")
        if not isinstance(agents, list) or not agents or set(agents) - SUPPORTED_AGENTS:
            errors.append(f"{resource_id}: invalid agents {agents!r}")
        platforms = resource.get("platforms")
        if not isinstance(platforms, list) or not platforms or set(platforms) - SUPPORTED_PLATFORMS:
            errors.append(f"{resource_id}: invalid platforms {platforms!r}")
        if not isinstance(resource.get("installable"), bool):
            errors.append(f"{resource_id}: installable must be boolean")
        if not isinstance(resource.get("setup_requires_approval"), bool):
            errors.append(f"{resource_id}: setup_requires_approval must be boolean")
        if resource.get("installable") and kind != "skill":
            errors.append(f"{resource_id}: only self-contained skills are installable")
        try:
            path = resolve_relative(root, str(resource.get("path", "")), f"{resource_id}.path")
        except AgentKitError as exc:
            errors.append(str(exc))
            continue
        if not path.exists():
            errors.append(f"{resource_id}: resource path does not exist: {path}")
            continue
        if path.is_symlink():
            errors.append(f"{resource_id}: resource path may not be a symlink")
        if kind == "skill":
            catalog_skills.add(resource_id)
            if not path.is_dir():
                errors.append(f"{resource_id}: skill path must be a directory")
            else:
                skill_file = path / "SKILL.md"
                metadata_file = path / "agents" / "openai.yaml"
                try:
                    frontmatter = parse_frontmatter(skill_file)
                    if set(frontmatter) != {"name", "description"}:
                        errors.append(
                            f"{skill_file}: frontmatter must contain only name and description"
                        )
                    if frontmatter.get("name") != resource_id:
                        errors.append(f"{skill_file}: name must equal {resource_id}")
                    if path.name != resource_id:
                        errors.append(f"{resource_id}: folder name must equal skill name")
                except AgentKitError as exc:
                    errors.append(str(exc))
                if not metadata_file.exists():
                    errors.append(f"{resource_id}: missing agents/openai.yaml")
                else:
                    errors.extend(validate_openai_yaml(metadata_file, resource_id))
        for field in ("docs", "evals"):
            value = resource.get(field)
            if value is None:
                continue
            try:
                referenced = resolve_relative(root, str(value), f"{resource_id}.{field}")
                if not referenced.is_file():
                    errors.append(f"{resource_id}: {field} file does not exist: {referenced}")
                elif field == "evals":
                    errors.extend(validate_evals(referenced))
            except AgentKitError as exc:
                errors.append(str(exc))
        tests = resource.get("tests", [])
        if not isinstance(tests, list) or not all(isinstance(item, str) for item in tests):
            errors.append(f"{resource_id}: tests must be an array of paths")
        else:
            for item in tests:
                try:
                    test_path = resolve_relative(root, item, f"{resource_id}.tests")
                    if not test_path.is_file():
                        errors.append(f"{resource_id}: test file does not exist: {test_path}")
                except AgentKitError as exc:
                    errors.append(str(exc))

    skill_root = root / "skills"
    disk_skills = {
        path.name
        for path in skill_root.iterdir()
        if path.is_dir() and not path.is_symlink() and (path / "SKILL.md").is_file()
    }
    missing_catalog = disk_skills - catalog_skills
    missing_disk = catalog_skills - disk_skills
    if missing_catalog:
        errors.append(f"skills missing from toolkit.toml: {sorted(missing_catalog)}")
    if missing_disk:
        errors.append(f"catalog skills missing from skills/: {sorted(missing_disk)}")

    catalog_paths = []
    for resource_id, resource in resources.items():
        try:
            catalog_paths.append(
                resolve_relative(root, str(resource["path"]), f"{resource_id}.path")
            )
        except AgentKitError:
            continue
    for directory in ("instructions", "templates", "policies", "hooks", "adapters", "tools"):
        resource_root = root / directory
        if not resource_root.exists():
            continue
        for path in resource_root.rglob("*"):
            if not path.is_file() or any(part in GENERATED_DIRS for part in path.parts):
                continue
            if not any(candidate == path or candidate in path.parents for candidate in catalog_paths):
                errors.append(f"reusable resource is not covered by toolkit.toml: {path}")
    return errors


def validate_repository(root: Path | None = None) -> list[str]:
    root = ROOT if root is None else root
    try:
        catalog = load_catalog(root)
    except AgentKitError as exc:
        return [str(exc)]
    errors = validate_catalog(root, catalog)
    errors.extend(validate_markdown_links(root))
    errors.extend(validate_generated_artifacts(root))
    errors.extend(validate_repository_controls(root, catalog))
    errors.extend(validate_project_tracking(root))
    if not (root / "AGENTS.md").is_file():
        errors.append("missing AGENTS.md")
    claude = root / "CLAUDE.md"
    claude_lines = (
        claude.read_text(encoding="utf-8").splitlines() if claude.is_file() else []
    )
    if "@AGENTS.md" not in (line.strip() for line in claude_lines):
        errors.append("CLAUDE.md must import AGENTS.md with @AGENTS.md")
    return errors


def source_python_files(root: Path) -> list[Path]:
    roots = [root / name for name in ("scripts", "skills", "hooks", "tools", "tests")]
    return sorted(
        path
        for source_root in roots
        if source_root.exists()
        for path in source_root.rglob("*.py")
        if not any(part in GENERATED_DIRS for part in path.parts)
    )


def compile_repository(root: Path) -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="agent-kit-compile-") as temporary:
        target = Path(temporary)
        for index, path in enumerate(source_python_files(root)):
            try:
                py_compile.compile(str(path), cfile=str(target / f"{index}.pyc"), doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append(str(exc))
    return errors


def git_status(root: Path) -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    result = subprocess.run(
        [git, "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def run_tests(root: Path) -> int:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        cwd=root,
        env=environment,
        check=False,
    )
    return result.returncode


def digest_tree(path: Path) -> str:
    if not path.is_dir() or path.is_symlink():
        raise AgentKitError(f"refusing non-directory or symlinked resource: {path}")
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if any(part in GENERATED_DIRS for part in item.relative_to(path).parts):
            continue
        if item.is_symlink():
            raise AgentKitError(f"refusing symlinked resource content: {item}")
        if not item.is_file():
            continue
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def agent_home(agent: str) -> Path:
    if agent == "codex":
        return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    if agent == "claude":
        return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")).expanduser()
    raise AgentKitError(f"unsupported agent: {agent}")


def state_dir(home: Path) -> Path:
    return home / ".agent-kit"


def state_path(home: Path) -> Path:
    return state_dir(home) / "state.json"


@contextlib.contextmanager
def ownership_lock(home: Path, timeout: float = 15.0):
    """Serialize installation-state mutations across local agent sessions."""
    directory = state_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise AgentKitError(f"refusing symlinked ownership directory: {directory}")
    if os.name != "nt":
        directory.chmod(0o700)
    path = directory / "install.lock"
    if path.is_symlink():
        raise AgentKitError(f"refusing symlinked ownership lock: {path}")
    handle = path.open("a+b")
    if os.name != "nt":
        path.chmod(0o600)
    acquired = False
    deadline = time.monotonic() + timeout
    try:
        while not acquired:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    if not handle.read(1):
                        handle.seek(0)
                        handle.write(b"\0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise AgentKitError(f"timed out waiting for ownership lock: {path}")
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def blank_state() -> dict[str, Any]:
    return {"schema_version": STATE_SCHEMA, "installations": {}, "trash": {}}


def load_state(home: Path) -> dict[str, Any]:
    path = state_path(home)
    if not path.exists():
        return blank_state()
    if path.is_symlink():
        raise AgentKitError(f"refusing symlinked ownership state: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentKitError(f"cannot load ownership state {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA:
        raise AgentKitError(f"unsupported ownership state: {path}")
    if not isinstance(value.get("installations"), dict) or not isinstance(value.get("trash"), dict):
        raise AgentKitError(f"malformed ownership state: {path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise AgentKitError(f"refusing symlinked state path: {path}")
    if os.name != "nt":
        path.parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def installation_destination(home: Path, resource_id: str) -> Path:
    if not RESOURCE_ID.fullmatch(resource_id):
        raise AgentKitError(f"invalid resource id: {resource_id}")
    return home / "skills" / resource_id


def require_resource(catalog: dict[str, Any], resource_id: str, installable: bool = False) -> dict[str, Any]:
    resource = resource_map(catalog).get(resource_id)
    if resource is None:
        raise AgentKitError(f"unknown resource: {resource_id}")
    if installable and (resource.get("kind") != "skill" or not resource.get("installable")):
        raise AgentKitError(f"resource is not an installable skill: {resource_id}")
    return resource


def owned_installation(
    state: dict[str, Any], resource_id: str, destination: Path
) -> dict[str, Any]:
    entry = state["installations"].get(resource_id)
    if not isinstance(entry, dict):
        raise AgentKitError(f"existing destination is not owned by agent-kit: {destination}")
    if Path(str(entry.get("path", ""))) != destination:
        raise AgentKitError(f"ownership state path does not match destination: {destination}")
    if not destination.is_dir() or destination.is_symlink():
        raise AgentKitError(f"owned installation is missing or unsafe: {destination}")
    actual = digest_tree(destination)
    if actual != entry.get("digest"):
        raise AgentKitError(
            f"installed skill has drifted; refusing overwrite or removal: {destination}"
        )
    return entry


def trash_deployment(
    home: Path,
    state: dict[str, Any],
    resource_id: str,
    destination: Path,
    entry: dict[str, Any],
) -> Path:
    root = state_dir(home) / "trash"
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise AgentKitError(f"refusing symlinked trash directory: {root}")
    records = state["trash"].setdefault(resource_id, [])
    if not isinstance(records, list):
        raise AgentKitError(f"malformed trash state for {resource_id}")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = root / f"{resource_id}-{stamp}-{uuid.uuid4().hex[:8]}"
    destination.replace(target)
    records.append({**entry, "path": str(target), "trashed_at": utc_now()})
    return target


def install_skill(
    resource_id: str,
    agent: str,
    apply: bool,
    yes: bool,
    root: Path | None = None,
) -> None:
    root = ROOT if root is None else root
    catalog = load_catalog(root)
    resource = require_resource(catalog, resource_id, installable=True)
    source = resolve_relative(root, resource["path"], f"{resource_id}.path")
    source_digest = digest_tree(source)
    home = agent_home(agent)
    destination = installation_destination(home, resource_id)
    state = load_state(home)
    existing = destination.exists() or destination.is_symlink()
    if existing:
        owned_installation(state, resource_id, destination)
    action = "update" if existing else "install"
    print(f"agent-kit {action} proposal (no changes yet):")
    print(f"  resource: {resource_id} {resource['version']}")
    print(f"  source:   {source}")
    print(f"  target:   {destination}")
    print("  permissions: unchanged; run the skill bootstrap separately after review")
    if yes and not apply:
        raise AgentKitError("--yes requires --apply")
    if not apply:
        print("Dry run only. Re-run with --apply --yes after reviewing the proposal.")
        return
    if not yes:
        raise AgentKitError("--apply requires --yes")

    with ownership_lock(home):
        state = load_state(home)
        existing = destination.exists() or destination.is_symlink()
        previous: dict[str, Any] | None = None
        if existing:
            previous = owned_installation(state, resource_id, destination)
            if previous.get("digest") == source_digest:
                print(f"already current -> {destination}")
                return
        skills_dir = destination.parent
        skills_dir.mkdir(parents=True, exist_ok=True)
        if skills_dir.is_symlink():
            raise AgentKitError(f"refusing symlinked skills directory: {skills_dir}")
        staged = skills_dir / f".{resource_id}.agent-kit-stage-{uuid.uuid4().hex}"
        moved: Path | None = None
        try:
            shutil.copytree(source, staged, symlinks=False)
            if digest_tree(staged) != source_digest:
                raise AgentKitError("staged installation digest does not match source")
            if previous is not None:
                moved = trash_deployment(home, state, resource_id, destination, previous)
            staged.replace(destination)
            state["installations"][resource_id] = {
                "agent": agent,
                "digest": source_digest,
                "installed_at": utc_now(),
                "path": str(destination),
                "version": resource["version"],
            }
            atomic_write_json(state_path(home), state)
        except Exception:
            if destination.exists() and digest_tree(destination) == source_digest:
                shutil.rmtree(destination)
            if moved is not None and not destination.exists() and moved.exists():
                moved.replace(destination)
                records = state["trash"].get(resource_id, [])
                if records:
                    records.pop()
            raise
        finally:
            if staged.exists():
                shutil.rmtree(staged)
    print(f"installed {resource_id} -> {destination}")
    if moved is not None:
        print(f"previous owned deployment retained for rollback -> {moved}")
    if resource.get("setup_requires_approval"):
        print("Permission setup is still gated. Preview the installed setup_permissions.py separately.")


def uninstall_skill(
    resource_id: str,
    agent: str,
    apply: bool,
    yes: bool,
    root: Path | None = None,
) -> None:
    root = ROOT if root is None else root
    catalog = load_catalog(root)
    require_resource(catalog, resource_id, installable=True)
    home = agent_home(agent)
    destination = installation_destination(home, resource_id)
    state = load_state(home)
    entry = owned_installation(state, resource_id, destination)
    print("agent-kit uninstall proposal (no changes yet):")
    print(f"  resource: {resource_id} {entry.get('version', '?')}")
    print(f"  target:   {destination}")
    print(f"  action:   move the verified owned deployment to {state_dir(home) / 'trash'}")
    print("  permissions: unchanged; remove skill permissions separately after review")
    if yes and not apply:
        raise AgentKitError("--yes requires --apply")
    if not apply:
        print("Dry run only. Re-run with --apply --yes after reviewing the proposal.")
        return
    if not yes:
        raise AgentKitError("--apply requires --yes")
    with ownership_lock(home):
        state = load_state(home)
        entry = owned_installation(state, resource_id, destination)
        moved = trash_deployment(home, state, resource_id, destination, entry)
        try:
            del state["installations"][resource_id]
            atomic_write_json(state_path(home), state)
        except Exception:
            moved.replace(destination)
            records = state["trash"].get(resource_id, [])
            if records:
                records.pop()
            state["installations"][resource_id] = entry
            raise
    print(f"uninstalled {resource_id}; recoverable deployment -> {moved}")


def rollback_skill(
    resource_id: str,
    agent: str,
    apply: bool,
    yes: bool,
    root: Path | None = None,
) -> None:
    root = ROOT if root is None else root
    catalog = load_catalog(root)
    require_resource(catalog, resource_id, installable=True)
    home = agent_home(agent)
    destination = installation_destination(home, resource_id)
    state = load_state(home)
    records = state["trash"].get(resource_id, [])
    if not isinstance(records, list) or not records:
        raise AgentKitError(f"no owned rollback deployment exists for {resource_id}")
    candidate = records[-1]
    source = Path(str(candidate.get("path", "")))
    if not contained(state_dir(home) / "trash", source) or not source.is_dir() or source.is_symlink():
        raise AgentKitError(f"rollback deployment is missing or unsafe: {source}")
    if digest_tree(source) != candidate.get("digest"):
        raise AgentKitError(f"rollback deployment has drifted: {source}")
    current = None
    if destination.exists() or destination.is_symlink():
        current = owned_installation(state, resource_id, destination)
    print("agent-kit rollback proposal (no changes yet):")
    print(f"  resource: {resource_id}")
    print(f"  restore:  {source}")
    print(f"  target:   {destination}")
    if yes and not apply:
        raise AgentKitError("--yes requires --apply")
    if not apply:
        print("Dry run only. Re-run with --apply --yes after reviewing the proposal.")
        return
    if not yes:
        raise AgentKitError("--apply requires --yes")
    with ownership_lock(home):
        state = load_state(home)
        records = state["trash"].get(resource_id, [])
        if not isinstance(records, list) or not records:
            raise AgentKitError(f"no owned rollback deployment exists for {resource_id}")
        candidate = records[-1]
        source = Path(str(candidate.get("path", "")))
        if not contained(state_dir(home) / "trash", source) or not source.is_dir() or source.is_symlink():
            raise AgentKitError(f"rollback deployment is missing or unsafe: {source}")
        if digest_tree(source) != candidate.get("digest"):
            raise AgentKitError(f"rollback deployment has drifted: {source}")
        current = None
        if destination.exists() or destination.is_symlink():
            current = owned_installation(state, resource_id, destination)
        records.pop()
        current_trash: Path | None = None
        try:
            if current is not None:
                current_trash = trash_deployment(home, state, resource_id, destination, current)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
            state["installations"][resource_id] = {
                **candidate,
                "path": str(destination),
                "installed_at": utc_now(),
            }
            state["installations"][resource_id].pop("trashed_at", None)
            atomic_write_json(state_path(home), state)
        except Exception:
            if destination.exists() and not source.exists():
                destination.replace(source)
            if current_trash is not None and current_trash.exists():
                current_trash.replace(destination)
                if records:
                    records.pop()
            records.append(candidate)
            if current is None:
                state["installations"].pop(resource_id, None)
            else:
                state["installations"][resource_id] = current
            raise
    print(f"rolled back {resource_id} -> {destination}")



def deterministic_zip(
    source: Path,
    destination: Path,
    root_name: str,
    repository_root: Path = ROOT,
    include_notices: bool = True,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    os.close(descriptor)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path in sorted(source.rglob("*"), key=lambda value: value.as_posix()):
                if path.is_symlink():
                    raise AgentKitError(f"refusing symlinked package content: {path}")
                if not path.is_file() or any(
                    part in GENERATED_DIRS
                    for part in path.relative_to(source).parts
                ):
                    continue
                name = f"{root_name}/{path.relative_to(source).as_posix()}"
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(
                    info,
                    path.read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
            if include_notices:
                for notice in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
                    path = repository_root / notice
                    info = zipfile.ZipInfo(
                        notice, date_time=(1980, 1, 1, 0, 0, 0)
                    )
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    archive.writestr(
                        info,
                        path.read_bytes(),
                        compress_type=zipfile.ZIP_DEFLATED,
                        compresslevel=9,
                    )
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def selected_skill_ids(
    catalog: dict[str, Any], selected: list[str] | None
) -> list[str]:
    resources = resource_map(catalog)
    ids = selected or [
        resource_id
        for resource_id, resource in resources.items()
        if resource.get("kind") == "skill" and resource.get("installable")
    ]
    if len(ids) != len(set(ids)):
        raise AgentKitError("package resource selection contains duplicates")
    for resource_id in ids:
        require_resource(catalog, resource_id, installable=True)
    return sorted(ids)


def plugins_for_skills(
    catalog: dict[str, Any], selected: list[str]
) -> list[dict[str, Any]]:
    chosen = set(selected)
    result: list[dict[str, Any]] = []
    for plugin in plugin_map(catalog).values():
        plugin_skills = set(plugin["skills"])
        overlap = plugin_skills & chosen
        if overlap and overlap != plugin_skills:
            raise AgentKitError(
                f"selection splits grouped plugin {plugin['id']}: "
                f"select all of {sorted(plugin_skills)}"
            )
        if overlap:
            result.append(plugin)
    covered = {skill for plugin in result for skill in plugin["skills"]}
    missing = chosen - covered
    if missing:
        raise AgentKitError(f"selected skills have no plugin mapping: {sorted(missing)}")
    return result


def _copy_notices(destination: Path, root: Path) -> None:
    for notice in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(root / notice, destination / notice)


def build_plugin_tree(
    destination: Path,
    catalog: dict[str, Any],
    plugin: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    resources = resource_map(catalog)
    metadata = resolved_plugin_metadata(root, catalog, plugin, resources)
    destination.mkdir(parents=True, exist_ok=False)
    skills_root = destination / "skills"
    skills_root.mkdir()
    for skill_id in metadata["skills"]:
        source = resolve_relative(root, resources[skill_id]["path"], f"{skill_id}.path")
        digest_tree(source)
        shutil.copytree(source, skills_root / skill_id)

    manifest = {
        "name": metadata["id"],
        "version": metadata["version"],
        "description": metadata["description"],
        "author": {
            "name": metadata["author_name"],
            "url": metadata["author_url"],
        },
        "homepage": metadata["homepage"],
        "repository": metadata["repository"],
        "license": metadata["license"],
        "skills": "./skills/",
        "interface": {
            "displayName": metadata["display_name"],
            "shortDescription": metadata["short_description"],
            "longDescription": metadata["description"],
            "developerName": metadata["author_name"],
            "category": metadata["category"],
            "capabilities": [],
            "websiteURL": metadata["homepage"],
            "defaultPrompt": metadata["default_prompts"],
        },
    }
    manifest_path = destination / ".codex-plugin" / "plugin.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _copy_notices(destination, root)
    return metadata


def build_marketplace_tree(
    destination: Path,
    catalog: dict[str, Any],
    plugins: list[dict[str, Any]],
    root: Path,
) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    entries: list[dict[str, Any]] = []
    plugins_root = destination / "plugins"
    plugins_root.mkdir()
    for plugin in plugins:
        build_plugin_tree(plugins_root / plugin["id"], catalog, plugin, root)
        entries.append(
            {
                "name": plugin["id"],
                "source": {
                    "source": "local",
                    "path": f"./plugins/{plugin['id']}",
                },
                "policy": {
                    "installation": plugin["installation"],
                    "authentication": plugin["authentication"],
                },
                "category": plugin["category"],
            }
        )
    marketplace = {
        "name": catalog["plugin_marketplace"]["name"],
        "interface": {
            "displayName": catalog["plugin_marketplace"]["display_name"],
        },
        "plugins": entries,
    }
    (destination / "marketplace.json").write_text(
        json.dumps(marketplace, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _copy_notices(destination, root)


def _write_checksums(output: Path, artifacts: list[Path]) -> Path:
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in artifacts
    ]
    sums = output / "SHA256SUMS"
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return sums


def package_artifacts(
    output: Path,
    selected: list[str] | None = None,
    package_format: str = "skill",
    root: Path | None = None,
) -> list[Path]:
    root = ROOT if root is None else root
    if package_format not in {"skill", "plugin", "all"}:
        raise AgentKitError(f"unsupported package format: {package_format}")
    catalog = load_catalog(root)
    resources = resource_map(catalog)
    plugin_errors = validate_plugin_catalog(root, catalog, resources)
    if plugin_errors:
        raise AgentKitError(plugin_errors[0])
    ids = selected_skill_ids(catalog, selected)
    plugins = plugins_for_skills(catalog, ids)
    output = output if output.is_absolute() else root / output
    if not contained(root, output):
        raise AgentKitError("package output must stay inside the repository")
    output.mkdir(parents=True, exist_ok=True)

    artifacts: list[Path] = []
    if package_format in {"skill", "all"}:
        for resource_id in ids:
            resource = resources[resource_id]
            source = resolve_relative(root, resource["path"], f"{resource_id}.path")
            name = f"{resource_id}-{resource['version']}.zip"
            destination = output / name
            deterministic_zip(source, destination, resource_id, root)
            artifacts.append(destination)

    if package_format in {"plugin", "all"}:
        with tempfile.TemporaryDirectory(
            prefix=".agent-kit-package-", dir=output
        ) as temporary:
            staging = Path(temporary)
            for plugin in plugins:
                plugin_root = staging / f"plugin-{plugin['id']}"
                metadata = build_plugin_tree(plugin_root, catalog, plugin, root)
                destination = (
                    output
                    / f"{plugin['id']}-plugin-{metadata['version']}.zip"
                )
                deterministic_zip(
                    plugin_root,
                    destination,
                    plugin["id"],
                    root,
                    include_notices=False,
                )
                artifacts.append(destination)

            marketplace_root = staging / "marketplace"
            build_marketplace_tree(marketplace_root, catalog, plugins, root)
            marketplace_archive = (
                output
                / f"agent-kit-marketplace-{catalog['toolkit_version']}.zip"
            )
            deterministic_zip(
                marketplace_root,
                marketplace_archive,
                "agent-kit-marketplace",
                root,
                include_notices=False,
            )
            artifacts.append(marketplace_archive)

    artifacts.sort(key=lambda path: path.name)
    artifacts.append(_write_checksums(output, artifacts))
    return artifacts


def package_skills(
    output: Path, selected: list[str] | None = None, root: Path | None = None
) -> list[Path]:
    return package_artifacts(output, selected, "skill", root)

def command_list(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    resources = list(resource_map(catalog).values())
    if args.kind:
        resources = [resource for resource in resources if resource["kind"] == args.kind]
    resources.sort(key=lambda resource: (resource["kind"], resource["id"]))
    if args.json:
        print(
            json.dumps(
                {
                    "schema_version": catalog["schema_version"],
                    "toolkit_version": catalog["toolkit_version"],
                    "plugin_marketplace": catalog["plugin_marketplace"],
                    "plugins": list(plugin_map(catalog).values()),
                    "resources": resources,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"agent-kit {catalog['toolkit_version']} resources")
        for resource in resources:
            support = "/".join(resource["agents"])
            marker = "installable" if resource["installable"] else "source"
            print(
                f"  {resource['id']:<24} {resource['kind']:<12} {resource['version']:<8} "
                f"{support:<13} {marker}"
            )
    return 0


def installation_status(resource: dict[str, Any], agent: str) -> dict[str, Any]:
    home = agent_home(agent)
    destination = installation_destination(home, resource["id"])
    try:
        state = load_state(home)
        entry = state["installations"].get(resource["id"])
        if not destination.exists():
            status = "not-installed" if entry is None else "missing"
        elif not isinstance(entry, dict):
            status = "unowned"
        elif destination.is_symlink():
            status = "unsafe-symlink"
        else:
            status = "current" if digest_tree(destination) == entry.get("digest") else "drifted"
        return {"agent": agent, "home": str(home), "path": str(destination), "status": status}
    except AgentKitError as exc:
        return {"agent": agent, "home": str(home), "path": str(destination), "status": "error", "error": str(exc)}


def command_doctor(args: argparse.Namespace) -> int:
    errors = validate_repository()
    catalog = load_catalog()
    checks: dict[str, Any] = {
        "toolkit_version": catalog.get("toolkit_version"),
        "python": platform.python_version(),
        "python_supported": sys.version_info >= (3, 11),
        "platform": platform_name(),
        "git": shutil.which("git"),
        "gh": shutil.which("gh"),
        "validation_errors": errors,
        "installations": [],
    }
    for resource in resource_map(catalog).values():
        if resource.get("installable"):
            for agent in sorted(resource["agents"]):
                checks["installations"].append(installation_status(resource, agent))
    healthy = not errors and checks["python_supported"]
    checks["healthy"] = healthy
    if args.json:
        print(json.dumps(checks, indent=2, ensure_ascii=False))
    else:
        print(f"agent-kit {checks['toolkit_version']} doctor")
        print(f"  Python:   {checks['python']} ({'ok' if checks['python_supported'] else 'unsupported'})")
        print(f"  Platform: {checks['platform']}")
        print(f"  GitHub CLI: {checks['gh'] or 'not found'}")
        print(f"  Repository: {'valid' if not errors else f'{len(errors)} error(s)'}")
        for install in checks["installations"]:
            print(f"  {install['agent']:<6} {Path(install['path']).name:<16} {install['status']}")
        for error in errors:
            print(f"ERROR: {error}")
    return 0 if healthy else 1


def command_check(args: argparse.Namespace) -> int:
    before = git_status(ROOT)
    errors = validate_repository()
    errors.extend(compile_repository(ROOT))
    if errors:
        print(f"agent-kit check failed with {len(errors)} error(s):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    if not args.skip_tests and run_tests(ROOT) != 0:
        print("agent-kit check failed: unit tests failed", file=sys.stderr)
        return 1
    after = git_status(ROOT)
    if before is not None and after != before:
        print("agent-kit check failed: validation changed the working tree", file=sys.stderr)
        return 1
    print("agent-kit check passed")
    return 0


def command_package(args: argparse.Namespace) -> int:
    artifacts = package_artifacts(
        Path("dist"), args.resources or None, args.package_format
    )
    for artifact in artifacts:
        print(artifact.relative_to(ROOT))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("list", help="list cataloged resources")
    command.add_argument("--json", action="store_true")
    command.add_argument("--kind", choices=sorted(SUPPORTED_KINDS))
    command.set_defaults(handler=command_list)

    command = subparsers.add_parser("doctor", help="inspect compatibility and installed state")
    command.add_argument("--json", action="store_true")
    command.set_defaults(handler=command_doctor)

    command = subparsers.add_parser("check", help="run the canonical repository validation gate")
    command.add_argument("--skip-tests", action="store_true", help=argparse.SUPPRESS)
    command.set_defaults(handler=command_check)

    for name, help_text, handler in (
        ("install", "preview or install/update one skill", install_skill),
        ("uninstall", "preview or recoverably remove one owned skill", uninstall_skill),
        ("rollback", "preview or restore the newest owned deployment", rollback_skill),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("resource")
        command.add_argument("--agent", choices=sorted(SUPPORTED_AGENTS), required=True)
        command.add_argument("--apply", action="store_true")
        command.add_argument("--yes", action="store_true")
        command.set_defaults(handler=handler)

    command = subparsers.add_parser("package", help="build deterministic release archives")
    command.add_argument("resources", nargs="*")
    command.add_argument(
        "--format",
        choices=("skill", "plugin", "all"),
        default="skill",
        dest="package_format",
    )
    command.set_defaults(handler=command_package)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {"install", "uninstall", "rollback"}:
            args.handler(args.resource, args.agent, args.apply, args.yes)
            return 0
        return int(args.handler(args))
    except AgentKitError as exc:
        print(f"agent-kit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
