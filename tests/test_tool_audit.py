import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "tool-audit"
SCRIPTS = SKILL / "scripts"
CLASSES = SKILL / "references" / "command-classes.tsv"
sys.path.insert(0, str(SCRIPTS))

common = importlib.import_module("_common")
audit = importlib.import_module("audit")
config_audit = importlib.import_module("config_audit")
inventory = importlib.import_module("inventory")
setup_permissions = importlib.import_module("setup_permissions")
usage = importlib.import_module("usage")


class CatalogTests(unittest.TestCase):
    def test_catalog_is_valid_reviewed_policy(self):
        allowed = {"read", "write", "destructive", "network", "exec", "mixed"}
        seen = set()
        for number, raw in enumerate(CLASSES.read_text(encoding="utf-8").splitlines(), 1):
            if not raw or raw.startswith("#"):
                continue
            fields = raw.split("\t")
            self.assertEqual(3, len(fields), f"line {number}")
            tool, subcommand, command_class = fields
            self.assertTrue(tool, f"line {number}")
            self.assertTrue(subcommand, f"line {number}")
            self.assertIn(command_class, allowed, f"line {number}")
            self.assertNotIn((tool, subcommand), seen, f"duplicate line {number}")
            seen.add((tool, subcommand))
        self.assertNotIn(("gh-api-get", "*"), seen)

    def test_specific_subcommand_overrides_default(self):
        self.assertEqual("mixed", common.classify("git", None))
        self.assertEqual("read", common.classify("git", "status"))
        self.assertEqual("destructive", common.classify("git", "reset"))
        self.assertEqual("mixed", common.classify("git", "diff"))
        self.assertEqual("write", common.classify("git", "fetch"))
        self.assertEqual("write", common.classify("cargo", "fmt"))
        self.assertEqual("mixed", common.classify("gh", "api"))
        self.assertEqual("read", common.classify("gh", "search repos"))

    def test_reviewed_local_catalog_can_override_baseline(self):
        original_cache = common._CLASSES
        try:
            with tempfile.TemporaryDirectory() as td:
                local = Path(td) / "tool-audit" / "command-classes.local.tsv"
                local.parent.mkdir()
                local.write_text("private-cli\t*\tread\ngit\tstatus\tmixed\n",
                                 encoding="utf-8")
                with mock.patch.dict(os.environ, {"TOOL_AUDIT_DATA_DIR": td}, clear=False):
                    common._CLASSES = None
                    self.assertEqual("read", common.classify("private-cli", None))
                    self.assertEqual("mixed", common.classify("git", "status"))
        finally:
            common._CLASSES = original_cache


