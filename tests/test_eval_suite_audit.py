import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "eval-suite-audit"
SCRIPT = SKILL / "scripts" / "suite_audit.py"


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


suite_audit = load_module(SCRIPT, "suite_audit_under_test")


class EvalSuiteAuditTests(unittest.TestCase):
    def suite(self):
        cases = []
        for case_id, title, importance in (
            ("api-basic", "Add a basic endpoint", "required"),
            ("api-duplicate", "Add another basic endpoint", "standard"),
        ):
            cases.append(
                {
                    "case_id": case_id,
                    "title": title,
                    "kind": "implementation",
                    "importance": importance,
                    "fixture": f"fixtures/{case_id}",
                    "task": title + ".",
                    "coverage": "regression",
                    "platforms": ["linux", "windows", "macos"],
                    "required_capabilities": [],
                    "assertion_ids": ["endpoint-exists"],
                }
            )
        return {
            "schema_version": "project-eval-suite/v1",
            "suite_id": "sample-suite",
            "title": "Sample suite",
            "cases": cases,
            "profiles": {
                "smoke": {
                    "case_ids": ["api-basic", "api-duplicate"],
                    "repetitions": 1,
                    "max_invocations": 2,
                    "max_seconds": 120,
                    "max_tokens": 20000,
                    "max_cost_usd": None,
                    "network": False,
                    "effects": ["workspace_edit", "command_execution"],
                }
            },
        }

    def repository(self, directory: Path):
        (directory / "evals" / "project").mkdir(parents=True)
        for case_id in ("api-basic", "api-duplicate"):
            fixture = directory / "evals" / "project" / "fixtures" / case_id
            fixture.mkdir(parents=True)
            (fixture / "README.md").write_text(f"Fixture for {case_id}.\n", encoding="utf-8")
        suite_path = directory / "evals" / "project" / "suite.json"
        suite_path.write_text(json.dumps(self.suite()), encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=directory, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=directory, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=directory, check=True)
        subprocess.run(["git", "add", "."], cwd=directory, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=directory, check=True)
        return suite_path

    def resolved(self, directory: Path):
        self.repository(directory)
        return suite_audit.resolve_context(directory, "evals/project/suite.json", [])

    def recommendation(self, context, **changes):
        first, second = context["cases"]
        evidence_ids = [
            item["evidence_id"]
            for item in context["evidence"]
            if set(item["case_ids"]) & {first["case_id"], second["case_id"]}
        ]
        value = {
            "case_ids": [first["case_id"], second["case_id"]],
            "action": "merge",
            "strength": "strong",
            "reason": "The two cases protect the same endpoint-construction behavior.",
            "confidence": "high",
            "evidence_ids": evidence_ids,
            "basis": "duplicate_coverage",
            "unique_coverage": "The merged case preserves endpoint construction and validation.",
            "replacement_coverage": {
                "status": "complete",
                "case_ids": [first["case_id"]],
                "explanation": "api-basic retains the shared behavior with parameters.",
            },
            "coverage_effect": "preserved",
            "cost_effect": "decrease",
            "limitations": [],
        }
        value.update(changes)
        return value

    def draft(self, context, recommendation=None):
        return {
            "completion": "complete",
            "recommendations": [recommendation or self.recommendation(context)],
            "limitations": [],
        }

    def test_committed_suite_resolves_and_ready_merge_is_derived(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = self.resolved(Path(temporary))
            result = suite_audit.finalize(context, self.draft(context))
        self.assertEqual(result["outcome"], "maintenance_recommended")
        self.assertEqual(result["next_action"], "maintain")
        self.assertTrue(result["recommendations"][0]["ready"])
        self.assertFalse(result["recommendations"][0]["decision_required"])

    def test_age_or_passing_cannot_be_a_retirement_basis(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = self.resolved(Path(temporary))
            recommendation = self.recommendation(
                context,
                case_ids=["api-basic"],
                action="retire",
                basis="healthy_unique_coverage",
                reason="This old case has always passed and caught no recent failure.",
                replacement_coverage={"status": "none", "case_ids": [], "explanation": "No replacement is proposed."},
            )
            with self.assertRaisesRegex(suite_audit.AuditError, "retire lacks"):
                suite_audit.finalize(context, self.draft(context, recommendation))

    def test_demotion_and_coverage_loss_require_a_decision(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = self.resolved(Path(temporary))
            basic_evidence = next(
                item["evidence_id"]
                for item in context["evidence"]
                if item["case_ids"] == ["api-basic"]
            )
            recommendation = self.recommendation(
                context,
                case_ids=["api-basic"],
                action="demote",
                basis="other",
                evidence_ids=[basic_evidence],
                coverage_effect="loss",
                cost_effect="decrease",
                replacement_coverage={"status": "none", "case_ids": [], "explanation": "No replacement exists."},
            )
            result = suite_audit.finalize(context, self.draft(context, recommendation))
        self.assertEqual(result["next_action"], "decision")
        self.assertTrue(result["recommendations"][0]["decision_required"])
        self.assertFalse(result["recommendations"][0]["ready"])

    def test_unrelated_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = self.resolved(Path(temporary))
            recommendation = self.recommendation(
                context,
                case_ids=["api-basic"],
                action="keep",
                basis="healthy_unique_coverage",
                evidence_ids=[
                    next(item["evidence_id"] for item in context["evidence"] if item["case_ids"] == ["api-duplicate"])
                ],
                replacement_coverage={"status": "none", "case_ids": [], "explanation": "No replacement is needed."},
                coverage_effect="preserved",
                cost_effect="none",
            )
            with self.assertRaisesRegex(suite_audit.AuditError, "unrelated"):
                suite_audit.finalize(context, self.draft(context, recommendation))

    def test_suite_drift_and_uncommitted_semantic_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = self.resolved(root)
            changed = self.suite()
            changed["title"] = "Changed suite"
            (root / "evals" / "project" / "suite.json").write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(suite_audit.AuditError, "differs from committed"):
                suite_audit.finalize(context, self.draft(context))

    def test_context_bound_validation_rejects_forged_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = self.resolved(Path(temporary))
            result = suite_audit.finalize(context, self.draft(context))
            forged = copy.deepcopy(result)
            forged["recommendations"][0]["evidence"][0]["summary"] = "Forged summary"
            self.assertIs(suite_audit.validate_result(forged), forged)
            with self.assertRaisesRegex(suite_audit.AuditError, "not context-bound"):
                suite_audit.validate_result(forged, context=context)

    def test_explicit_compatible_run_and_candidate_evidence_are_sanitized(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.repository(root)
            suite_digest = suite_audit._sha_bytes(
                suite_audit._canonical_bytes(self.suite())
            )
            configuration = {
                "runner": "recorded",
                "runner_version": "1.0.0",
                "agent": "codex",
                "model": None,
                "reasoning": None,
                "platform": "linux",
                "environment_sha256": "1" * 64,
                "adapter_sha256": "2" * 64,
                "launcher_sha256": "3" * 64,
                "instructions_sha256": "4" * 64,
                "profile_sha256": "5" * 64,
            }
            configuration["configuration_sha256"] = suite_audit._sha_bytes(
                suite_audit._canonical_bytes(configuration)
            )
            run_case = {
                "case_id": "api-basic",
                "importance": "required",
                "status": "passed",
                "last_observation": "passed",
                "stability": "repeated_observations",
                "repetitions": 3,
                "passed": 3,
                "failed": 0,
                "forbidden_effect_failures": 0,
                "duration_ms": 120,
                "tokens": {"value": None, "provenance": "unavailable"},
                "target_sha256": "6" * 64,
                "grader_sha256": "7" * 64,
                "observation_sha256s": ["8" * 64, "9" * 64, "a" * 64],
                "evidence": [{"evidence_id": "endpoint-check", "kind": "assertion", "status": "pass", "sha256": "b" * 64, "summary": "Endpoint assertion passed.", "redacted": True}],
                "limitations": [],
            }
            run = {
                "schema_version": "project-eval-run-result/v1",
                "run_id": "run-one",
                "producer": {"name": "project-eval", "version": "1.1.0"},
                "suite": {"suite_id": "sample-suite", "suite_sha256": suite_digest, "profile": "smoke"},
                "source": {"kind": "local", "authority": "evidence_only", "bundle_sha256": None},
                "target": {"repository_sha256": "c" * 64, "definition_sha256": "d" * 64, "fixture_set_sha256": "e" * 64, "revision": None},
                "configuration": configuration,
                "completion": "complete",
                "outcome": "pass",
                "next_action": "none",
                "cases": [run_case],
                "summary": {"total_cases": 1, "passed_cases": 1, "failed_cases": 0, "unavailable_cases": 0, "total_repetitions": 3, "passed_repetitions": 3, "failed_repetitions": 0, "required_failures": 0, "important_failures": 0, "forbidden_effect_failures": 0, "last_observation": "passed", "stability": "repeated_observations", "duration_ms": 120, "tokens": {"value": None, "provenance": "unavailable"}},
                "limitations": [],
            }
            candidate = {
                "schema_version": "eval-candidate-result/v1",
                "producer": {"name": "eval-candidate-audit", "version": "1.0.0"},
                "context_sha256": "f" * 64,
                "completion": "complete",
                "outcome": "candidates",
                "next_action": "draft",
                "source_digest": "0" * 64,
                "target": {"repository_sha256": "1" * 64, "suite_sha256": suite_digest},
                "candidates": [
                    {
                        "candidate_id": "candidate-overlap",
                        "pain_point": "The endpoint case omits one existing response check.",
                        "proposed_case": {"kind": "implementation", "phase": "verification", "task_summary": "Exercise the existing response check."},
                        "reason": "One bounded session observed the missing check.",
                        "evidence": [{"evidence_id": "session-one", "kind": "session_summary", "sha256": "2" * 64, "summary": "A redacted bounded observation.", "redacted": True}],
                        "evidence_count": 1,
                        "independent_session_count": 1,
                        "overlap": {"relation": "extends", "case_ids": ["api-basic"], "reason": "The existing case covers the same endpoint."},
                        "confidence": "low",
                        "proposed_importance": "standard",
                        "behavior_basis": "existing",
                        "cost_effect": "none",
                        "promotion_requirements": [],
                        "readiness": "ready",
                    }
                ],
                "limitations": [],
            }
            run_path = root / "run.json"
            candidate_path = root / "candidate.json"
            run_path.write_text(json.dumps(run), encoding="utf-8")
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            context = suite_audit.resolve_context(
                root,
                "evals/project/suite.json",
                [run_path, candidate_path],
            )
        self.assertEqual(2, len(context["evidence_sources"]))
        self.assertTrue(any(item["kind"] == "run_receipt" for item in context["evidence"]))
        self.assertTrue(any(item["kind"] == "session_summary" for item in context["evidence"]))
        self.assertNotIn("path", json.dumps(context["evidence"]))

    def test_partial_or_internally_inconsistent_producer_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.repository(root)
            partial = root / "partial.json"
            partial.write_text(json.dumps({"schema_version": "project-eval-run-result/v1", "run_id": "run-one", "suite": {"suite_sha256": "a" * 64}, "cases": []}), encoding="utf-8")
            with self.assertRaisesRegex(suite_audit.AuditError, "not canonical"):
                suite_audit.resolve_context(root, "evals/project/suite.json", [partial])

    def test_context_binds_committed_fixture_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = self.resolved(root)
            basic = next(item for item in context["cases"] if item["case_id"] == "api-basic")
            self.assertEqual(1, basic["fixture_files"])
            self.assertGreater(basic["fixture_bytes"], 0)
            self.assertRegex(basic["fixture_sha256"], r"^[0-9a-f]{64}$")
            fixture = root / "evals" / "project" / "fixtures" / "api-basic" / "README.md"
            fixture.write_text("Changed but not committed.\n", encoding="utf-8")
            with self.assertRaisesRegex(suite_audit.AuditError, "differs from committed"):
                suite_audit._validate_context(context, current=True)

    def test_human_and_json_cli_use_one_canonical_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = self.resolved(root)
            result = suite_audit.finalize(context, self.draft(context))
            result_path = root.parent / (root.name + "-result.json")
            result_path.write_text(json.dumps(result), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "render", "--input", str(result_path), "--format", "human"],
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            )
            self.assertIn("merge", completed.stdout)
            self.assertIn("Evidence:", completed.stdout)
            result_path.unlink()

    def test_behavioral_prompts_do_not_reveal_grader_outcomes(self):
        banned = {"keep", "refresh", "merge", "simplify", "demote", "retire", "ready", "pass", "cost decrease"}
        for filename in ("cases.json", "suite.json"):
            manifest = json.loads((ROOT / "evals" / "eval-suite-audit" / filename).read_text(encoding="utf-8"))
            cases = manifest if isinstance(manifest, list) else manifest["cases"]
            for case in cases:
                prompt = case["prompt"].lower()
                self.assertFalse(
                    any(term in prompt for term in banned),
                    f"{filename}:{case['id']} leaks a grader outcome",
                )


if __name__ == "__main__":
    unittest.main()
