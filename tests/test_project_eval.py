import copy
import concurrent.futures
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "project-eval"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


project_eval = load_module("project_eval", SCRIPTS / "project_eval.py")


def suite():
    return {
        "schema_version": "project-eval-suite/v1",
        "suite_id": "sample-project",
        "title": "Sample project",
        "cases": [
            {
                "case_id": "explain-api",
                "title": "Explain the API",
                "kind": "explanation",
                "importance": "required",
                "fixture": "fixtures/explain-api",
                "task": "Explain how the API validates input.",
                "coverage": "development",
                "platforms": ["linux", "windows", "macos"],
                "required_capabilities": [],
                "assertion_ids": ["mentions-validation"],
            }
        ],
        "profiles": {
            "smoke": {
                "case_ids": ["explain-api"],
                "repetitions": 1,
                "max_invocations": 1,
                "max_seconds": 60,
                "max_tokens": None,
                "max_cost_usd": None,
                "network": False,
                "effects": [],
            }
        },
    }


def result():
    configuration = {
        "runner": "recorded",
        "runner_version": "1.0.0",
        "agent": "codex",
        "model": None,
        "reasoning": None,
        "platform": "linux",
        "environment_sha256": "e" * 64,
        "adapter_sha256": "3" * 64,
        "launcher_sha256": "4" * 64,
        "instructions_sha256": "5" * 64,
        "profile_sha256": "6" * 64,
    }
    configuration["configuration_sha256"] = project_eval._object_digest(configuration)
    return {
        "schema_version": "project-eval-run-result/v1",
        "run_id": "run-001",
        "producer": {"name": "project-eval", "version": "1.1.0"},
        "suite": {
            "suite_id": "sample-project",
            "suite_sha256": "a" * 64,
            "profile": "smoke",
        },
        "source": {"kind": "local", "authority": "evidence_only", "bundle_sha256": None},
        "target": {
            "repository_sha256": "b" * 64,
            "definition_sha256": "c" * 64,
            "fixture_set_sha256": "d" * 64,
            "revision": None,
        },
        "configuration": configuration,
        "completion": "complete",
        "outcome": "pass",
        "next_action": "none",
        "cases": [
            {
                "case_id": "explain-api",
                "importance": "required",
                "status": "passed",
                "last_observation": "passed",
                "stability": "single_observation",
                "repetitions": 1,
                "passed": 1,
                "failed": 0,
                "forbidden_effect_failures": 0,
                "duration_ms": 12,
                "tokens": {"value": None, "provenance": "unavailable"},
                "target_sha256": "f" * 64,
                "grader_sha256": "1" * 64,
                "observation_sha256s": ["7" * 64],
                "evidence": [
                    {
                        "evidence_id": "mentions-validation",
                        "kind": "assertion",
                        "status": "pass",
                        "sha256": "2" * 64,
                        "summary": "validation mentioned",
                        "redacted": True,
                    }
                ],
                "limitations": [],
            }
        ],
        "summary": {
            "total_cases": 1,
            "passed_cases": 1,
            "failed_cases": 0,
            "unavailable_cases": 0,
            "total_repetitions": 1,
            "passed_repetitions": 1,
            "failed_repetitions": 0,
            "required_failures": 0,
            "important_failures": 0,
            "forbidden_effect_failures": 0,
            "last_observation": "passed",
            "stability": "single_observation",
            "duration_ms": 12,
            "tokens": {"value": None, "provenance": "unavailable"},
        },
        "limitations": [],
    }


def evidence_reference():
    return {
        "evidence_id": "session-one",
        "kind": "session_summary",
        "sha256": "3" * 64,
        "summary": "A bounded redacted observation.",
        "redacted": True,
    }


def candidate_result():
    return {
        "schema_version": "eval-candidate-result/v1",
        "producer": {"name": "eval-candidate-audit", "version": "1.0.0"},
        "context_sha256": "9" * 64,
        "completion": "complete",
        "outcome": "candidates",
        "next_action": "draft",
        "source_digest": "4" * 64,
        "target": {"repository_sha256": "5" * 64, "suite_sha256": "6" * 64},
        "candidates": [
            {
                "candidate_id": "candidate-one",
                "pain_point": "The workflow repeatedly missed one existing contract.",
                "proposed_case": {
                    "kind": "implementation",
                    "phase": "implementation",
                    "task_summary": "Exercise the missed existing contract.",
                },
                "reason": "Independent sessions observed the same bounded failure.",
                "evidence": [evidence_reference()],
                "evidence_count": 2,
                "independent_session_count": 1,
                "overlap": {"relation": "none", "case_ids": [], "reason": "No current case covers it."},
                "confidence": "medium",
                "proposed_importance": "standard",
                "behavior_basis": "existing",
                "cost_effect": "none",
                "promotion_requirements": ["Calibrate the hidden grader."],
                "readiness": "ready",
            }
        ],
        "limitations": [],
    }


def run_git(root, *arguments):
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


