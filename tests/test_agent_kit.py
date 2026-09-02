import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_kit = load_module("agent_kit", ROOT / "scripts" / "agent_kit.py")
gh_api_get = load_module(
    "gh_api_get", ROOT / "tools" / "gh-api-get" / "gh_api_get.py"
)
github_guard = load_module(
    "github_api_guard", ROOT / "hooks" / "github-api-guard.py"
)
configure_github = load_module(
    "configure_github", ROOT / "scripts" / "configure_github.py"
)


class CatalogAndValidationTests(unittest.TestCase):
    def test_catalog_covers_every_skill_and_validates(self):
        catalog = agent_kit.load_catalog(ROOT)
        resources = agent_kit.resource_map(catalog)
        skills = {
            path.name
            for path in (ROOT / "skills").iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        }
        catalog_skills = {
            resource_id
            for resource_id, resource in resources.items()
            if resource["kind"] == "skill"
        }
        self.assertEqual(skills, catalog_skills)
        self.assertEqual([], agent_kit.validate_repository(ROOT))

    def test_workflow_gate_requires_one_exact_non_bypassable_command(self):
        command = "python scripts/agent_kit.py check"
        self.assertTrue(agent_kit.workflow_has_exact_run_command(f"run: {command}\n", command))
        self.assertFalse(
            agent_kit.workflow_has_exact_run_command(
                f"run: {command} --skip-tests\n", command
            )
        )
        self.assertFalse(
            agent_kit.workflow_has_exact_run_command(
                f"run: {command}\n# {command}\n", command
            )
        )

        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            workflows = fixture / ".github" / "workflows"
            workflows.mkdir(parents=True)
            for name in ("ci.yml", "release.yml"):
                shutil.copy2(ROOT / ".github" / "workflows" / name, workflows / name)
            catalog = agent_kit.load_catalog(ROOT)
            ci = workflows / "ci.yml"
            ci.write_text(
                ci.read_text(encoding="utf-8").replace(
                    f"run: {command}", f"run: {command} --skip-tests"
                ),
                encoding="utf-8",
            )
            errors = agent_kit.validate_repository_controls(fixture, catalog)
            self.assertTrue(
                any("ci.yml: canonical gate must be exactly one run entry" in item for item in errors),
                errors,
            )

    def test_check_detects_worktree_mutation_on_every_failure_path(self):
        args = type("Args", (), {"skip_tests": False})()
        scenarios = (
            ("repository validation", ["invalid repository"], 0),
            ("unit tests", [], 1),
        )
        for label, validation_errors, test_status in scenarios:
            with self.subTest(label=label), mock.patch.object(
                agent_kit,
                "validation_snapshot",
                side_effect=[("git", "before"), ("git", "after")],
            ), mock.patch.object(
                agent_kit, "validate_repository", return_value=validation_errors
            ), mock.patch.object(
                agent_kit, "compile_repository", return_value=[]
            ), mock.patch.object(
                agent_kit, "run_tests", return_value=test_status
            ), contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(1, agent_kit.command_check(args))
            self.assertIn("validation changed the working tree", errors.getvalue())

    def test_check_snapshots_non_git_sources_and_raised_failures(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            source = fixture / "source.txt"
            source.write_text("before\n", encoding="utf-8")
            before = agent_kit.validation_snapshot(fixture)
            source.write_text("after\n", encoding="utf-8")
            after = agent_kit.validation_snapshot(fixture)
            self.assertEqual("tree", before[0])
            self.assertNotEqual(before, after)

            before_directory = after
            (fixture / "empty").mkdir()
            after_directory = agent_kit.validation_snapshot(fixture)
            self.assertNotEqual(before_directory, after_directory)

            if os.name != "nt":
                before_mode = after_directory
                source.chmod(stat.S_IMODE(source.stat().st_mode) ^ stat.S_IXUSR)
                after_mode = agent_kit.validation_snapshot(fixture)
                self.assertNotEqual(before_mode, after_mode)

        args = type("Args", (), {"skip_tests": False})()
        with mock.patch.object(
            agent_kit,
            "validation_snapshot",
            side_effect=[("git", "before"), ("git", "after")],
        ) as snapshot, mock.patch.object(
            agent_kit, "validate_repository", side_effect=RuntimeError("failed")
        ), contextlib.redirect_stderr(io.StringIO()) as errors:
            with self.assertRaisesRegex(RuntimeError, "failed"):
                agent_kit.command_check(args)
        self.assertEqual(2, snapshot.call_count)
        self.assertIn("validation changed the working tree", errors.getvalue())

    def test_git_snapshot_detects_rewrites_with_unchanged_porcelain_status(self):
        git = shutil.which("git")
        if git is None:
            self.skipTest("git is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            subprocess.run([git, "init", "-q"], cwd=fixture, check=True)
            tracked = fixture / "tracked.txt"
            untracked = fixture / "untracked.txt"
            tracked.write_text("staged\n", encoding="utf-8")
            subprocess.run([git, "add", "tracked.txt"], cwd=fixture, check=True)
            tracked.write_text("dirty one\n", encoding="utf-8")
            untracked.write_text("loose one\n", encoding="utf-8")

            status_before = agent_kit.git_status(fixture)
            snapshot_before = agent_kit.validation_snapshot(fixture)
            tracked.write_text("dirty two\n", encoding="utf-8")
            untracked.write_text("loose two\n", encoding="utf-8")
            status_after = agent_kit.git_status(fixture)
            snapshot_after = agent_kit.validation_snapshot(fixture)

            self.assertEqual(status_before, status_after)
            self.assertNotEqual(snapshot_before, snapshot_after)

    def test_git_snapshot_rejects_link_like_source_ancestors(self):
        windows_reparse = type(
            "WindowsReparseStat",
            (),
            {
                "st_mode": stat.S_IFDIR,
                "st_file_attributes": getattr(
                    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
                ),
            },
        )()
        self.assertTrue(agent_kit._validation_link_like(windows_reparse))

        git = shutil.which("git")
        if git is None:
            self.skipTest("git is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = base / "repository"
            outside = base / "outside"
            fixture.mkdir()
            outside.mkdir()
            subprocess.run([git, "init", "-q"], cwd=fixture, check=True)
            tracked = fixture / "tracked"
            tracked.mkdir()
            (tracked / "source.txt").write_text("inside\n", encoding="utf-8")
            subprocess.run(
                [git, "add", "tracked/source.txt"], cwd=fixture, check=True
            )
            shutil.rmtree(tracked)
            (outside / "source.txt").write_text("outside\n", encoding="utf-8")
            try:
                os.symlink(outside, tracked, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks are unavailable: {exc}")

            with self.assertRaisesRegex(agent_kit.AgentKitError, "source ancestor"):
                agent_kit.validation_snapshot(fixture)

    def test_source_digest_detects_ancestor_swap_after_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = base / "repository"
            outside = base / "outside"
            tracked = fixture / "tracked"
            saved = fixture / "saved"
            tracked.mkdir(parents=True)
            outside.mkdir()
            source = tracked / "source.txt"
            source.write_text("inside\n", encoding="utf-8")
            (outside / "source.txt").write_text("outside\n", encoding="utf-8")
            real_open = os.open

            def open_then_swap(path, flags):
                descriptor = real_open(path, flags)
                tracked.rename(saved)
                try:
                    os.symlink(outside, tracked, target_is_directory=True)
                except OSError:
                    os.close(descriptor)
                    raise
                return descriptor

            try:
                with mock.patch.object(agent_kit.os, "open", side_effect=open_then_swap):
                    with self.assertRaisesRegex(
                        agent_kit.AgentKitError, "source ancestor"
                    ):
                        agent_kit._hash_validation_path(
                            hashlib.sha256(), fixture, b"tracked/source.txt"
                        )
            except OSError as exc:
                self.skipTest(f"directory symlinks are unavailable: {exc}")

    def test_git_worktree_snapshot_fails_closed_when_git_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            (fixture / ".git").mkdir()
            with mock.patch.object(agent_kit.shutil, "which", return_value=None):
                with self.assertRaisesRegex(agent_kit.AgentKitError, "git is unavailable"):
                    agent_kit.validation_snapshot(fixture)

    def test_list_json_is_machine_readable(self):
        args = type("Args", (), {"kind": "skill", "json": True})()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, agent_kit.command_list(args))
        value = json.loads(output.getvalue())
        self.assertEqual(2, value["schema_version"])
        self.assertEqual(
            [
                "agent-context",
                "build-interactive-diagram",
                "grill-me",
                "project-review",
                "review-and-fix",
                "review-guidance-audit",
                "serve-artifacts",
                "todo-capture",
                "tool-audit",
                "verification-harness-audit",
            ],
            sorted(resource["id"] for resource in value["resources"]),
        )

    def test_all_evaluation_files_are_valid(self):
        catalog = agent_kit.load_catalog(ROOT)
        for resource in agent_kit.resource_map(catalog).values():
            if "evals" in resource:
                path = ROOT / resource["evals"]
                self.assertEqual([], agent_kit.validate_evals(path), resource["id"])

    def test_claude_uses_native_shared_contract_import(self):
        lines = (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
        self.assertIn("@AGENTS.md", (line.strip() for line in lines))

    def test_agent_contract_defaults_repository_reviews_to_project_review(self):
        contract = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("skills/project-review/SKILL.md", contract)
        self.assertIn("trusted starting revision", contract)
        self.assertIn("do not fall back to the reviewed copy", contract)
        self.assertIn("explicitly requests a different review method", contract)
        self.assertIn("does not authorize verification", contract)
        self.assertIn("durable, non-obvious acceptance", contract)
        self.assertIn("merely because a subtree exists", contract)
        self.assertIn("duplicate `SKILL.md`", contract)
        self.assertIn("does not govern its own change", contract)
        self.assertIn("skills/review-and-fix/SKILL.md", contract)
        self.assertIn("skills/review-guidance-audit/SKILL.md", contract)
        self.assertIn("general harness auditing", contract)
        self.assertIn("starting-revision copy", contract)

    def test_project_tracking_rejects_invalid_status_and_progress(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            shutil.copytree(ROOT / ".claude", fixture / ".claude")
            epic = (
                fixture
                / ".claude"
                / "epics"
                / "archived"
                / "agent-toolkit-hardening"
            )
            task = epic / "001.md"
            task.write_text(
                task.read_text(encoding="utf-8").replace(
                    "status: closed", "status: completed", 1
                ),
                encoding="utf-8",
            )
            errors = agent_kit.validate_project_tracking(fixture)
            self.assertTrue(any("task status must be" in error for error in errors))
            self.assertTrue(any("does not match task state" in error for error in errors))

            epic_file = epic / "epic.md"
            epic_file.write_text(
                epic_file.read_text(encoding="utf-8").replace(
                    "status: completed", "status: in-progress", 1
                ),
                encoding="utf-8",
            )
            errors = agent_kit.validate_project_tracking(fixture)
            self.assertTrue(any("archived epic must be completed" in error for error in errors))

    def test_project_tracking_requires_completed_epics_to_be_archived(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            shutil.copytree(ROOT / ".claude", fixture / ".claude")
            archived = (
                fixture
                / ".claude"
                / "epics"
                / "archived"
                / "agent-toolkit-hardening"
            )
            active = fixture / ".claude" / "epics" / "agent-toolkit-hardening"
            shutil.copytree(archived, active)
            errors = agent_kit.validate_project_tracking(fixture)
            self.assertTrue(any("completed epic must be archived" in error for error in errors))


class LifecycleTests(unittest.TestCase):
    def test_install_uninstall_and_rollback_are_previewed_owned_and_recoverable(self):
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary) / "agent home with spaces"
            environment = {"CODEX_HOME": str(codex_home)}
            with mock.patch.dict(os.environ, environment, clear=False):
                agent_kit.install_skill("grill-me", "codex", apply=False, yes=False)
                destination = codex_home / "skills" / "grill-me"
                self.assertFalse(destination.exists())

                with self.assertRaises(agent_kit.AgentKitError):
                    agent_kit.install_skill("grill-me", "codex", apply=True, yes=False)
                self.assertFalse(destination.exists())
                with self.assertRaisesRegex(agent_kit.AgentKitError, "--yes requires"):
                    agent_kit.install_skill("grill-me", "codex", apply=False, yes=True)

                agent_kit.install_skill("grill-me", "codex", apply=True, yes=True)
                self.assertTrue((destination / "SKILL.md").is_file())
                self.assertFalse((codex_home / "rules").exists())
                self.assertFalse((codex_home / "settings.json").exists())

                state_file = codex_home / ".agent-kit" / "state.json"
                state = json.loads(state_file.read_text(encoding="utf-8"))
                self.assertIn("grill-me", state["installations"])
                self.assertEqual(
                    agent_kit.CURRENT_DIGEST_VERSION,
                    state["installations"]["grill-me"]["digest_version"],
                )
                if os.name != "nt":
                    self.assertEqual(stat.S_IMODE(state_file.stat().st_mode), 0o600)
                    self.assertEqual(stat.S_IMODE(state_file.parent.stat().st_mode), 0o700)

                skill_file = destination / "SKILL.md"
                original = skill_file.read_text(encoding="utf-8")
                skill_file.write_text(original + "\nlocal drift\n", encoding="utf-8")
                with self.assertRaisesRegex(agent_kit.AgentKitError, "drifted"):
                    agent_kit.uninstall_skill("grill-me", "codex", apply=True, yes=True)
                skill_file.write_text(original, encoding="utf-8")

                agent_kit.uninstall_skill("grill-me", "codex", apply=False, yes=False)
                self.assertTrue(destination.exists())
                agent_kit.uninstall_skill("grill-me", "codex", apply=True, yes=True)
                self.assertFalse(destination.exists())
                state = json.loads(state_file.read_text(encoding="utf-8"))
                trash = state["trash"]["grill-me"]
                self.assertEqual(1, len(trash))
                self.assertTrue(Path(trash[0]["path"]).exists())

                agent_kit.rollback_skill("grill-me", "codex", apply=False, yes=False)
                self.assertFalse(destination.exists())
                agent_kit.rollback_skill("grill-me", "codex", apply=True, yes=True)
                self.assertTrue(destination.exists())
                self.assertEqual(
                    agent_kit.digest_tree(ROOT / "skills" / "grill-me"),
                    agent_kit.digest_tree(destination),
                )

    def test_install_excludes_generated_files_and_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "source"
            shutil.copytree(
                ROOT,
                fixture,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "dist"),
            )
            source = fixture / "skills" / "grill-me"
            for directory in agent_kit.GENERATED_DIRS:
                generated = source / directory
                generated.mkdir()
                (generated / "ignored.txt").write_text("ignored", encoding="utf-8")
            for suffix in agent_kit.GENERATED_SUFFIXES:
                (source / f"ignored{suffix}").write_text("ignored", encoding="utf-8")
            generated_suffix_directory = source / "ignored-directory.tmp"
            generated_suffix_directory.mkdir()
            (generated_suffix_directory / "ignored.txt").write_text(
                "ignored", encoding="utf-8"
            )

            codex_home = root / "codex"
            destination = codex_home / "skills" / "grill-me"
            with mock.patch.dict(
                os.environ, {"CODEX_HOME": str(codex_home)}, clear=False
            ):
                agent_kit.install_skill(
                    "grill-me", "codex", apply=True, yes=True, root=fixture
                )

            self.assertTrue((destination / "SKILL.md").is_file())
            deployed = [
                path.relative_to(destination) for path in destination.rglob("*")
            ]
            self.assertFalse(
                any(agent_kit.is_generated_relative_path(path) for path in deployed),
                deployed,
            )

    def test_owned_update_retains_and_rolls_back_previous_deployment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "source"
            shutil.copytree(
                ROOT,
                fixture,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "dist"),
            )
            codex_home = root / "codex"
            destination = codex_home / "skills" / "grill-me"
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}, clear=False):
                agent_kit.install_skill(
                    "grill-me", "codex", apply=True, yes=True, root=fixture
                )
                old_digest = agent_kit.digest_tree(destination)
                source_skill = fixture / "skills" / "grill-me" / "SKILL.md"
                source_skill.write_text(
                    source_skill.read_text(encoding="utf-8") + "\n<!-- updated -->\n",
                    encoding="utf-8",
                )
                generated = source_skill.parent / "__pycache__"
                generated.mkdir()
                (generated / "updated.pyc").write_bytes(b"generated")
                (source_skill.parent / "updated.tmp").write_text(
                    "generated", encoding="utf-8"
                )
                new_digest = agent_kit.digest_tree(fixture / "skills" / "grill-me")
                self.assertNotEqual(old_digest, new_digest)
                agent_kit.install_skill(
                    "grill-me", "codex", apply=True, yes=True, root=fixture
                )
                self.assertEqual(new_digest, agent_kit.digest_tree(destination))
                self.assertFalse((destination / "__pycache__").exists())
                self.assertFalse((destination / "updated.tmp").exists())
                state = agent_kit.load_state(codex_home)
                self.assertEqual(1, len(state["trash"]["grill-me"]))

                agent_kit.rollback_skill(
                    "grill-me", "codex", apply=True, yes=True, root=fixture
                )
                self.assertEqual(old_digest, agent_kit.digest_tree(destination))

    def test_legacy_generated_suffix_install_and_rollback_remain_manageable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "source"
            shutil.copytree(
                ROOT,
                fixture,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "dist"),
            )
            codex_home = root / "codex"
            destination = codex_home / "skills" / "grill-me"
            environment = {"CODEX_HOME": str(codex_home)}
            with mock.patch.dict(os.environ, environment, clear=False):
                agent_kit.install_skill(
                    "grill-me", "codex", apply=True, yes=True, root=fixture
                )

                legacy_generated = destination / "legacy.tmp"
                legacy_generated.write_text("v1.3.0 copied this", encoding="utf-8")
                state = agent_kit.load_state(codex_home)
                legacy_entry = state["installations"]["grill-me"]
                legacy_entry["digest"] = agent_kit.legacy_digest_tree(destination)
                legacy_entry.pop("digest_version")
                agent_kit.atomic_write_json(agent_kit.state_path(codex_home), state)

                resource = agent_kit.require_resource(
                    agent_kit.load_catalog(fixture), "grill-me"
                )
                self.assertEqual(
                    "current",
                    agent_kit.installation_status(resource, "codex")["status"],
                )

                source_skill = fixture / "skills" / "grill-me" / "SKILL.md"
                source_skill.write_text(
                    source_skill.read_text(encoding="utf-8") + "\n<!-- updated -->\n",
                    encoding="utf-8",
                )
                agent_kit.install_skill(
                    "grill-me", "codex", apply=True, yes=True, root=fixture
                )
                self.assertFalse(legacy_generated.exists())
                state = agent_kit.load_state(codex_home)
                self.assertEqual(
                    agent_kit.CURRENT_DIGEST_VERSION,
                    state["installations"]["grill-me"]["digest_version"],
                )
                self.assertNotIn(
                    "digest_version", state["trash"]["grill-me"][-1]
                )

                agent_kit.rollback_skill(
                    "grill-me", "codex", apply=True, yes=True, root=fixture
                )
                self.assertTrue(legacy_generated.is_file())
                state = agent_kit.load_state(codex_home)
                self.assertNotIn(
                    "digest_version", state["installations"]["grill-me"]
                )
                agent_kit.uninstall_skill(
                    "grill-me", "codex", apply=False, yes=False, root=fixture
                )

    def test_unknown_ownership_digest_version_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary) / "codex"
            environment = {"CODEX_HOME": str(codex_home)}
            with mock.patch.dict(os.environ, environment, clear=False):
                agent_kit.install_skill(
                    "grill-me", "codex", apply=True, yes=True
                )
                state = agent_kit.load_state(codex_home)
                state["installations"]["grill-me"]["digest_version"] = 3
                agent_kit.atomic_write_json(agent_kit.state_path(codex_home), state)

                with self.assertRaisesRegex(
                    agent_kit.AgentKitError,
                    "unsupported ownership digest version",
                ):
                    agent_kit.uninstall_skill(
                        "grill-me", "codex", apply=False, yes=False
                    )

    def test_unowned_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary) / "codex"
            destination = codex_home / "skills" / "grill-me"
            destination.mkdir(parents=True)
            (destination / "user.txt").write_text("mine", encoding="utf-8")
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}, clear=False):
                with self.assertRaisesRegex(agent_kit.AgentKitError, "not owned"):
                    agent_kit.install_skill("grill-me", "codex", apply=True, yes=True)
            self.assertEqual("mine", (destination / "user.txt").read_text(encoding="utf-8"))

    def test_release_packages_are_deterministic_and_self_describing(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "repository with spaces"
            shutil.copytree(
                ROOT,
                fixture,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "dist"),
            )
            source = fixture / "skills" / "grill-me"
            generated = source / "__pycache__"
            generated.mkdir()
            (generated / "ignored.pyc").write_bytes(b"generated")
            (source / "ignored.tmp").write_text("generated", encoding="utf-8")
            first = agent_kit.package_skills(Path("first"), ["grill-me"], fixture)
            second = agent_kit.package_skills(Path("second"), ["grill-me"], fixture)
            first_zip = next(path for path in first if path.suffix == ".zip")
            second_zip = next(path for path in second if path.suffix == ".zip")
            self.assertEqual(first_zip.read_bytes(), second_zip.read_bytes())
            with zipfile.ZipFile(first_zip) as archive:
                names = set(archive.namelist())
            self.assertIn("grill-me/SKILL.md", names)
            self.assertFalse(any("__pycache__" in name for name in names), names)
            self.assertFalse(any(name.endswith(".tmp") for name in names), names)
            self.assertIn("LICENSE", names)
            self.assertIn("THIRD_PARTY_NOTICES.md", names)
            sums = (fixture / "first" / "SHA256SUMS").read_text(encoding="utf-8")
            self.assertIn(first_zip.name, sums)


    def test_plugin_and_marketplace_packages_are_deterministic_and_selected(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "repository with spaces"
            shutil.copytree(
                ROOT,
                fixture,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "dist"),
            )
            first = agent_kit.package_artifacts(
                Path("plugins-first"), ["grill-me"], "plugin", fixture
            )
            second = agent_kit.package_artifacts(
                Path("plugins-second"), ["grill-me"], "plugin", fixture
            )
            first_plugin = next(
                path for path in first if path.name.startswith("grill-me-plugin-")
            )
            second_plugin = next(
                path for path in second if path.name.startswith("grill-me-plugin-")
            )
            self.assertEqual(first_plugin.read_bytes(), second_plugin.read_bytes())

            with zipfile.ZipFile(first_plugin) as archive:
                names = set(archive.namelist())
                manifest = json.loads(
                    archive.read("grill-me/.codex-plugin/plugin.json")
                )
                packaged_skill = archive.read("grill-me/skills/grill-me/SKILL.md")
            self.assertEqual("grill-me", manifest["name"])
            self.assertEqual("./skills/", manifest["skills"])
            self.assertNotIn("apps", manifest)
            self.assertNotIn("mcpServers", manifest)
            self.assertNotIn("hooks", manifest)
            self.assertIsInstance(manifest["interface"]["defaultPrompt"], list)
            self.assertEqual([], manifest["interface"]["capabilities"])
            self.assertIn("grill-me/LICENSE", names)
            self.assertEqual(
                (fixture / "skills" / "grill-me" / "SKILL.md").read_bytes(),
                packaged_skill,
            )

            marketplace_zip = next(
                path
                for path in first
                if path.name.startswith("agent-kit-marketplace-")
            )
            with zipfile.ZipFile(marketplace_zip) as archive:
                marketplace = json.loads(
                    archive.read(
                        "agent-kit-marketplace/.agents/plugins/marketplace.json"
                    )
                )
                marketplace_names = set(archive.namelist())
            self.assertEqual(["grill-me"], [item["name"] for item in marketplace["plugins"]])
            self.assertEqual(
                "./plugins/grill-me",
                marketplace["plugins"][0]["source"]["path"],
            )
            self.assertIn(
                "agent-kit-marketplace/plugins/grill-me/.codex-plugin/plugin.json",
                marketplace_names,
            )
            self.assertNotIn(
                "agent-kit-marketplace/marketplace.json", marketplace_names
            )
            sums = (fixture / "plugins-first" / "SHA256SUMS").read_text(
                encoding="utf-8"
            )
            self.assertIn(first_plugin.name, sums)
            self.assertIn(marketplace_zip.name, sums)

    def test_all_format_includes_every_standalone_plugin_and_marketplace(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "source"
            shutil.copytree(
                ROOT,
                fixture,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "dist"),
            )
            artifacts = agent_kit.package_artifacts(
                Path("release"), None, "all", fixture
            )
            archives = [path for path in artifacts if path.suffix == ".zip"]
            self.assertEqual(17, len(archives))
            self.assertEqual(6, len([path for path in archives if "-plugin-" in path.name]))
            self.assertEqual(
                1,
                len(
                    [
                        path
                        for path in archives
                        if path.name.startswith("agent-kit-marketplace-")
                    ]
                ),
            )

    def test_grouped_artifacts_plugin_is_atomic_and_contains_both_skills(self):
        with self.assertRaisesRegex(agent_kit.AgentKitError, "splits grouped plugin"):
            agent_kit.plugins_for_skills(
                agent_kit.load_catalog(ROOT), ["build-interactive-diagram"]
            )

        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "source"
            shutil.copytree(
                ROOT,
                fixture,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "dist"),
            )
            artifacts = agent_kit.package_artifacts(
                Path("grouped"),
                ["build-interactive-diagram", "serve-artifacts"],
                "plugin",
                fixture,
            )
            plugin = next(path for path in artifacts if path.name.startswith("artifacts-plugin-"))
            with zipfile.ZipFile(plugin) as archive:
                names = set(archive.namelist())
                manifest = json.loads(archive.read("artifacts/.codex-plugin/plugin.json"))
            self.assertIn("artifacts/skills/build-interactive-diagram/SKILL.md", names)
            self.assertIn("artifacts/skills/serve-artifacts/SKILL.md", names)
            self.assertEqual("artifacts", manifest["name"])
            self.assertEqual(2, len(manifest["interface"]["defaultPrompt"]))

    def test_grouped_review_plugin_is_atomic_and_contains_all_skills(self):
        with self.assertRaisesRegex(agent_kit.AgentKitError, "splits grouped plugin"):
            agent_kit.plugins_for_skills(
                agent_kit.load_catalog(ROOT), ["review-and-fix"]
            )

        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "source"
            shutil.copytree(
                ROOT,
                fixture,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "dist"),
            )
            artifacts = agent_kit.package_artifacts(
                Path("review-group"),
                [
                    "project-review",
                    "review-and-fix",
                    "review-guidance-audit",
                    "verification-harness-audit",
                ],
                "plugin",
                fixture,
            )
            plugin = next(
                path for path in artifacts if path.name.startswith("project-review-plugin-")
            )
            with zipfile.ZipFile(plugin) as archive:
                names = set(archive.namelist())
                manifest = json.loads(
                    archive.read("project-review/.codex-plugin/plugin.json")
                )
            self.assertIn("project-review/skills/project-review/SKILL.md", names)
            self.assertIn("project-review/skills/review-and-fix/SKILL.md", names)
            self.assertIn("project-review/skills/review-guidance-audit/SKILL.md", names)
            self.assertIn("project-review/skills/verification-harness-audit/SKILL.md", names)
            self.assertEqual("project-review", manifest["name"])
            self.assertEqual(3, len(manifest["interface"]["defaultPrompt"]))

    def test_grouped_plugin_skills_remain_independently_packageable(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "source"
            shutil.copytree(
                ROOT,
                fixture,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "dist"),
            )
            artifacts = agent_kit.package_artifacts(
                Path("standalone"), ["review-guidance-audit"], "skill", fixture
            )
            archive = next(
                path
                for path in artifacts
                if path.name.startswith("review-guidance-audit-")
            )
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
            self.assertIn(
                "review-guidance-audit/SKILL.md",
                names,
            )
            self.assertNotIn(
                "review-guidance-audit/skills/project-review/SKILL.md",
                names,
            )

            verification_artifacts = agent_kit.package_artifacts(
                Path("standalone-verification"),
                ["verification-harness-audit"],
                "skill",
                fixture,
            )
            verification_archive = next(
                path
                for path in verification_artifacts
                if path.name.startswith("verification-harness-audit-")
            )
            with zipfile.ZipFile(verification_archive) as bundle:
                verification_names = set(bundle.namelist())
                resolver_source = bundle.read(
                    "verification-harness-audit/scripts/harness_context.py"
                ).decode("utf-8")
                result_source = bundle.read(
                    "verification-harness-audit/scripts/harness_result.py"
                ).decode("utf-8")
            expected_runtime = {
                "LICENSE",
                "THIRD_PARTY_NOTICES.md",
                "verification-harness-audit/SKILL.md",
                "verification-harness-audit/agents/openai.yaml",
                "verification-harness-audit/references/audit-rubric.md",
                "verification-harness-audit/references/resolver-context.md",
                "verification-harness-audit/references/result-authoring.md",
                "verification-harness-audit/references/verification-harness-result.schema.json",
                "verification-harness-audit/scripts/harness_context.py",
                "verification-harness-audit/scripts/harness_result.py",
            }
            self.assertEqual(expected_runtime, verification_names)
            for source in (resolver_source, result_source):
                self.assertNotIn("from scripts", source)
                self.assertNotIn("import scripts", source)
                self.assertNotIn("skills.project_review", source)
                self.assertNotIn("skills.review_guidance_audit", source)

    def test_invalid_plugin_membership_and_unknown_package_selection_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "source"
            shutil.copytree(
                ROOT,
                fixture,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "dist"),
            )
            catalog_path = fixture / "toolkit.toml"
            catalog_path.write_text(
                catalog_path.read_text(encoding="utf-8").replace(
                    'id = "agent-context"\nskills = ["agent-context"]',
                    'id = "agent-context"\nskills = ["grill-me"]',
                    1,
                ),
                encoding="utf-8",
            )
            errors = agent_kit.validate_catalog(
                fixture, agent_kit.load_catalog(fixture)
            )
            self.assertTrue(
                any("exactly one plugin" in error for error in errors), errors
            )

            with self.assertRaisesRegex(agent_kit.AgentKitError, "unknown resource"):
                agent_kit.package_artifacts(
                    Path("release"), ["does-not-exist"], "plugin", ROOT
                )


