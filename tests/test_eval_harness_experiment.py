import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "eval-harness-experiment"
SCRIPT = SKILL / "scripts" / "experiment.py"
PROJECT_EVAL_SCRIPT = ROOT / "skills" / "project-eval" / "scripts" / "project_eval.py"


def load_module(path: Path, name: str):
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


experiment = load_module(SCRIPT, "eval_harness_experiment_under_test")
project_eval = load_module(PROJECT_EVAL_SCRIPT, "project_eval_for_experiment_test")


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


class EvalHarnessExperimentTests(unittest.TestCase):
    suite_sha = "1" * 64
    suite_id = "harness-suite"

    def repository(self, root: Path):
        (root / "AGENTS.md").write_text("Use the existing harness.\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
        subprocess.run(["git", "add", "AGENTS.md"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
        surface = experiment._committed_surface(root, "AGENTS.md")
        return head, experiment._repository_binding(head, [surface]), surface

    def configuration(self, instructions="2" * 64):
        value = {
            "runner": "codex-cli",
            "runner_version": "0.150.1",
            "agent": "codex",
            "model": "gpt-5.6-sol",
            "reasoning": "medium",
            "platform": "linux",
            "environment_sha256": "3" * 64,
            "adapter_sha256": "4" * 64,
            "launcher_sha256": "5" * 64,
            "instructions_sha256": instructions,
            "profile_sha256": "6" * 64,
        }
        value["configuration_sha256"] = sha(canonical(value))
        return value

    def run_result(self, run_id, durations, *, instructions="2" * 64, target_repository="7" * 64, failures=None, effects=None, repetitions=3, tokens=300):
        failures = failures or {}
        effects = effects or {}
        cases = []
        for case_id, importance, duration in zip(("development", "holdout", "regression"), ("required", "standard", "important"), durations):
            failed = failures.get(case_id, 0)
            passed = repetitions - failed
            status = "passed" if not failed else "failed"
            case_tokens = tokens // 3
            cases.append({
                "case_id": case_id,
                "importance": importance,
                "status": status,
                "last_observation": status,
                "stability": "repeated_observations",
                "repetitions": repetitions,
                "passed": passed,
                "failed": failed,
                "forbidden_effect_failures": effects.get(case_id, 0),
                "duration_ms": duration,
                "tokens": {"value": case_tokens, "provenance": "host_observed"},
                "target_sha256": sha(f"target:{run_id}:{case_id}".encode()),
                "grader_sha256": sha(f"grader:{case_id}".encode()),
                "observation_sha256s": [sha(f"{run_id}:{case_id}:{index}".encode()) for index in range(repetitions)],
                "evidence": [],
                "limitations": [],
            })
        required_failed = int(cases[0]["status"] != "passed")
        result = {
            "schema_version": "project-eval-run-result/v1",
            "run_id": run_id,
            "producer": {"name": "project-eval", "version": "1.1.0"},
            "suite": {"suite_id": self.suite_id, "suite_sha256": self.suite_sha, "profile": "compare"},
            "source": {"kind": "local", "authority": "evidence_only", "bundle_sha256": None},
            "target": {"repository_sha256": target_repository, "definition_sha256": "8" * 64, "fixture_set_sha256": "9" * 64, "revision": None},
            "configuration": self.configuration(instructions),
            "completion": "complete",
            "outcome": "fail" if required_failed else "pass",
            "next_action": "triage" if required_failed else "none",
            "cases": cases,
            "summary": {
                "total_cases": 3,
                "passed_cases": sum(item["status"] == "passed" for item in cases),
                "failed_cases": sum(item["status"] == "failed" for item in cases),
                "unavailable_cases": 0,
                "total_repetitions": repetitions * 3,
                "passed_repetitions": sum(item["passed"] for item in cases),
                "failed_repetitions": sum(item["failed"] for item in cases),
                "required_failures": required_failed,
                "important_failures": int(cases[2]["status"] != "passed"),
                "forbidden_effect_failures": sum(item["forbidden_effect_failures"] for item in cases),
                "last_observation": cases[-1]["last_observation"],
                "stability": "repeated_observations",
                "duration_ms": sum(durations),
                "tokens": {"value": sum(item["tokens"]["value"] for item in cases), "provenance": "host_observed"},
            },
            "limitations": [],
        }
        experiment.evidence_contracts.validate_project_eval_run(result)
        return result

    def request(self, repository_sha, candidates, *, objective=None, budget=None, no_progress=3):
        return {
            "schema_version": "eval-harness-experiment-request/v1",
            "experiment_id": "instruction-tuning",
            "objective": objective or {"metric": "time", "direction": "decrease", "tolerance": 0.01, "target": None},
            "editable_surfaces": ["AGENTS.md"],
            "suites": [{
                "suite_id": self.suite_id,
                "suite_sha256": self.suite_sha,
                "development_case_ids": ["development"],
                "holdout_case_ids": ["holdout"],
                "regression_case_ids": ["regression"],
            }],
            "profile": "compare",
            "runner": {key: value for key, value in self.configuration().items() if key not in {"instructions_sha256", "configuration_sha256"}},
            "requirements": {"minimum_repetitions": 3, "no_progress_limit": no_progress},
            "guardrail_tolerances": {"correctness": 0, "completion": 0, "time": 0, "tokens": 0, "cost": 0},
            "budget": budget or {"max_candidates": len(candidates), "max_run_receipts": 1 + len(candidates), "max_seconds": 100, "max_tokens": 100000, "max_cost_usd": None},
            "baseline": {"runs": [{"suite_id": self.suite_id, "path": "baseline.json"}], "cost_usd": {"value": None, "provenance": "unavailable"}},
            "candidates": [{"candidate_id": item, "variant_path": f"{item}.variant.json", "runs": [{"suite_id": self.suite_id, "path": f"{item}.json"}], "cost_usd": {"value": None, "provenance": "unavailable"}} for item in candidates],
        }

    def arrange(self, directory: Path, candidate_runs, *, objective=None, budget=None, no_progress=3):
        repo = directory / "repo"
        inputs = directory / "inputs"
        repo.mkdir()
        inputs.mkdir()
        head, repository_sha, surface = self.repository(repo)
        (inputs / "baseline.json").write_text(json.dumps(self.run_result("baseline", [3000, 3000, 3000])), encoding="utf-8")
        for candidate_id, run in candidate_runs.items():
            variant = {
                "schema_version": "eval-harness-variant/v1",
                "candidate_id": candidate_id,
                "base_revision": head,
                "base_repository_sha256": repository_sha,
                "editable_surfaces": [{key: surface[key] for key in ("path", "sha256", "mode")}],
                "rationale": f"Try the bounded {candidate_id} instruction variant.",
                "edits": [{"path": "AGENTS.md", "before_sha256": surface["sha256"], "after_text": f"Use the {candidate_id} harness.\n"}],
            }
            (inputs / f"{candidate_id}.variant.json").write_text(json.dumps(variant), encoding="utf-8")
            patch = experiment._validate_variant(
                variant,
                candidate_id,
                head,
                repository_sha,
                {surface["path"]: surface},
            )
            binding = {
                "schema_version": "project-eval-experiment-binding/v1",
                "producer": {"name": "project-eval", "version": "1.2.0"},
                "candidate_id": candidate_id,
                "base_revision": head,
                "base_repository_sha256": repository_sha,
                "patch_sha256": patch["patch_sha256"],
                "variant_sha256": sha(canonical(variant)),
                "run_result_sha256": sha(canonical(run)),
                "run_result": run,
            }
            (inputs / f"{candidate_id}.json").write_text(json.dumps(binding), encoding="utf-8")
        request = self.request(repository_sha, list(candidate_runs), objective=objective, budget=budget, no_progress=no_progress)
        request_path = directory / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return repo, inputs, request_path

    def resolve_and_evaluate(self, directory: Path, candidate_runs, **kwargs):
        repo, inputs, request = self.arrange(directory, candidate_runs, **kwargs)
        context = experiment.resolve_context(repo, request, inputs)
        return repo, inputs, request, context, experiment.evaluate(context)

    def candidate(self, run_id, durations, **kwargs):
        return self.run_result(run_id, durations, instructions=sha(run_id.encode()), target_repository=sha((run_id + "-repo").encode()), **kwargs)

    def test_clear_improvement_requires_paired_quality_and_returns_bound_patch(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, _, _, context, result = self.resolve_and_evaluate(Path(temporary), {"faster": self.candidate("faster", [2000, 2000, 2000])})
            self.assertEqual(result["outcome"], "clear_improvement")
            self.assertEqual(result["stop"]["reason"], "target_achieved")
            self.assertEqual(result["candidates"][0]["classification"], "clear_improvement")
            self.assertEqual(result["candidates"][0]["patch"]["base_repository_sha256"], context["target"]["repository_sha256"])
            self.assertEqual((repo / "AGENTS.md").read_text(), "Use the existing harness.\n")

    def test_hidden_holdout_regression_is_retained_as_tradeoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, _, _, _, result = self.resolve_and_evaluate(Path(temporary), {"overfit": self.candidate("overfit", [1000, 1000, 1000], failures={"holdout": 1})})
        item = result["candidates"][0]
        self.assertEqual(item["classification"], "tradeoff")
        self.assertTrue(item["guardrail_regression"])
        self.assertEqual(result["next_action"], "decision")

    def test_small_noisy_win_is_inconclusive(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, _, _, _, result = self.resolve_and_evaluate(Path(temporary), {"noise": self.candidate("noise", [2999, 3000, 3000])}, objective={"metric": "time", "direction": "decrease", "tolerance": 1, "target": None})
        self.assertEqual(result["candidates"][0]["classification"], "inconclusive")

    def test_cost_win_below_quality_floor_is_not_an_improvement(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, inputs, request_path = self.arrange(Path(temporary), {"cheap": self.candidate("cheap", [1000, 1000, 1000], failures={"development": 1})}, objective={"metric": "cost", "direction": "decrease", "tolerance": 0.1, "target": None})
            request = json.loads(request_path.read_text())
            request["baseline"]["cost_usd"] = {"value": 5, "provenance": "host_observed"}
            request["candidates"][0]["cost_usd"] = {"value": 1, "provenance": "host_observed"}
            request["budget"]["max_cost_usd"] = 20
            request_path.write_text(json.dumps(request), encoding="utf-8")
            result = experiment.evaluate(experiment.resolve_context(repo, request_path, inputs))
        self.assertEqual(result["candidates"][0]["classification"], "no_improvement")

    def test_forbidden_effect_and_budget_breach_stop_without_a_winner(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, _, _, _, result = self.resolve_and_evaluate(Path(temporary), {"unsafe": self.candidate("unsafe", [1000, 1000, 1000], failures={"holdout": 1}, effects={"holdout": 1})})
        self.assertEqual(result["completion"], "incomplete")
        self.assertEqual(result["stop"]["reason"], "forbidden_effect")
        self.assertTrue(result["candidates"][0]["effect_breach"])

    def test_repeated_no_progress_stops_before_later_candidates(self):
        candidates = {
            "same-one": self.candidate("same-one", [3000, 3000, 3000]),
            "same-two": self.candidate("same-two", [3000, 3000, 3000]),
            "later": self.candidate("later", [1000, 1000, 1000]),
        }
        with tempfile.TemporaryDirectory() as temporary:
            _, _, _, _, result = self.resolve_and_evaluate(Path(temporary), candidates, no_progress=2)
        self.assertEqual(result["stop"]["reason"], "no_progress")
        self.assertEqual({item["candidate_id"] for item in result["candidates"]}, {"same-one", "same-two"})

    def test_unpaired_or_reused_receipts_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, inputs, request_path = self.arrange(root, {"candidate": self.candidate("candidate", [2000, 2000, 2000])})
            request = json.loads(request_path.read_text())
            request["candidates"][0]["runs"][0]["path"] = "baseline.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            with self.assertRaisesRegex(experiment.ExperimentError, "distinct paths"):
                experiment.resolve_context(repo, request_path, inputs)

    def test_candidate_binding_rejects_a_swapped_run_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, inputs, request_path = self.arrange(
                root, {"candidate": self.candidate("candidate", [2000, 2000, 2000])}
            )
            binding_path = inputs / "candidate.json"
            binding = json.loads(binding_path.read_text(encoding="utf-8"))
            binding["run_result"] = self.candidate("unrelated", [1000, 1000, 1000])
            binding_path.write_text(json.dumps(binding), encoding="utf-8")
            with self.assertRaisesRegex(experiment.ExperimentError, "does not bind its run result"):
                experiment.resolve_context(repo, request_path, inputs)

    def test_scope_drift_and_live_mutation_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, inputs, request_path = self.arrange(root, {"candidate": self.candidate("candidate", [2000, 2000, 2000])})
            context = experiment.resolve_context(repo, request_path, inputs)
            (repo / "AGENTS.md").write_text("Drifted.\n", encoding="utf-8")
            with self.assertRaisesRegex(experiment.ExperimentError, "differs from committed"):
                experiment.evaluate(context)

    def test_materialization_cannot_hide_active_tree_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, inputs, request_path = self.arrange(root, {"candidate": self.candidate("candidate", [2000, 2000, 2000])})
            original = experiment._materialize_selected_surfaces

            def mutate(surfaces, variants, repository):
                original(surfaces, variants, repository)
                (repo / "AGENTS.md").write_text("Mutated by a hostile step.\n", encoding="utf-8")

            with mock.patch.object(experiment, "_materialize_selected_surfaces", side_effect=mutate):
                with self.assertRaisesRegex(experiment.ExperimentError, "differs from committed"):
                    experiment.resolve_context(repo, request_path, inputs)

    def test_context_bound_validation_rejects_forged_ranking(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, _, _, context, result = self.resolve_and_evaluate(Path(temporary), {"candidate": self.candidate("candidate", [2000, 2000, 2000])})
            forged = copy.deepcopy(result)
            forged["candidates"][0]["patch"]["rationale"] = "Forged rationale that was not in the selected context."
            self.assertIs(experiment.validate_result(forged), forged)
            with self.assertRaisesRegex(experiment.ExperimentError, "not deterministically derived"):
                experiment.validate_result(forged, context=context)

    def test_standalone_consumers_reject_every_forged_classification(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, _, _, _, result = self.resolve_and_evaluate(
                Path(temporary),
                {"candidate": self.candidate("candidate", [2000, 2000, 2000])},
            )
        for classification, outcome, next_action, stop_reason in (
            ("tradeoff", "tradeoff", "decision", "decision_required"),
            ("inconclusive", "inconclusive", "retry", "candidates_exhausted"),
            ("no_improvement", "no_improvement", "none", "candidates_exhausted"),
            ("incomplete", "incomplete", "manual", "candidates_exhausted"),
        ):
            with self.subTest(classification=classification):
                forged = copy.deepcopy(result)
                forged["candidates"][0]["classification"] = classification
                forged["outcome"] = outcome
                forged["next_action"] = next_action
                forged["completion"] = "incomplete" if outcome == "incomplete" else "complete"
                forged["stop"]["reason"] = stop_reason
                with self.assertRaisesRegex(experiment.ExperimentError, "classification"):
                    experiment.validate_result(forged)
                with self.assertRaisesRegex(project_eval.EvalError, "classification"):
                    project_eval.validate_artifact(forged, "experiment")

    def test_project_eval_binding_is_derived_from_the_applied_variant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, inputs, _ = self.arrange(
                root, {"candidate": self.candidate("candidate", [2000, 2000, 2000])}
            )
            variant = json.loads((inputs / "candidate.variant.json").read_text(encoding="utf-8"))
            (repo / "AGENTS.md").write_text(
                variant["edits"][0]["after_text"], encoding="utf-8"
            )
            state = project_eval._validate_experiment_variant_state(repo, variant)
            run = self.candidate("candidate", [2000, 2000, 2000])
            binding = project_eval._experiment_run_binding(state, run)
            expected_patch_sha = json.loads(
                (inputs / "candidate.json").read_text(encoding="utf-8")
            )["patch_sha256"]
        self.assertEqual(binding["patch_sha256"], expected_patch_sha)
        self.assertEqual(binding["run_result_sha256"], sha(canonical(run)))

    def test_project_eval_binding_rejects_missing_or_extra_variant_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, inputs, _ = self.arrange(
                root, {"candidate": self.candidate("candidate", [2000, 2000, 2000])}
            )
            variant = json.loads((inputs / "candidate.variant.json").read_text(encoding="utf-8"))
            with self.assertRaisesRegex(project_eval.EvalError, "selected variant"):
                project_eval._validate_experiment_variant_state(repo, variant)
            (repo / "AGENTS.md").write_text(
                variant["edits"][0]["after_text"], encoding="utf-8"
            )
            (repo / "unrelated.txt").write_text("not selected\n", encoding="utf-8")
            with self.assertRaisesRegex(project_eval.EvalError, "outside the selected variant"):
                project_eval._validate_experiment_variant_state(repo, variant)

    def test_output_is_create_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result.json"
            experiment._emit({"value": "first"}, "json", output)
            with self.assertRaises(experiment.path_safety.SafetyError):
                experiment._emit({"value": "second"}, "json", output)

    def test_cli_round_trip_and_standalone_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, inputs, request_path = self.arrange(root, {"candidate": self.candidate("candidate", [2000, 2000, 2000])})
            context_path = root / "context.json"
            result_path = root / "result.json"
            subprocess.run([sys.executable, "-E", "-S", str(SCRIPT), "resolve", "--repo", str(repo), "--request", str(request_path), "--input-root", str(inputs), "--output", str(context_path)], check=True)
            subprocess.run([sys.executable, "-E", "-S", str(SCRIPT), "evaluate", "--context", str(context_path), "--format", "json", "--output", str(result_path)], check=True)
            validated = subprocess.run([sys.executable, "-E", "-S", str(SCRIPT), "validate", "--input", str(result_path), "--context", str(context_path)], check=True, capture_output=True, text=True)
            consumed = subprocess.run([sys.executable, "-E", "-S", str(PROJECT_EVAL_SCRIPT), "validate-artifact", "--kind", "experiment", "--input", str(result_path)], check=False, capture_output=True, text=True)
        self.assertIn('"valid":true', validated.stdout)
        self.assertEqual(consumed.returncode, 0, consumed.stderr)
        self.assertIn('"valid":true', consumed.stdout)


if __name__ == "__main__":
    unittest.main()
