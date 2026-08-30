import contextlib
import copy
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guidance_context = load_module(
    "review_guidance_context",
    ROOT / "skills" / "review-guidance-audit" / "scripts" / "guidance_context.py",
)
guidance_result = load_module(
    "review_guidance_result",
    ROOT / "skills" / "review-guidance-audit" / "scripts" / "guidance_result.py",
)


def context_args(root, **overrides):
    values = {
        "repo": str(root),
        "paths": ["src/example.py"],
        "parts": [],
        "global_review_file": None,
        "max_files": 5000,
        "max_guidance_bytes": 131072,
    }
    values.update(overrides)
    return Namespace(**values)


def make_fixture(root):
    (root / "src" / "deep").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "REVIEW.md").write_text("Keep public names stable.\n", encoding="utf-8")
    (root / "src" / "REVIEW.md").write_text("Check parser failures.\n", encoding="utf-8")
    (root / "src" / "example.py").write_text("def parse(value):\n    return value\n", encoding="utf-8")
    (root / "src" / "deep" / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_example.py").write_text("def test_parse():\n    assert True\n", encoding="utf-8")


def repository_source(context, target="src/example.py", source_path="REVIEW.md"):
    chain = next(item for item in context["guidance"] if target in item["applies_to"])
    return next(
        source
        for source in chain["sources"]
        if source["source_kind"] == "repository" and source["path"] == source_path
    )


def draft_for(context, recommendation=None):
    paths = [item["path"] for item in context["target"]["files"]]
    return {
        "summary": {"conclusion": "The selected guidance is useful but can be shorter."},
        "coverage": {
            "complete": True,
            "inspected_paths": paths,
            "excluded": [],
            "context_paths": ["tests/test_example.py"] if "tests/test_example.py" not in paths else [],
        },
        "recommendations": [] if recommendation is None else [recommendation],
        "limitations": [],
    }


def remove_recommendation(context):
    source = repository_source(context)
    return {
        "action": "remove",
        "strength": "strong",
        "decision": "ready",
        "intent_effect": "preserved",
        "title": "Remove the fully enforced syntax rule",
        "reason": "The required deterministic review-loop validator enforces the same invariant.",
        "current_guidance": [
            {
                "source_kind": "repository",
                "path": source["path"],
                "sha256": source["sha256"],
                "start_line": 1,
                "end_line": 1,
            }
        ],
        "destination": None,
        "affected_targets": ["T001"],
        "affected_paths": ["src/example.py"],
        "evidence": [
            {
                "kind": "test",
                "description": "A required local validator enforces the syntax rule.",
                "location": {
                    "path": "tests/test_example.py",
                    "start_line": 1,
                    "end_line": 2,
                },
            }
        ],
        "estimated_savings": {
            "words": 4,
            "bytes": 25,
            "basis": "Removes one redundant sentence from inherited guidance.",
        },
        "proposed_text": None,
        "harness_changes": [
            {
                "relationship": "replace",
                "kind": "validator",
                "summary": "Keep the syntax validator in the review loop.",
                "reason": "It is the complete automated replacement for this rule.",
                "coverage": "complete",
                "timing": "review_loop",
                "speed": "fast",
                "enforcement": "required",
                "determinism": "deterministic",
                "availability": "ordinary",
                "diagnostics": "actionable",
                "paths": ["tests/test_example.py"],
            }
        ],
    }


class GuidanceContextTests(unittest.TestCase):
    def test_loads_global_root_and_nested_guidance_in_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            make_fixture(root)
            global_file = Path(temporary) / "global.md"
            global_file.write_bytes(b"Global rule.\r\n")

            context = guidance_context.resolve(
                context_args(root, global_review_file=str(global_file))
            )

            chain = next(item for item in context["guidance"] if "src/example.py" in item["applies_to"])
            self.assertEqual(
                ["skill", "user_global", "repository", "repository"],
                [item["source_kind"] for item in chain["sources"]],
            )
            self.assertEqual("Global rule.\n", chain["sources"][1]["content"])
            self.assertEqual(["REVIEW.md", "src/REVIEW.md"], [item["path"] for item in chain["sources"] if item["source_kind"] == "repository"])
            self.assertEqual([], context["limitations"])

    def test_part_scope_preserves_exact_line_range(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)

            context = guidance_context.resolve(
                context_args(root, paths=[], parts=["src/example.py:1:2"])
            )

            self.assertEqual(
                {"target_id": "T001", "kind": "part", "path": "src/example.py", "start_line": 1, "end_line": 2},
                context["target"]["requested"][0],
            )
            self.assertEqual(["src/example.py"], [item["path"] for item in context["target"]["files"]])

    def test_part_scope_rejects_an_empty_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            (root / "empty.py").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(
                guidance_context.ContextError, "cannot target an empty file"
            ):
                guidance_context.resolve(
                    context_args(root, paths=[], parts=["empty.py:1:1"])
                )

    def test_requested_target_count_matches_finalizer_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            (root / "src" / "example.py").write_text("\n" * 1000, encoding="utf-8")
            accepted = [
                f"src/example.py:{line}:{line}"
                for line in range(1, guidance_context.MAX_REQUESTED_TARGETS + 1)
            ]

            context = guidance_context.resolve(
                context_args(root, paths=[], parts=accepted)
            )
            self.assertEqual(
                guidance_context.MAX_REQUESTED_TARGETS,
                len(context["target"]["requested"]),
            )

            with self.assertRaisesRegex(
                guidance_context.ContextError, "requested target selection exceeds"
            ):
                guidance_context.resolve(
                    context_args(
                        root,
                        paths=[],
                        parts=[*accepted, "src/example.py:1001:1001"],
                    )
                )

    def test_directory_and_project_scope_expand_recursively(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)

            directory = guidance_context.resolve(context_args(root, paths=["src"]))
            project = guidance_context.resolve(context_args(root, paths=["."]))

            self.assertEqual(
                {"src/REVIEW.md", "src/example.py", "src/deep/worker.py"},
                {item["path"] for item in directory["target"]["files"]},
            )
            self.assertIn("tests/test_example.py", {item["path"] for item in project["target"]["files"]})
            self.assertEqual("directory", directory["target"]["requested"][0]["kind"])
            self.assertEqual("project", project["target"]["requested"][0]["kind"])

    def test_context_metrics_capture_inheritance_fanout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)

            context = guidance_context.resolve(context_args(root, paths=["src"]))

            root_metric = next(item for item in context["context_metrics"]["per_source"] if item["source_kind"] == "repository" and item["path"] == "REVIEW.md")
            self.assertEqual(3, root_metric["fanout"])
            self.assertGreater(context["context_metrics"]["maximum_effective_words"], 0)

    def test_guidance_budget_fails_closed_without_using_it_as_quality_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            (root / "REVIEW.md").write_text("word " * 400, encoding="utf-8")

            context = guidance_context.resolve(
                context_args(root, max_guidance_bytes=1024)
            )

            self.assertTrue(any(item["code"] == "guidance_budget" and item["material"] for item in context["limitations"]))
            self.assertFalse(context["guidance"][0]["complete"])

    def test_aggregate_guidance_budget_keeps_context_machine_readable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            (root / "REVIEW.md").write_text("root-rule " * 6500, encoding="utf-8")
            for index in range(100):
                directory = root / f"area-{index:03d}"
                directory.mkdir()
                (directory / "REVIEW.md").write_text(
                    f"Area {index} rule.\n", encoding="utf-8"
                )
                (directory / "module.py").write_text(
                    f"VALUE = {index}\n", encoding="utf-8"
                )

            context = guidance_context.resolve(context_args(root, paths=["."]))
            self.assertTrue(
                any(
                    item["code"] == "guidance_budget" and item["material"]
                    for item in context["limitations"]
                )
            )
            self.assertTrue(any(not chain["complete"] for chain in context["guidance"]))
            data = guidance_context._serialized_context(context)
            self.assertLessEqual(len(data), guidance_result.MAX_JSON_BYTES)

            output = Path(temporary) / "context.json"
            guidance_context._write_context(context, str(output))
            self.assertEqual(context, guidance_result._read_json(str(output)))

    def test_path_escape_and_link_targets_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "project"
            root.mkdir()
            outside = parent / "outside.py"
            outside.write_text("secret = True\n", encoding="utf-8")
            with self.assertRaises(guidance_context.ContextError):
                guidance_context.resolve(context_args(root, paths=["../outside.py"]))
            link = root / "link.py"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(guidance_context.ContextError):
                guidance_context.resolve(context_args(root, paths=["link.py"]))

    def test_technical_file_ceiling_reports_material_truncation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)

            context = guidance_context.resolve(context_args(root, paths=["."], max_files=2))

            self.assertEqual(2, len(context["target"]["files"]))
            self.assertTrue(any(item["code"] == "scope_truncated" and item["material"] for item in context["limitations"]))
            with self.assertRaisesRegex(guidance_context.ContextError, "max-files"):
                guidance_context.resolve(
                    context_args(root, paths=["."], max_files=guidance_context.MAX_FILES + 1)
                )

    def test_resolver_collections_stay_within_finalizer_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir(parents=True)
            for index in range(guidance_context.MAX_LIMITATIONS + 1):
                (data / f"{index:04d}.bin").write_bytes(b"\0")

            context = guidance_context.resolve(context_args(root, paths=["data"]))

            self.assertEqual(
                guidance_context.MAX_LIMITATIONS, len(context["limitations"])
            )
            self.assertIn(
                "additional limitation records",
                context["limitations"][-1]["message"],
            )
            guidance_result._validate_context(context)

    @unittest.skipIf(os.name == "nt", "deep path limits vary on Windows")
    def test_deep_guidance_chain_is_bounded_and_incomplete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root
            for _ in range(guidance_context.MAX_GUIDANCE_SOURCES_PER_CHAIN):
                current /= "d"
                current.mkdir()
                (current / "REVIEW.md").write_text("Rule.\n", encoding="utf-8")
            target = current / "target.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            relative = target.relative_to(root).as_posix()

            context = guidance_context.resolve(context_args(root, paths=[relative]))

            self.assertEqual(
                guidance_context.MAX_GUIDANCE_SOURCES_PER_CHAIN,
                len(context["guidance"][0]["sources"]),
            )
            self.assertFalse(context["guidance"][0]["complete"])
            self.assertTrue(
                any(
                    item["code"] == "guidance_budget" and item["material"]
                    for item in context["limitations"]
                )
            )
            guidance_result._validate_context(context)

    def test_binary_non_utf8_and_oversized_files_are_classified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            (root / "binary.dat").write_bytes(b"value\0payload")
            (root / "non-utf8.dat").write_bytes(b"\xff")
            with (root / "oversized.dat").open("wb") as handle:
                handle.truncate(guidance_context.MAX_INSPECTION_FILE_BYTES + 1)

            context = guidance_context.resolve(
                context_args(
                    root,
                    paths=["binary.dat", "non-utf8.dat", "oversized.dat"],
                )
            )
            kinds = {
                item["path"]: item["inspection_kind"]
                for item in context["target"]["files"]
            }

            self.assertEqual("binary", kinds["binary.dat"])
            self.assertEqual("non_utf8", kinds["non-utf8.dat"])
            self.assertEqual("oversized", kinds["oversized.dat"])
            self.assertEqual(
                {"binary.dat", "non-utf8.dat", "oversized.dat"},
                {
                    path
                    for limitation in context["limitations"]
                    if limitation["code"] == "target_unreadable"
                    and limitation["material"]
                    for path in limitation["affected_paths"]
                },
            )

    @unittest.skipIf(shutil.which("git") is None, "Git is unavailable")
    def test_git_aware_scope_excludes_ignored_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            (root / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
            (root / "ignored.py").write_text("IGNORED = True\n", encoding="utf-8")
            subprocess.run(
                ["git", "init", "--quiet", str(root)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            context = guidance_context.resolve(context_args(root, paths=["."]))

            paths = {item["path"] for item in context["target"]["files"]}
            self.assertNotIn("ignored.py", paths)
            self.assertTrue(context["discovery"]["git_ignore_rules_used"])

    @unittest.skipIf(os.name == "nt", "POSIX permissions required")
    def test_unreadable_file_is_disclosed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            unreadable = root / "unreadable.txt"
            unreadable.write_text("hidden\n", encoding="utf-8")
            unreadable.chmod(0)
            try:
                context = guidance_context.resolve(
                    context_args(root, paths=["unreadable.txt"])
                )
            finally:
                unreadable.chmod(0o600)

            self.assertEqual(
                "unreadable", context["target"]["files"][0]["inspection_kind"]
            )

    def test_shared_unreadable_guidance_marks_every_applicable_chain_incomplete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            (root / "src" / "REVIEW.md").unlink()
            (root / "src" / "REVIEW.md").mkdir()

            context = guidance_context.resolve(
                context_args(
                    root,
                    paths=["src/example.py", "src/deep/worker.py"],
                )
            )

            for target in ("src/example.py", "src/deep/worker.py"):
                chain = next(
                    item
                    for item in context["guidance"]
                    if target in item["applies_to"]
                )
                self.assertFalse(chain["complete"])
                self.assertTrue(
                    any(
                        limitation["code"] == "guidance_unreadable"
                        and limitation["material"]
                        and target in limitation["affected_paths"]
                        for limitation in context["limitations"]
                    )
                )

    def test_fallback_walk_reports_skipped_link_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            make_fixture(root)
            outside = Path(temporary) / "outside"
            outside.mkdir()
            (outside / "secret.py").write_text("SECRET = True\n", encoding="utf-8")
            link = root / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks unavailable")

            context = guidance_context.resolve(context_args(root, paths=["."]))

            self.assertNotIn(
                "linked/secret.py",
                {item["path"] for item in context["target"]["files"]},
            )
            self.assertTrue(
                any(
                    item["code"] == "target_unreadable"
                    and item["affected_paths"] == ["linked"]
                    and item["material"]
                    for item in context["limitations"]
                )
            )

    @unittest.skipIf(os.name == "nt", "control characters are not valid Windows file names")
    def test_fallback_walk_rejects_unrepresentable_file_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            (root / "bad\nname.py").write_text("VALUE = 1\n", encoding="utf-8")

            with self.assertRaisesRegex(
                guidance_context.ContextError, "unrepresentable file path"
            ):
                guidance_context.resolve(context_args(root, paths=["."]))

    def test_context_output_uses_exclusive_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "context.json"
            guidance_context._write_context({"value": 1}, str(destination))
            self.assertEqual({"value": 1}, json.loads(destination.read_text(encoding="utf-8")))
            with self.assertRaises(guidance_context.ContextError):
                guidance_context._write_context({"value": 2}, str(destination))

    @unittest.skipIf(os.name == "nt", "control characters are not valid Windows paths")
    def test_control_characters_are_rejected_in_absolute_authority_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "bad\nroot"
            root.mkdir()
            with self.assertRaisesRegex(
                guidance_context.ContextError, "control characters"
            ):
                guidance_context.resolve(context_args(root))

            project = Path(temporary) / "project"
            project.mkdir()
            make_fixture(project)
            global_file = Path(temporary) / "global\nREVIEW.md"
            global_file.write_text("Rule.\n", encoding="utf-8")
            with self.assertRaisesRegex(
                guidance_context.ContextError, "control characters"
            ):
                guidance_context.resolve(
                    context_args(project, global_review_file=str(global_file))
                )

    @unittest.skipIf(os.name == "nt", "POSIX permissions required")
    def test_project_root_walk_failure_finalizes_incomplete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            root.chmod(0)
            try:
                context = guidance_context.resolve(context_args(root, paths=["."]))
                self.assertEqual([], context["limitations"][0]["affected_paths"])
                result = guidance_result.finalize(
                    context,
                    {
                        "summary": {"conclusion": "The project root was unreadable."},
                        "coverage": {
                            "complete": True,
                            "inspected_paths": [],
                            "excluded": [],
                            "context_paths": [],
                        },
                        "recommendations": [],
                        "limitations": [],
                    },
                )
            finally:
                root.chmod(0o700)

            self.assertEqual("INCOMPLETE", result["status"])


class GuidanceResultTests(unittest.TestCase):
    def make_context(self, root):
        make_fixture(root)
        return guidance_context.resolve(context_args(root))

    def test_finalizer_binds_context_and_renders_same_canonical_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = self.make_context(root)
            result = guidance_result.finalize(context, draft_for(context, remove_recommendation(context)))

            self.assertEqual("COMPLETE", result["status"])
            self.assertEqual(str(root.resolve()), result["target"]["repository_root"])
            self.assertEqual("R001", result["recommendations"][0]["recommendation_id"])
            self.assertEqual(1, result["summary"]["harness_changes"])
            rendered = guidance_result.render_human(result)
            self.assertIn("Review guidance audit: COMPLETE", rendered)
            self.assertIn("[replace]", rendered)
            self.assertIn("Guidance: repository:REVIEW.md:1", rendered)
            self.assertIn("Estimated savings: 4 words / 25 bytes.", rendered)
            guidance_result._validate_result(result)

    def test_canonical_result_cannot_claim_complete_with_unloaded_guidance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = self.make_context(root)
            result = guidance_result.finalize(context, draft_for(context))
            tampered = copy.deepcopy(result)
            repository = next(
                source
                for source in tampered["guidance"][0]["sources"]
                if source["source_kind"] == "repository"
            )
            repository["loaded"] = False
            tampered["guidance"][0]["complete"] = True

            with self.assertRaisesRegex(
                guidance_result.ResultError, "cannot hide unloaded guidance"
            ):
                guidance_result._validate_result(tampered)
            with self.assertRaisesRegex(
                guidance_result.ResultError, "cannot hide unloaded guidance"
            ):
                guidance_result.render_human(tampered)

            truthy_strings = copy.deepcopy(result)
            repository = next(
                source
                for source in truthy_strings["guidance"][0]["sources"]
                if source["source_kind"] == "repository"
            )
            repository["loaded"] = "yes"
            truthy_strings["guidance"][0]["complete"] = "yes"
            with self.assertRaisesRegex(
                guidance_result.ResultError, "complete must be boolean"
            ):
                guidance_result._validate_result(truthy_strings)
            with self.assertRaisesRegex(
                guidance_result.ResultError, "complete must be boolean"
            ):
                guidance_result.render_human(truthy_strings)

    def test_draft_cannot_supply_target_or_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = self.make_context(root)
            draft = draft_for(context)
            draft["target"] = context["target"]
            with self.assertRaisesRegex(guidance_result.ResultError, "unknown fields"):
                guidance_result.finalize(context, draft)

    def test_rule_reference_must_apply_to_every_affected_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = self.make_context(root)
            recommendation = remove_recommendation(context)
            recommendation["current_guidance"][0]["sha256"] = "f" * 64
            with self.assertRaisesRegex(guidance_result.ResultError, "not applicable"):
                guidance_result.finalize(context, draft_for(context, recommendation))

    def test_context_rejects_sibling_guidance_and_forged_metrics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = self.make_context(root)
            sibling = copy.deepcopy(context)
            source = next(
                item
                for item in sibling["guidance"][0]["sources"]
                if item["source_kind"] == "repository"
            )
            source["path"] = "sibling/REVIEW.md"
            with self.assertRaisesRegex(guidance_result.ResultError, "non-applicable"):
                guidance_result.finalize(sibling, draft_for(context))

            forged = copy.deepcopy(context)
            forged["context_metrics"]["per_source"][0]["fanout"] += 1
            with self.assertRaisesRegex(guidance_result.ResultError, "per_source is inconsistent"):
                guidance_result.finalize(forged, draft_for(context))

    def test_finalizer_rejects_stale_target_or_broad_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = self.make_context(root)
            (root / "src" / "example.py").write_text("changed = True\n", encoding="utf-8")
            with self.assertRaisesRegex(guidance_result.ResultError, "context is stale"):
                guidance_result.finalize(context, draft_for(context))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            context = guidance_context.resolve(context_args(root, paths=["src"]))
            (root / "src" / "new.py").write_text("NEW = True\n", encoding="utf-8")
            with self.assertRaisesRegex(guidance_result.ResultError, "context is stale"):
                guidance_result.finalize(context, draft_for(context))

    def test_changed_intent_requires_user_decision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = self.make_context(root)
            recommendation = remove_recommendation(context)
            recommendation["intent_effect"] = "changed"
            with self.assertRaisesRegex(guidance_result.ResultError, "decision_required"):
                guidance_result.finalize(context, draft_for(context, recommendation))

    def test_part_recommendation_requires_evidence_inside_exact_range(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            context = guidance_context.resolve(
                context_args(root, paths=[], parts=["src/example.py:1:1"])
            )
            recommendation = remove_recommendation(context)
            with self.assertRaisesRegex(guidance_result.ResultError, "evidence inside affected part"):
                guidance_result.finalize(context, draft_for(context, recommendation))

            recommendation["evidence"][0]["location"] = {
                "path": "src/example.py",
                "start_line": 1,
                "end_line": 2,
            }
            with self.assertRaisesRegex(guidance_result.ResultError, "evidence inside affected part"):
                guidance_result.finalize(context, draft_for(context, recommendation))

            recommendation["evidence"][0]["location"] = {
                "path": "src/example.py",
                "start_line": 1,
                "end_line": 1,
            }
            result = guidance_result.finalize(
                context, draft_for(context, recommendation)
            )
            self.assertEqual(["T001"], result["recommendations"][0]["affected_targets"])

    def test_replacement_requires_fast_complete_required_deterministic_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = self.make_context(root)
            for field, value in (
                ("coverage", "partial"),
                ("timing", "pre_deploy"),
                ("speed", "slow"),
                ("enforcement", "optional"),
                ("determinism", "nondeterministic"),
                ("availability", "restricted"),
                ("diagnostics", "weak"),
            ):
                with self.subTest(field=field):
                    recommendation = remove_recommendation(context)
                    recommendation["harness_changes"][0][field] = value
                    with self.assertRaisesRegex(guidance_result.ResultError, "replacement requires"):
                        guidance_result.finalize(context, draft_for(context, recommendation))

    def test_slow_check_can_support_but_not_replace_guidance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = self.make_context(root)
            recommendation = remove_recommendation(context)
            recommendation["action"] = "keep"
            recommendation["harness_changes"][0].update(
                {
                    "relationship": "support",
                    "coverage": "complete",
                    "timing": "pre_deploy",
                    "speed": "slow",
                    "enforcement": "required",
                }
            )
            result = guidance_result.finalize(context, draft_for(context, recommendation))
            self.assertEqual("keep", result["recommendations"][0]["action"])
            self.assertEqual("support", result["recommendations"][0]["harness_changes"][0]["relationship"])

    def test_freestanding_harness_proposals_are_structurally_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = self.make_context(root)
            draft = draft_for(context)
            draft["harness_changes"] = []
            with self.assertRaisesRegex(guidance_result.ResultError, "unknown fields"):
                guidance_result.finalize(context, draft)

    def test_coverage_must_account_for_every_target_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            context = guidance_context.resolve(context_args(root, paths=["src"]))
            draft = draft_for(context)
            draft["coverage"]["inspected_paths"].pop()
            with self.assertRaisesRegex(guidance_result.ResultError, "account for every"):
                guidance_result.finalize(context, draft)

    def test_context_material_limitation_forces_incomplete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            (root / "REVIEW.md").write_text("word " * 400, encoding="utf-8")
            context = guidance_context.resolve(context_args(root, max_guidance_bytes=1024))
            result = guidance_result.finalize(context, draft_for(context))
            self.assertEqual("INCOMPLETE", result["status"])

    def test_non_text_target_must_be_materially_excluded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            (root / "binary.dat").write_bytes(b"value\0payload")
            context = guidance_context.resolve(
                context_args(root, paths=["binary.dat"])
            )

            with self.assertRaisesRegex(
                guidance_result.ResultError, "cannot claim non-text"
            ):
                guidance_result.finalize(context, draft_for(context))

            draft = draft_for(context)
            draft["coverage"] = {
                "complete": False,
                "inspected_paths": [],
                "excluded": [
                    {
                        "path": "binary.dat",
                        "reason": "The target is binary and unavailable to text inspection.",
                        "material": True,
                    }
                ],
                "context_paths": [],
            }
            result = guidance_result.finalize(context, draft)
            self.assertEqual("INCOMPLETE", result["status"])

    def test_recommendation_cannot_cite_unloaded_guidance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            (root / "REVIEW.md").write_text("word " * 400, encoding="utf-8")
            context = guidance_context.resolve(
                context_args(root, max_guidance_bytes=1024)
            )
            recommendation = remove_recommendation(context)
            with self.assertRaisesRegex(guidance_result.ResultError, "unloaded source"):
                guidance_result.finalize(
                    context, draft_for(context, recommendation)
                )

    def test_duplicate_json_members_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.json"
            path.write_text('{"summary": {}, "summary": {}}', encoding="utf-8")
            with self.assertRaisesRegex(guidance_result.ResultError, "duplicate JSON member"):
                guidance_result._read_json(str(path))

    def test_json_input_and_strings_reject_unsafe_size_or_unicode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "large.json"
            path.write_bytes(b" " * (guidance_result.MAX_JSON_BYTES + 1))
            with self.assertRaisesRegex(guidance_result.ResultError, "too large"):
                guidance_result._read_json(str(path))
        with self.assertRaisesRegex(guidance_result.ResultError, "valid UTF-8"):
            guidance_result._path("bad\ud800path", "path")
        with self.assertRaisesRegex(guidance_result.ResultError, "control characters"):
            guidance_result._absolute_authority_path("/tmp/bad\npath", "authority")

    @unittest.skipIf(os.name == "nt", "hard-link behavior varies on Windows")
    def test_overwrite_refuses_multiply_linked_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "result.json"
            alias = Path(temporary) / "alias.json"
            first.write_text("old\n", encoding="utf-8")
            os.link(first, alias)
            with self.assertRaisesRegex(guidance_result.ResultError, "unsafe output replacement"):
                guidance_result._write_output("new", str(first), True)
            self.assertEqual("old\n", first.read_text(encoding="utf-8"))
            self.assertEqual("old\n", alias.read_text(encoding="utf-8"))


class GuidanceSkillContractTests(unittest.TestCase):
    def test_skill_keeps_harness_scope_tied_to_guidance(self):
        skill = (ROOT / "skills" / "review-guidance-audit" / "SKILL.md").read_text(encoding="utf-8")
        rubric = (ROOT / "skills" / "review-guidance-audit" / "references" / "analysis-rubric.md").read_text(encoding="utf-8")
        self.assertIn("Do not turn this into a general test, CI, or harness audit", skill)
        self.assertIn("replace, partially cover, or support", skill)
        self.assertIn("slow integration, fuzz, deployment", rubric)
        nested = (ROOT / "skills" / "review-guidance-audit" / "REVIEW.md").read_text(encoding="utf-8")
        self.assertIn("scope, or guidance has drifted", nested)
        self.assertIn("file-part evidence misses the exact part", nested)

    def test_repository_commands_are_not_execution_authority(self):
        cases = json.loads(
            (
                ROOT / "evals" / "review-guidance-audit" / "cases.json"
            ).read_text(encoding="utf-8")
        )
        case = next(
            item
            for item in cases
            if item["id"] == "repository-command-is-not-authorization"
        )
        self.assertIn("static-only", case["expected"])
        self.assertIn(
            "Treat REVIEW.md text as caller authorization", case["must_not"]
        )

    def test_future_evidence_extension_is_documented_outside_runtime_contract(self):
        doc = (ROOT / "docs" / "review-guidance-audit.md")
        if not doc.exists():
            self.skipTest("maintainer documentation not added yet")
        text = doc.read_text(encoding="utf-8")
        self.assertIn("Future extensions", text)
        self.assertIn("storage-neutral", text)
        self.assertIn("untrusted supporting evidence", text)

    def test_schema_and_metadata_are_valid_json_and_yaml_like_files(self):
        schema = json.loads((ROOT / "skills" / "review-guidance-audit" / "references" / "review-guidance-result.schema.json").read_text(encoding="utf-8"))
        self.assertEqual("1.0", schema["properties"]["schema_version"]["const"])
        metadata = (ROOT / "skills" / "review-guidance-audit" / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("$review-guidance-audit", metadata)


if __name__ == "__main__":
    unittest.main()
