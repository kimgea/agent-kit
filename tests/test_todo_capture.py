import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "todo-capture"
SCRIPTS = SKILL / "scripts"
SAFE = SCRIPTS / "todo_safe.py"
DIRECT = SCRIPTS / "todo.py"
PROJECT = SCRIPTS / "todo_project.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_setup_modules():
    common = load_module("todo_capture_common", SCRIPTS / "_common.py")
    previous = sys.modules.get("_common")
    sys.modules["_common"] = common
    try:
        setup = load_module("todo_capture_setup_permissions", SCRIPTS / "setup_permissions.py")
    finally:
        if previous is None:
            sys.modules.pop("_common", None)
        else:
            sys.modules["_common"] = previous
    return common, setup


TODO_COMMON, TODO_SETUP = load_setup_modules()


class TodoCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "todo-capture"
        self.environment = os.environ.copy()
        self.environment["TODO_CAPTURE_DATA_DIR"] = str(self.base)

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, *args, direct=False):
        script = DIRECT if direct else SAFE
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=ROOT,
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def new_args(self, slug, title=None, repo="_general", domain="tooling"):
        return (
            "new", "--repo", repo, "--domain", domain,
            "--slug", slug, "--title", title or f"Capture {slug}",
            "--source", "conversation 2026-08-01", "--priority", "normal",
            "--why", f"A concrete symptom requires {slug}.",
            "--where", "src/example.py — Example.run — affected boundary",
            "--what", f"Implement and verify {slug}.",
            "--constraint", "Preserve the current public contract.",
            "--out-of-scope", "Do not redesign unrelated components.",
            "--link", "conversation 2026-08-01",
        )

    def test_complete_lifecycle_and_private_modes(self):
        created = self.run_cli(*self.new_args("permission-boundary"))
        self.assertEqual(created.returncode, 0, created.stderr)
        entry = self.root / "_general" / "tooling-permission-boundary.md"
        index = self.root / "INDEX.md"
        self.assertTrue(entry.is_file())
        self.assertIn('source: "conversation 2026-08-01"', entry.read_text(encoding="utf-8"))
        self.assertIn("A concrete symptom requires permission-boundary.",
                      entry.read_text(encoding="utf-8"))
        self.assertNotIn("What's wrong or missing today", entry.read_text(encoding="utf-8"))
        self.assertIn("[[tooling-permission-boundary]]", index.read_text(encoding="utf-8"))

        listed = self.run_cli("list", "--json")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        rows = json.loads(listed.stdout)
        self.assertEqual([row["id"] for row in rows], ["tooling-permission-boundary"])
        self.assertEqual(self.run_cli("check").returncode, 0)
        shown = self.run_cli("show", "tooling-permission-boundary")
        self.assertIn("# Capture permission-boundary", shown.stdout)

        finished = self.run_cli(
            "done", "tooling-permission-boundary", "--note", "Fixed in commit abc123"
        )
        self.assertEqual(finished.returncode, 0, finished.stderr)
        archived = self.root / "_general" / "archive" / entry.name
        self.assertFalse(entry.exists())
        self.assertIn("**Resolved:** Fixed in commit abc123", archived.read_text(encoding="utf-8"))
        self.assertNotIn("tooling-permission-boundary", index.read_text(encoding="utf-8"))
        self.assertEqual(self.run_cli("check").returncode, 0)
        self.assertEqual(
            self.run_cli(
                "done", "tooling-permission-boundary", "--note", "again"
            ).returncode,
            2,
        )

        if os.name != "nt":
            self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(index.stat().st_mode & 0o777, 0o600)
            self.assertEqual(archived.stat().st_mode & 0o777, 0o600)

    def test_domain_add_enables_a_repo_without_direct_file_edits(self):
        added = self.run_cli(
            "domain-add", "--repo", "sample", "--domain", "api",
            "--note", "API and public contracts",
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        vocabulary = self.root / "domains.local.tsv"
        self.assertEqual(
            vocabulary.read_text(encoding="utf-8"),
            "sample\tapi\tAPI and public contracts\n",
        )
        repeated = self.run_cli(
            "domain-add", "--repo", "sample", "--domain", "api",
            "--note", "ignored duplicate note",
        )
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(vocabulary.read_text(encoding="utf-8").count("sample\tapi"), 1)
        created = self.run_cli(*self.new_args("custom-domain", repo="sample", domain="api"))
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertTrue((self.root / "sample" / "api-custom-domain.md").is_file())
        if os.name != "nt":
            self.assertEqual(vocabulary.stat().st_mode & 0o777, 0o600)

    def test_safe_dispatcher_rejects_custom_paths_but_direct_helper_supports_them(self):
        custom = self.base / "custom-store"
        denied = self.run_cli("list", "--dir", str(custom))
        self.assertEqual(denied.returncode, 2)
        self.assertIn("unrecognized arguments", denied.stderr)
        self.assertFalse(custom.exists())

        direct = self.run_cli(
            *self.new_args("custom-store"), "--dir", str(custom), direct=True
        )
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertTrue(
            (custom / "_general" / "tooling-custom-store.md").is_file()
        )

    def test_safe_help_describes_the_fixed_store_boundary(self):
        safe_help = self.run_cli("--help")
        self.assertEqual(safe_help.returncode, 0, safe_help.stderr)
        self.assertIn("no custom path option", safe_help.stdout)
        self.assertNotIn("supports ``--dir``", safe_help.stdout)

        direct_help = self.run_cli("--help", direct=True)
        self.assertEqual(direct_help.returncode, 0, direct_help.stderr)
        self.assertIn("supports ``--dir``", direct_help.stdout)

    def test_path_and_frontmatter_injection_are_rejected(self):
        bad_repo = self.run_cli(*self.new_args("bad", repo="../escape"))
        self.assertEqual(bad_repo.returncode, 2)
        self.assertFalse((self.base / "escape").exists())

        bad_source = self.run_cli(
            *self.new_args("bad-source"), "--source", "ticket\nstatus: blocked"
        )
        self.assertEqual(bad_source.returncode, 2)
        self.assertFalse(
            (self.root / "_general" / "tooling-bad-source.md").exists()
        )

        bad_domain = self.run_cli(
            "domain-add", "--repo", "../escape", "--domain", "api"
        )
        self.assertEqual(bad_domain.returncode, 2)

        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "domains.local.tsv").write_text(
            "../outside\tapi\tmalformed path\n", encoding="utf-8"
        )
        malformed_vocab = self.run_cli(*self.new_args("vocabulary"))
        self.assertEqual(malformed_vocab.returncode, 2)
        self.assertIn("must use lowercase", malformed_vocab.stderr)

    def test_index_drift_is_reported_and_next_mutation_rebuilds_it(self):
        self.assertEqual(self.run_cli(*self.new_args("first")).returncode, 0)
        (self.root / "INDEX.md").write_text("# stale\n", encoding="utf-8")
        check = self.run_cli("check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("differs from the active entry files", check.stdout)
        self.assertEqual(self.run_cli(*self.new_args("second")).returncode, 0)
        self.assertEqual(self.run_cli("check").returncode, 0)
        index = (self.root / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("[[tooling-first]]", index)
        self.assertIn("[[tooling-second]]", index)

    def test_concurrent_writers_preserve_every_entry_and_index_line(self):
        processes = [
            subprocess.Popen(
                [sys.executable, str(SAFE), *self.new_args(f"parallel-{number}")],
                cwd=ROOT,
                env=self.environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for number in range(6)
        ]
        results = [process.communicate(timeout=30) + (process.returncode,) for process in processes]
        self.assertTrue(
            all(returncode == 0 for _stdout, _stderr, returncode in results), results
        )
        rows = json.loads(self.run_cli("list", "--json").stdout)
        self.assertEqual(len(rows), 6)
        self.assertEqual(self.run_cli("check").returncode, 0)

    def test_duplicate_concurrent_id_has_one_winner(self):
        command = [sys.executable, str(SAFE), *self.new_args("same-id")]
        processes = [
            subprocess.Popen(
                command, cwd=ROOT, env=self.environment, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            for _ in range(2)
        ]
        results = [process.communicate(timeout=30) + (process.returncode,) for process in processes]
        self.assertEqual(sorted(result[2] for result in results), [0, 2], results)
        self.assertEqual(len(list((self.root / "_general").glob("tooling-same-id.md"))), 1)

    def test_check_reports_symlinked_entries(self):
        self.root.mkdir(parents=True, exist_ok=True)
        repo = self.root / "_general"
        repo.mkdir()
        outside = self.base / "outside.md"
        outside.write_text("not a todo\n", encoding="utf-8")
        try:
            (repo / "tooling-linked.md").symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        checked = self.run_cli("check")
        self.assertEqual(checked.returncode, 1)
        self.assertIn("symlinked entry", checked.stdout)

    def test_safe_dispatcher_refuses_symlinked_store_root(self):
        target = self.base / "redirect-target"
        target.mkdir()
        try:
            self.root.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        attempted = self.run_cli(*self.new_args("redirected"))
        self.assertEqual(attempted.returncode, 2)
        self.assertIn("symlinked todo data store", attempted.stderr)
        self.assertFalse((target / "_general").exists())

    def test_safe_dispatcher_refuses_linked_lock(self):
        self.root.mkdir()
        external = self.base / "external-lock"
        external.write_bytes(b"")
        lock = self.root / ".todo-capture.lock"
        try:
            os.link(external, lock)
        except (OSError, NotImplementedError):
            self.skipTest("hard links unavailable")
        attempted = self.run_cli(*self.new_args("linked-lock"))
        self.assertEqual(attempted.returncode, 2)
        self.assertIn("linked or replaced todo lock", attempted.stderr)
        self.assertEqual(external.read_bytes(), b"")
        self.assertFalse((self.root / "_general").exists())


class TodoProjectRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.project = self.base / "sample project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.private_base = self.base / "private"
        self.environment = os.environ.copy()
        self.environment["TODO_CAPTURE_DATA_DIR"] = str(self.private_base)

    def tearDown(self):
        self.temporary.cleanup()

    def run_project(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(PROJECT), *args],
            cwd=cwd or self.project,
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def configure(self, backend="repository"):
        (self.project / ".todo-capture.toml").write_text(
            f'version = 1\nbackend = "{backend}"\n', encoding="utf-8"
        )

    def test_unconfigured_project_uses_private_store(self):
        route = self.run_project("route")
        self.assertEqual(route.returncode, 0, route.stderr)
        self.assertEqual(json.loads(route.stdout)["backend"], "private")
        created = self.run_project(
            "new", "--repo", "_general", "--domain", "tooling",
            "--slug", "private-default", "--title", "Private default",
            "--why", "Keep this private", "--where", "src/example.py",
            "--what", "Follow up", "--out-of-scope", "No other work",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertTrue((self.private_base / "todo-capture" / "_general" /
                         "tooling-private-default.md").is_file())
        self.assertFalse((self.project / ".todo").exists())

    def test_explicit_private_backend_keeps_fixed_store(self):
        self.configure("private")
        route = self.run_project("route")
        self.assertEqual(route.returncode, 0, route.stderr)
        selected = json.loads(route.stdout)
        self.assertEqual(selected["backend"], "private")
        self.assertEqual(selected["store"], str(self.private_base / "todo-capture"))
        self.assertFalse((self.project / ".todo").exists())

    def test_repository_store_lifecycle_from_nested_directory(self):
        self.configure()
        nested = self.project / "src" / "module"
        nested.mkdir(parents=True)
        route = self.run_project("route", cwd=nested)
        self.assertEqual(route.returncode, 0, route.stderr)
        selected = json.loads(route.stdout)
        self.assertEqual(selected["backend"], "repository")
        added = self.run_project(
            "domain-add", "--repo", "sample", "--domain", "api",
            "--note", "API follow-ups", cwd=nested,
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertTrue(os.path.samefile(selected["store"], self.project / ".todo"))
        created = self.run_project(
            "new", "--repo", "sample", "--domain", "api",
            "--slug", "route-check", "--title", "Check route",
            "--why", "A concrete project issue", "--where", "src/module/client.py",
            "--what", "Fix the route", "--out-of-scope", "No API redesign",
            cwd=nested,
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        store = self.project / ".todo"
        entry = store / "sample" / "api-route-check.md"
        self.assertTrue(entry.is_file())
        self.assertFalse((self.private_base / "todo-capture").exists())
        self.assertEqual(self.run_project("check", cwd=nested).returncode, 0)
        self.assertIn("api-route-check", self.run_project("list", cwd=nested).stdout)
        self.assertIn("# Check route", self.run_project(
            "show", "api-route-check", cwd=nested).stdout)
        finished = self.run_project(
            "done", "api-route-check", "--note", "Fixed in PR 42", cwd=nested,
        )
        self.assertEqual(finished.returncode, 0, finished.stderr)
        self.assertTrue((store / "sample" / "archive" / entry.name).is_file())
        self.assertEqual(self.run_project("check", cwd=nested).returncode, 0)
        status = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=self.project, text=True, capture_output=True, check=True,
        ).stdout
        self.assertNotIn(".todo-capture.lock", status)
        self.assertIn(".todo/.gitignore", status)
        self.assertIn(".todo/.todo-capture-store", status)

    def test_unsafe_config_and_store_fail_without_private_fallback(self):
        config = self.project / ".todo-capture.toml"
        config.write_text('version = 1\nbackend = "github"\n', encoding="utf-8")
        unknown = self.run_project("list")
        self.assertEqual(unknown.returncode, 2)
        self.assertIn("unsupported", unknown.stderr)
        self.assertFalse((self.private_base / "todo-capture").exists())
        config.write_text('version = 1\nbackend = "repository"\npath = "../elsewhere"\n',
                          encoding="utf-8")
        self.assertEqual(self.run_project("list").returncode, 2)
        config.write_text('version = true\nbackend = "repository"\n', encoding="utf-8")
        self.assertEqual(self.run_project("list").returncode, 2)
        config.unlink()
        external = self.base / "outside"
        external.mkdir()
        try:
            config.symlink_to(external / "config.toml")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.assertIn("symlinked project configuration", self.run_project("list").stderr)
        config.unlink()
        self.configure()
        (self.project / ".todo").symlink_to(external, target_is_directory=True)
        blocked = self.run_project("domain-add", "--repo", "sample", "--domain", "api")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("symlinked project todo store", blocked.stderr)
        self.assertEqual(list(external.iterdir()), [])

    def test_existing_foreign_store_and_custom_path_are_rejected(self):
        self.configure()
        store = self.project / ".todo"
        store.mkdir()
        (store / "INDEX.md").write_text("foreign content", encoding="utf-8")
        blocked = self.run_project("domain-add", "--repo", "sample", "--domain", "api")
        self.assertEqual(blocked.returncode, 2)
        self.assertEqual((store / "INDEX.md").read_text(encoding="utf-8"),
                         "foreign content")
        self.assertEqual(self.run_project("list", "--dir", str(self.base)).returncode, 2)
        self.assertEqual(self.run_project("list", "--di", str(self.base)).returncode, 2)
        self.assertEqual((store / "INDEX.md").read_text(encoding="utf-8"),
                         "foreign content")

    def test_empty_store_is_adopted_only_after_valid_command(self):
        self.configure()
        store = self.project / ".todo"
        store.mkdir()
        invalid = self.run_project("new", "--repo", "sample")
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(list(store.iterdir()), [])
        added = self.run_project(
            "domain-add", "--repo", "sample", "--domain", "api")
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertTrue((store / ".todo-capture-store").is_file())

    def test_modified_project_ignore_file_is_not_accepted(self):
        self.configure()
        self.assertEqual(self.run_project(
            "domain-add", "--repo", "sample", "--domain", "api").returncode, 0)
        override = self.base / "external-store"
        abbreviated = self.run_project("list", "--di", str(override))
        self.assertEqual(abbreviated.returncode, 2)
        self.assertFalse(override.exists())
        ignore = self.project / ".todo" / ".gitignore"
        ignore.write_text(".todo-capture.lock\n!.todo-capture.lock\n", encoding="utf-8")
        rejected = self.run_project("route")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("must contain only", rejected.stderr)

    def test_symlinked_project_lock_cannot_change_external_file(self):
        self.configure()
        self.assertEqual(self.run_project(
            "domain-add", "--repo", "sample", "--domain", "api").returncode, 0)
        lock = self.project / ".todo" / ".todo-capture.lock"
        lock.unlink()
        external = self.base / "external-lock"
        external.write_bytes(b"")
        try:
            lock.symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        blocked = self.run_project("domain-add", "--repo", "sample", "--domain", "other")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("project todo lock", blocked.stderr)
        self.assertEqual(external.read_bytes(), b"")
        self.assertFalse((self.private_base / "todo-capture").exists())

    def test_hardlinked_project_lock_cannot_change_external_file(self):
        self.configure()
        self.assertEqual(self.run_project(
            "domain-add", "--repo", "sample", "--domain", "api").returncode, 0)
        lock = self.project / ".todo" / ".todo-capture.lock"
        lock.unlink()
        external = self.base / "external-lock"
        external.write_bytes(b"")
        try:
            os.link(external, lock)
        except (OSError, NotImplementedError):
            self.skipTest("hard links unavailable")
        blocked = self.run_project("domain-add", "--repo", "sample", "--domain", "other")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("project todo lock", blocked.stderr)
        self.assertEqual(external.read_bytes(), b"")
        self.assertFalse((self.private_base / "todo-capture").exists())


class TodoPermissionTests(unittest.TestCase):
    def test_generated_rules_pin_only_the_fixed_store_dispatcher(self):
        with mock.patch.object(TODO_SETUP, "interpreter_forms", return_value=[("python",)]):
            codex = TODO_SETUP.codex_rule_text()
            claude = TODO_SETUP.claude_rules()
        self.assertIn(TODO_SETUP.starlark(str(SAFE)), codex)
        self.assertNotIn(TODO_SETUP.starlark(str(DIRECT)), codex)
        self.assertNotIn(TODO_SETUP.starlark(str(PROJECT)), codex)
        self.assertNotIn("--dir", codex)
        self.assertTrue(claude)
        safe_forms = set(TODO_SETUP.script_forms(None, str(SAFE)))
        direct_forms = set(TODO_SETUP.script_forms(None, str(DIRECT)))
        project_forms = set(TODO_SETUP.script_forms(None, str(PROJECT)))
        self.assertTrue(all(any(form in rule for form in safe_forms) for rule in claude))
        self.assertTrue(all(not any(form in rule for form in direct_forms) for rule in claude))
        self.assertTrue(all(not any(form in rule for form in project_forms) for rule in claude))
        self.assertTrue(all("--dir" not in rule for rule in claude))
        for subcommand in TODO_COMMON.SAFE_SUBCOMMANDS:
            self.assertIn(f'"{subcommand}"', codex)
            self.assertTrue(any(f" {subcommand} " in rule for rule in claude))

    def test_claude_setup_is_idempotent_migrates_owned_rules_and_removes_exactly(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            claude_home = base / "claude"
            data_base = base / "state"
            settings_path = claude_home / "settings.json"
            claude_home.mkdir()
            original_rule = "Bash(git status)"
            settings_path.write_text(
                json.dumps({
                    "permissions": {"allow": [original_rule]},
                    "sandbox": {"filesystem": {"allowWrite": [str(base / "other")]}}
                }),
                encoding="utf-8",
            )
            environment = {
                "CLAUDE_CONFIG_DIR": str(claude_home),
                "TODO_CAPTURE_DATA_DIR": str(data_base),
            }
            with mock.patch.dict(os.environ, environment, clear=False), mock.patch.object(
                    TODO_SETUP, "interpreter_forms", return_value=[("python",)]):
                data_dir = Path(TODO_COMMON.data_root())
                state_path = Path(TODO_SETUP.claude_state_target())
                legacy_state_path = Path(TODO_SETUP.legacy_claude_state_target())
                legacy_bash = f"Bash(python {DIRECT} new:*)"
                legacy_write = f"Write(//{str(data_dir).replace(os.sep, '/')}/**)"
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
                settings["permissions"]["allow"].extend([legacy_bash, legacy_write])
                settings["permissions"]["additionalDirectories"] = [str(data_dir)]
                settings_path.write_text(json.dumps(settings), encoding="utf-8")
                data_dir.mkdir(parents=True)
                legacy_state_path.write_text(
                    json.dumps({
                        "settings": str(settings_path),
                        "added_rules": [legacy_bash, legacy_write],
                        "added_dir": str(data_dir),
                    }),
                    encoding="utf-8",
                )

                TODO_SETUP.install_claude()
                first = json.loads(settings_path.read_text(encoding="utf-8"))
                self.assertTrue(state_path.is_file())
                self.assertFalse(legacy_state_path.exists())
                TODO_SETUP.install_claude()
                second = json.loads(settings_path.read_text(encoding="utf-8"))
                self.assertEqual(first, second)
                allow = second["permissions"]["allow"]
                self.assertIn(original_rule, allow)
                self.assertNotIn(legacy_bash, allow)
                self.assertNotIn(legacy_write, allow)
                self.assertFalse(any(rule.startswith("Write(") for rule in allow))
                self.assertTrue(any(rule.startswith("Read(") for rule in allow))
                self.assertTrue(any(rule.startswith("Edit(") for rule in allow))
                self.assertFalse(any(
                    rule.startswith("Edit(") and "domains.local.tsv" in rule
                    for rule in allow
                ))
                self.assertFalse(any("INDEX.md" in rule for rule in allow))
                broad_edit = f"Edit({TODO_SETUP.claude_file_pattern(str(data_dir))})"
                self.assertNotIn(broad_edit, allow)
                self.assertTrue(any(str(SAFE) in rule for rule in allow))
                self.assertIn(
                    str(data_dir), second["sandbox"]["filesystem"]["allowWrite"]
                )
                if os.name != "nt":
                    self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)

                TODO_SETUP.remove_claude()
                removed = json.loads(settings_path.read_text(encoding="utf-8"))
                self.assertEqual(removed["permissions"]["allow"], [original_rule])
                self.assertEqual(
                    removed["sandbox"]["filesystem"]["allowWrite"],
                    [str(base / "other")],
                )
                self.assertFalse(state_path.exists())
                if os.name != "nt":
                    self.assertEqual(data_dir.stat().st_mode & 0o777, 0o700)

    def test_codex_setup_is_idempotent_private_and_removable(self):
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary) / "codex"
            with mock.patch.dict(
                    os.environ, {"CODEX_HOME": str(codex_home)}, clear=False), \
                    mock.patch.object(
                        TODO_SETUP, "interpreter_forms", return_value=[("python",)]
                    ):
                TODO_SETUP.install_codex()
                rules_path = Path(TODO_SETUP.codex_target())
                first = rules_path.read_text(encoding="utf-8")
                TODO_SETUP.install_codex()
                self.assertEqual(first, rules_path.read_text(encoding="utf-8"))
                self.assertIn(TODO_SETUP.starlark(str(SAFE)), first)
                self.assertNotIn(TODO_SETUP.starlark(str(DIRECT)), first)
                if os.name != "nt":
                    self.assertEqual(rules_path.stat().st_mode & 0o777, 0o600)
                TODO_SETUP.remove_codex()
                self.assertFalse(rules_path.exists())

    def test_permission_state_cannot_claim_unrelated_rules_or_settings_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            claude_home = base / "claude"
            claude_home.mkdir()
            settings_path = claude_home / "settings.json"
            unrelated = "Bash(git status)"
            settings_path.write_text(
                json.dumps({"permissions": {"allow": [unrelated]}}), encoding="utf-8"
            )
            environment = {
                "CLAUDE_CONFIG_DIR": str(claude_home),
                "TODO_CAPTURE_DATA_DIR": str(base / "state"),
            }
            with mock.patch.dict(os.environ, environment, clear=False):
                state_path = Path(TODO_SETUP.claude_state_target())
                state_path.write_text(
                    json.dumps({
                        "settings": str(settings_path),
                        "added_rules": [unrelated],
                    }),
                    encoding="utf-8",
                )
                TODO_SETUP.remove_claude()
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
                self.assertEqual(settings["permissions"]["allow"], [unrelated])

                state_path.write_text(
                    json.dumps({
                        "settings": str(base / "other.json"),
                        "added_rules": [],
                    }),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, "unexpected settings file"):
                    TODO_SETUP.remove_claude()

    def test_data_root_platform_defaults_and_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.dict(
                    os.environ,
                    {"TODO_CAPTURE_DATA_DIR": temporary},
                    clear=False):
                self.assertEqual(
                    TODO_COMMON.data_root(), str(Path(temporary) / "todo-capture")
                )
                self.assertEqual(
                    TODO_COMMON.data_root(str(Path(temporary) / "exact")),
                    str(Path(temporary) / "exact"),
                )

    def test_windows_generates_bash_and_powershell_rules(self):
        if os.name != "nt":
            self.skipTest("Windows-only rule form")
        rules = TODO_SETUP.claude_rules()
        self.assertTrue(any(rule.startswith("Bash(") for rule in rules))
        self.assertTrue(any(rule.startswith("PowerShell(") for rule in rules))


class TodoEvalDefinitionTests(unittest.TestCase):
    def test_project_eval_suite_is_ready(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "skills/project-eval/scripts/project_eval.py"),
             "readiness", "--repo", str(ROOT), "--eval-root", "evals/todo-capture",
             "--suite", "suite.json", "--format", "json"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "ready")

    def test_eval_snapshots_match_skill_source(self):
        source = {
            file.relative_to(SKILL): file.read_bytes()
            for file in SKILL.rglob("*") if file.is_file() and "__pycache__" not in file.parts
        }
        fixtures = ROOT / "evals/todo-capture/fixtures"
        for case in ("configured-project-store", "unconfigured-private-store",
                     "unsupported-issue-backend"):
            with self.subTest(case=case):
                snapshot = fixtures / case / "history/initial/.agents/skills/todo-capture"
                actual = {
                    file.relative_to(snapshot): file.read_bytes()
                    for file in snapshot.rglob("*") if file.is_file()
                }
                self.assertEqual(actual, source)


if __name__ == "__main__":
    unittest.main()
