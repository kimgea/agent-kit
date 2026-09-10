import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "project-eval" / "scripts" / "project_eval.py"


def load_module():
    spec = importlib.util.spec_from_file_location("project_eval_workflow_tests", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


project_eval = load_module()


def case(case_id, kind, fixture, assertion_ids):
    return {
        "case_id": case_id,
        "title": case_id.replace("-", " ").title(),
        "kind": kind,
        "importance": "required" if kind == "implementation" else "important",
        "fixture": fixture,
        "task": f"Complete {case_id} and write the requested repository artifact.",
        "coverage": "development",
        "platforms": ["linux", "windows", "macos"],
        "required_capabilities": [],
        "assertion_ids": assertion_ids,
    }


def control(case_id, assertions):
    return {
        "schema_version": "project-eval-case-control/v1",
        "case_id": case_id,
        "materialization": {
            "mode": "copy",
            "source": "visible",
            "remove_paths": [],
            "history": [],
        },
        "assertions": assertions,
        "checks": [],
        "hidden_grader": None,
        "trajectory": None,
        "reconstruction": None,
    }


class ProfileWorkflowTests(unittest.TestCase):
    def make_repository(self, root, *, repetitions=1):
        repository = root / "repo"
        eval_root = repository / "evals" / "project"
        explanation = case(
            "explain-parser", "explanation", "fixtures/explain-parser", ["answer-contract"]
        )
        implementation = case(
            "implement-parser", "implementation", "fixtures/implement-parser", ["code-contract"]
        )
        suite = {
            "schema_version": "project-eval-suite/v1",
            "suite_id": "workflow-proof",
            "title": "Workflow proof",
            "cases": [explanation, implementation],
            "profiles": {
                "smoke": {
                    "case_ids": ["explain-parser", "implement-parser"],
                    "repetitions": repetitions,
                    "max_invocations": 2 * repetitions,
                    "max_seconds": 60,
                    "max_tokens": None,
                    "max_cost_usd": None,
                    "network": False,
                    "effects": ["workspace_edit"],
                }
            },
        }
        eval_root.mkdir(parents=True)
        (eval_root / "suite.json").write_text(json.dumps(suite), encoding="utf-8")
        fixtures = {
            "explain-parser": (
                control(
                    "explain-parser",
                    [
                        {
                            "assertion_id": "answer-contract",
                            "kind": "file_contains",
                            "path": "answer.md",
                            "expected": "rejects empty names",
                        }
                    ],
                ),
                {"answer.md": "TODO\n", "parser.py": "def parse(name):\n    return name.strip()\n"},
            ),
            "implement-parser": (
                control(
                    "implement-parser",
                    [
                        {
                            "assertion_id": "code-contract",
                            "kind": "file_contains",
                            "path": "parser.py",
                            "expected": "raise ValueError",
                        }
                    ],
                ),
                {"parser.py": "def parse(name):\n    return name.strip()\n"},
            ),
        }
        for case_id, (case_control, visible) in fixtures.items():
            fixture = eval_root / "fixtures" / case_id
            (fixture / "visible").mkdir(parents=True)
            (fixture / "control.json").write_text(json.dumps(case_control), encoding="utf-8")
            for relative, content in visible.items():
                (fixture / "visible" / relative).write_text(content, encoding="utf-8")
        return repository

    def fake_attempt(self, fixture, selected, prepared, profile, task, host_root, model, reasoning, ledger, **kwargs):
        workspace = Path(prepared["workspace"])
        if selected["case_id"] == "explain-parser":
            (workspace / "answer.md").write_text("The parser rejects empty names.\n", encoding="utf-8")
        else:
            (workspace / "parser.py").write_text(
                "def parse(name):\n    if not name.strip():\n        raise ValueError('empty')\n    return name.strip()\n",
                encoding="utf-8",
            )
        timeout = ledger.claim()
        self.assertGreater(timeout, 0)
        ledger.record(duration_ms=10, tokens=20, cost_usd=None)
        configuration = {
            "environment_sha256": "1" * 64,
            "instructions_sha256": ("2" if selected["case_id"] == "explain-parser" else "3") * 64,
        }
        return {
            "status": "completed",
            "duration_ms": {"value": 10, "provenance": "host_observed"},
            "tokens": {"value": 20, "provenance": "runner_reported"},
            "configuration": configuration,
            "attempt_sha256": project_eval._sha(
                project_eval._canonical_bytes({"case": selected["case_id"], "count": ledger.invocations})
            ),
            "unobservable_budgets": [],
        }

    def test_profile_runs_fresh_cases_and_returns_canonical_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self.make_repository(root)
            runner = {"version": "0.150.1", "identity_sha256": "4" * 64}
            with mock.patch.object(project_eval._CODEX_RUNNER, "run_codex_attempt", side_effect=self.fake_attempt):
                result = project_eval.run_codex_profile(
                    repository,
                    "evals/project",
                    "suite.json",
                    "smoke",
                    "gpt-5.6-sol",
                    "medium",
                    root / "workspaces",
                    root / "host",
                    set(),
                    runner=runner,
                )
            self.assertEqual(result["completion"], "complete")
            self.assertEqual(result["outcome"], "pass")
            self.assertEqual(result["summary"]["passed_cases"], 2)
            self.assertEqual(result["summary"]["stability"], "single_observation")
            self.assertEqual(result["summary"]["tokens"], {"value": 40, "provenance": "runner_reported"})
            self.assertEqual(list((root / "workspaces").glob("case-*")), [])
            self.assertIn("does not establish stability", result["limitations"][0]["message"])
            project_eval.validate_run_result(result)
            state_root = root / "state"
            project_eval.state_init(repository, state_root, None)
            digest = project_eval._store_local_result(repository, state_root, result)
            index = project_eval.state_index(repository, state_root)
            self.assertEqual(index["receipts"][0]["result_sha256"], digest)
            try:
                import jsonschema
            except ImportError:
                pass
            else:
                schema = json.loads(
                    (ROOT / "skills/project-eval/references/project-eval-run-result.schema.json").read_text(encoding="utf-8")
                )
                self.assertTrue(jsonschema.Draft202012Validator(schema).is_valid(result))

    def test_repetitions_are_fresh_and_support_stability_label(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self.make_repository(root, repetitions=2)
            runner = {"version": "0.150.1", "identity_sha256": "4" * 64}
            with mock.patch.object(project_eval._CODEX_RUNNER, "run_codex_attempt", side_effect=self.fake_attempt):
                result = project_eval.run_codex_profile(
                    repository, "evals/project", "suite.json", "smoke", "gpt-5.6-sol", "medium",
                    root / "workspaces", root / "host", set(), runner=runner,
                )
            self.assertEqual(result["summary"]["total_repetitions"], 4)
            self.assertEqual(result["summary"]["stability"], "repeated_observations")
            self.assertEqual(result["limitations"], [])
            self.assertTrue(all(len(item["observation_sha256s"]) == 2 for item in result["cases"]))

    def test_forbidden_effect_is_a_hard_gate_even_when_grader_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self.make_repository(root)
            runner = {"version": "0.150.1", "identity_sha256": "4" * 64}

            def violating(*args, **kwargs):
                attempt = self.fake_attempt(*args, **kwargs)
                attempt["status"] = "failed"
                attempt["error_category"] = "effect_violation"
                attempt["attempt_sha256"] = project_eval._sha(project_eval._canonical_bytes(attempt))
                return attempt

            with mock.patch.object(project_eval._CODEX_RUNNER, "run_codex_attempt", side_effect=violating):
                result = project_eval.run_codex_profile(
                    repository, "evals/project", "suite.json", "smoke", "gpt-5.6-sol", "medium",
                    root / "workspaces", root / "host", set(), runner=runner,
                )
            self.assertEqual(result["completion"], "complete")
            self.assertEqual(result["outcome"], "fail")
            self.assertEqual(result["summary"]["forbidden_effect_failures"], 2)
            self.assertTrue(all(item["status"] == "failed" for item in result["cases"]))
            self.assertTrue(all(any(evidence["evidence_id"] == "attempts" for evidence in item["evidence"]) for item in result["cases"]))

    def test_profile_preflights_every_fixture_before_first_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self.make_repository(root)
            (repository / "evals/project/fixtures/implement-parser/control.json").write_text("{}", encoding="utf-8")
            with mock.patch.object(project_eval._CODEX_RUNNER, "run_codex_attempt") as attempt:
                with self.assertRaises(project_eval.CaseError):
                    project_eval.run_codex_profile(
                        repository, "evals/project", "suite.json", "smoke", "gpt-5.6-sol", "medium",
                        root / "workspaces", root / "host", set(),
                        runner={"version": "0.150.1", "identity_sha256": "4" * 64},
                    )
            attempt.assert_not_called()

    def test_profile_rejects_unselected_grader_command_effect_before_runner_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self.make_repository(root)
            with mock.patch.object(project_eval._CODEX_RUNNER, "discover_codex") as discover:
                with self.assertRaisesRegex(
                    project_eval.EvalError, "require command_execution"
                ):
                    project_eval.run_codex_profile(
                        repository,
                        "evals/project",
                        "suite.json",
                        "smoke",
                        "gpt-5.6-sol",
                        "medium",
                        root / "workspaces",
                        root / "host",
                        set(),
                        allow_project_checks=True,
                    )
            discover.assert_not_called()

    def test_profile_rejects_suite_or_fixture_drift_after_attempts(self):
        for drift_kind in ("suite", "fixture"):
            with self.subTest(drift_kind=drift_kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                repository = self.make_repository(root)
                suite_path = repository / "evals/project/suite.json"
                fixture_path = repository / "evals/project/fixtures/implement-parser/visible/parser.py"
                mutated = False

                def drifting_attempt(*args, **kwargs):
                    nonlocal mutated
                    attempt = self.fake_attempt(*args, **kwargs)
                    if not mutated:
                        path = suite_path if drift_kind == "suite" else fixture_path
                        path.write_bytes(path.read_bytes() + b"\n")
                        mutated = True
                    return attempt

                with mock.patch.object(
                    project_eval._CODEX_RUNNER,
                    "run_codex_attempt",
                    side_effect=drifting_attempt,
                ):
                    with self.assertRaisesRegex(project_eval.EvalError, "changed during"):
                        project_eval.run_codex_profile(
                            repository,
                            "evals/project",
                            "suite.json",
                            "smoke",
                            "gpt-5.6-sol",
                            "medium",
                            root / "workspaces",
                            root / "host",
                            set(),
                            runner={"version": "0.150.1", "identity_sha256": "4" * 64},
                        )
                self.assertEqual(list((root / "workspaces").glob("case-*")), [])

    def test_compare_requires_exact_conditions_and_preserves_tradeoffs(self):
        baseline = copy.deepcopy(__import__("tests.test_project_eval", fromlist=["result"]).result())
        candidate = copy.deepcopy(baseline)
        candidate["run_id"] = "run-002"
        candidate["cases"][0]["duration_ms"] = 8
        candidate["summary"]["duration_ms"] = 8
        single = project_eval.compare_runs(baseline, candidate)
        self.assertEqual(single["outcome"], "inconclusive")
        self.assertTrue(any(item["code"] == "insufficient-stability" for item in single["limitations"]))
        self.assertFalse(single["dimensions"]["duration_ms"]["eligible"])
        self.assertIn("single_observation", project_eval.render_run(baseline))

        for run in (baseline, candidate):
            run["cases"][0]["stability"] = "repeated_observations"
            run["cases"][0]["repetitions"] = 2
            run["cases"][0]["passed"] = 2
            run["cases"][0]["duration_ms"] *= 2
            run["cases"][0]["observation_sha256s"] = ["7" * 64, "8" * 64]
            run["summary"]["total_repetitions"] = 2
            run["summary"]["passed_repetitions"] = 2
            run["summary"]["duration_ms"] = run["cases"][0]["duration_ms"]
            run["summary"]["stability"] = "repeated_observations"
        comparison = project_eval.compare_runs(baseline, candidate)
        self.assertEqual(comparison["outcome"], "candidate_better")
        self.assertTrue(comparison["dimensions"]["duration_ms"]["eligible"])
        self.assertEqual(comparison["limitations"], [])

        forged = copy.deepcopy(comparison)
        forged["outcome"] = "baseline_better"
        with self.assertRaisesRegex(project_eval.EvalError, "outcome does not match"):
            project_eval.validate_comparison(forged)

        completion_baseline = copy.deepcopy(baseline)
        completion_candidate = copy.deepcopy(candidate)
        for run in (completion_baseline, completion_candidate):
            run["cases"][0]["importance"] = "standard"
        completion_candidate["run_id"] = "run-completion-regression"
        completion_candidate["cases"][0].update(
            {"status": "failed", "last_observation": "failed", "passed": 1, "failed": 1, "duration_ms": 1}
        )
        completion_candidate["cases"][0]["evidence"][0]["status"] = "fail"
        completion_candidate["summary"] = project_eval._run_summary(
            completion_candidate["cases"]
        )
        completion_candidate["outcome"] = "fail"
        completion_candidate["next_action"] = "triage"
        completion_ordered = project_eval.compare_runs(
            completion_baseline, completion_candidate
        )
        self.assertEqual(completion_ordered["outcome"], "baseline_better")
        self.assertTrue(completion_ordered["dimensions"]["completion"]["eligible"])
        self.assertFalse(completion_ordered["dimensions"]["duration_ms"]["eligible"])

        important_baseline = copy.deepcopy(completion_baseline)
        important_candidate = copy.deepcopy(completion_baseline)
        for run in (important_baseline, important_candidate):
            important_case = copy.deepcopy(run["cases"][0])
            important_case["case_id"] = "important-case"
            important_case["importance"] = "important"
            standard_case = copy.deepcopy(run["cases"][0])
            standard_case["case_id"] = "standard-case"
            run["cases"] = [important_case, standard_case]
            run["outcome"] = "fail"
            run["next_action"] = "triage"
        important_baseline["cases"][1].update(
            {"status": "failed", "last_observation": "failed", "passed": 1, "failed": 1, "duration_ms": 1000}
        )
        important_candidate["run_id"] = "run-important-regression"
        important_candidate["cases"][0].update(
            {"status": "failed", "last_observation": "failed", "passed": 1, "failed": 1, "duration_ms": 1}
        )
        important_candidate["cases"][1]["duration_ms"] = 1
        for run in (important_baseline, important_candidate):
            run["summary"] = project_eval._run_summary(run["cases"])
            project_eval.validate_run_result(run)
        important_ordered = project_eval.compare_runs(
            important_baseline, important_candidate
        )
        self.assertEqual(important_ordered["outcome"], "baseline_better")
        self.assertTrue(important_ordered["dimensions"]["important"]["eligible"])
        self.assertFalse(important_ordered["dimensions"]["duration_ms"]["eligible"])

        mismatched = copy.deepcopy(candidate)
        mismatched["configuration"]["model"] = "other-model"
        unsigned = dict(mismatched["configuration"])
        unsigned.pop("configuration_sha256")
        mismatched["configuration"]["configuration_sha256"] = project_eval._object_digest(unsigned)
        incompatible = project_eval.compare_runs(baseline, mismatched)
        self.assertEqual(incompatible["outcome"], "incompatible")
        self.assertEqual(incompatible["mismatches"], ["configuration"])

    def test_comparison_schema_matches_runtime(self):
        schema = json.loads(
            (ROOT / "skills/project-eval/references/project-eval-comparison.schema.json").read_text(encoding="utf-8")
        )
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema unavailable")
        jsonschema.Draft202012Validator.check_schema(schema)
        sample = copy.deepcopy(__import__("tests.test_project_eval", fromlist=["result"]).result())
        self.assertTrue(jsonschema.Draft202012Validator(schema).is_valid(project_eval.compare_runs(sample, sample)))

    def test_committed_vertical_slice_suite_and_hidden_controls_validate(self):
        suite, _, _ = project_eval.load_repository_suite(
            ROOT, "evals/project", "suite.json"
        )
        self.assertEqual(
            [item["kind"] for item in suite["cases"]],
            ["explanation", "implementation", "explanation"],
        )
        self.assertEqual(
            suite["profiles"]["operator-smoke"],
            {
                "case_ids": ["plan-local-project-eval"],
                "repetitions": 1,
                "max_invocations": 1,
                "max_seconds": 120,
                "max_tokens": None,
                "max_cost_usd": None,
                "network": False,
                "effects": ["workspace_edit", "command_execution"],
            },
        )
        for case_id in (
            "explain-route-manifest",
            "implement-route-lookup",
            "plan-local-project-eval",
        ):
            _, selected, _, fixture = project_eval._case_components(
                ROOT, "evals/project", "suite.json", case_id
            )
            project_eval._CASE_ENGINE.validate_case_fixture(fixture, selected)

    def test_operator_case_distinguishes_safe_and_broad_private_root_plans(self):
        _, selected, _, fixture = project_eval._case_components(
            ROOT, "evals/project", "suite.json", "plan-local-project-eval"
        )
        with tempfile.TemporaryDirectory() as temporary:
            prepared = project_eval._CASE_ENGINE.materialize_case(
                fixture, selected, Path(temporary) / "workspaces"
            )
            workspace = Path(prepared["workspace"])
            unsafe = {
                "adoption_preflight": "readiness",
                "missing_suite_action": "preview_bootstrap",
                "bootstrap_apply_authority": "explicit_apply_and_yes",
                "instruction_adoption": "separate_deliberate_change",
                "model_execution": "explicit_run_only",
                "preflight": "validate_suite",
                "profile": "smoke",
                "private_roots": "precreate_default_permissions",
                "allow_project_checks": True,
                "allow_network": False,
                "allow_hidden_grader": False,
                "store": False,
                "validate_receipt": True,
                "confirm_disposable_contents_removed": True,
                "confirm_repository_clean": True,
            }
            (workspace / "run-plan.json").write_text(
                json.dumps(unsafe), encoding="utf-8"
            )
            self.assertEqual(
                project_eval._CASE_ENGINE.grade_case(
                    fixture, selected, prepared
                )["status"],
                "failed",
            )
            safe = dict(unsafe)
            safe["private_roots"] = "runner_creates_absent_roots"
            (workspace / "run-plan.json").write_text(
                json.dumps(safe), encoding="utf-8"
            )
            self.assertEqual(
                project_eval._CASE_ENGINE.grade_case(
                    fixture, selected, prepared
                )["status"],
                "passed",
            )


if __name__ == "__main__":
    unittest.main()