class GitHubReadBoundaryTests(unittest.TestCase):
    def test_wrapper_forces_get_and_github_dot_com(self):
        command = gh_api_get.build_command(
            ["/repos/owner/repo/issues", "--raw-field", "state=open", "--paginate"],
            gh="/bin/gh",
        )
        self.assertEqual(
            ["/bin/gh", "api", "--method", "GET", "--hostname", "github.com"],
            command[:6],
        )
        self.assertIn("--raw-field", command)

    def test_wrapper_rejects_mutation_surfaces(self):
        cases = [
            ["graphql"],
            ["https://evil.example/api"],
            ["/repos/a/b", "--method", "POST"],
            ["/repos/a/b", "--field", "name=value"],
            ["/repos/a/b", "--input", "payload.json"],
            ["/repos/a/b", "--hostname", "example.com"],
            ["/repos/a/b", "--header", "Authorization: bearer secret"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                with self.assertRaises(gh_api_get.UsageError):
                    gh_api_get.build_command(argv)

    def test_guard_blocks_direct_gh_api_only(self):
        self.assertTrue(github_guard.blocked("gh api /repos/a/b"))
        self.assertTrue(github_guard.blocked("rg x | /usr/bin/gh api graphql"))
        self.assertFalse(github_guard.blocked("gh-api-get /repos/a/b"))
        self.assertFalse(github_guard.blocked("gh pr view 1"))


class GitHubConfigurationBoundaryTests(unittest.TestCase):
    def test_fixed_plan_has_no_caller_controlled_remote_surface(self):
        operations = configure_github.mutations(None)
        self.assertEqual("kimgea/agent-kit", configure_github.REPOSITORY)
        self.assertEqual("POST", operations[-1].method)
        self.assertEqual("/rulesets", operations[-1].path)
        self.assertTrue(all(item.method in {"POST", "PUT"} for item in operations))
        self.assertTrue(all(item.path.startswith("/") for item in operations))
        paths = [item.path for item in operations]
        self.assertLess(
            paths.index("/vulnerability-alerts"),
            paths.index("/automated-security-fixes"),
        )
        command = configure_github.metadata_command("/bin/gh")
        self.assertEqual(["/bin/gh", "repo", "edit", "kimgea/agent-kit"], command[:4])

    def test_write_access_controls_merge_without_a_protection_bypass(self):
        protection = configure_github.protection_ruleset_payload()

        self.assertEqual([], protection["bypass_actors"])
        self.assertNotIn("update", {rule["type"] for rule in protection["rules"]})
        operations = configure_github.mutations(
            {
                configure_github.PROTECTION_RULESET_NAME: 42,
                configure_github.LEGACY_OWNER_MERGE_RULESET_NAME: 84,
            }
        )
        self.assertEqual(("PUT", "/rulesets/42"), operations[-2][1:3])
        self.assertEqual(("DELETE", "/rulesets/84"), operations[-1][1:3])
        self.assertIsNone(operations[-1].payload)

        without_legacy = configure_github.mutations(
            {
                configure_github.PROTECTION_RULESET_NAME: 42,
                configure_github.LEGACY_OWNER_MERGE_RULESET_NAME: None,
            }
        )
        self.assertEqual(("PUT", "/rulesets/42"), without_legacy[-1][1:3])
        self.assertNotIn("DELETE", {operation.method for operation in without_legacy})

        for invalid in (True, 0, -1, "84"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    configure_github.ConfigurationError, "invalid id"
                ):
                    configure_github.legacy_ruleset_retirement(invalid)  # type: ignore[arg-type]

    def test_legacy_ruleset_retirement_sends_one_exact_delete(self):
        operation = configure_github.legacy_ruleset_retirement(84)
        self.assertIsNotNone(operation)
        response = mock.MagicMock()
        response.__enter__.return_value.status = 204
        with mock.patch.object(
            configure_github.urllib.request, "urlopen", return_value=response
        ) as urlopen:
            configure_github.apply_mutation(operation, "test-token")  # type: ignore[arg-type]

        request = urlopen.call_args.args[0]
        self.assertEqual("DELETE", request.get_method())
        self.assertEqual(
            "https://api.github.com/repos/kimgea/agent-kit/rulesets/84",
            request.full_url,
        )
        self.assertEqual(b"", request.data)

    def test_existing_named_ruleset_is_updated_and_ambiguous_state_is_refused(self):
        completed = mock.Mock(
            returncode=0,
            stdout=(
                '[{"id": 42, "name": "Protect main"},'
                '{"id": 84, "name": "Owner-only main merges"}]'
            ),
            stderr="",
        )
        with mock.patch.object(configure_github.subprocess, "run", return_value=completed):
            discovered = configure_github.discover_ruleset_ids("gh-api-get")
        self.assertEqual(
            {"Protect main": 42, "Owner-only main merges": 84}, discovered
        )
        operations = configure_github.mutations(discovered)
        self.assertEqual(("PUT", "/rulesets/42"), operations[-2][1:3])
        self.assertEqual(("DELETE", "/rulesets/84"), operations[-1][1:3])

        completed.stdout = (
            '[{"id": 1, "name": "Owner-only main merges"},'
            '{"id": 2, "name": "Owner-only main merges"}]'
        )
        with mock.patch.object(configure_github.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(configure_github.ConfigurationError, "multiple"):
                configure_github.discover_ruleset_ids("gh-api-get")

    def test_apply_identity_is_pinned_to_the_repository_owner(self):
        completed = mock.Mock(
            returncode=0,
            stdout='{"login": "kimgea", "id": 1296762}',
            stderr="",
        )
        with mock.patch.object(configure_github.subprocess, "run", return_value=completed):
            configure_github.require_authenticated_owner("gh-api-get")

        completed.stdout = '{"login": "someone-else", "id": 123}'
        with mock.patch.object(configure_github.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(configure_github.ConfigurationError, "refusing"):
                configure_github.require_authenticated_owner("gh-api-get")

    def test_configuration_is_preview_only_without_two_part_confirmation(self):
        with mock.patch.object(
            configure_github,
            "discover_ruleset_ids",
            return_value={name: None for name in configure_github.RULESET_NAMES},
        ), mock.patch.object(configure_github, "get_token") as get_token, mock.patch.object(
            configure_github, "apply_mutation"
        ) as mutate, mock.patch.object(
            configure_github, "require_authenticated_owner"
        ) as require_owner:
            configure_github.configure(apply=False, yes=False, wrapper="gh-api-get")
            get_token.assert_not_called()
            mutate.assert_not_called()
            require_owner.assert_not_called()
            with self.assertRaisesRegex(configure_github.ConfigurationError, "--yes requires"):
                configure_github.configure(apply=False, yes=True, wrapper="gh-api-get")
            with self.assertRaisesRegex(configure_github.ConfigurationError, "both"):
                configure_github.configure(apply=True, yes=False, wrapper="gh-api-get")


if __name__ == "__main__":
    unittest.main()
