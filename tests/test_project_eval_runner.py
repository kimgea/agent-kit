import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "project-eval" / "scripts"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


case_engine = load_module("project_eval_runner_case_engine_tests", SCRIPTS / "case_engine.py")
codex_runner = load_module("project_eval_codex_runner_tests", SCRIPTS / "codex_runner.py")
project_eval = load_module("project_eval_runner_cli_tests", SCRIPTS / "project_eval.py")


def selected_case(kind="implementation"):
    return {
        "case_id": "runner-case",
        "kind": kind,
        "coverage": "development",
        "platforms": ["linux", "windows", "macos"],
        "required_capabilities": [],
        "assertion_ids": ["answer-present"],
    }


def control():
    return {
        "schema_version": "project-eval-case-control/v1",
        "case_id": "runner-case",
        "materialization": {
            "mode": "copy",
            "source": "visible",
            "remove_paths": [],
            "history": [],
        },
        "assertions": [
            {
                "assertion_id": "answer-present",
                "kind": "file_contains",
                "path": "answer.txt",
                "expected": "correct",
            }
        ],
        "checks": [],
        "hidden_grader": None,
        "trajectory": None,
        "reconstruction": None,
    }


def profile(*, effects=None, seconds=10, tokens=1000, cost=1.0, network=False):
    return {
        "case_ids": ["runner-case"],
        "repetitions": 1,
        "max_invocations": 1,
        "max_seconds": seconds,
        "max_tokens": tokens,
        "max_cost_usd": cost,
        "network": network,
        "effects": list(effects or ["workspace_edit"]),
    }


def write_fixture(root):
    fixture = root / "fixture"
    (fixture / "visible").mkdir(parents=True)
    (fixture / "control.json").write_text(json.dumps(control()), encoding="utf-8")
    (fixture / "visible" / "answer.txt").write_text("not yet\n", encoding="utf-8")
    return fixture


FAKE_RUNNER = r'''import json
from pathlib import Path
import subprocess
import sys
import time

args = sys.argv[1:]
workspace = Path(args[args.index("--cd") + 1])
result = Path(args[args.index("--output-last-message") + 1])
mode_path = workspace / "runner-mode.txt"
mode = mode_path.read_text(encoding="utf-8").strip() if mode_path.exists() else "edit"
sys.stdin.read()
if mode == "timeout":
    marker = (workspace / "marker-path.txt").read_text(encoding="utf-8").strip()
    subprocess.Popen([sys.executable, "-c", "import pathlib,sys,time;time.sleep(2);pathlib.Path(sys.argv[1]).write_text('orphan', encoding='utf-8')", marker])
    time.sleep(30)
if mode == "instructions":
    (workspace / "AGENTS.md").write_text("changed\n", encoding="utf-8")
else:
    (workspace / "answer.txt").write_text("correct\n", encoding="utf-8")
if mode == "command":
    print(json.dumps({"type":"item.completed","item":{"id":"cmd-1","type":"command_execution"}}), flush=True)
if mode == "network":
    print(json.dumps({"type":"item.completed","item":{"id":"web-1","type":"web_search"}}), flush=True)
result.write_text("done\n", encoding="utf-8")
print(json.dumps({"type":"turn.completed","usage":{"total_tokens":7}}), flush=True)
'''


