import copy
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "project-eval" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


case_engine = load_module("project_eval_case_engine_tests", SCRIPTS / "case_engine.py")
project_eval = load_module("project_eval_with_cases_tests", SCRIPTS / "project_eval.py")


def selected_case(case_id="explain", kind="explanation", coverage="development", capabilities=None):
    return {
        "case_id": case_id,
        "kind": kind,
        "coverage": coverage,
        "platforms": ["linux", "windows", "macos"],
        "required_capabilities": list(capabilities or []),
        "assertion_ids": ["answer-present"],
    }


def control(case_id="explain", mode="copy", source="visible"):
    return {
        "schema_version": "project-eval-case-control/v1",
        "case_id": case_id,
        "materialization": {
            "mode": mode,
            "source": source,
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


def write_fixture(root, value, files):
    fixture = root / "fixture"
    fixture.mkdir()
    (fixture / "control.json").write_text(json.dumps(value), encoding="utf-8")
    for relative, content in files.items():
        path = fixture / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return fixture


class ControlContractTests(unittest.TestCase):
    def test_rejects_inline_or_arbitrary_command_forms(self):
        value = control()
        value["checks"] = [
            {"check_id": "unsafe", "kind": "shell", "timeout_seconds": 1}
        ]
        with self.assertRaisesRegex(case_engine.CaseError, "fixed project check"):
            case_engine.validate_control(value)

        value = control()
        value["checks"] = [
            {
                "check_id": "unsafe",
                "kind": "python-compile",
                "timeout_seconds": 1,
                "command": "python -c 'unsafe'",
            }
        ]
        with self.assertRaisesRegex(case_engine.CaseError, "fields"):
            case_engine.validate_control(value)

        value = control(source="hidden")
        with self.assertRaisesRegex(case_engine.CaseError, "visible directory"):
            case_engine.validate_control(value)

        value = control()
        value["hidden_grader"] = {
            "grader_id": "hidden-compile",
            "kind": "python-compile",
            "timeout_seconds": 1,
            "path": "visible/grader.py",
        }
        with self.assertRaisesRegex(case_engine.CaseError, "fields"):
            case_engine.validate_control(value)

    def test_case_control_schema_is_valid_json(self):
        path = ROOT / "skills" / "project-eval" / "references" / "project-eval-case-control.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(schema["$defs"]["id"]["pattern"], case_engine.ID.pattern)
        self.assertEqual(schema["$defs"]["hidden_grader"]["required"], ["grader_id", "kind", "timeout_seconds"])

    def test_public_schemas_match_key_runtime_boundaries(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema unavailable")
        references = ROOT / "skills" / "project-eval" / "references"
        control_schema = json.loads((references / "project-eval-case-control.schema.json").read_text(encoding="utf-8"))
        prepared_schema = json.loads((references / "project-eval-prepared-case.schema.json").read_text(encoding="utf-8"))
        grade_schema = json.loads((references / "project-eval-case-grade.schema.json").read_text(encoding="utf-8"))

        jsonschema.Draft202012Validator.check_schema(control_schema)
        invalid = control()
        invalid["materialization"]["remove_paths"] = ["answer.txt"]
        self.assertFalse(jsonschema.Draft202012Validator(control_schema).is_valid(invalid))

        mapping_lookup = control(case_id="lookup")
        mapping_lookup["assertions"] = [
            {
                "assertion_id": "mapping-lookup",
                "kind": "python_mapping_lookup",
                "path": "routes.py",
                "expected": {
                    "function": "get_route",
                    "mapping_argument": "routes",
                    "key_argument": "name",
                },
            }
        ]
        self.assertTrue(jsonschema.Draft202012Validator(control_schema).is_valid(mapping_lookup))
        invalid_lookup = copy.deepcopy(mapping_lookup)
        invalid_lookup["assertions"][0]["expected"]["function"] = "not a name"
        self.assertFalse(jsonschema.Draft202012Validator(control_schema).is_valid(invalid_lookup))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = write_fixture(root, control(), {"visible/answer.txt": "correct\n"})
            case = selected_case()
            prepared = case_engine.materialize_case(fixture, case, root / "workspaces")
            self.assertTrue(jsonschema.Draft202012Validator(prepared_schema).is_valid(prepared))
            relative = dict(prepared)
            relative["workspace"] = "relative/workspace"
            self.assertFalse(jsonschema.Draft202012Validator(prepared_schema).is_valid(relative))
            grade = case_engine.grade_case(fixture, case, prepared)
            self.assertTrue(jsonschema.Draft202012Validator(grade_schema).is_valid(grade))

    def test_control_loader_rejects_duplicate_json_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            (fixture / "control.json").write_text(
                '{"schema_version":"project-eval-case-control/v1","schema_version":"other"}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(case_engine.CaseError, "duplicate JSON member"):
                case_engine.load_control(fixture)


class MaterializationTests(unittest.TestCase):
    def test_workspace_paths_must_remain_outside_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repo"
            repository.mkdir()
            with self.assertRaisesRegex(project_eval.EvalError, "outside the repository"):
                project_eval._external_workspace_path(
                    repository, str(repository / "agent-work"), "workspace root"
                )

    def test_explanation_and_implementation_copy_only_visible_source(self):
        for kind in ("explanation", "implementation"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = write_fixture(
                    root,
                    control(),
                    {
                        "visible/answer.txt": "not yet\n",
                        "hidden/expected.txt": "correct\n",
                        "holdouts/secret.txt": "holdout\n",
                    },
                )
                prepared = case_engine.materialize_case(
                    fixture, selected_case(kind=kind), root / "workspaces"
                )
                workspace = Path(prepared["workspace"])
                self.assertEqual((workspace / "answer.txt").read_text(encoding="utf-8"), "not yet\n")
                self.assertFalse((workspace / "control.json").exists())
                self.assertFalse((workspace / "hidden").exists())
                self.assertFalse((workspace / "holdouts").exists())
                self.assertFalse((workspace / ".git").exists())

    def test_visible_control_eval_and_expected_content_is_rejected_at_any_depth(self):
        for relative in (
            "visible/evals/case.json",
            "visible/nested/control.json",
            "visible/nested/hidden/secret.txt",
            "visible/nested/holdouts/secret.txt",
            "visible/nested/expected/result.txt",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = write_fixture(
                    root,
                    control(),
                    {relative: "protected", "visible/answer.txt": "not yet"},
                )
                with self.assertRaisesRegex(case_engine.CaseError, "prohibited"):
                    case_engine.materialize_case(fixture, selected_case(), root / "workspaces")

        for relative in ("visible/Nested/Hidden/secret.txt", "visible/Nested/CONTROL.JSON"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = write_fixture(
                    root, control(), {relative: "protected", "visible/answer.txt": "not yet"}
                )
                with self.assertRaisesRegex(case_engine.CaseError, "prohibited"):
                    case_engine.materialize_case(fixture, selected_case(), root / "workspaces")

        if hasattr(os, "symlink"):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = write_fixture(root, control(), {"visible/answer.txt": "not yet"})
                try:
                    (fixture / "visible" / "link.txt").symlink_to(root / "missing")
                except OSError:
                    return
                with self.assertRaisesRegex(case_engine.CaseError, "link-like"):
                    case_engine.materialize_case(fixture, selected_case(), root / "workspaces")

    def test_explicit_sanitized_history_is_the_only_history_path(self):
        if shutil.which("git") is None:
            self.skipTest("git unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = control(mode="history", source=None)
            value["materialization"]["history"] = [
                {"source": "history/one", "message": "First"},
                {"source": "history/two", "message": "Second"},
            ]
            fixture = write_fixture(
                root,
                value,
                {
                    "history/one/answer.txt": "first\n",
                    "history/two/answer.txt": "second\n",
                    "hidden/expected.txt": "never copied\n",
                },
            )
            case = selected_case(capabilities=["sanitized-history"])
            prepared = case_engine.materialize_case(fixture, case, root / "workspaces")
            workspace = Path(prepared["workspace"])
            count = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=workspace,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            self.assertEqual(count, "2")
            self.assertEqual((workspace / "answer.txt").read_text(encoding="utf-8"), "second\n")
            self.assertFalse((workspace / "hidden").exists())


class GradingTests(unittest.TestCase):
    def test_python_mapping_lookup_accepts_behavior_not_incidental_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = control(case_id="lookup")
            value["assertions"] = [
                {
                    "assertion_id": "mapping-lookup",
                    "kind": "python_mapping_lookup",
                    "path": "routes.py",
                    "expected": {
                        "function": "get_route",
                        "mapping_argument": "routes",
                        "key_argument": "name",
                    },
                }
            ]
            fixture = write_fixture(
                root,
                value,
                {
                    "visible/routes.py": (
                        "def get_route(routes, name):\n"
                        "    # return routes[name] is not enough in a comment\n"
                        "    return routes.get(name)\n"
                    )
                },
            )
            selected = selected_case(case_id="lookup", kind="implementation")
            selected["assertion_ids"] = ["mapping-lookup"]
            prepared = case_engine.materialize_case(fixture, selected, root / "workspaces")
            self.assertEqual(case_engine.grade_case(fixture, selected, prepared)["status"], "failed")
            (Path(prepared["workspace"]) / "routes.py").write_text(
                "def get_route(routes, name):\n"
                "    \"\"\"Return the registered handler.\"\"\"\n"
                "    return routes[name]\n",
                encoding="utf-8",
            )
            self.assertEqual(case_engine.grade_case(fixture, selected, prepared)["status"], "passed")

    def test_built_in_assertions_observe_workspace_and_do_not_trust_claims(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = write_fixture(root, control(), {"visible/answer.txt": "not yet\n"})
            case = selected_case()
            prepared = case_engine.materialize_case(fixture, case, root / "workspaces")
            workspace = Path(prepared["workspace"])
            failed = case_engine.grade_case(fixture, case, prepared)
            self.assertEqual(failed["status"], "failed")
            (workspace / "answer.txt").write_text("correct\n", encoding="utf-8")
            passed = case_engine.grade_case(fixture, case, prepared)
            self.assertEqual(passed["status"], "passed")
            self.assertEqual(passed["evidence"][0]["status"], "pass")
            self.assertEqual(passed["preparation_sha256"], prepared["preparation_sha256"])
            self.assertEqual(passed["fixture_sha256"], prepared["fixture_sha256"])

    def test_fixed_project_check_requires_explicit_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = control()
            value["checks"] = [
                {"check_id": "compile", "kind": "python-compile", "timeout_seconds": 10}
            ]
            fixture = write_fixture(
                root,
                value,
                {"visible/answer.txt": "correct\n", "visible/module.py": "VALUE = 1\n"},
            )
            case = selected_case()
            prepared = case_engine.materialize_case(fixture, case, root / "workspaces")
            self.assertEqual(case_engine.grade_case(fixture, case, prepared)["status"], "failed")
            self.assertEqual(
                case_engine.grade_case(fixture, case, prepared, allow_project_checks=True)["status"],
                "passed",
            )

    def test_hidden_grader_is_fixed_and_requires_explicit_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = control()
            value["hidden_grader"] = {
                "grader_id": "hidden-compile",
                "kind": "python-compile",
                "timeout_seconds": 10,
            }
            fixture = write_fixture(
                root,
                value,
                {
                    "visible/answer.txt": "correct\n",
                    "visible/module.py": "VALUE = 1\n",
                    "hidden/grader.py": "raise SystemExit('must not execute')\n",
                },
            )
            case = selected_case()
            prepared = case_engine.materialize_case(fixture, case, root / "workspaces")
            self.assertEqual(case_engine.grade_case(fixture, case, prepared)["status"], "failed")
            self.assertEqual(
                case_engine.grade_case(fixture, case, prepared, allow_hidden_grader=True)["status"],
                "passed",
            )

    def test_grade_rejects_fixture_drift_and_workspace_substitution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = write_fixture(root, control(), {"visible/answer.txt": "correct\n"})
            case = selected_case()
            prepared = case_engine.materialize_case(fixture, case, root / "workspaces")

            changed_fixture = copy.deepcopy(prepared)
            (fixture / "hidden" / "new.txt").parent.mkdir()
            (fixture / "hidden" / "new.txt").write_text("new", encoding="utf-8")
            with self.assertRaisesRegex(case_engine.CaseError, "fixture digest"):
                case_engine.grade_case(fixture, case, changed_fixture)

            (fixture / "hidden" / "new.txt").unlink()
            (fixture / "hidden").rmdir()
            replacement = root / "replacement"
            replacement.mkdir()
            forged = copy.deepcopy(prepared)
            forged["workspace"] = str(replacement)
            unsigned = dict(forged)
            unsigned.pop("preparation_sha256")
            forged["preparation_sha256"] = case_engine._sha(case_engine._canonical(unsigned))
            with self.assertRaisesRegex(case_engine.CaseError, "identity"):
                case_engine.grade_case(fixture, case, forged)

    def test_prepared_receipt_is_bound_and_context_must_be_host_owned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = write_fixture(root, control(), {"visible/answer.txt": "correct\n"})
            case = selected_case()
            prepared = case_engine.materialize_case(fixture, case, root / "workspaces")
            self.assertRegex(prepared["preparation_sha256"], case_engine.SHA256)
            self.assertRegex(prepared["workspace_identity_sha256"], case_engine.SHA256)
            unsigned = dict(prepared)
            digest = unsigned.pop("preparation_sha256")
            self.assertEqual(digest, case_engine._sha(case_engine._canonical(unsigned)))
            context_path = Path(prepared["workspace"]) / "prepared.json"
            workspace_root = root / "workspaces"
            with self.assertRaisesRegex(project_eval.EvalError, "outside the workspace root"):
                project_eval._prepared_context_output(root / "repo", workspace_root, str(context_path))


class ReconstructionAndTrajectoryTests(unittest.TestCase):
    def test_reconstruction_calibration_proves_all_four_conditions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = control(case_id="restore", mode="reconstruction", source="golden")
            value["materialization"]["remove_paths"] = ["answer.txt"]
            value["reconstruction"] = {
                "golden_source": "golden",
                "alternative_sources": ["alternatives/one"],
                "protected_paths": ["answer.txt"],
            }
            fixture = write_fixture(
                root,
                value,
                {
                    "golden/answer.txt": "correct\n",
                    "alternatives/one/answer.txt": "correct\n",
                    "alternatives/one/note.txt": "different implementation\n",
                },
            )
            case = selected_case(case_id="restore", kind="implementation", coverage="regression")
            calibration = case_engine.calibrate_reconstruction(fixture, case, root / "workspaces")
            self.assertEqual(calibration["status"], "passed")
            self.assertTrue(calibration["prepared_start_failed"])
            self.assertTrue(calibration["golden_passed"])
            self.assertFalse(calibration["protected_source_leaked"])
            self.assertEqual(calibration["alternatives"], [{"passed": True, "distinct": True}])

    def test_reconstruction_calibration_covers_every_removed_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = control(case_id="restore", mode="reconstruction", source="golden")
            value["materialization"]["remove_paths"] = ["removed"]
            value["reconstruction"] = {
                "golden_source": "golden",
                "alternative_sources": ["alternatives/one"],
                "protected_paths": ["answer.txt"],
            }
            fixture = write_fixture(
                root,
                value,
                {
                    "golden/answer.txt": "correct\n",
                    "golden/removed/secret.txt": "unique removed implementation\n",
                    "golden/leak.txt": "unique removed implementation\n",
                    "alternatives/one/answer.txt": "correct\n",
                    "alternatives/one/different.txt": "alternative\n",
                },
            )
            case = selected_case(case_id="restore", kind="implementation", coverage="regression")
            calibration = case_engine.calibrate_reconstruction(fixture, case, root / "workspaces")
            self.assertEqual(calibration["status"], "failed")
            self.assertTrue(calibration["protected_source_leaked"])

    def test_responder_reveals_only_one_mapped_fact(self):
        value = control(case_id="clarify")
        value["trajectory"] = {
            "phases": ["clarification", "implementation"],
            "facts": [
                {
                    "fact_id": "retention-days",
                    "keywords": ["retention", "days"],
                    "answer": "Retain records for 30 days.",
                    "phases": ["clarification"],
                },
                {
                    "fact_id": "account-owner",
                    "keywords": ["account", "owner"],
                    "answer": "The organization owns the account.",
                    "phases": ["clarification"],
                },
            ],
        }
        response = case_engine.respond_to_question(
            value, "clarification", "How many retention days are required?"
        )
        self.assertEqual(response["status"], "answered")
        self.assertEqual(response["fact_id"], "retention-days")
        self.assertNotIn("organization", response["answer"])
        unanswered = case_engine.respond_to_question(value, "clarification", "Tell me everything")
        self.assertEqual(unanswered, {
            "schema_version": "project-eval-clarification-response/v1",
            "status": "unanswered",
            "fact_id": None,
            "answer": None,
        })

    def test_platform_and_capability_conditions_are_not_false_failures(self):
        case = selected_case(capabilities=["docker"])
        self.assertEqual(case_engine.platform_eligibility(case, set())["status"], "unavailable")
        current = {"Linux": "linux", "Windows": "windows", "Darwin": "macos"}[platform.system()]
        other = next(item for item in ("linux", "windows", "macos") if item != current)
        case["platforms"] = [other]
        self.assertEqual(case_engine.platform_eligibility(case, {"docker"})["status"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
