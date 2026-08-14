import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_context = load_module(
    "agent_context", ROOT / "skills" / "agent-context" / "scripts" / "context.py"
)


def toml_value(value):
    return json.dumps(value, ensure_ascii=False)


def write_context(root, source_id, layer, **categories):
    root.mkdir(parents=True, exist_ok=True)
    lines = [
        "schema_version = 1",
        f"id = {toml_value(source_id)}",
        f"layer = {toml_value(layer)}",
    ]
    for category in agent_context.CATEGORIES:
        lines.extend(["", f"[{category}]"])
        for key, value in categories.get(category, {}).items():
            lines.append(f"{key} = {toml_value(value)}")
    path = root / "context.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_registry(path, sources, projects, always=None):
    lines = [
        "schema_version = 1",
        f"always = {toml_value(always or [])}",
    ]
    for source_id, source_path in sources:
        lines.extend(
            [
                "",
                "[[sources]]",
                f"id = {toml_value(source_id)}",
                f"path = {toml_value(str(source_path))}",
            ]
        )
    for project in projects:
        lines.extend(["", "[[projects]]"])
        if project.get("path") is not None:
            lines.append(f"path = {toml_value(str(project['path']))}")
        lines.append(f"remotes = {toml_value(project.get('remotes', []))}")
        lines.append(f"use = {toml_value(project.get('use', []))}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class ContextPathTests(unittest.TestCase):
    def test_config_path_uses_platform_native_locations(self):
        home = Path("/users/example")
        self.assertEqual(
            Path("/config") / "agent-kit" / "context.toml",
            agent_context.config_path(
                {"XDG_CONFIG_HOME": "/config"}, home, platform_id="linux"
            ),
        )
        self.assertEqual(
            home
            / "Library"
            / "Application Support"
            / "agent-kit"
            / "context.toml",
            agent_context.config_path({}, home, platform_id="darwin"),
        )
        self.assertEqual(
            Path("C:/Users/Example/AppData/Roaming") / "agent-kit" / "context.toml",
            agent_context.config_path(
                {"APPDATA": "C:/Users/Example/AppData/Roaming"},
                home,
                platform_id="win32",
            ),
        )
        with self.assertRaisesRegex(agent_context.ContextError, "absolute"):
            agent_context.config_path(
                {"AGENT_KIT_CONTEXT_CONFIG": "relative.toml"},
                home,
                platform_id="linux",
            )


class ContextResolutionTests(unittest.TestCase):
    def build_fixture(self, base):
        project = base / "project with spaces"
        project.mkdir()
        user = base / "user"
        profile_a = base / "profile-a"
        profile_b = base / "profile-b"
        domain = base / "domain"
        repository = base / "repository"
        write_context(
            user,
            "user-global",
            "user",
            preferences={"tone": "user", "global-only": True},
        )
        write_context(profile_a, "profile-a", "profile", preferences={"tone": "a"})
        write_context(profile_b, "profile-b", "profile", preferences={"tone": "b"})
        write_context(
            domain,
            "domain",
            "domain",
            preferences={"tone": "domain"},
            facts={"organization": "private-example"},
        )
        write_context(
            repository,
            "repository",
            "repository",
            preferences={"tone": "repository"},
            secret_refs={"issue-token": "env:ISSUE_TOKEN"},
        )
        registry = write_registry(
            base / "config" / "context.toml",
            [
                ("user-global", user),
                ("profile-a", profile_a),
                ("profile-b", profile_b),
                ("domain", domain),
                ("repository", repository),
            ],
            [
                {
                    "path": project,
                    "remotes": [],
                    "use": ["repository", "profile-a", "profile-b", "domain"],
                }
            ],
            always=["user-global"],
        )
        return project, registry

    def test_precedence_tie_order_provenance_and_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, registry = self.build_fixture(base)
            session = base / "session.toml"
            write_context(
                base / "session-source",
                "session",
                "session",
                preferences={"tone": "session"},
            ).replace(session)

            result = agent_context.resolve_context(
                registry_path=registry,
                project=project,
                session=session,
                remotes=set(),
            )

            self.assertEqual(
                [
                    "agent-kit-public",
                    "user-global",
                    "profile-a",
                    "profile-b",
                    "domain",
                    "repository",
                    "session",
                ],
                [item["id"] for item in result["sources"]],
            )
            self.assertEqual("session", result["context"]["preferences"]["tone"])
            self.assertEqual(
                "session", result["provenance"]["preferences"]["tone"]
            )
            self.assertEqual(
                "private-example", result["context"]["facts"]["organization"]
            )
            self.assertEqual(
                "env:ISSUE_TOKEN",
                result["context"]["secret_refs"]["issue-token"],
            )
            self.assertIn(
                "instruction-authority", result["context"]["invariants"]
            )

    def test_use_override_replaces_project_mapping_but_keeps_user_global(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, registry = self.build_fixture(base)
            result = agent_context.resolve_context(
                registry_path=registry,
                project=project,
                use_override=["profile-a"],
                remotes=set(),
            )
            self.assertEqual(
                ["agent-kit-public", "user-global", "profile-a"],
                [item["id"] for item in result["sources"]],
            )
            self.assertEqual("a", result["context"]["preferences"]["tone"])

    def test_exact_remote_matching_and_ambiguous_mappings_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            project.mkdir()
            profile = base / "profile"
            write_context(profile, "work", "profile")
            registry_path = write_registry(
                base / "context.toml",
                [("work", profile)],
                [
                    {
                        "remotes": ["https://github.com/example/project.git"],
                        "use": ["work"],
                    }
                ],
            )
            registry = agent_context.load_registry(registry_path)
            agent_context.load_registered_sources(registry)
            self.assertEqual(
                ["work"],
                agent_context.select_project_sources(
                    registry,
                    project,
                    remotes={"https://github.com/example/project.git"},
                ),
            )

            write_registry(
                registry_path,
                [("work", profile)],
                [
                    {"path": project, "use": ["work"]},
                    {
                        "remotes": ["https://github.com/example/project.git"],
                        "use": ["work"],
                    },
                ],
            )
            registry = agent_context.load_registry(registry_path)
            with self.assertRaisesRegex(agent_context.ContextError, "multiple"):
                agent_context.select_project_sources(
                    registry,
                    project,
                    remotes={"https://github.com/example/project.git"},
                )

    def test_resolve_reads_only_selected_sources_while_doctor_checks_all(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            project.mkdir()
            selected = base / "selected"
            write_context(selected, "selected", "profile", facts={"chosen": True})
            missing = base / "missing-unselected"
            registry = write_registry(
                base / "context.toml",
                [("selected", selected), ("unselected", missing)],
                [{"path": project, "use": ["selected"]}],
            )

            result = agent_context.resolve_context(
                registry_path=registry, project=project, remotes=set()
            )
            self.assertTrue(result["context"]["facts"]["chosen"])
            self.assertNotIn(
                "unselected", [source["id"] for source in result["sources"]]
            )
            with self.assertRaisesRegex(agent_context.ContextError, "real directory"):
                agent_context.doctor_context(registry)

    def test_doctor_prints_no_values_and_changes_no_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, registry = self.build_fixture(base)
            inputs = [registry, *base.glob("*/context.toml")]
            before = {
                path: (path.read_bytes(), path.stat().st_mtime_ns) for path in inputs
            }
            output = io.StringIO()
            with mock.patch.dict(
                os.environ,
                {"AGENT_KIT_CONTEXT_CONFIG": str(registry)},
                clear=False,
            ), contextlib.redirect_stdout(output):
                self.assertEqual(0, agent_context.main(["doctor", "--json"]))
            report = json.loads(output.getvalue())
            self.assertTrue(report["healthy"])
            self.assertNotIn("private-example", output.getvalue())
            after = {
                path: (path.read_bytes(), path.stat().st_mtime_ns) for path in inputs
            }
            self.assertEqual(before, after)
            self.assertTrue(project.is_dir())

    def test_secret_references_require_a_recognized_symbolic_scheme(self):
        for reference in (
            "env:ACCOUNT_TOKEN",
            "file:/mounted/secrets/account-token",
            r"file:C:\\Secrets\\account-token",
            "keychain:account-token",
        ):
            result = agent_context.validate_context(
                {
                    "schema_version": 1,
                    "id": "private",
                    "layer": "profile",
                    "secret_refs": {"token": reference},
                },
                "test",
                {"profile"},
            )
            self.assertEqual(reference, result["secret_refs"]["token"])

        with self.assertRaisesRegex(agent_context.ContextError, "symbolic"):
            agent_context.validate_context(
                {
                    "schema_version": 1,
                    "id": "private",
                    "layer": "profile",
                    "secret_refs": {"token": "ghp_literal-token-value"},
                },
                "test",
                {"profile"},
            )

    def test_private_invariants_secret_paths_unknown_ids_and_symlinks_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            project.mkdir()

            private = base / "private"
            write_context(
                private,
                "private",
                "profile",
                invariants={"override": "not allowed"},
            )
            registry = write_registry(
                base / "registry.toml",
                [("private", private)],
                [{"path": project, "use": ["private"]}],
            )
            with self.assertRaisesRegex(agent_context.ContextError, "invariants"):
                agent_context.resolve_context(
                    registry_path=registry, project=project, remotes=set()
                )

            write_context(
                private,
                "private",
                "profile",
                secret_refs={"token": "/tmp/not-symbolic"},
            )
            with self.assertRaisesRegex(agent_context.ContextError, "symbolic"):
                agent_context.resolve_context(
                    registry_path=registry, project=project, remotes=set()
                )

            write_context(private, "private", "profile")
            registry.write_text(
                registry.read_text(encoding="utf-8").replace(
                    'use = ["private"]', 'use = ["unknown"]'
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(agent_context.ContextError, "unknown"):
                agent_context.resolve_context(
                    registry_path=registry, project=project, remotes=set()
                )

            if hasattr(os, "symlink"):
                link = base / "linked"
                try:
                    link.symlink_to(private, target_is_directory=True)
                except OSError:
                    return
                linked_registry = write_registry(
                    base / "linked-registry.toml",
                    [("private", link)],
                    [{"path": project, "use": ["private"]}],
                )
                with self.assertRaisesRegex(agent_context.ContextError, "symlink"):
                    agent_context.resolve_context(
                        registry_path=linked_registry,
                        project=project,
                        remotes=set(),
                    )

                linked_file_root = base / "linked-file"
                linked_file_root.mkdir()
                real_file = write_context(base / "real-file", "private", "profile")
                try:
                    (linked_file_root / "context.toml").symlink_to(real_file)
                except OSError:
                    return
                linked_file_registry = write_registry(
                    base / "linked-file-registry.toml",
                    [("private", linked_file_root)],
                    [{"path": project, "use": ["private"]}],
                )
                with self.assertRaisesRegex(agent_context.ContextError, "symlink"):
                    agent_context.resolve_context(
                        registry_path=linked_file_registry,
                        project=project,
                        remotes=set(),
                    )


if __name__ == "__main__":
    unittest.main()
