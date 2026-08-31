import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
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
project_review_result = load_module(
    "behavioral_eval_project_review_result",
    ROOT / "skills" / "project-review" / "scripts" / "review_result.py",
)
review_workflow = load_module(
    "behavioral_eval_review_workflow",
    ROOT / "skills" / "review-and-fix" / "scripts" / "review_workflow.py",
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


def complete_project_review_result(context):
    guidance = behavioral_eval._project_review_guidance(context)
    groups = [
        {
            "group_id": f"R{index:03d}",
            "paths": list(chain["applies_to"]),
            "guidance_chain_ids": [chain["chain_id"]],
            "reviewer_mode": "lead",
        }
        for index, chain in enumerate(guidance, 1)
    ]
    return project_review_result.finalize_draft(
        {
            "target": context["target"],
            "changes": context["changes"],
            "summary": {"conclusion": "The selected snapshot is safe."},
            "guidance": guidance,
            "coverage": {
                "complete": True,
                "requested_paths": context["target"]["requested_paths"],
                "reviewed_paths": context["target"]["requested_paths"],
                "context_paths": [],
                "groups": groups,
                "residual_risk": [],
            },
            "verification": [],
            "findings": [],
            "limitations": [],
        }
    )


def review_and_fix_batch(context, *, finding=None):
    outcome = "changes_requested" if finding is not None else "pass"
    envelope = {
        "target": context["target"],
        "source": {
            "reviewer": "project-review",
            "reviewer_version": "1.0.0",
            "output_format": "project_review_json",
            "output_sha256": "0" * 64,
            "completed": True,
            "verdict": "BLOCK" if finding is not None else "PASS",
            "outcome": outcome,
        },
    }
    return review_workflow.finalize_batch(
        {
            "normalization": {
                "confidence": "high",
                "notes": ["The fixed project-review adapter preserved canonical evidence."],
            },
            "findings": [] if finding is None else [finding],
            "limitations": [],
        },
        envelope,
    )


def accepted_review_and_fix_result(context, before_sha256, after_sha256):
    path = context["target"]["requested_paths"][0]
    location = {"path": path, "start_line": 1, "end_line": 1}
    initial = review_and_fix_batch(
        context,
        finding={
            "source_id": "F001",
            "source_fingerprint": "1" * 64,
            "disposition": "blocker",
            "severity": "low",
            "confidence": "high",
            "scope_relation": "pre_existing",
            "actionability": "actionable",
            "title": "Correct the heading",
            "problem": "The heading does not use the required glossary spelling.",
            "impact": "The touched documentation violates its review policy.",
            "evidence": [
                {
                    "kind": "rule",
                    "description": "The review policy requires the glossary spelling.",
                    "location": location,
                }
            ],
            "primary_location": location,
            "related_locations": [],
            "safe_direction": "Use the glossary spelling in the heading.",
            "field_provenance": {
                "disposition": "explicit",
                "severity": "explicit",
                "confidence": "explicit",
                "scope_relation": "explicit",
                "actionability": "explicit",
                "safe_direction": "explicit",
            },
            "normalization_confidence": "high",
            "normalization_notes": [],
        },
    )
    selection = {
        "finding_id": initial["findings"][0]["finding_id"],
        "selection": {
            "source_kind": "caller",
            "basis": "caller_explicit",
            "source": "The caller explicitly selected the bounded documentation blocker.",
        },
    }
    plan = review_workflow.finalize_plan(
        {
            "assessment": {
                "intent_status": "explicit",
                "intent_source": "review_rule",
                "behavior_effect": "restorative",
                "change_kind": "text_only",
                "remedy_shape": "singular",
                "scope_size": "small",
                "reversible": True,
                "validation": "static_sufficient",
                "plan_confidence": "high",
                "risk_factors": [],
            },
            "proposal": {
                "summary": "Correct the heading spelling.",
                "rationale": "The glossary and review rule fix the exact intended text.",
                "paths": [path],
                "steps": ["Replace the misspelled heading with the glossary spelling."],
                "alternatives": [],
                "validation_steps": ["Inspect the corrected heading and glossary term."],
            },
        },
        initial,
        selection,
    )
    current = review_and_fix_batch(context)
    assessment = review_workflow.assess_round(
        {
            "round": 1,
            "expected_reviewers": [
                {"reviewer": "project-review", "reviewer_version": "1.0.0"}
            ],
            "previous_batches": [initial],
            "current_batches": [current],
        }
    )
    return review_workflow.finalize_run(
        {
            "rounds": [
                {"round": 0, "batches": [initial], "assessment": None},
                {"round": 1, "batches": [current], "assessment": assessment},
            ],
            "plans": [{"context": selection, "plan": plan, "applied": True}],
            "changes": [
                {
                    "path": path,
                    "before_sha256": before_sha256,
                    "after_sha256": after_sha256,
                }
            ],
            "validation": [
                {
                    "method": "static",
                    "description": "The heading now exactly matches the glossary term.",
                    "status": "passed",
                    "command": None,
                    "authorization_source": "not_required",
                    "plan_refs": [
                        {
                            "batch_sha256": plan["batch_sha256"],
                            "finding_fingerprint": plan["finding"]["fingerprint"],
                        }
                    ],
                }
            ],
            "summary": {"conclusion": "The bounded heading fix passed fresh review."},
        },
        context,
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

    def test_input_symlinked_ancestor_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            real = base / "real"
            fixture = real / "fixture"
            fixture.mkdir(parents=True)
            source = fixture / "value.txt"
            source.write_text("safe", encoding="utf-8")
            linked = base / "linked"
            try:
                linked.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            with self.assertRaisesRegex(behavioral_eval.EvalError, "link-like path"):
                behavioral_eval.snapshot_fixture(linked / "fixture")
            with self.assertRaisesRegex(behavioral_eval.EvalError, "link-like path"):
                behavioral_eval._read_bytes(
                    linked / "fixture" / "value.txt", "linked input", 1024
                )

    def test_windows_reparse_metadata_is_link_like(self):
        metadata = types.SimpleNamespace(
            st_mode=0o040755,
            st_file_attributes=0x400,
        )
        with mock.patch.object(
            behavioral_eval.stat,
            "FILE_ATTRIBUTE_REPARSE_POINT",
            0x400,
            create=True,
        ):
            self.assertTrue(behavioral_eval._metadata_is_link_like(metadata))

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

    def test_frozen_source_snapshots_survive_later_source_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            value = source / "value.txt"
            value.write_text("frozen", encoding="utf-8")
            frozen = behavioral_eval.snapshot_fixture(source)
            digest = behavioral_eval._snapshot_digest(frozen)
            value.write_text("drifted", encoding="utf-8")
            destination = base / "destination"
            behavioral_eval._materialize_snapshot(frozen, destination)
            self.assertEqual(
                "frozen", (destination / "value.txt").read_text(encoding="utf-8")
            )
            self.assertEqual(digest, behavioral_eval._snapshot_digest(frozen))
            self.assertNotEqual(
                digest,
                behavioral_eval._snapshot_digest(
                    behavioral_eval.snapshot_fixture(source)
                ),
            )


class MutationPolicyTests(unittest.TestCase):
    def fixture_states(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        source = base / "source"
        source.mkdir()
        (source / "docs").mkdir()
        (source / "docs" / "help.md").write_text("before\n", encoding="utf-8")
        destination = base / "destination"
        behavioral_eval.materialize_fixture(source, destination)
        return destination, behavioral_eval.snapshot_fixture_state(destination)

    def test_exact_declared_content_mutation_passes(self):
        fixture, before = self.fixture_states()
        path = fixture / "docs" / "help.md"
        path.write_text("after\n", encoding="utf-8")
        after = behavioral_eval.snapshot_fixture_state(fixture)
        digest = after["docs/help.md"]["sha256"]

        report = behavioral_eval.evaluate_fixture_mutations(
            before,
            after,
            [{"path": "docs/help.md", "after_sha256": digest}],
        )
        self.assertTrue(report["passed"], report["message"])
        self.assertEqual(["docs/help.md"], [item["path"] for item in report["changes"]])

    def test_wrong_digest_mode_and_undeclared_file_fail(self):
        fixture, before = self.fixture_states()
        path = fixture / "docs" / "help.md"
        path.write_bytes(b"after\n")
        changed = behavioral_eval.snapshot_fixture_state(fixture)
        report = behavioral_eval.evaluate_fixture_mutations(
            before,
            changed,
            [{"path": "docs/help.md", "after_sha256": "f" * 64}],
        )
        self.assertFalse(report["passed"])
        self.assertIn("digest", report["message"])

        mode_changed = json.loads(json.dumps(changed))
        mode_changed["docs/help.md"]["mode"] ^= 1
        report = behavioral_eval.evaluate_fixture_mutations(
            before,
            mode_changed,
            [{"path": "docs/help.md", "after_sha256": mode_changed["docs/help.md"]["sha256"]}],
        )
        self.assertFalse(report["passed"])
        self.assertIn("mode", report["message"])

        (fixture / "extra.txt").write_text("unexpected\n", encoding="utf-8")
        added = behavioral_eval.snapshot_fixture_state(fixture)
        report = behavioral_eval.evaluate_fixture_mutations(
            before,
            added,
            [{"path": "docs/help.md", "after_sha256": added["docs/help.md"]["sha256"]}],
        )
        self.assertFalse(report["passed"])
        self.assertIn("added or removed", report["message"])

    def test_directory_addition_and_mode_change_fail(self):
        fixture, before = self.fixture_states()
        (fixture / "empty").mkdir()
        added = behavioral_eval.snapshot_fixture_state(fixture)
        report = behavioral_eval.evaluate_fixture_mutations(before, added, [])
        self.assertFalse(report["passed"])
        self.assertIn("added or removed", report["message"])

        (fixture / "empty").rmdir()
        mode_changed = json.loads(json.dumps(before))
        mode_changed["docs"]["mode"] ^= 1
        report = behavioral_eval.evaluate_fixture_mutations(before, mode_changed, [])
        self.assertFalse(report["passed"])
        self.assertIn("undeclared", report["message"])

    def test_declared_mutation_requires_post_run_evidence(self):
        _, before = self.fixture_states()
        report = behavioral_eval.evaluate_fixture_mutations(
            before,
            None,
            [{"path": "docs/help.md", "after_sha256": "0" * 64}],
        )
        self.assertFalse(report["passed"])
        self.assertFalse(report["observed"])

    def test_mutation_mode_uses_windows_readonly_attribute_when_present(self):
        metadata = types.SimpleNamespace(st_mode=0o100644, st_file_attributes=0x21)
        self.assertEqual(1, behavioral_eval._mutation_mode(metadata))

    @unittest.skipUnless(os.name == "nt", "Windows read-only attributes are platform-specific")
    def test_windows_readonly_mutation_is_observed(self):
        fixture, before = self.fixture_states()
        path = fixture / "docs" / "help.md"
        os.chmod(path, 0o444)
        after = behavioral_eval.snapshot_fixture_state(fixture)
        report = behavioral_eval.evaluate_fixture_mutations(before, after, [])
        self.assertFalse(report["passed"])
        self.assertIn("undeclared", report["message"])


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
            bound, message = behavioral_eval._bind_result(self.suite, context, result)
            self.assertFalse(bound)
            self.assertIn("target", message)

    def test_malformed_recorded_result_fails_canonical_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            path.write_text('{"schema_version":"1.0"}', encoding="utf-8")
            context_path = Path(temporary) / "context.json"
            context_path.write_text("{}", encoding="utf-8")
            passed, message = behavioral_eval.validate_result_contract(
                self.suite, path, context_path, ROOT
            )
            self.assertFalse(passed)
            self.assertIn("missing", message)


class ProjectReviewContractTests(unittest.TestCase):
    def setUp(self):
        self.suite = behavioral_eval.load_suite(ROOT, "project-review")
        self.case = behavioral_eval._case_by_id(
            self.suite, "safe-compatibility-counterexample"
        )
        self.source = ROOT / "evals" / "project-review" / self.case["fixture"]

    def test_context_result_validation_and_authority_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = base / "fixture"
            behavioral_eval.materialize_fixture(self.source, fixture)
            context_path = base / "context.json"
            context = behavioral_eval.resolve_context(
                self.suite, self.case, fixture, context_path, ROOT
            )
            result = complete_project_review_result(context)
            result_path = base / "result.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")

            valid, message = behavioral_eval.validate_result_contract(
                self.suite, result_path, context_path, ROOT
            )
            self.assertTrue(valid, message)
            bound, message = behavioral_eval._bind_result(
                self.suite, context, result
            )
            self.assertTrue(bound, message)

            result["target"]["requested_paths"] = ["events/other.py"]
            bound, message = behavioral_eval._bind_result(
                self.suite, context, result
            )
            self.assertFalse(bound)
            self.assertIn("target", message)

    def test_suite_has_pass_block_incomplete_nonblocking_and_command_boundary_cases(self):
        self.assertEqual(6, len(self.suite["cases"]))
        ids = {item["id"] for item in self.suite["cases"]}
        self.assertIn("nested-tenant-rule", ids)
        self.assertIn("non-blocking-maintainability", ids)
        self.assertIn("ordinary-cross-file-defect", ids)
        self.assertIn("conflicting-contract-incomplete", ids)
        command_case = behavioral_eval._case_by_id(
            self.suite, "repository-command-not-authority"
        )
        self.assertEqual(["scripts/expensive-check"], command_case["forbidden_commands"])


class ReviewAndFixContractTests(unittest.TestCase):
    def setUp(self):
        self.suite = behavioral_eval.load_suite(ROOT, "review-and-fix")
        self.case = behavioral_eval._case_by_id(self.suite, "routine-heading-fix")
        self.source = ROOT / "evals" / "review-and-fix" / self.case["fixture"]

    def test_context_result_validation_and_observed_change_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = base / "fixture"
            behavioral_eval.materialize_fixture(self.source, fixture)
            before = behavioral_eval.snapshot_fixture_state(fixture)
            context_path = base / "context.json"
            context = behavioral_eval.resolve_context(
                self.suite, self.case, fixture, context_path, ROOT
            )
            expected = self.case["expected_mutations"][0]
            change = {
                "path": expected["path"],
                "before_sha256": before[expected["path"]]["sha256"],
                "after_sha256": expected["after_sha256"],
            }
            result = accepted_review_and_fix_result(
                context, change["before_sha256"], change["after_sha256"]
            )
            result_path = base / "result.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")

            valid, message = behavioral_eval.validate_result_contract(
                self.suite, result_path, context_path, ROOT
            )
            self.assertTrue(valid, message)
            bound, message = behavioral_eval._bind_result(
                self.suite, context, result, [change]
            )
            self.assertTrue(bound, message)

            forged = json.loads(json.dumps(result))
            forged["changes"][0]["after_sha256"] = "f" * 64
            bound, message = behavioral_eval._bind_result(
                self.suite, context, forged, [change]
            )
            self.assertFalse(bound)
            self.assertIn("changes", message)

    def test_malformed_recorded_reviewer_context_is_a_binding_failure(self):
        bound, message = behavioral_eval._bind_result(
            self.suite,
            {"reviewers": [1]},
            {},
        )
        self.assertFalse(bound)
        self.assertIn("reviewer 0", message)

    def test_fixed_dependency_paths_and_prompt_are_isolated(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "skills").mkdir()
            runtime_skills = {
                "review-and-fix": base / "skills" / "review-and-fix",
                "project-review": base / "skills" / "project-review",
            }
            for skill_id, destination in runtime_skills.items():
                behavioral_eval.materialize_skill(ROOT / "skills" / skill_id, destination)
            paths = behavioral_eval._contract(self.suite, ROOT, runtime_skills)
            self.assertEqual(
                runtime_skills["project-review"] / "scripts" / "review_context.py",
                paths["context"],
            )
            self.assertEqual(
                runtime_skills["review-and-fix"] / "scripts" / "review_workflow.py",
                paths["validator"],
            )
            host_context = base / "host" / "context.json"
            prompt = behavioral_eval._runner_prompt(
                self.suite,
                self.case,
                base / "fixture",
                base / "work",
                runtime_skills,
                host_context,
            )
            self.assertIn(str(runtime_skills["review-and-fix"] / "SKILL.md"), prompt)
            self.assertIn(str(runtime_skills["project-review"] / "SKILL.md"), prompt)
            self.assertNotIn(self.case["expected_mutations"][0]["after_sha256"], prompt)
            self.assertNotIn("suite.json", prompt)
            self.assertIn(str(host_context), prompt)
            self.assertNotIn("do not write inside\nthe repository", prompt)

    def test_recorded_accepted_fix_is_graded_against_actual_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = base / "fixture-after"
            behavioral_eval.materialize_fixture(self.source, fixture)
            before = behavioral_eval.snapshot_fixture_state(fixture)
            context_path = base / "context.json"
            context = behavioral_eval.resolve_context(
                self.suite, self.case, fixture, context_path, ROOT
            )
            target = self.case["expected_mutations"][0]
            (fixture / target["path"]).write_bytes(
                b"# Installation\n\nFollow these steps to install the application.\n"
            )
            result = accepted_review_and_fix_result(
                context,
                before[target["path"]]["sha256"],
                target["after_sha256"],
            )
            result_path = base / "result.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            output = base / "grade.json"

            code = behavioral_eval.command_grade(
                argparse.Namespace(
                    suite="review-and-fix",
                    case="routine-heading-fix",
                    context=str(context_path),
                    result=str(result_path),
                    fixture_after=str(fixture),
                    output=str(output),
                )
            )
            self.assertEqual(0, code)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["passed"])
            self.assertEqual(
                ["docs/help.md"],
                [item["path"] for item in report["fixture_mutation"]["changes"]],
            )

    def test_suite_covers_fix_decision_authorization_and_scope_stops(self):
        self.assertEqual(5, len(self.suite["cases"]))
        ids = {item["id"] for item in self.suite["cases"]}
        self.assertEqual(
            {
                "routine-heading-fix",
                "product-choice-decision",
                "security-policy-decision",
                "remote-authorization",
                "out-of-target-remedy",
            },
            ids,
        )
        remote = behavioral_eval._case_by_id(self.suite, "remote-authorization")
        self.assertEqual(["scripts/deploy"], remote["forbidden_commands"])


