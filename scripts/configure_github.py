#!/usr/bin/env python3
"""Preview or apply the reviewed GitHub settings for kimgea/agent-kit.

This is deliberately not a general GitHub API client. The repository, endpoints,
methods, payloads, and ruleset are constants so approving this script does not
approve arbitrary remote mutations.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, NamedTuple


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "kimgea/agent-kit"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
API_VERSION = "2026-03-10"
PROTECTION_RULESET_NAME = "Protect main"
LEGACY_OWNER_MERGE_RULESET_NAME = "Owner-only main merges"
RULESET_NAMES = (PROTECTION_RULESET_NAME, LEGACY_OWNER_MERGE_RULESET_NAME)
OWNER_LOGIN = "kimgea"
OWNER_ID = 1_296_762
DESCRIPTION = "Shared, reusable, safety-conscious resources for Codex and Claude Code agents."
TOPICS = ("agent-toolkit", "ai-agents", "claude-code", "codex", "skills")
REQUIRED_CHECKS = (
    "validate (ubuntu-latest, py3.11)",
    "validate (ubuntu-latest, py3.13)",
    "validate (windows-latest, py3.11)",
    "validate (windows-latest, py3.13)",
)


class ConfigurationError(RuntimeError):
    """A safe configuration precondition or operation failed."""


class Mutation(NamedTuple):
    label: str
    method: str
    path: str
    payload: dict[str, Any] | None = None


def metadata_command(gh: str = "gh") -> list[str]:
    command = [
        gh,
        "repo",
        "edit",
        REPOSITORY,
        "--description",
        DESCRIPTION,
        "--enable-issues",
        "--enable-wiki=false",
        "--enable-merge-commit=false",
        "--enable-rebase-merge=false",
        "--enable-squash-merge",
        "--delete-branch-on-merge",
        "--allow-update-branch",
    ]
    for topic in TOPICS:
        command.extend(("--add-topic", topic))
    return command


def protection_ruleset_payload() -> dict[str, Any]:
    return {
        "name": PROTECTION_RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {
            "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}
        },
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "required_linear_history"},
            {
                "type": "pull_request",
                "parameters": {
                    "allowed_merge_methods": ["squash"],
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_approving_review_count": 0,
                    "required_review_thread_resolution": True,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "do_not_enforce_on_create": True,
                    "required_status_checks": [
                        {"context": context} for context in REQUIRED_CHECKS
                    ],
                    "strict_required_status_checks_policy": True,
                },
            },
        ],
    }


def ruleset_mutation(
    *, name: str, label: str, payload: dict[str, Any], ruleset_id: int | None
) -> Mutation:
    if payload.get("name") != name:
        raise ConfigurationError(f"ruleset payload name does not match {name!r}")
    method = "PUT" if ruleset_id is not None else "POST"
    path = f"/rulesets/{ruleset_id}" if ruleset_id is not None else "/rulesets"
    return Mutation(label, method, path, payload)


def legacy_ruleset_retirement(ruleset_id: int | None) -> Mutation | None:
    if ruleset_id is None:
        return None
    if (
        not isinstance(ruleset_id, int)
        or isinstance(ruleset_id, bool)
        or ruleset_id < 1
    ):
        raise ConfigurationError("legacy owner-only ruleset has an invalid id")
    return Mutation(
        "remove the obsolete owner-only merge gate",
        "DELETE",
        f"/rulesets/{ruleset_id}",
    )


def mutations(ruleset_ids: dict[str, int | None] | None = None) -> list[Mutation]:
    discovered = ruleset_ids or {name: None for name in RULESET_NAMES}
    operations = [
        Mutation(
            "restrict GitHub Actions to SHA-pinned GitHub-owned actions",
            "PUT",
            "/actions/permissions",
            {"enabled": True, "allowed_actions": "selected", "sha_pinning_required": True},
        ),
        Mutation(
            "allow only GitHub-owned actions",
            "PUT",
            "/actions/permissions/selected-actions",
            {
                "github_owned_allowed": True,
                "verified_allowed": False,
                "patterns_allowed": [],
            },
        ),
        Mutation(
            "keep the workflow token read-only and unable to approve pull requests",
            "PUT",
            "/actions/permissions/workflow",
            {
                "default_workflow_permissions": "read",
                "can_approve_pull_request_reviews": False,
            },
        ),
        Mutation(
            "enable Dependabot vulnerability alerts", "PUT", "/vulnerability-alerts"
        ),
        Mutation("enable Dependabot security updates", "PUT", "/automated-security-fixes"),
        Mutation(
            "enable private vulnerability reporting",
            "PUT",
            "/private-vulnerability-reporting",
        ),
        Mutation("enable immutable releases", "PUT", "/immutable-releases"),
    ]
    operations.append(
        ruleset_mutation(
            name=PROTECTION_RULESET_NAME,
            label="create or update the default-branch protection ruleset",
            payload=protection_ruleset_payload(),
            ruleset_id=discovered.get(PROTECTION_RULESET_NAME),
        )
    )
    retirement = legacy_ruleset_retirement(
        discovered.get(LEGACY_OWNER_MERGE_RULESET_NAME)
    )
    if retirement is not None:
        operations.append(retirement)
    return operations


def find_get_wrapper() -> str:
    installed = shutil.which("gh-api-get")
    if installed:
        return installed
    local_name = "gh-api-get.cmd" if sys.platform == "win32" else "gh-api-get"
    local = ROOT / "tools" / "gh-api-get" / local_name
    if local.is_file():
        return str(local)
    raise ConfigurationError("gh-api-get is required to inspect existing rulesets")


def run_get(wrapper: str, endpoint: str) -> Any:
    command = [
        wrapper,
        endpoint,
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or "gh-api-get failed"
        raise ConfigurationError(f"GitHub inspection failed: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("gh-api-get returned invalid JSON") from exc


def discover_ruleset_ids(wrapper: str | None = None) -> dict[str, int | None]:
    get = wrapper or find_get_wrapper()
    value = run_get(
        get, f"/repos/{REPOSITORY}/rulesets?includes_parents=false&per_page=100"
    )
    if not isinstance(value, list):
        raise ConfigurationError("GitHub returned an invalid ruleset collection")
    discovered: dict[str, int | None] = {}
    for name in RULESET_NAMES:
        matches = [
            item
            for item in value
            if isinstance(item, dict) and item.get("name") == name
        ]
        if len(matches) > 1:
            raise ConfigurationError(
                f"multiple rulesets are named {name!r}; refusing to guess"
            )
        if not matches:
            discovered[name] = None
            continue
        ruleset_id = matches[0].get("id")
        if not isinstance(ruleset_id, int) or ruleset_id < 1:
            raise ConfigurationError(f"ruleset {name!r} has an invalid id")
        discovered[name] = ruleset_id
    return discovered


def require_authenticated_owner(wrapper: str) -> None:
    value = run_get(wrapper, "/user")
    if not isinstance(value, dict):
        raise ConfigurationError("GitHub returned an invalid authenticated user")
    if value.get("login") != OWNER_LOGIN or value.get("id") != OWNER_ID:
        raise ConfigurationError(
            f"refusing to apply as any GitHub identity except {OWNER_LOGIN!r} "
            f"(user id {OWNER_ID})"
        )


def get_token(gh: str = "gh") -> str:
    result = subprocess.run(
        [gh, "auth", "token"], check=False, capture_output=True, text=True
    )
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        raise ConfigurationError("GitHub CLI authentication is unavailable; run `gh auth login`")
    return token


def apply_mutation(operation: Mutation, token: str) -> None:
    body = None if operation.payload is None else json.dumps(operation.payload).encode("utf-8")
    request = urllib.request.Request(
        API_ROOT + operation.path,
        data=body if body is not None else b"",
        method=operation.method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "agent-kit-repository-configurator/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status not in {200, 201, 204}:
                raise ConfigurationError(
                    f"{operation.label} returned unexpected HTTP {response.status}"
                )
    except urllib.error.HTTPError as exc:
        detail = exc.read(1024).decode("utf-8", errors="replace")
        raise ConfigurationError(
            f"{operation.label} failed with HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ConfigurationError(f"{operation.label} failed: {exc.reason}") from exc


def print_plan(ruleset_ids: dict[str, int | None]) -> None:
    print(f"Repository: {REPOSITORY}")
    print("Mode: preview (no settings will be changed)")
    print("Metadata command:")
    print("  " + " ".join(metadata_command()))
    print("Fixed API mutations:")
    for operation in mutations(ruleset_ids):
        print(f"  {operation.method} {operation.path} — {operation.label}")
    print("Review the fixed constants and rerun with --apply --yes to apply them.")


def configure(*, apply: bool, yes: bool, gh: str = "gh", wrapper: str | None = None) -> None:
    if yes and not apply:
        raise ConfigurationError("--yes requires --apply")
    if apply and not yes:
        raise ConfigurationError("remote changes require both --apply and --yes")
    get = wrapper or find_get_wrapper()
    ruleset_ids = discover_ruleset_ids(get)
    if not apply:
        print_plan(ruleset_ids)
        return

    require_authenticated_owner(get)
    token = get_token(gh)
    subprocess.run(metadata_command(gh), check=True)
    for operation in mutations(ruleset_ids):
        print(f"Applying: {operation.label}")
        apply_mutation(operation, token)
    print(f"Applied reviewed GitHub settings to {REPOSITORY}.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the fixed remote changes")
    parser.add_argument("--yes", action="store_true", help="confirm the reviewed fixed change set")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        configure(apply=args.apply, yes=args.yes)
    except (ConfigurationError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