class ProtocolTests(unittest.TestCase):
    def test_suite_accepts_bounded_definition(self):
        value = suite()
        self.assertIs(project_eval.validate_suite(value), value)

    def test_suite_rejects_duplicate_case_and_unknown_profile_reference(self):
        duplicate = suite()
        duplicate["cases"].append(copy.deepcopy(duplicate["cases"][0]))
        with self.assertRaisesRegex(project_eval.EvalError, "duplicate case_id"):
            project_eval.validate_suite(duplicate)
        unknown = suite()
        unknown["profiles"]["smoke"]["case_ids"] = ["missing-case"]
        with self.assertRaisesRegex(project_eval.EvalError, "unknown cases"):
            project_eval.validate_suite(unknown)

    def test_suite_rejects_unsafe_fixture_and_insufficient_budget(self):
        unsafe = suite()
        unsafe["cases"][0]["fixture"] = "../private"
        with self.assertRaises(project_eval.EvalError):
            project_eval.validate_suite(unsafe)
        insufficient = suite()
        insufficient["profiles"]["smoke"]["repetitions"] = 2
        with self.assertRaisesRegex(project_eval.EvalError, "cannot cover"):
            project_eval.validate_suite(insufficient)

    def test_run_result_enforces_pass_and_measurement_invariants(self):
        value = result()
        self.assertIs(project_eval.validate_run_result(value), value)
        failed = result()
        failed["cases"][0]["status"] = "failed"
        failed["cases"][0]["passed"] = 0
        failed["cases"][0]["failed"] = 1
        failed["summary"]["passed_cases"] = 0
        failed["summary"]["failed_cases"] = 1
        failed["summary"]["passed_repetitions"] = 0
        failed["summary"]["failed_repetitions"] = 1
        failed["summary"]["required_failures"] = 1
        failed["summary"]["last_observation"] = "failed"
        failed["cases"][0]["last_observation"] = "failed"
        with self.assertRaisesRegex(project_eval.EvalError, "passing run"):
            project_eval.validate_run_result(failed)
        boolean_count = result()
        boolean_count["cases"][0]["passed"] = True
        with self.assertRaises(project_eval.EvalError):
            project_eval.validate_run_result(boolean_count)
        empty_pass = result()
        empty_pass["cases"] = []
        empty_pass["summary"] = {
            "total_cases": 0,
            "passed_cases": 0,
            "failed_cases": 0,
            "unavailable_cases": 0,
            "total_repetitions": 0,
            "passed_repetitions": 0,
            "failed_repetitions": 0,
            "required_failures": 0,
            "important_failures": 0,
            "forbidden_effect_failures": 0,
            "last_observation": "none",
            "stability": "insufficient",
            "duration_ms": 0,
            "tokens": {"value": 0, "provenance": "host_observed"},
        }
        with self.assertRaisesRegex(project_eval.EvalError, "at least one case"):
            project_eval.validate_run_result(empty_pass)

    def test_complete_result_rejects_material_limitation(self):
        value = result()
        value["limitations"] = [
            {"code": "missing-evidence", "message": "Evidence is missing.", "material": True}
        ]
        with self.assertRaisesRegex(project_eval.EvalError, "complete run"):
            project_eval.validate_run_result(value)

    def test_run_result_rejects_duplicate_case_id_and_unbound_import(self):
        duplicate = result()
        duplicate["cases"].append(copy.deepcopy(duplicate["cases"][0]))
        duplicate["cases"][1]["repetitions"] = 2
        with self.assertRaisesRegex(project_eval.EvalError, "duplicate case result"):
            project_eval.validate_run_result(duplicate)
        imported = result()
        imported["source"]["kind"] = "imported"
        with self.assertRaisesRegex(project_eval.EvalError, "portable bundle digest"):
            project_eval.validate_run_result(imported)

    def test_run_result_rejects_target_configuration_and_summary_drift(self):
        configuration_drift = result()
        configuration_drift["configuration"]["runner"] = "codex"
        with self.assertRaisesRegex(project_eval.EvalError, "does not bind"):
            project_eval.validate_run_result(configuration_drift)
        target_drift = result()
        target_drift["target"]["repository_sha256"] = "not-a-digest"
        with self.assertRaises(project_eval.EvalError):
            project_eval.validate_run_result(target_drift)
        summary_drift = result()
        summary_drift["summary"]["total_cases"] = 0
        with self.assertRaisesRegex(project_eval.EvalError, "does not match"):
            project_eval.validate_run_result(summary_drift)

    def test_family_protocol_rejects_open_payloads_and_unsafe_ready_candidate(self):
        value = candidate_result()
        self.assertIs(project_eval.validate_artifact(value, "candidate"), value)
        open_payload = candidate_result()
        open_payload["candidates"][0]["private"] = {"text": "raw transcript"}
        with self.assertRaisesRegex(project_eval.EvalError, "extra=.*private"):
            project_eval.validate_artifact(open_payload, "candidate")
        unsafe_ready = candidate_result()
        unsafe_ready["candidates"][0]["behavior_basis"] = "new"
        with self.assertRaisesRegex(project_eval.EvalError, "cannot be ready"):
            project_eval.validate_artifact(unsafe_ready, "candidate")

    def test_repository_suite_binds_manifest_and_fixtures_to_eval_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            eval_root = repository / "evals" / "project"
            fixture = eval_root / "fixtures" / "explain-api"
            fixture.mkdir(parents=True)
            path = eval_root / "suite.json"
            path.write_text(json.dumps(suite()), encoding="utf-8")
            value, _, resolved = project_eval.load_repository_suite(
                repository, "evals/project", "suite.json"
            )
            self.assertEqual(value["suite_id"], "sample-project")
            self.assertEqual(resolved, path)
            escaped = suite()
            escaped["cases"][0]["fixture"] = "../outside"
            path.write_text(json.dumps(escaped), encoding="utf-8")
            with self.assertRaises(project_eval.EvalError):
                project_eval.load_repository_suite(repository, "evals/project", "suite.json")

    def test_human_renderer_makes_format_controls_visible(self):
        value = result()
        value["completion"] = "incomplete"
        value["outcome"] = "unknown"
        value["next_action"] = "retry"
        value["limitations"] = [
            {"code": "unsafe-output", "message": "path\u202evalue", "material": True}
        ]
        text = project_eval.render_run(project_eval.validate_run_result(value))
        self.assertIn("path\\u202evalue", text)
        self.assertNotIn("\u202e", text)

    def test_every_public_schema_is_valid_json(self):
        for path in sorted((SKILL / "references").glob("*.schema.json")):
            with self.subTest(path=path.name):
                json.loads(path.read_text(encoding="utf-8"))

    def test_runtime_identifier_rules_match_public_schemas(self):
        run_schema = json.loads(
            (SKILL / "references" / "project-eval-run-result.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(run_schema["$defs"]["profile_id"]["pattern"], project_eval.PROFILE_ID.pattern)
        self.assertEqual(run_schema["$defs"]["run_id"]["pattern"], project_eval.RUN_ID.pattern)
        for name in ("eval-candidate-result.schema.json", "eval-experiment-result.schema.json", "eval-suite-audit-result.schema.json"):
            schema = json.loads((SKILL / "references" / name).read_text(encoding="utf-8"))
            self.assertEqual(schema["$defs"]["id"]["pattern"], project_eval.PROFILE_ID.pattern)

        invalid_candidate = candidate_result()
        invalid_candidate["candidates"][0]["overlap"]["case_ids"] = ["Not Canonical"]
        with self.assertRaisesRegex(project_eval.EvalError, "overlap.case_ids"):
            project_eval.validate_artifact(invalid_candidate, "candidate")

        recommendation = {
            "recommendation_id": "recommendation-one",
            "case_ids": ["Not Canonical"],
            "action": "refresh",
            "strength": "moderate",
            "reason": "The case no longer reflects the current contract.",
            "confidence": "high",
            "evidence": [evidence_reference()],
            "basis": "stale_but_relevant",
            "unique_coverage": "The case covers one public behavior.",
            "replacement_coverage": {
                "status": "complete",
                "case_ids": ["explain-api"],
                "explanation": "A refreshed case preserves that behavior.",
            },
            "coverage_effect": "preserved",
            "cost_effect": "none",
            "decision_required": False,
            "ready": True,
            "limitations": [],
        }
        with self.assertRaisesRegex(project_eval.EvalError, "case_ids"):
            project_eval._validate_suite_recommendation(recommendation, "recommendation")


class SetupTests(unittest.TestCase):
    def test_readiness_and_preview_are_deterministic_and_non_mutating(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            repository.mkdir()
            before = sorted(repository.rglob("*"))
            readiness = project_eval.project_eval_readiness(repository)
            preview = project_eval.project_eval_bootstrap(repository)
            self.assertEqual(readiness["status"], "not_configured")
            self.assertEqual(readiness["operation"], "readiness")
            self.assertEqual(preview["status"], "preview")
            self.assertEqual(preview["operation"], "preview")
            self.assertFalse(readiness["mutated"])
            self.assertFalse(preview["mutated"])
            self.assertEqual(readiness["starter"], preview["starter"])
            self.assertEqual(before, sorted(repository.rglob("*")))
            self.assertIn("project coverage is not established", project_eval.render_readiness(preview))

    def test_apply_creates_and_grades_complete_starter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            repository.mkdir()
            with mock.patch.object(
                project_eval,
                "project_eval_readiness",
                wraps=project_eval.project_eval_readiness,
            ) as readiness:
                applied = project_eval.project_eval_bootstrap(
                    repository, apply=True, yes=True
                )
            self.assertEqual(readiness.call_count, 1)
            self.assertEqual(applied["status"], "applied")
            self.assertTrue(applied["mutated"])
            files = project_eval._starter_files()
            self.assertEqual(
                applied["starter"]["files"],
                project_eval._starter_listing("evals/project", files),
            )
            self.assertEqual(
                applied["suite"]["source_sha256"],
                project_eval._sha(files["suite.json"]),
            )
            ready = project_eval.project_eval_readiness(repository)
            self.assertEqual(ready["status"], "ready")
            suite_value, case, _, fixture = project_eval._case_components(
                repository, "evals/project", "suite.json", "explain-starter"
            )
            self.assertEqual(suite_value["suite_id"], "starter-project-eval")
            prepared = project_eval._CASE_ENGINE.materialize_case(
                fixture, case, root / "workspaces"
            )
            workspace = Path(prepared["workspace"])
            (workspace / "answer.json").write_text(
                json.dumps(
                    {
                        "source": "README.md",
                        "purpose": "prove_eval_mechanics",
                        "project_coverage": "not_established",
                    }
                ),
                encoding="utf-8",
            )
            grade = project_eval._CASE_ENGINE.grade_case(fixture, case, prepared)
            self.assertEqual(grade["status"], "passed")

    def test_custom_suite_path_is_reflected_in_preview_and_apply(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            repository.mkdir()
            preview = project_eval.project_eval_bootstrap(
                repository, suite_value="manifests/starter.json"
            )
            paths = [item["path"] for item in preview["starter"]["files"]]
            self.assertIn("evals/project/manifests/starter.json", paths)
            self.assertNotIn("evals/project/suite.json", paths)
            applied = project_eval.project_eval_bootstrap(
                repository,
                suite_value="manifests/starter.json",
                apply=True,
                yes=True,
            )
            self.assertEqual(applied["status"], "applied")
            self.assertTrue(
                (repository / "evals" / "project" / "manifests" / "starter.json").is_file()
            )

    def test_custom_suite_path_cannot_collide_with_fixture_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            repository.mkdir()
            for suite_path in (
                "fixtures/explain-starter/control.json",
                "FIXTURES/EXPLAIN-STARTER/CONTROL.JSON",
                "fixtures/explain-starter/visible/answer.json/nested.json",
            ):
                with self.subTest(suite_path=suite_path), self.assertRaisesRegex(
                    project_eval.EvalError, "collides"
                ):
                    project_eval.project_eval_bootstrap(
                        repository, suite_value=suite_path
                    )
            self.assertEqual(list(repository.iterdir()), [])

    def test_bootstrap_requires_both_flags_and_refuses_existing_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            repository.mkdir()
            for apply, yes in ((True, False), (False, True)):
                with self.subTest(apply=apply, yes=yes), self.assertRaisesRegex(
                    project_eval.EvalError, "--apply and --yes"
                ):
                    project_eval.project_eval_bootstrap(
                        repository, apply=apply, yes=yes
                    )
            project_eval.project_eval_bootstrap(repository, apply=True, yes=True)
            replay = project_eval.project_eval_bootstrap(
                repository, apply=True, yes=True
            )
            self.assertEqual(replay["status"], "not_needed")
            self.assertFalse(replay["mutated"])

            partial = Path(temporary) / "partial"
            destination = partial / "evals" / "project"
            destination.mkdir(parents=True)
            marker = destination / "owner.txt"
            marker.write_text("keep\n", encoding="utf-8")
            blocked = project_eval.project_eval_bootstrap(
                partial, apply=True, yes=True
            )
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep\n")
            self.assertEqual(sorted(destination.iterdir()), [marker])

    def test_readiness_reports_invalid_and_unsafe_states(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            eval_root = repository / "evals" / "project"
            eval_root.mkdir(parents=True)
            (eval_root / "suite.json").write_text("{}", encoding="utf-8")
            invalid = project_eval.project_eval_readiness(repository)
            self.assertEqual(invalid["status"], "invalid")
            self.assertEqual(invalid["limitations"][0]["code"], "suite-invalid")
            if os.name != "nt":
                unsafe_repository = root / "unsafe-repo"
                unsafe_repository.symlink_to(repository, target_is_directory=True)
                unsafe = project_eval.project_eval_readiness(unsafe_repository)
                self.assertEqual(unsafe["status"], "unsafe")
                self.assertEqual(unsafe["limitations"][0]["code"], "unsafe-repository")

    def test_starter_bytes_are_lf_stable_and_setup_schema_accepts_output(self):
        files = project_eval._starter_files()
        self.assertEqual(sorted(files), list(project_eval.STARTER_FILES))
        for raw in files.values():
            self.assertNotIn(b"\r", raw)
        try:
            import jsonschema
        except ImportError:
            return
        schema = json.loads(
            (SKILL / "references" / "project-eval-setup-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            repository.mkdir()
            value = project_eval.project_eval_bootstrap(repository)
            self.assertTrue(jsonschema.Draft202012Validator(schema).is_valid(value))

    def test_setup_schema_and_runtime_reject_direct_text_and_path_drift(self):
        try:
            import jsonschema
        except ImportError:
            jsonschema = None
        schema = json.loads(
            (SKILL / "references" / "project-eval-setup-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validator = (
            jsonschema.Draft202012Validator(schema) if jsonschema is not None else None
        )

        def direct_string_accepts(rule, value):
            return (
                rule.get("minLength", 0)
                <= len(value)
                <= rule.get("maxLength", sys.maxsize)
                and project_eval.re.search(rule["pattern"], value) is not None
            )

        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            repository.mkdir()
            preview = project_eval.project_eval_bootstrap(repository)
            applied = project_eval.project_eval_bootstrap(
                repository, apply=True, yes=True
            )
            invalid_results = []

            oversized_path = copy.deepcopy(preview)
            oversized_path["target"]["eval_root"] = "a" * 4097
            invalid_results.append(
                (oversized_path, schema["$defs"]["path"], "a" * 4097)
            )

            controlled_repository = copy.deepcopy(preview)
            controlled_repository["target"]["repository"] += "\nredirected"
            invalid_results.append(
                (
                    controlled_repository,
                    schema["$defs"]["text8192"],
                    controlled_repository["target"]["repository"],
                )
            )

            controlled_limitation = copy.deepcopy(preview)
            controlled_limitation["operation"] = "readiness"
            controlled_limitation["status"] = "unsafe"
            controlled_limitation["starter"]["files"] = []
            controlled_limitation["next_action"] = "inspect_repository"
            controlled_limitation["limitations"] = [
                {"code": "unsafe-repository", "message": "unsafe\npath", "material": True}
            ]
            invalid_results.append(
                (
                    controlled_limitation,
                    schema["$defs"]["text20000"],
                    "unsafe\npath",
                )
            )

            trailing_path = copy.deepcopy(preview)
            trailing_path["target"]["eval_root"] += "\n"
            invalid_results.append(
                (trailing_path, schema["$defs"]["path"], "evals/project\n")
            )

            trailing_repository = copy.deepcopy(preview)
            trailing_repository["target"]["repository"] += "\n"
            invalid_results.append(
                (
                    trailing_repository,
                    schema["$defs"]["text8192"],
                    trailing_repository["target"]["repository"],
                )
            )

            trailing_version = copy.deepcopy(preview)
            trailing_version["producer"]["version"] += "\n"
            invalid_results.append(
                (
                    trailing_version,
                    schema["properties"]["producer"]["properties"]["version"],
                    trailing_version["producer"]["version"],
                )
            )

            trailing_suite_id = copy.deepcopy(applied)
            trailing_suite_id["suite"]["suite_id"] += "\n"
            invalid_results.append(
                (
                    trailing_suite_id,
                    schema["properties"]["suite"]["oneOf"][1]["properties"][
                        "suite_id"
                    ],
                    trailing_suite_id["suite"]["suite_id"],
                )
            )

            trailing_digest = copy.deepcopy(applied)
            trailing_digest["suite"]["source_sha256"] += "\n"
            invalid_results.append(
                (
                    trailing_digest,
                    schema["$defs"]["sha256"],
                    trailing_digest["suite"]["source_sha256"],
                )
            )

            trailing_code = copy.deepcopy(controlled_limitation)
            trailing_code["limitations"][0]["message"] = "unsafe path"
            trailing_code["limitations"][0]["code"] += "\n"
            invalid_results.append(
                (
                    trailing_code,
                    schema["properties"]["limitations"]["items"]["properties"][
                        "code"
                    ],
                    trailing_code["limitations"][0]["code"],
                )
            )

            for value, rule, direct_value in invalid_results:
                with self.subTest(value=value):
                    self.assertFalse(direct_string_accepts(rule, direct_value))
                    if validator is not None:
                        self.assertFalse(validator.is_valid(value))
                    with self.assertRaises(project_eval.EvalError):
                        project_eval.validate_setup_result(value)

            boundary_values = (
                (
                    schema["properties"]["producer"]["properties"]["version"],
                    "a",
                    "a" * 128,
                ),
                (
                    schema["properties"]["suite"]["oneOf"][1]["properties"][
                        "suite_id"
                    ],
                    "a",
                    "a" * 64,
                ),
                (
                    schema["properties"]["limitations"]["items"]["properties"][
                        "code"
                    ],
                    "a",
                    "a" * 64,
                ),
                (schema["$defs"]["sha256"], "a" * 64, "f" * 64),
                (schema["$defs"]["path"], "a", "a" * 4096),
                (schema["$defs"]["text8192"], "a", "a" * 8192),
                (schema["$defs"]["text20000"], "a", "a" * 20000),
            )
            for rule, minimum, maximum in boundary_values:
                with self.subTest(rule=rule, boundary="minimum"):
                    self.assertTrue(direct_string_accepts(rule, minimum))
                with self.subTest(rule=rule, boundary="maximum"):
                    self.assertTrue(direct_string_accepts(rule, maximum))

    def test_setup_validator_binds_suite_evidence_to_the_selected_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            repository.mkdir()
            preview = project_eval.project_eval_bootstrap(repository)
            self.assertIs(project_eval.validate_setup_result(preview), preview)

            relative_repository = copy.deepcopy(preview)
            relative_repository["target"]["repository"] = "repo"
            with self.assertRaisesRegex(project_eval.EvalError, "absolute canonical"):
                project_eval.validate_setup_result(relative_repository)

            noncanonical_repository = copy.deepcopy(preview)
            noncanonical_repository["target"]["repository"] = (
                str(repository) + os.sep + "."
            )
            with self.assertRaisesRegex(project_eval.EvalError, "absolute canonical"):
                project_eval.validate_setup_result(noncanonical_repository)

            non_json_suite = copy.deepcopy(preview)
            non_json_suite["target"]["suite"] = "suite.txt"
            with self.assertRaisesRegex(project_eval.EvalError, "JSON file"):
                project_eval.validate_setup_result(non_json_suite)

            applied = project_eval.project_eval_bootstrap(
                repository, apply=True, yes=True
            )
            self.assertIs(project_eval.validate_setup_result(applied), applied)

            relative_evidence = copy.deepcopy(applied)
            relative_evidence["suite"]["path"] = "evals/project/suite.json"
            with self.assertRaisesRegex(project_eval.EvalError, "absolute canonical"):
                project_eval.validate_setup_result(relative_evidence)

            sibling_evidence = copy.deepcopy(applied)
            sibling_evidence["suite"]["path"] = str(
                repository / "evals" / "other" / "suite.json"
            )
            with self.assertRaisesRegex(project_eval.EvalError, "selected target"):
                project_eval.validate_setup_result(sibling_evidence)

            case_drift = copy.deepcopy(applied)
            case_drift["suite"]["path"] = str(
                repository / "evals" / "project" / "SUITE.json"
            )
            with self.assertRaisesRegex(project_eval.EvalError, "selected target"):
                project_eval.validate_setup_result(case_drift)

    def test_setup_human_output_makes_format_controls_visible(self):
        with tempfile.TemporaryDirectory(prefix="repo-\u202e-") as temporary:
            repository = Path(temporary)
            value = project_eval.project_eval_readiness(repository)
            rendered = project_eval.render_readiness(value)
            self.assertIn("\\u202e", rendered)
            self.assertNotIn("\u202e", rendered)

    def test_setup_artifact_cli_validates_canonical_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            repository.mkdir()
            result_path = root / "setup.json"
            result_path.write_bytes(
                project_eval._canonical_bytes(
                    project_eval.project_eval_bootstrap(repository)
                )
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "project_eval.py"),
                    "validate-artifact",
                    "--kind",
                    "setup",
                    "--input",
                    str(result_path),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                json.loads(completed.stdout),
                {"schema_version": "project-eval-setup-result/v1", "valid": True},
            )

    def test_creation_failure_uses_platform_safe_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            repository.mkdir()
            original = project_eval._PATH_SAFETY._write_descriptor
            calls = 0

            def fail_second(descriptor, data):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("forced write failure")
                return original(descriptor, data)

            with mock.patch.object(
                project_eval._PATH_SAFETY, "_write_descriptor", side_effect=fail_second
            ):
                expected = (
                    "cannot create starter evaluation tree"
                    if os.name == "nt"
                    else "partial created content was preserved"
                )
                with self.assertRaisesRegex(project_eval.EvalError, expected):
                    project_eval.project_eval_bootstrap(
                        repository, apply=True, yes=True
                    )
            if os.name == "nt":
                self.assertEqual(list(repository.iterdir()), [])
            else:
                self.assertTrue((repository / "evals" / "project").is_dir())
                readiness = project_eval.project_eval_readiness(repository)
                self.assertEqual(readiness["status"], "incomplete")

    def test_creation_failure_preserves_raced_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            repository.mkdir()
            original = project_eval._PATH_SAFETY._write_descriptor
            calls = 0

            def replace_then_fail(descriptor, data):
                nonlocal calls
                calls += 1
                if calls == 2:
                    control = (
                        repository
                        / "evals"
                        / "project"
                        / "fixtures"
                        / "explain-starter"
                        / "control.json"
                    )
                    control.rename(control.with_name("owned-control.json"))
                    control.write_text("replacement\n", encoding="utf-8")
                    raise OSError("forced write failure after replacement")
                return original(descriptor, data)

            with mock.patch.object(
                project_eval._PATH_SAFETY,
                "_write_descriptor",
                side_effect=replace_then_fail,
            ):
                expected = (
                    "rollback was incomplete"
                    if os.name == "nt"
                    else "partial created content was preserved"
                )
                with self.assertRaisesRegex(project_eval.EvalError, expected):
                    project_eval.project_eval_bootstrap(
                        repository, apply=True, yes=True
                    )
            control = (
                repository
                / "evals"
                / "project"
                / "fixtures"
                / "explain-starter"
                / "control.json"
            )
            self.assertEqual(control.read_text(encoding="utf-8"), "replacement\n")

    def test_creation_success_rejects_raced_file_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            repository.mkdir()
            original = project_eval._PATH_SAFETY._write_descriptor
            calls = 0

            def replace_after_final_write(descriptor, data):
                nonlocal calls
                calls += 1
                result = original(descriptor, data)
                if calls == len(project_eval.STARTER_FILES):
                    control = (
                        repository
                        / "evals"
                        / "project"
                        / "fixtures"
                        / "explain-starter"
                        / "control.json"
                    )
                    control.rename(control.with_name("owned-control.json"))
                    control.write_text("replacement\n", encoding="utf-8")
                return result

            with mock.patch.object(
                project_eval._PATH_SAFETY,
                "_write_descriptor",
                side_effect=replace_after_final_write,
            ):
                expected = (
                    "rollback was incomplete"
                    if os.name == "nt"
                    else "partial created content was preserved"
                )
                with self.assertRaisesRegex(project_eval.EvalError, expected):
                    project_eval.project_eval_bootstrap(
                        repository, apply=True, yes=True
                    )
            control = (
                repository
                / "evals"
                / "project"
                / "fixtures"
                / "explain-starter"
                / "control.json"
            )
            self.assertEqual(control.read_text(encoding="utf-8"), "replacement\n")

    def test_creation_success_rejects_raced_directory_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            repository.mkdir()
            original = project_eval._PATH_SAFETY._write_descriptor
            calls = 0

            def replace_after_final_write(descriptor, data):
                nonlocal calls
                calls += 1
                result = original(descriptor, data)
                if calls == len(project_eval.STARTER_FILES):
                    visible = (
                        repository
                        / "evals"
                        / "project"
                        / "fixtures"
                        / "explain-starter"
                        / "visible"
                    )
                    visible.rename(visible.with_name("owned-visible"))
                    visible.mkdir()
                    (visible / "foreign.txt").write_text(
                        "replacement\n", encoding="utf-8"
                    )
                return result

            with mock.patch.object(
                project_eval._PATH_SAFETY,
                "_write_descriptor",
                side_effect=replace_after_final_write,
            ):
                expected = (
                    "rollback was incomplete"
                    if os.name == "nt"
                    else "partial created content was preserved"
                )
                with self.assertRaisesRegex(project_eval.EvalError, expected):
                    project_eval.project_eval_bootstrap(
                        repository, apply=True, yes=True
                    )
            marker = (
                repository
                / "evals"
                / "project"
                / "fixtures"
                / "explain-starter"
                / "visible"
                / "foreign.txt"
            )
            self.assertEqual(marker.read_text(encoding="utf-8"), "replacement\n")


class BundleTests(unittest.TestCase):
    def write_result(self, root):
        path = root / "result.json"
        path.write_bytes(project_eval._canonical_bytes(result()))
        return path

    def test_export_is_deterministic_and_refuses_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result_path = self.write_result(root)
            first = root / "first.zip"
            second = root / "second.zip"
            one = project_eval.bundle_export(str(result_path), [], first)
            two = project_eval.bundle_export(str(result_path), [], second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(one["bundle_sha256"], two["bundle_sha256"])
            with self.assertRaises(project_eval.EvalError):
                project_eval.bundle_export(str(result_path), [], first)

    def test_export_rejects_sensitive_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result_path = self.write_result(root)
            evidence = root / "evidence.json"
            evidence.write_text(json.dumps({"raw_transcript": "private"}), encoding="utf-8")
            with self.assertRaisesRegex(project_eval.EvalError, "sensitive field"):
                project_eval.bundle_export(str(result_path), [str(evidence)], root / "bundle.zip")

    def test_export_rejects_unknown_evidence_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result_path = self.write_result(root)
            evidence = root / "evidence.json"
            evidence.write_text(
                json.dumps({"schema_version": "third-party/v1", "summary": "opaque"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(project_eval.EvalError, "incompatible schema"):
                project_eval.bundle_export(
                    str(result_path), [str(evidence)], root / "bundle.zip"
                )

    def test_bundle_manifest_requires_content_addressed_evidence_names(self):
        result_raw = project_eval._canonical_bytes(result())
        evidence_raw = b"{}"
        manifest = project_eval._bundle_manifest(
            result_raw,
            [(f"evidence/{'a' * 64}.json", evidence_raw)],
        )
        with self.assertRaisesRegex(project_eval.EvalError, "unsupported bundle member path"):
            project_eval.validate_bundle_manifest(manifest)

    def test_bundle_round_trip_stores_external_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            repository.mkdir()
            run_git(repository, "init", "-q")
            state_root = root / "state"
            result_path = self.write_result(root)
            bundle = root / "evidence.zip"
            exported = project_eval.bundle_export(str(result_path), [], bundle)
            imported = project_eval.bundle_import(bundle, repository, state_root)
            self.assertEqual(imported["authority"], "evidence_only")
            self.assertEqual(imported["bundle_sha256"], exported["bundle_sha256"])
            index = project_eval.state_index(repository, state_root)
            self.assertEqual(index["receipts"][0]["source"], "imported")
            self.assertEqual(index["receipts"][0]["outcome"], "pass")
            receipt_path = next((state_root / "projects" / index["namespace"] / "receipts").iterdir())
            stored = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["source"]["kind"], "imported")
            self.assertEqual(stored["source"]["bundle_sha256"], exported["bundle_sha256"])

    def test_concurrent_identical_imports_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            repository.mkdir()
            run_git(repository, "init", "-q")
            state_root = root / "state"
            result_path = self.write_result(root)
            bundle = root / "evidence.zip"
            project_eval.bundle_export(str(result_path), [], bundle)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                receipts = list(
                    executor.map(
                        lambda _: project_eval.bundle_import(bundle, repository, state_root),
                        range(2),
                    )
                )
            self.assertEqual(receipts[0], receipts[1])
            index = project_eval.state_index(repository, state_root)
            self.assertEqual(len(index["receipts"]), 1)
            project = state_root / "projects" / index["namespace"]
            self.assertEqual(list(project.rglob("*.tmp")), [])
            self.assertEqual(
                sorted(path.name for path in (state_root / "projects").iterdir()),
                [index["namespace"]],
            )

    def test_failed_import_never_indexes_external_receipt_as_local(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            repository.mkdir()
            run_git(repository, "init", "-q")
            state_root = root / "state"
            result_path = self.write_result(root)
            bundle = root / "evidence.zip"
            project_eval.bundle_export(str(result_path), [], bundle)
            original = project_eval._write_content_addressed

            def fail_receipt(path, raw):
                if path.parent.name == "receipts":
                    raise project_eval.EvalError("injected receipt failure")
                return original(path, raw)

            with mock.patch.object(project_eval, "_write_content_addressed", side_effect=fail_receipt):
                with self.assertRaisesRegex(project_eval.EvalError, "injected"):
                    project_eval.bundle_import(bundle, repository, state_root)
            self.assertEqual(project_eval.state_index(repository, state_root)["receipts"], [])

    def test_import_rejects_traversal_and_duplicate_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            repository.mkdir()
            bad = root / "bad.zip"
            with zipfile.ZipFile(bad, "w") as archive:
                archive.writestr("../manifest.json", b"{}")
                archive.writestr("result.json", b"{}")
            with self.assertRaisesRegex(project_eval.EvalError, "unsafe archive"):
                project_eval.bundle_import(bad, repository, root / "state")

            duplicate = root / "duplicate.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(duplicate, "w") as archive:
                    archive.writestr("manifest.json", b"{}")
                    archive.writestr("manifest.json", b"{}")
            with self.assertRaisesRegex(project_eval.EvalError, "duplicate archive"):
                project_eval.bundle_import(duplicate, repository, root / "state")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_import_rejects_symlinked_bundle_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            repository.mkdir()
            actual = root / "actual.zip"
            actual.write_bytes(b"not zip")
            link = root / "link.zip"
            try:
                link.symlink_to(actual)
            except OSError as exc:
                self.skipTest(str(exc))
            with self.assertRaises(project_eval.EvalError):
                project_eval.bundle_import(link, repository, root / "state")


class StateTests(unittest.TestCase):
    def test_default_state_roots_follow_platform_conventions(self):
        with mock.patch.object(project_eval.platform, "system", return_value="Windows"), mock.patch.dict(
            os.environ, {"LOCALAPPDATA": "C:/Users/test/AppData/Local"}, clear=False
        ):
            self.assertEqual(
                project_eval._default_state_root(),
                Path("C:/Users/test/AppData/Local") / "Agent Kit" / "project-eval",
            )
        with mock.patch.object(project_eval.platform, "system", return_value="Darwin"), mock.patch.object(
            project_eval.Path, "home", return_value=Path("/Users/test")
        ):
            self.assertEqual(
                project_eval._default_state_root(),
                Path("/Users/test/Library/Application Support/Agent Kit/project-eval"),
            )
    def test_git_state_init_is_explicit_and_worktrees_share_namespace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            repository.mkdir()
            run_git(repository, "init", "-q")
            run_git(repository, "config", "user.email", "eval@example.invalid")
            run_git(repository, "config", "user.name", "Eval Fixture")
            (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            run_git(repository, "add", "tracked.txt")
            run_git(repository, "commit", "-q", "-m", "initial")
            state_root = root / "state"
            before = project_eval.state_info(repository, state_root)
            self.assertIsNone(before["namespace"])
            initialized = project_eval.state_init(repository, state_root, "1" * 32)
            self.assertEqual(initialized["namespace"], "1" * 32)
            worktree = root / "worktree"
            run_git(repository, "worktree", "add", "-q", str(worktree), "-b", "fixture-worktree")
            shared = project_eval.state_info(worktree, state_root)
            self.assertEqual(shared["namespace"], "1" * 32)
            self.assertEqual(shared["project_state"], initialized["project_state"])

    def test_non_git_state_is_path_bound_and_fresh_without_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "project"
            repository.mkdir()
            state_root = root / "state"
            first = project_eval.state_info(repository, state_root)
            second = project_eval.state_info(repository, state_root)
            self.assertEqual(first["namespace"], second["namespace"])
            self.assertFalse(first["initialized"])
            initialized = project_eval.state_init(repository, state_root, None)
            self.assertTrue(initialized["initialized"])

    def test_state_index_rejects_missing_or_non_directory_owned_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "project"
            repository.mkdir()
            state_root = root / "state"
            initialized = project_eval.state_init(repository, state_root, None)
            project = Path(initialized["project_state"])
            (project / "receipts").rmdir()
            with self.assertRaisesRegex(project_eval.EvalError, "private run receipt"):
                project_eval.state_index(repository, state_root)
            (project / "receipts").write_text("not a directory", encoding="utf-8")
            with self.assertRaisesRegex(project_eval.EvalError, "not a directory"):
                project_eval.state_index(repository, state_root)

    def test_state_index_rejects_unexpected_owned_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "project"
            repository.mkdir()
            state_root = root / "state"
            initialized = project_eval.state_init(repository, state_root, None)
            project = Path(initialized["project_state"])

            (project / "imports" / "unexpected.txt").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(project_eval.EvalError, "unexpected entry"):
                project_eval.state_index(repository, state_root)
            (project / "imports" / "unexpected.txt").unlink()

            (project / "receipts" / "unexpected.txt").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(project_eval.EvalError, "unexpected entry"):
                project_eval.state_index(repository, state_root)
            (project / "receipts" / "unexpected.txt").unlink()

            (project / "bundles" / "unexpected.txt").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(project_eval.EvalError, "unexpected entry"):
                project_eval.state_index(repository, state_root)

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor-relative race probe")
    def test_content_addressed_publication_never_overwrites_race_winner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / ("a" * 64 + ".json")
            original_link = project_eval._PATH_SAFETY.os.link

            def install_different_winner(source, target, **kwargs):
                descriptor = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=kwargs["dst_dir_fd"],
                )
                try:
                    os.write(descriptor, b"different")
                finally:
                    os.close(descriptor)
                return original_link(source, target, **kwargs)

            with mock.patch.object(
                project_eval._PATH_SAFETY.os,
                "link",
                side_effect=install_different_winner,
            ):
                with self.assertRaisesRegex(project_eval.EvalError, "different content"):
                    project_eval._write_content_addressed(destination, b"expected")
            self.assertEqual(destination.read_bytes(), b"different")

    @unittest.skipUnless(os.name == "nt", "native Windows immutable publication")
    def test_windows_content_addressed_publication_can_verify_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / ("a" * 64 + ".json")
            project_eval._write_content_addressed(destination, b"expected")
            project_eval._write_content_addressed(destination, b"expected")
            self.assertEqual(destination.read_bytes(), b"expected")
            with self.assertRaisesRegex(project_eval.EvalError, "different content"):
                project_eval._write_content_addressed(destination, b"different")

    @unittest.skipUnless(os.name == "posix", "POSIX permission assertion")
    def test_private_state_requires_private_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "project"
            repository.mkdir()
            state_root = root / "state"
            project_eval.state_init(repository, state_root, None)
            self.assertEqual(state_root.stat().st_mode & 0o777, 0o700)
            state_root.chmod(0o755)
            with self.assertRaisesRegex(project_eval.EvalError, "permissions"):
                project_eval.state_init(repository, state_root, None)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_state_init_rejects_symlinked_ancestor_without_creating_namespace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            repository.mkdir()
            run_git(repository, "init", "-q")
            outside = root / "outside"
            outside.mkdir()
            state_root = root / "state-link" / "private"
            try:
                (root / "state-link").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(str(exc))
            with self.assertRaises(project_eval.EvalError):
                project_eval.state_init(repository, state_root, "2" * 32)
            self.assertFalse((repository / ".git" / "agent-kit-project-eval-id").exists())
            self.assertFalse((outside / "private").exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_state_discovery_rejects_dangling_git_control_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "missing"

            dangling_git = root / "dangling-git"
            dangling_git.mkdir()
            try:
                (dangling_git / ".git").symlink_to(missing, target_is_directory=True)
            except OSError as exc:
                self.skipTest(str(exc))
            with self.assertRaisesRegex(project_eval.EvalError, "link-like .git"):
                project_eval.state_info(dangling_git, root / "state-a")

            dangling_common = root / "dangling-common"
            dangling_common.mkdir()
            run_git(dangling_common, "init", "-q")
            (dangling_common / ".git" / "commondir").symlink_to(missing)
            with self.assertRaisesRegex(project_eval.EvalError, "link-like Git commondir"):
                project_eval.state_info(dangling_common, root / "state-b")

            dangling_namespace = root / "dangling-namespace"
            dangling_namespace.mkdir()
            run_git(dangling_namespace, "init", "-q")
            (dangling_namespace / ".git" / "agent-kit-project-eval-id").symlink_to(missing)
            with self.assertRaisesRegex(project_eval.EvalError, "link-like project-eval namespace"):
                project_eval.state_info(dangling_namespace, root / "state-c")


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments, stdin=None):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "project_eval.py"), *arguments],
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_validate_suite_cli_and_duplicate_json_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            path = repository / "evals" / "project" / "suite.json"
            (path.parent / "fixtures" / "explain-api").mkdir(parents=True)
            path.write_text(json.dumps(suite()), encoding="utf-8")
            completed = self.run_cli(
                "validate-suite", "--repo", str(repository), "--suite", "suite.json"
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(json.loads(completed.stdout)["valid"])
            duplicate = self.run_cli(
                "validate-artifact",
                "--kind",
                "run",
                "--input",
                "-",
                stdin='{"schema_version":"x","schema_version":"y"}',
            )
            self.assertEqual(duplicate.returncode, 2)
            self.assertIn("duplicate JSON member", duplicate.stderr)


if __name__ == "__main__":
    unittest.main()