class TranscriptTests(unittest.TestCase):
    def write_jsonl(self, path, records):
        path.write_text("".join(json.dumps(record) + "\n" for record in records),
                        encoding="utf-8")

    def test_claude_tool_use_and_result(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "claude.jsonl"
            self.write_jsonl(path, [{
                "timestamp": "2026-07-29T12:00:00Z",
                "message": {"content": [
                    {"type": "tool_use", "name": "Bash", "id": "call-1",
                     "input": {"command": "git status"}},
                    {"type": "tool_result", "tool_use_id": "call-1", "is_error": False},
                ]},
            }])
            uses = list(common.iter_tool_uses(path))
            results = list(common.iter_tool_results(path))
        self.assertEqual(("Bash", {"command": "git status"}), uses[0][:2])
        self.assertEqual([("call-1", False)], results)

    def test_codex_direct_and_wrapped_calls(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "codex.jsonl"
            self.write_jsonl(path, [
                {"timestamp": "2026-07-29T12:00:00Z", "type": "response_item",
                 "payload": {"type": "function_call", "name": "exec_command",
                             "call_id": "direct", "arguments": json.dumps({"cmd": "git log"})}},
                {"timestamp": "2026-07-29T12:01:00Z", "type": "response_item",
                 "payload": {"type": "custom_tool_call", "name": "exec",
                             "call_id": "wrapped",
                             "input": "await tools.exec_command({cmd: 'rg needle'}); "
                                      "await tools.web__run({search_query: [{q: 'docs'}]});"}},
                {"type": "response_item",
                 "payload": {"type": "function_call_output", "call_id": "direct",
                             "output": {"is_error": True}}},
            ])
            uses = list(common.iter_tool_uses(path))
            results = list(common.iter_tool_results(path))
        self.assertEqual("Bash", uses[0][0])
        self.assertEqual("git log", uses[0][1]["command"])
        self.assertEqual("Bash", uses[1][0])
        self.assertEqual("rg needle", uses[1][1]["command"])
        self.assertEqual("web__run", uses[2][0])
        self.assertEqual([("direct", True)], results)

    def test_codex_text_encoded_failures_are_detected_conservatively(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "codex.jsonl"
            self.write_jsonl(path, [
                {"type": "response_item", "payload": {
                    "type": "function_call_output", "call_id": "shell",
                    "output": "Chunk ID: x\nProcess exited with code 2\nOutput:\nfailed\n",
                }},
                {"type": "response_item", "payload": {
                    "type": "custom_tool_call_output", "call_id": "patch",
                    "output": [{"type": "input_text",
                                "text": "apply_patch verification failed: missing context"}],
                }},
                {"type": "response_item", "payload": {
                    "type": "custom_tool_call_output", "call_id": "ambiguous",
                    "output": [{"type": "input_text", "text": "CHECK\nexit=1\n"}],
                }},
                {"type": "response_item", "payload": {
                    "type": "function_call_output", "call_id": "reader",
                    "output": "Process exited with code 0\nOutput:\n"
                              "Process exited with code 2\n",
                }},
            ])
            details = list(common.iter_tool_result_details(path))
            results = list(common.iter_tool_results(path))
        self.assertEqual((2,), details[0][1]["process_exit_codes"])
        self.assertTrue(details[1][1]["patch_failure"])
        self.assertFalse(details[2][1]["is_error"])
        self.assertEqual([], list(details[2][1]["process_exit_codes"]))
        self.assertEqual([("shell", True), ("patch", True), ("ambiguous", False),
                          ("reader", False)], results)

    def test_expected_nonzero_is_narrow(self):
        self.assertTrue(usage.expected_nonzero("rg missing src", "rg", 1))
        self.assertTrue(usage.expected_nonzero("which optional", "which", 1))
        self.assertTrue(usage.expected_nonzero("command -v optional", "command", 1))
        self.assertTrue(usage.expected_nonzero(
            "git diff --quiet HEAD", "git diff", 1))
        self.assertFalse(usage.expected_nonzero("pytest", "pytest", 1))
        self.assertFalse(usage.expected_nonzero("rg missing src", "rg", 2))


class PathAndInventoryTests(unittest.TestCase):
    def test_data_override_and_discovery_are_outside_skill(self):
        with tempfile.TemporaryDirectory() as td:
            env = {"TOOL_AUDIT_DATA_DIR": td, "CODEX_THREAD_ID": "test"}
            with mock.patch.dict(os.environ, env, clear=True):
                expected = Path(td) / "tool-audit" / "codex"
                self.assertEqual(str(expected), common.data_root("codex"))
                self.assertEqual(str(expected / "discovered-tools.tsv"),
                                 inventory.discovered_file())
                inventory.learn(["private-local-cli"], "codex")
                generated = expected / "discovered-tools.tsv"
                self.assertTrue(generated.exists())
                self.assertNotIn(str(SKILL), str(generated))
                if os.name != "nt":
                    self.assertEqual(0o600, generated.stat().st_mode & 0o777)

    @unittest.skipUnless(os.name != "nt" and sys.platform != "darwin",
                         "Linux XDG path test")
    def test_linux_uses_xdg_state_home(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": td}, clear=True):
                self.assertEqual(str(Path(td) / "tool-audit" / "claude"),
                                 common.data_root("claude"))

    def test_system_filter_recognizes_windows_and_unix_plumbing(self):
        self.assertTrue(inventory.is_system(r"C:\Windows\System32\where.exe"))
        self.assertTrue(inventory.is_system("/usr/bin/base64"))
        self.assertFalse(inventory.is_system("/usr/local/bin/rg"))
        self.assertFalse(inventory.is_system("/opt/homebrew/bin/rg"))


class PermissionTests(unittest.TestCase):
    def test_config_output_redacts_embedded_credentials(self):
        secret = "github_pat_this-must-never-appear"
        prefix = f"curl -H Authorization: Bearer {secret}"
        for agent in ("codex", "claude"):
            rendered = config_audit.rule_text(prefix, agent)
            self.assertNotIn(secret, rendered)
            self.assertIn("[REDACTED]", rendered)

    def test_codex_restrictive_prefix_shadows_allow(self):
        rules = [
            {"decision": "allow", "tokens": ["rm", "temporary.txt"],
             "rule_id": "allow-rm"},
            {"decision": "prompt", "tokens": ["rm"], "rule_id": "prompt-rm"},
            {"decision": "allow", "tokens": ["git", "status"],
             "rule_id": "allow-status"},
        ]
        self.assertEqual(["git status"], config_audit.codex_allow_prefixes(rules))
        self.assertEqual(1, config_audit.configured_rule_count(rules, "codex"))

    def test_lint_recognizes_fixed_profiles_from_an_installed_copy(self):
        installed = "/some/home/.codex/skills/tool-audit/scripts/audit.py"
        self.assertEqual("usage", config_audit.scoped_audit_profile(
            f"python {installed} usage"))
        self.assertIsNone(config_audit.scoped_audit_profile(
            f"python {installed} usage-extra"))
        self.assertIsNone(config_audit.scoped_audit_profile(
            "python /unrelated/scripts/audit.py usage"))

    def test_codex_rules_expand_only_fixed_profiles(self):
        interpreter_forms = {("python3",), ("py", "-3")}
        with mock.patch.object(setup_permissions, "interpreter_forms",
                               return_value=sorted(interpreter_forms)):
            text = setup_permissions.codex_rule_text()
        self.assertNotIn("*", text)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tool-audit.rules"
            path.write_text(text, encoding="utf-8")
            rules = config_audit.load_codex_rules(str(path))
        self.assertTrue(rules)
        for rule in rules:
            self.assertEqual("allow", rule["decision"])
            self.assertIn(tuple(rule["tokens"][:-2]), interpreter_forms)
            self.assertEqual(str(SCRIPTS / "audit.py"), rule["tokens"][-2])
            self.assertIn(rule["tokens"][-1], audit.PROFILES)

    def test_claude_install_is_exact_idempotent_and_removable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            claude_home = root / "claude"
            state_home = root / "state"
            settings_path = claude_home / "settings.json"
            settings_path.parent.mkdir()
            original = {
                "permissions": {"allow": ["Bash(git status)"]},
                "sandbox": {"filesystem": {"allowWrite": [str(root / "existing")] }},
                "env": {"PRESERVE": "yes"},
            }
            settings_path.write_text(json.dumps(original), encoding="utf-8")
            env = {"CLAUDE_CONFIG_DIR": str(claude_home),
                   "TOOL_AUDIT_DATA_DIR": str(state_home), "CLAUDECODE": "1"}
            with mock.patch.dict(os.environ, env, clear=False):
                setup_permissions.install_claude()
                first = json.loads(settings_path.read_text(encoding="utf-8"))
                setup_permissions.install_claude()
                second = json.loads(settings_path.read_text(encoding="utf-8"))
                self.assertEqual(first, second)
                added = [entry for entry in first["permissions"]["allow"]
                         if entry != "Bash(git status)"]
                self.assertTrue(added)
                self.assertTrue(all("*" not in entry for entry in added))
                self.assertIn(common.data_root("claude"),
                              first["sandbox"]["filesystem"]["allowWrite"])
                setup_permissions.remove_claude()
            restored = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(original, restored)


class DispatcherTests(unittest.TestCase):
    def run_audit(self, *args, env=None):
        return subprocess.run([sys.executable, str(SCRIPTS / "audit.py"), *args],
                              text=True, capture_output=True, env=env, timeout=30)

    def test_extra_arguments_and_unknown_profiles_are_rejected(self):
        self.assertNotEqual(0, self.run_audit("inventory", "extra").returncode)
        self.assertNotEqual(0, self.run_audit("inventory-versions").returncode)
        capability_modules = {"inventory_versions", "inventory_learn",
                              "snapshot_custom", "setup_permissions"}
        self.assertFalse(capability_modules & {module for module, _ in audit.PROFILES.values()})

    def test_safe_snapshot_uses_fixed_agent_data_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = os.environ.copy()
            env.update({
                "CODEX_HOME": str(root / "codex"),
                "CODEX_THREAD_ID": "test",
                "TOOL_AUDIT_DATA_DIR": str(root / "state"),
                "PATH": "",
            })
            result = self.run_audit("snapshot", env=env)
            expected = root / "state" / "tool-audit" / "codex" / "history.jsonl"
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(expected.exists())
            if os.name != "nt":
                self.assertEqual(0o600, expected.stat().st_mode & 0o777)
                self.assertEqual(0o700, expected.parent.stat().st_mode & 0o777)

    def test_usage_errors_reports_process_patch_and_expected_statuses(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = root / "codex" / "sessions" / "2026" / "07" / "30" / "one.jsonl"
            session.parent.mkdir(parents=True)
            records = [
                {"timestamp": "2026-07-30T12:00:00Z", "type": "session_meta",
                 "payload": {"source": "cli", "cwd": str(root)}},
                {"timestamp": "2026-07-30T12:00:01Z", "type": "response_item",
                 "payload": {"type": "function_call", "name": "exec_command",
                             "call_id": "rg", "arguments": json.dumps({"cmd": "rg absent src"})}},
                {"timestamp": "2026-07-30T12:00:02Z", "type": "response_item",
                 "payload": {"type": "function_call_output", "call_id": "rg",
                             "output": "Process exited with code 1\nOutput:\n"}},
                {"timestamp": "2026-07-30T12:00:03Z", "type": "response_item",
                 "payload": {"type": "function_call", "name": "exec_command",
                             "call_id": "tests", "arguments": json.dumps({"cmd": "pytest"})}},
                {"timestamp": "2026-07-30T12:00:04Z", "type": "response_item",
                 "payload": {"type": "function_call_output", "call_id": "tests",
                             "output": "Process exited with code 1\nOutput:\nfailed\n"}},
                {"timestamp": "2026-07-30T12:00:05Z", "type": "response_item",
                 "payload": {"type": "function_call", "name": "apply_patch",
                             "call_id": "patch", "arguments": "{}"}},
                {"timestamp": "2026-07-30T12:00:06Z", "type": "response_item",
                 "payload": {"type": "function_call_output", "call_id": "patch",
                             "output": "apply_patch verification failed: missing context"}},
            ]
            session.write_text("".join(json.dumps(record) + "\n" for record in records),
                               encoding="utf-8")
            env = os.environ.copy()
            env.update({"CODEX_HOME": str(root / "codex"), "CODEX_THREAD_ID": "test"})
            result = self.run_audit("usage-errors", env=env)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Actionable failures: 2", result.stdout)
        self.assertIn("Expected non-error statuses: 1", result.stdout)
        self.assertIn("patch application failure", result.stdout)

    def test_usage_friction_aggregates_codex_and_claude_without_samples(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex = root / "codex" / "sessions" / "2026" / "07" / "30" / "codex.jsonl"
            codex.parent.mkdir(parents=True)
            codex_records = [
                {"timestamp": "2026-07-30T12:00:00Z", "type": "session_meta",
                 "payload": {"source": "cli", "cwd": str(root)}},
                {"timestamp": "2026-07-30T12:00:01Z", "type": "event_msg",
                 "payload": {"type": "user_message", "message": "A"}},
                {"timestamp": "2026-07-30T12:00:02Z", "type": "event_msg",
                 "payload": {"type": "user_message", "message": "What should we do next?"}},
            ]
            codex.write_text("".join(json.dumps(record) + "\n" for record in codex_records),
                             encoding="utf-8")

            autonomous = codex.with_name("exec.jsonl")
            exec_records = [
                {"timestamp": "2026-07-30T12:01:00Z", "type": "session_meta",
                 "payload": {"source": "exec", "cwd": str(root)}},
                {"timestamp": "2026-07-30T12:01:01Z", "type": "event_msg",
                 "payload": {"type": "user_message", "message": "Role: implementer\nDo work."}},
                {"timestamp": "2026-07-30T12:02:00Z", "type": "event_msg",
                 "payload": {"type": "task_complete", "duration_ms": 60000,
                             "last_agent_message": "Issue #7 complete; another agent detected."}},
                {"timestamp": "2026-07-30T12:02:01Z", "type": "event_msg",
                 "payload": {"type": "task_complete", "duration_ms": 60000,
                             "last_agent_message": "Issue #7 returned to review."}},
            ]
            autonomous.write_text(
                "".join(json.dumps(record) + "\n" for record in exec_records), encoding="utf-8")

            claude = root / "claude" / "projects" / "project" / "claude.jsonl"
            claude.parent.mkdir(parents=True)
            claude.write_text(json.dumps({
                "timestamp": "2026-07-30T12:03:00Z", "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": "continue"}]},
            }) + "\n", encoding="utf-8")

            env = os.environ.copy()
            for key in ("CODEX_THREAD_ID", "CODEX_CI", "CLAUDECODE", "CLAUDE_CODE"):
                env.pop(key, None)
            env.update({"CODEX_HOME": str(root / "codex"),
                        "CLAUDE_CONFIG_DIR": str(root / "claude")})
            result = self.run_audit("usage-friction", env=env)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("interactive_cli", result.stdout)
        self.assertIn("autonomous_exec", result.stdout)
        self.assertIn("claude_transcript", result.stdout)
        self.assertIn("#7=", result.stdout)
        self.assertIn("Privacy:", result.stdout)
        self.assertNotIn("What should we do next?", result.stdout)


if __name__ == "__main__":
    unittest.main()