class CodexRunnerTests(unittest.TestCase):
    def make_attempt(self, root, *, mode="edit", selected_profile=None, allow_network=False):
        fixture = write_fixture(root)
        case = selected_case()
        prepared = case_engine.materialize_case(fixture, case, root / "workspaces")
        workspace = Path(prepared["workspace"])
        if mode != "edit":
            (workspace / "runner-mode.txt").write_text(mode, encoding="utf-8")
            prepared["workspace_initial_sha256"] = case_engine.tree_digest(workspace)
            unsigned = dict(prepared)
            unsigned.pop("preparation_sha256")
            prepared["preparation_sha256"] = codex_runner._sha(codex_runner._canonical(unsigned))
        script = root / "fake_codex.py"
        script.write_text(FAKE_RUNNER, encoding="utf-8")
        runner = {
            "command": [sys.executable, "-I", "-S", str(script)],
            "launcher_sha256": "1" * 64,
            "help_sha256": "2" * 64,
            "version": "0.1.0",
            "identity_sha256": "3" * 64,
        }
        selected_profile = selected_profile or profile()
        ledger = codex_runner.BudgetLedger.from_profile(selected_profile)
        result = codex_runner.run_codex_attempt(
            fixture,
            case,
            prepared,
            selected_profile,
            "Make the answer correct.",
            root / "host",
            "gpt-test",
            "medium",
            ledger,
            allow_network=allow_network,
            runner=runner,
        )
        return result, fixture, case, prepared, ledger

    def test_command_is_fixed_ephemeral_and_offline_by_default(self):
        runner = {"command": ["codex"], "version": "1.2.3", "identity_sha256": "3" * 64}
        command = codex_runner.build_codex_command(
            runner,
            Path("/work"),
            Path("/host/result"),
            "gpt-test",
            "high",
            workspace_edit=True,
            network=False,
        )
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn('approval_policy="never"', command)
        self.assertNotIn("--sandbox", command)
        self.assertIn('default_permissions="project-eval"', command)
        permission = next(item for item in command if item.startswith("permissions.project-eval.filesystem="))
        self.assertIn('":root"="deny"', permission)
        self.assertIn('":minimal"="read"', permission)
        self.assertIn('":workspace_roots"={"."="write"', permission)
        self.assertIn("permissions.project-eval.network.enabled=false", command)
        self.assertIn('web_search="disabled"', command)
        self.assertIn("agents.enabled=false", command)

        environment = codex_runner._runner_environment()
        self.assertNotIn("SSH_AUTH_SOCK", environment)
        self.assertEqual(environment["PYTHONNOUSERSITE"], "1")

        parser = project_eval._parser()
        parsed = parser.parse_args(["runner-info"])
        self.assertEqual(parsed.command, "runner-info")
        parsed = parser.parse_args(
            [
                "run-codex-attempt",
                "--repo",
                "/repo",
                "--suite",
                "suite.json",
                "--case",
                "runner-case",
                "--profile",
                "smoke",
                "--prepared",
                "/host/prepared.json",
                "--host-root",
                "/host/capture",
                "--model",
                "gpt-test",
                "--reasoning",
                "medium",
            ]
        )
        self.assertEqual(parsed.command, "run-codex-attempt")

    def test_successful_attempt_is_bound_measured_and_schema_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, fixture, case, prepared, ledger = self.make_attempt(Path(temporary))
            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["workspace_changed"])
            self.assertEqual(result["tokens"], {"value": 7, "provenance": "runner_reported"})
            self.assertEqual(result["duration_ms"]["provenance"], "host_observed")
            self.assertEqual(result["cost_microusd"], {"value": None, "provenance": "unavailable"})
            self.assertEqual(result["unobservable_budgets"], ["cost"])
            self.assertEqual(ledger.invocations, 1)
            self.assertEqual(ledger.tokens, 7)
            self.assertEqual(
                result["attempt_sha256"],
                codex_runner._sha(codex_runner._canonical({k: v for k, v in result.items() if k != "attempt_sha256"})),
            )
            self.assertEqual(case_engine.grade_case(fixture, case, prepared)["status"], "passed")
            self.assertEqual(list((Path(temporary) / "host").iterdir()), [])

            try:
                import jsonschema
            except ImportError:
                return
            schema = json.loads(
                (ROOT / "skills" / "project-eval" / "references" / "project-eval-runner-attempt.schema.json").read_text(encoding="utf-8")
            )
            jsonschema.Draft202012Validator.check_schema(schema)
            self.assertTrue(jsonschema.Draft202012Validator(schema).is_valid(result))

    def test_budget_counts_retries_and_records_unobservable_token_cost(self):
        value = profile(tokens=10, cost=1.0)
        value["max_invocations"] = 2
        ledger = codex_runner.BudgetLedger.from_profile(value)
        self.assertGreaterEqual(ledger.claim(), 1)
        ledger.record(duration_ms=1, tokens=None, cost_usd=None)
        self.assertGreaterEqual(ledger.claim(), 1)
        with self.assertRaisesRegex(codex_runner.RunnerError, "invocations"):
            ledger.claim()
        self.assertIsNone(ledger.tokens)
        self.assertIsNone(ledger.cost_usd)

    def test_profile_schedule_freezes_cases_repetitions_and_retry_capacity(self):
        case = selected_case()
        suite = {
            "cases": [case],
            "profiles": {
                "compare": {
                    **profile(),
                    "repetitions": 3,
                    "max_invocations": 4,
                }
            },
        }
        schedule = codex_runner.build_profile_schedule(suite, "compare", set())
        self.assertEqual(
            schedule["planned"],
            [
                {"case_id": "runner-case", "repetition": 1},
                {"case_id": "runner-case", "repetition": 2},
                {"case_id": "runner-case", "repetition": 3},
            ],
        )
        self.assertEqual(schedule["retry_capacity"], 1)

        unavailable = {**case, "required_capabilities": ["docker"]}
        suite["cases"] = [unavailable]
        schedule = codex_runner.build_profile_schedule(suite, "compare", set())
        self.assertEqual(schedule["planned"], [])
        self.assertEqual(schedule["excluded"][0]["status"], "unavailable")

    def test_effect_and_instruction_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result, _, _, _, _ = self.make_attempt(root, mode="command")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error_category"], "effect_violation")
            self.assertIn("commands ran without command_execution authority", result["effect_errors"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result, _, _, _, _ = self.make_attempt(root, mode="instructions")
            self.assertEqual(result["status"], "failed")
            self.assertIn("frozen agent instructions changed during the attempt", result["effect_errors"])

    def test_network_requires_matching_profile_and_explicit_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(codex_runner.RunnerError, "explicit network authorization"):
                self.make_attempt(root, selected_profile=profile(network=True))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result, _, _, _, _ = self.make_attempt(
                root,
                mode="network",
                selected_profile=profile(network=True),
                allow_network=True,
            )
            self.assertEqual(result["status"], "completed")

    def test_recorded_output_grading_does_not_claim_direct_runner_support(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = write_fixture(root)
            case = selected_case()
            prepared = case_engine.materialize_case(fixture, case, root / "workspaces")
            Path(prepared["workspace"]).joinpath("answer.txt").write_text("correct\n", encoding="utf-8")
            result = codex_runner.grade_recorded_case(fixture, case, prepared)
            self.assertEqual(result["runner"], "recorded-output")
            self.assertEqual(result["direct_runner_compatibility"], [])
            self.assertEqual(result["grade"]["status"], "passed")

    def test_timeout_reaps_descendant_before_returning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = write_fixture(root)
            case = selected_case()
            prepared = case_engine.materialize_case(fixture, case, root / "workspaces")
            workspace = Path(prepared["workspace"])
            marker = root / "orphan-marker.txt"
            (workspace / "runner-mode.txt").write_text("timeout", encoding="utf-8")
            (workspace / "marker-path.txt").write_text(str(marker), encoding="utf-8")
            prepared["workspace_initial_sha256"] = case_engine.tree_digest(workspace)
            unsigned = dict(prepared)
            unsigned.pop("preparation_sha256")
            prepared["preparation_sha256"] = codex_runner._sha(codex_runner._canonical(unsigned))
            script = root / "fake_codex.py"
            script.write_text(FAKE_RUNNER, encoding="utf-8")
            runner = {
                "command": [sys.executable, "-I", "-S", str(script)],
                "launcher_sha256": "1" * 64,
                "help_sha256": "2" * 64,
                "version": "0.1.0",
                "identity_sha256": "3" * 64,
            }
            selected_profile = profile(seconds=1)
            result = codex_runner.run_codex_attempt(
                fixture,
                case,
                prepared,
                selected_profile,
                "Wait.",
                root / "host",
                "gpt-test",
                "medium",
                codex_runner.BudgetLedger.from_profile(selected_profile),
                runner=runner,
            )
            self.assertEqual(result["status"], "timed_out")
            time.sleep(2.2)
            self.assertFalse(marker.exists())

if __name__ == "__main__":
    unittest.main()