class CodexRunnerTests(unittest.TestCase):
    def test_windows_batch_launcher_is_rejected_and_native_path_is_preserved(self):
        with self.assertRaisesRegex(behavioral_eval.EvalError, "batch"):
            behavioral_eval._codex_command_prefix(
                Path("Program Files & Tools") / "codex.cmd", "nt"
            )
        native, native_kind = behavioral_eval._codex_command_prefix(
            Path("Program Files & Tools") / "codex.exe", "nt"
        )
        self.assertEqual(
            [str(Path("Program Files & Tools") / "codex.exe")], native
        )
        self.assertEqual("native", native_kind)

    def test_agent_result_text_rejects_depth_and_invalid_unicode(self):
        nested = "[" * 2000 + "0" + "]" * 2000
        with self.assertRaisesRegex(behavioral_eval.EvalError, "nesting"):
            behavioral_eval._parse_agent_result_text(nested)
        with self.assertRaisesRegex(behavioral_eval.EvalError, "Unicode"):
            behavioral_eval._parse_agent_result_text('{"value":"\ud800"}')

    def test_agent_prompt_uses_isolated_skill_and_hides_expectations(self):
        suite = behavioral_eval.load_suite(ROOT, "review-guidance-audit")
        case = behavioral_eval._case_by_id(suite, "slow-test-supports-rule")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill = base / "evaluated-skill" / "review-guidance-audit"
            prompt = behavioral_eval._runner_prompt(
                suite,
                case,
                base / "fixture",
                base / "work",
                {"review-guidance-audit": skill},
            )
        self.assertIn(str(skill / "SKILL.md"), prompt)
        self.assertNotIn("suite.json", prompt)
        self.assertNotIn("default_assertions", prompt)
        self.assertNotIn("support-only", prompt)
        self.assertIn("do not perform repository mutations", prompt)

    def test_command_is_fixed_ephemeral_and_schema_constrained(self):
        suite = behavioral_eval.load_suite(ROOT, "review-guidance-audit")
        runner = {
            "command": ["codex"],
            "kind": "test",
            "sha256": "0" * 64,
            "version": "codex-cli test",
        }
        with tempfile.TemporaryDirectory() as temporary:
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
                runner,
            )
        self.assertEqual(["codex", "exec"], command[:2])
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--approve-for-me", command)
        self.assertNotIn("--sandbox", command)
        self.assertIn(
            "sandbox_workspace_write.exclude_slash_tmp=true", command
        )
        self.assertIn(
            "sandbox_workspace_write.exclude_tmpdir_env_var=true", command
        )
        self.assertIn("--output-schema", command)
        schema_index = command.index("--output-schema") + 1
        self.assertEqual(work / "agent-result.schema.json", Path(command[schema_index]))
        self.assertEqual("-", command[-1])
        self.assertNotIn("bash", command)

    def test_model_cannot_be_a_command_fragment(self):
        suite = behavioral_eval.load_suite(ROOT, "review-guidance-audit")
        runner = {
            "command": ["codex"],
            "kind": "test",
            "sha256": "0" * 64,
            "version": "codex-cli test",
        }
        with tempfile.TemporaryDirectory() as temporary:
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
                    runner,
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
        windows_job = mock.MagicMock()
        windows_patch = (
            mock.patch.object(
                behavioral_eval, "_WindowsJob", return_value=windows_job
            )
            if os.name == "nt"
            else contextlib.nullcontext()
        )
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            behavioral_eval, "build_codex_command", return_value=["codex", "exec"]
        ), mock.patch.object(
            behavioral_eval.subprocess, "Popen", return_value=process
        ), mock.patch.object(
            behavioral_eval, "_terminate_process_tree"
        ) as terminate, windows_patch:
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
                {
                    "review-guidance-audit": ROOT
                    / "skills"
                    / "review-guidance-audit"
                },
                "gpt-5.6-luna",
                "medium",
                1,
            )
        self.assertTrue(outcome["timed_out"])
        if os.name == "nt":
            windows_job.assign.assert_called_once_with(process)
            windows_job.terminate_and_wait.assert_called_once_with()
            windows_job.close.assert_called_once_with()
            terminate.assert_not_called()
        else:
            terminate.assert_called_once_with(process)

    def test_timeout_terminates_descendant_process(self):
        suite = behavioral_eval.load_suite(ROOT, "review-guidance-audit")
        case = behavioral_eval._case_by_id(suite, "json-consumer-output")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = base / "fixture"
            work = base / "work"
            fixture.mkdir()
            work.mkdir()
            marker = base / "survived.txt"
            parent = base / "parent.py"
            child = (
                "import pathlib,sys,time; time.sleep(2); "
                "pathlib.Path(sys.argv[1]).write_text('survived', encoding='utf-8')"
            )
            parent.write_text(
                "import subprocess,sys,time\n"
                f"subprocess.Popen([sys.executable, '-c', {child!r}, sys.argv[1]])\n"
                "time.sleep(60)\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                behavioral_eval,
                "build_codex_command",
                return_value=[sys.executable, str(parent), str(marker)],
            ):
                outcome = behavioral_eval._run_codex(
                    suite,
                    case,
                    fixture,
                    work,
                    work / "result.json",
                    work / "events.jsonl",
                    work / "stderr.txt",
                    ROOT,
                    {
                        "review-guidance-audit": ROOT
                        / "skills"
                        / "review-guidance-audit"
                    },
                    "gpt-5.6-luna",
                    "medium",
                    1,
                )
            self.assertTrue(outcome["timed_out"])
            time.sleep(2.5)
            self.assertFalse(marker.exists())

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
            runner,
        ):
            host = work.parent / "host"
            self.assertEqual(host, result.parent)
            self.assertEqual(host, events.parent)
            self.assertEqual(host, errors.parent)
            self.assertFalse(result.is_relative_to(work))
            sentinel = work.parent / "outside.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            hostile_result = work / "result.json"
            hostile_events = work / "events.jsonl"
            hostile_errors = work / "stderr.txt"
            try:
                hostile_result.symlink_to(sentinel)
            except (OSError, NotImplementedError):
                pass
            hostile_events.write_text("", encoding="utf-8")
            hostile_errors.write_text("concealed", encoding="utf-8")
            context = json.loads((result.parent / "context.json").read_text(encoding="utf-8"))
            result.write_text(
                json.dumps({"result_json": json.dumps(complete_result(context))}),
                encoding="utf-8",
            )
            self.assertEqual("unchanged", sentinel.read_text(encoding="utf-8"))
            events.write_text("", encoding="utf-8")
            errors.write_text("", encoding="utf-8")
            self.assertEqual([], behavioral_eval._parse_event_commands(events))
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
            runner = {
                "command": [str(fake_codex)],
                "kind": "test",
                "sha256": "1" * 64,
                "version": "codex-cli test",
            }
            with mock.patch.object(behavioral_eval, "_run_codex", side_effect=fake_run), mock.patch.object(
                behavioral_eval, "discover_codex_runner", return_value=runner
            ), contextlib.redirect_stdout(printed), contextlib.redirect_stderr(progress):
                code = behavioral_eval.command_run(args)
            self.assertEqual(0, code)
            summary = json.loads(printed.getvalue())
            self.assertEqual(1, summary["passed"])
            self.assertEqual("1" * 64, summary["runner_sha256"])
            self.assertRegex(summary["skill_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(summary["suite_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(summary["harness_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(
                summary["cases"][0]["fixture_sha256"], r"^[0-9a-f]{64}$"
            )
            self.assertEqual(
                "[1/1] json-consumer-output: running\n"
                "[1/1] json-consumer-output: passed\n",
                progress.getvalue(),
            )
            run_directory = Path(summary["output_directory"])
            self.assertTrue((run_directory / "summary.json").is_file())
            self.assertFalse((run_directory / "cases" / "json-consumer-output" / "events.jsonl").exists())

    def test_malformed_agent_output_is_recorded_as_failed_case(self):
        nested = "[" * 2000 + "0" + "]" * 2000

        def malformed_run(
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
            runner,
        ):
            result.write_text(
                json.dumps({"result_json": nested}), encoding="utf-8"
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
            runner = {
                "command": [str(base / "codex")],
                "kind": "test",
                "sha256": "1" * 64,
                "version": "codex-cli test",
            }
            printed = io.StringIO()
            progress = io.StringIO()
            with mock.patch.object(
                behavioral_eval, "_run_codex", side_effect=malformed_run
            ), mock.patch.object(
                behavioral_eval, "discover_codex_runner", return_value=runner
            ), contextlib.redirect_stdout(printed), contextlib.redirect_stderr(progress):
                code = behavioral_eval.command_run(args)
            self.assertEqual(1, code)
            summary = json.loads(printed.getvalue())
            self.assertEqual(1, summary["failed"])
            score = json.loads(
                (
                    Path(summary["output_directory"])
                    / "cases"
                    / "json-consumer-output"
                    / "score.json"
                ).read_text(encoding="utf-8")
            )
            self.assertFalse(score["passed"])
            self.assertIn("nesting", score["runner_error"])

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
            runner,
        ):
            context = json.loads((result.parent / "context.json").read_text(encoding="utf-8"))
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
            runner = {
                "command": [str(fake_codex)],
                "kind": "test",
                "sha256": "1" * 64,
                "version": "codex-cli test",
            }
            with mock.patch.object(behavioral_eval, "_run_codex", side_effect=mutating_run), mock.patch.object(
                behavioral_eval, "discover_codex_runner", return_value=runner
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

    def test_simulated_host_context_mutation_fails_the_case(self):
        def context_mutating_run(
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
            runner,
        ):
            context_path = result.parent / "context.json"
            context = json.loads(context_path.read_text(encoding="utf-8"))
            result.write_text(
                json.dumps({"result_json": json.dumps(complete_result(context))}),
                encoding="utf-8",
            )
            context_path.write_bytes(context_path.read_bytes() + b" ")
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
            runner = {
                "command": [str(base / "codex")],
                "kind": "test",
                "sha256": "1" * 64,
                "version": "codex-cli test",
            }
            printed = io.StringIO()
            progress = io.StringIO()
            with mock.patch.object(
                behavioral_eval, "_run_codex", side_effect=context_mutating_run
            ), mock.patch.object(
                behavioral_eval, "discover_codex_runner", return_value=runner
            ), contextlib.redirect_stdout(printed), contextlib.redirect_stderr(progress):
                code = behavioral_eval.command_run(args)
            self.assertEqual(1, code)
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
            self.assertFalse(score["context_unchanged"])
            self.assertIn("lead-owned context changed during the run", score["isolation_errors"])

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
