import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


behavioral_eval = load_module(
    "behavioral_eval", ROOT / "scripts" / "behavioral_eval.py"
)
guidance_result = load_module(
    "behavioral_eval_guidance_result",
    ROOT / "skills" / "review-guidance-audit" / "scripts" / "guidance_result.py",
)


def complete_result(context):
    inspected = [
        item["path"]
        for item in context["target"]["files"]
        if item["inspection_kind"] == "text"
    ]
    excluded = [
        {
            "path": item["path"],
            "reason": f"The resolver classified this target as {item['inspection_kind']}.",
            "material": True,
        }
        for item in context["target"]["files"]
        if item["inspection_kind"] != "text"
    ]
    return guidance_result.finalize(
        context,
        {
            "summary": {"conclusion": "The existing guidance is relevant and concise."},
            "coverage": {
                "complete": not excluded,
                "inspected_paths": inspected,
                "excluded": excluded,
                "context_paths": [],
            },
            "recommendations": [],
            "limitations": [],
        },
    )


class SuiteValidationTests(unittest.TestCase):
    def test_repository_suite_is_valid_and_model_free_to_check(self):
        with mock.patch.object(
            behavioral_eval, "_run_codex", side_effect=AssertionError("model invoked")
        ):
            suite = behavioral_eval.load_suite(ROOT, "review-guidance-audit")
            self.assertEqual(16, len(suite["cases"]))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = behavioral_eval.command_check(
                    argparse.Namespace(suite="review-guidance-audit", root=str(ROOT))
                )
            self.assertEqual(0, result)
            self.assertIn("16 cases", output.getvalue())

    def test_duplicate_json_members_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "value.json"
            path.write_bytes(b'{"status":1,"status":2}')
            with self.assertRaisesRegex(behavioral_eval.EvalError, "duplicate JSON"):
                behavioral_eval._load_json(path, "test value")

    def test_fixture_links_and_oversized_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "fixture"
            root.mkdir()
            target = root / "target.txt"
            target.write_text("safe", encoding="utf-8")
            link = root / "link.txt"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            with self.assertRaisesRegex(behavioral_eval.EvalError, "link-like"):
                behavioral_eval.snapshot_fixture(root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "fixture"
            root.mkdir()
            path = root / "large.bin"
            path.write_bytes(b"x" * (behavioral_eval.MAX_FIXTURE_FILE_BYTES + 1))
            with self.assertRaisesRegex(behavioral_eval.EvalError, "exceeds"):
                behavioral_eval.snapshot_fixture(root)

    def test_materialization_preserves_content_and_detects_mutation(self):
        source = (
            ROOT
            / "evals"
            / "review-guidance-audit"
            / "fixtures"
            / "json-consumer-output"
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "fixture"
            before = behavioral_eval.materialize_fixture(source, destination)
            unchanged = behavioral_eval.snapshot_fixture(destination)
            self.assertEqual(
                behavioral_eval._snapshot_identity(before),
                behavioral_eval._snapshot_identity(unchanged),
            )
            (destination / "src" / "value.py").write_text("changed", encoding="utf-8")
            changed = behavioral_eval.snapshot_fixture(destination)
            self.assertNotEqual(
                behavioral_eval._snapshot_identity(before),
                behavioral_eval._snapshot_identity(changed),
            )


class AssertionTests(unittest.TestCase):
    def assertion(self, operator, path, value):
        return {"id": "example", "operator": operator, "path": path, "value": value}

    def test_wildcard_partial_and_negative_assertions(self):
        result = {
            "recommendations": [
                {"action": "rewrite", "harness": [{"relationship": "support"}]},
                {"action": "move", "destination": {"path": "nested/REVIEW.md"}},
            ]
        }
        self.assertTrue(
            behavioral_eval.evaluate_assertion(
                result,
                self.assertion("any", "/recommendations/*", {"action": "move"}),
            )["passed"]
        )
        self.assertTrue(
            behavioral_eval.evaluate_assertion(
                result,
                self.assertion("none", "/recommendations/*", {"action": "remove"}),
            )["passed"]
        )
        self.assertTrue(
            behavioral_eval.evaluate_assertion(
                result,
                self.assertion(
                    "any",
                    "/recommendations/*",
                    {"harness": [{"relationship": "support"}]},
                ),
            )["passed"]
        )

    def test_sequence_and_count_assertions(self):
        result = {"paths": ["skill", "REVIEW.md", "src/REVIEW.md"]}
        self.assertTrue(
            behavioral_eval.evaluate_assertion(
                result,
                self.assertion(
                    "sequence", "/paths/*", ["REVIEW.md", "src/REVIEW.md"]
                ),
            )["passed"]
        )
        self.assertTrue(
            behavioral_eval.evaluate_assertion(
                result, self.assertion("count_equals", "/paths/*", 3)
            )["passed"]
        )


class RecordedGradingTests(unittest.TestCase):
    def setUp(self):
        self.suite = behavioral_eval.load_suite(ROOT, "review-guidance-audit")
        self.case = behavioral_eval._case_by_id(self.suite, "json-consumer-output")
        self.source = (
            ROOT / "evals" / "review-guidance-audit" / self.case["fixture"]
        )

    def test_recorded_result_is_bound_relocated_and_graded(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = base / "original" / "fixture"
            fixture.parent.mkdir()
            behavioral_eval.materialize_fixture(self.source, fixture)
            context_path = base / "context.json"
            context = behavioral_eval.resolve_context(
                self.suite, self.case, fixture, context_path, ROOT
            )
            result = complete_result(context)
            result_path = base / "result.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            output = base / "grade.json"
            code = behavioral_eval.command_grade(
                argparse.Namespace(
                    suite="review-guidance-audit",
                    case="json-consumer-output",
                    context=str(context_path),
                    result=str(result_path),
                    output=str(output),
                )
            )
            self.assertEqual(0, code)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["passed"])
            self.assertIsNone(report["fixture_mutation_free"])

    def test_target_rebinding_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = base / "fixture"
            behavioral_eval.materialize_fixture(self.source, fixture)
            context_path = base / "context.json"
            context = behavioral_eval.resolve_context(
                self.suite, self.case, fixture, context_path, ROOT
            )
            result = complete_result(context)
            result["target"]["requested"][0]["path"] = "other"
            bound, message = behavioral_eval._bind_result(context, result)
            self.assertFalse(bound)
            self.assertIn("target", message)

    def test_malformed_recorded_result_fails_canonical_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            path.write_text('{"schema_version":"1.0"}', encoding="utf-8")
            passed, message = behavioral_eval.validate_result_contract(
                self.suite, path, ROOT
            )
            self.assertFalse(passed)
            self.assertIn("missing", message)


class CodexRunnerTests(unittest.TestCase):
    def test_agent_prompt_uses_isolated_skill_and_hides_expectations(self):
        suite = behavioral_eval.load_suite(ROOT, "review-guidance-audit")
        case = behavioral_eval._case_by_id(suite, "slow-test-supports-rule")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            prompt = behavioral_eval._runner_prompt(
                suite,
                case,
                base / "fixture",
                base / "work",
                base / "evaluated-skill" / "review-guidance-audit",
            )
        self.assertIn("evaluated-skill/review-guidance-audit/SKILL.md", prompt)
        self.assertNotIn("suite.json", prompt)
        self.assertNotIn("default_assertions", prompt)
        self.assertNotIn("support-only", prompt)

    def test_command_is_fixed_ephemeral_and_schema_constrained(self):
        suite = behavioral_eval.load_suite(ROOT, "review-guidance-audit")
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            behavioral_eval.shutil, "which", return_value="/usr/bin/codex"
        ):
            base = Path(temporary)
            work = base / "work"
            work.mkdir()
            schema = json.loads(
                (ROOT / "evals" / "behavioral-agent-result.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            (work / "agent-result.schema.json").write_text(
                json.dumps(schema), encoding="utf-8"
            )
            command = behavioral_eval.build_codex_command(
                suite,
                base / "fixture",
                work,
                base / "result.json",
                ROOT,
                "gpt-5.6-luna",
                "medium",
            )
        self.assertEqual(["/usr/bin/codex", "exec"], command[:2])
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--approve-for-me", command)
        self.assertNotIn("--sandbox", command)
        self.assertIn("--output-schema", command)
        schema_index = command.index("--output-schema") + 1
        self.assertTrue(command[schema_index].endswith("work/agent-result.schema.json"))
        self.assertEqual("-", command[-1])
        self.assertNotIn("bash", command)

    def test_model_cannot_be_a_command_fragment(self):
        suite = behavioral_eval.load_suite(ROOT, "review-guidance-audit")
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            behavioral_eval.shutil, "which", return_value="/usr/bin/codex"
        ):
            base = Path(temporary)
            work = base / "work"
            work.mkdir()
            schema = json.loads(
                (ROOT / "evals" / "behavioral-agent-result.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            (work / "agent-result.schema.json").write_text(
                json.dumps(schema), encoding="utf-8"
            )
            with self.assertRaisesRegex(behavioral_eval.EvalError, "model id"):
                behavioral_eval.build_codex_command(
                    suite,
                    base / "fixture",
                    work,
                    base / "result.json",
                    ROOT,
                    "model; touch owned",
                    "medium",
                )

    def test_command_events_are_detected_without_scanning_prompt_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "./scripts/expensive-check",
                        },
                        "prompt": "Do not run expensive-check",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                ["./scripts/expensive-check"],
                behavioral_eval._parse_event_commands(path),
            )

    def test_forbidden_execution_distinguishes_reading_from_running(self):
        forbidden = ["scripts/expensive-check"]
        commands = [
            "cat /tmp/fixture/scripts/expensive-check",
            "rg marker /tmp/fixture/scripts/expensive-check",
        ]
        self.assertEqual(
            [], behavioral_eval._forbidden_command_hits(commands, forbidden)
        )
        self.assertEqual(
            forbidden,
            behavioral_eval._forbidden_command_hits(
                ["./scripts/expensive-check"], forbidden
            ),
        )
        self.assertEqual(
            forbidden,
            behavioral_eval._forbidden_command_hits(
                ["/bin/bash -lc './scripts/expensive-check'"], forbidden
            ),
        )

    def test_failed_event_is_summarized_without_retaining_the_stream(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "type": "turn.failed",
                        "error": {"message": "structured output schema was rejected"},
                        "unrelated": "do not retain this",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            summary = behavioral_eval._event_error_summary(path)
            self.assertEqual("structured output schema was rejected", summary)
            self.assertNotIn("unrelated", summary)

    def test_workflows_do_not_invoke_paid_behavioral_runs(self):
        for path in (ROOT / ".github" / "workflows").glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("behavioral_eval.py run", text)
            self.assertNotIn("--runner codex", text)

    def test_timeout_kills_the_local_runner(self):
        suite = behavioral_eval.load_suite(ROOT, "review-guidance-audit")
        case = behavioral_eval._case_by_id(suite, "json-consumer-output")
        process = mock.MagicMock()
        process.communicate.side_effect = [
            behavioral_eval.subprocess.TimeoutExpired("codex", 1),
            (b"", b""),
        ]
        process.returncode = -9
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            behavioral_eval, "build_codex_command", return_value=["codex", "exec"]
        ), mock.patch.object(behavioral_eval.subprocess, "Popen", return_value=process):
            base = Path(temporary)
            fixture = base / "fixture"
            work = base / "work"
            fixture.mkdir()
            work.mkdir()
            outcome = behavioral_eval._run_codex(
                suite,
                case,
                fixture,
                work,
                work / "result.json",
                work / "events.jsonl",
                work / "stderr.txt",
                ROOT,
                ROOT / "skills" / "review-guidance-audit",
                "gpt-5.6-luna",
                "medium",
                1,
            )
        self.assertTrue(outcome["timed_out"])
        process.kill.assert_called_once_with()

    def test_simulated_run_produces_local_evidence_without_invoking_codex(self):
        def fake_run(
            suite,
            case,
            fixture,
            work,
            result,
            events,
            errors,
            root,
            runtime_skill,
            model,
            reasoning_effort,
            timeout,
        ):
            context = json.loads((work / "context.json").read_text(encoding="utf-8"))
            result.write_text(
                json.dumps({"result_json": json.dumps(complete_result(context))}),
                encoding="utf-8",
            )
            events.write_text("", encoding="utf-8")
            errors.write_text("", encoding="utf-8")
            return {
                "exit_code": 0,
                "timed_out": False,
                "started_at": "2026-08-30T20:00:00+00:00",
                "finished_at": "2026-08-30T20:00:01+00:00",
                "duration_seconds": 1.0,
            }

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fake_codex = base / "codex"
            fake_codex.write_text("#!/bin/sh\nprintf 'codex-cli test\\n'\n", encoding="utf-8")
            os.chmod(fake_codex, 0o700)
            output = base / "results"
            output.mkdir()
            args = argparse.Namespace(
                suite="review-guidance-audit",
                runner="codex",
                case=["json-consumer-output"],
                model="gpt-5.6-luna",
                reasoning_effort="medium",
                timeout=30,
                output_dir=str(output),
            )
            printed = io.StringIO()
            progress = io.StringIO()
            with mock.patch.object(behavioral_eval, "_run_codex", side_effect=fake_run), mock.patch.object(
                behavioral_eval.shutil, "which", return_value=str(fake_codex)
            ), contextlib.redirect_stdout(printed), contextlib.redirect_stderr(progress):
                code = behavioral_eval.command_run(args)
            self.assertEqual(0, code)
            summary = json.loads(printed.getvalue())
            self.assertEqual(1, summary["passed"])
            self.assertEqual(
                "[1/1] json-consumer-output: running\n"
                "[1/1] json-consumer-output: passed\n",
                progress.getvalue(),
            )
            run_directory = Path(summary["output_directory"])
            self.assertTrue((run_directory / "summary.json").is_file())
            self.assertFalse((run_directory / "cases" / "json-consumer-output" / "events.jsonl").exists())

    def test_simulated_agent_mutation_fails_the_case(self):
        def mutating_run(
            suite,
            case,
            fixture,
            work,
            result,
            events,
            errors,
            root,
            runtime_skill,
            model,
            reasoning_effort,
            timeout,
        ):
            context = json.loads((work / "context.json").read_text(encoding="utf-8"))
            result.write_text(
                json.dumps({"result_json": json.dumps(complete_result(context))}),
                encoding="utf-8",
            )
            (fixture / "src" / "value.py").write_text("mutated", encoding="utf-8")
            events.write_text("", encoding="utf-8")
            errors.write_text("", encoding="utf-8")
            return {
                "exit_code": 0,
                "timed_out": False,
                "started_at": "2026-08-30T20:00:00+00:00",
                "finished_at": "2026-08-30T20:00:01+00:00",
                "duration_seconds": 1.0,
            }

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fake_codex = base / "codex"
            fake_codex.write_text("#!/bin/sh\nprintf 'codex-cli test\\n'\n", encoding="utf-8")
            os.chmod(fake_codex, 0o700)
            output = base / "results"
            output.mkdir()
            args = argparse.Namespace(
                suite="review-guidance-audit",
                runner="codex",
                case=["json-consumer-output"],
                model="gpt-5.6-luna",
                reasoning_effort="medium",
                timeout=30,
                output_dir=str(output),
            )
            printed = io.StringIO()
            progress = io.StringIO()
            with mock.patch.object(behavioral_eval, "_run_codex", side_effect=mutating_run), mock.patch.object(
                behavioral_eval.shutil, "which", return_value=str(fake_codex)
            ), contextlib.redirect_stdout(printed), contextlib.redirect_stderr(progress):
                code = behavioral_eval.command_run(args)
            self.assertEqual(1, code)
            self.assertIn("json-consumer-output: failed", progress.getvalue())
            summary = json.loads(printed.getvalue())
            score = json.loads(
                (
                    Path(summary["output_directory"])
                    / "cases"
                    / "json-consumer-output"
                    / "score.json"
                ).read_text(encoding="utf-8")
            )
            self.assertFalse(score["passed"])
            self.assertFalse(score["fixture_mutation_free"])

    def test_output_refuses_a_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            real = base / "real"
            real.mkdir()
            link = base / "link"
            try:
                link.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            with self.assertRaisesRegex(behavioral_eval.EvalError, "link-like"):
                behavioral_eval._write_new_json(link / "result.json", {"ok": True})


if __name__ == "__main__":
    unittest.main()
