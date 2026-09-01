import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness_context = load_module(
    "verification_harness_context",
    ROOT / "skills" / "verification-harness-audit" / "scripts" / "harness_context.py",
)


def context_args(root, **overrides):
    values = {
        "repo": str(root),
        "paths": ["tests/test_parser.py"],
        "parts": [],
        "focus_kind": None,
        "focus_value": None,
        "contexts": [],
        "inspections": [],
        "global_review_file": None,
        "command_plan": None,
        "evidence_metadata": None,
        "max_files": harness_context.DEFAULT_MAX_FILES,
        "max_file_bytes": harness_context.DEFAULT_MAX_FILE_BYTES,
        "max_total_bytes": harness_context.DEFAULT_MAX_TOTAL_BYTES,
        "max_traversal_entries": harness_context.DEFAULT_MAX_TRAVERSAL_ENTRIES,
        "max_context_files": harness_context.DEFAULT_MAX_CONTEXT_FILES,
        "max_context_bytes": harness_context.DEFAULT_MAX_CONTEXT_BYTES,
        "max_guidance_bytes": harness_context.DEFAULT_MAX_GUIDANCE_BYTES,
        "output": None,
    }
    values.update(overrides)
    return Namespace(**values)


def make_fixture(root):
    (root / "src").mkdir(parents=True)
    (root / "tests" / "nested").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "REVIEW.md").write_text("Protect public behavior.\n", encoding="utf-8")
    (root / "tests" / "REVIEW.md").write_text("Inspect assertions.\n", encoding="utf-8")
    (root / "tests" / "test_parser.py").write_bytes(b"def test_parse():\r\n    assert True\r\n")
    (root / "tests" / "nested" / "test_worker.py").write_text("def test_worker():\n    assert True\n", encoding="utf-8")
    (root / "src" / "parser.py").write_text("def parse(value):\n    return value\n", encoding="utf-8")
    (root / "docs" / "contract.md").write_text("Parsing is stable.\n", encoding="utf-8")


class ResolverTests(unittest.TestCase):
    def test_file_target_has_canonical_lf_digest_and_ordered_guidance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)

            context = harness_context.resolve(context_args(root))

            self.assertEqual("1.0.0", context["schema_version"])
            self.assertEqual("file", context["target"]["requested"][0]["kind"])
            record = context["inventory"]["files"][0]
            canonical = b"def test_parse():\n    assert True\n"
            self.assertEqual(len(canonical), record["bytes"])
            self.assertEqual(hashlib.sha256(canonical).hexdigest(), record["sha256"])
            chain = context["guidance"][0]
            repository_sources = [
                source["path"]
                for source in chain["sources"]
                if source["source_kind"] == "repository"
            ]
            self.assertEqual(["REVIEW.md", "tests/REVIEW.md"], repository_sources)
            self.assertTrue(context["inventory"]["complete"])

    def test_part_target_validates_lines_and_supports_explicit_focus(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)

            context = harness_context.resolve(
                context_args(root, paths=[], parts=["tests/test_parser.py:1:2"])
            )
            target = context["target"]["requested"][0]
            self.assertEqual("part", target["kind"])
            self.assertEqual({"kind": "line_range", "value": "1:2"}, target["focus"])

            focused = harness_context.resolve(
                context_args(
                    root,
                    focus_kind="test_case",
                    focus_value="test_parse",
                )
            )
            self.assertEqual("test_case", focused["target"]["requested"][0]["focus"]["kind"])

            with self.assertRaisesRegex(harness_context.ContextError, "exceeds"):
                harness_context.resolve(
                    context_args(root, paths=[], parts=["tests/test_parser.py:1:99"])
                )

            repeated_parts = harness_context.resolve(
                context_args(
                    root,
                    paths=[],
                    parts=[
                        "tests/test_parser.py:1:1",
                        "tests/test_parser.py:2:2",
                    ],
                )
            )
            self.assertEqual(
                len(b"def test_parse():\r\n    assert True\r\n"),
                repeated_parts["inventory"]["read_bytes"],
            )

    def test_directory_and_project_targets_are_recursive_and_stable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)

            directory = harness_context.resolve(context_args(root, paths=["tests"]))
            project = harness_context.resolve(context_args(root, paths=["."]))

            self.assertEqual("directory", directory["target"]["requested"][0]["kind"])
            self.assertEqual(
                ["tests/REVIEW.md", "tests/nested/test_worker.py", "tests/test_parser.py"],
                [item["path"] for item in directory["inventory"]["files"]],
            )
            self.assertEqual("project", project["target"]["requested"][0]["kind"])
            self.assertIn("src/parser.py", [item["path"] for item in project["inventory"]["files"]])
            self.assertTrue(
                all(
                    item["inspection_kind"] == "not_inspected"
                    for item in project["inventory"]["files"]
                )
            )
            self.assertGreater(project["inventory"]["traversed_entries"], 0)

    def test_project_root_review_file_receives_root_guidance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "REVIEW.md").write_text("Review the harness.\n", encoding="utf-8")

            context = harness_context.resolve(context_args(root, paths=["."]))
            chain = next(
                item for item in context["guidance"] if "REVIEW.md" in item["paths"]
            )
            self.assertTrue(
                any(
                    source["source_kind"] == "repository"
                    and source["path"] == "REVIEW.md"
                    for source in chain["sources"]
                )
            )

    def test_related_context_is_separate_and_cannot_duplicate_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)

            context = harness_context.resolve(
                context_args(root, contexts=["src/parser.py", "docs/contract.md"])
            )
            self.assertEqual(
                ["docs/contract.md", "src/parser.py"],
                [item["path"] for item in context["context_inventory"]],
            )
            self.assertEqual(["tests/test_parser.py"], [item["path"] for item in context["inventory"]["files"]])

            with self.assertRaisesRegex(harness_context.ContextError, "duplicate"):
                harness_context.resolve(
                    context_args(root, contexts=["tests/test_parser.py"])
                )
            with self.assertRaisesRegex(harness_context.ContextError, "duplicate"):
                harness_context.resolve(
                    context_args(
                        root,
                        paths=["tests"],
                        contexts=["tests/test_parser.py"],
                    )
                )

    def test_traversal_ceiling_is_material_and_not_silent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            for name in ["a", "b", "c"]:
                (root / name).mkdir()

            context = harness_context.resolve(
                context_args(root, paths=["."], max_traversal_entries=2)
            )
            self.assertEqual(2, context["inventory"]["traversed_entries"])
            self.assertFalse(context["inventory"]["complete"])
            self.assertTrue(
                any(item["code"] == "scope_truncated" and item["material"] for item in context["limitations"])
            )

    def test_directory_iterator_never_consumes_beyond_traversal_ceiling(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()

            class GuardedScandir:
                def __init__(self):
                    self.calls = 0

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, traceback):
                    return False

                def __iter__(self):
                    return self

                def __next__(self):
                    self.calls += 1
                    if self.calls > 2:
                        raise AssertionError("scandir consumed beyond the traversal ceiling")
                    return SimpleNamespace(
                        name=f"entry-{self.calls}",
                        path=str(root / f"entry-{self.calls}"),
                    )

            guarded = GuardedScandir()
            with mock.patch.object(harness_context.os, "scandir", return_value=guarded):
                context = harness_context.resolve(
                    context_args(root, paths=["."], max_traversal_entries=2)
                )

            self.assertEqual(2, guarded.calls)
            self.assertEqual(2, context["inventory"]["traversed_entries"])
            self.assertEqual([], context["inventory"]["files"])
            self.assertFalse(context["inventory"]["complete"])
            self.assertTrue(
                any(
                    item["code"] == "scope_truncated" and item["material"]
                    for item in context["limitations"]
                )
            )

    def test_content_ceilings_preserve_records_and_make_omissions_material(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "a.txt").write_text("abcd", encoding="utf-8")
            (root / "b.txt").write_text("efgh", encoding="utf-8")

            per_file = harness_context.resolve(
                context_args(root, paths=["a.txt"], max_file_bytes=2)
            )
            self.assertEqual("oversized", per_file["inventory"]["files"][0]["inspection_kind"])
            self.assertFalse(per_file["inventory"]["complete"])

            aggregate = harness_context.resolve(
                context_args(
                    root,
                    paths=["."],
                    inspections=["a.txt", "b.txt"],
                    max_total_bytes=4,
                )
            )
            records = {item["path"]: item for item in aggregate["inventory"]["files"]}
            self.assertEqual("text", records["a.txt"]["inspection_kind"])
            self.assertEqual("not_inspected", records["b.txt"]["inspection_kind"])
            self.assertEqual(4, aggregate["inventory"]["read_bytes"])
            self.assertFalse(aggregate["inventory"]["complete"])

            broad_oversized = harness_context.resolve(
                context_args(root, paths=["."], max_file_bytes=2)
            )
            self.assertTrue(
                any(
                    item["inspection_kind"] == "oversized"
                    for item in broad_oversized["inventory"]["files"]
                )
            )
            self.assertFalse(broad_oversized["inventory"]["complete"])

    def test_opened_target_is_bound_to_preflight_identity_and_remaining_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            target = root / "target.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            replacement = root / "replacement.py"
            replacement.write_text("VALUE = 222\n", encoding="utf-8")
            original_read = harness_context._read_regular
            replaced = False

            def replace_before_open(path, maximum, **kwargs):
                nonlocal replaced
                if Path(path) == target and not replaced:
                    os.replace(replacement, target)
                    replaced = True
                return original_read(path, maximum, **kwargs)

            with mock.patch.object(
                harness_context,
                "_read_regular",
                side_effect=replace_before_open,
            ):
                context = harness_context.resolve(
                    context_args(root, paths=["target.py"], max_total_bytes=10)
                )

            self.assertTrue(replaced)
            self.assertFalse(context["inventory"]["complete"])
            self.assertEqual(
                "unreadable",
                context["inventory"]["files"][0]["inspection_kind"],
            )
            self.assertTrue(
                any(
                    item["code"] == "target_unreadable"
                    and item["material"]
                    and "snapshot changed" in item["message"]
                    for item in context["limitations"]
                )
            )

            stable = root / "stable.py"
            stable.write_bytes(b"1234")
            metadata = stable.lstat()
            snapshot = harness_context._filesystem_snapshot(stable, metadata)
            stable.write_bytes(b"12345")
            with self.assertRaisesRegex(harness_context.ContextError, "snapshot changed"):
                original_read(stable, 4, expected_snapshot=snapshot)

    def test_same_inode_target_and_context_changes_are_material(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            target = root / "target.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            context_path = root / "contract.md"
            context_path.write_text("Contract A\n", encoding="utf-8")
            original_read = harness_context._read_regular

            for changed_path, args, limitation_code in [
                (target, context_args(root, paths=["target.py"]), "target_unreadable"),
                (
                    context_path,
                    context_args(
                        root,
                        paths=["target.py"],
                        contexts=["contract.md"],
                    ),
                    "context_unavailable",
                ),
            ]:
                with self.subTest(path=changed_path.name):
                    before = changed_path.stat()
                    changed = False

                    def rewrite_before_open(path, maximum, **kwargs):
                        nonlocal changed
                        if Path(path) == changed_path and not changed:
                            replacement = (
                                "VALUE = 2\n"
                                if changed_path == target
                                else "Contract B\n"
                            )
                            changed_path.write_text(replacement, encoding="utf-8")
                            os.utime(
                                changed_path,
                                ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000),
                            )
                            changed = True
                        return original_read(path, maximum, **kwargs)

                    with mock.patch.object(
                        harness_context,
                        "_read_regular",
                        side_effect=rewrite_before_open,
                    ):
                        context = harness_context.resolve(args)

                    self.assertTrue(changed)
                    self.assertTrue(
                        any(
                            item["code"] == limitation_code
                            and item["material"]
                            and "snapshot changed" in item["message"]
                            for item in context["limitations"]
                        )
                    )

    def test_explicit_links_are_rejected_and_broad_links_are_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            outside = Path(temporary) / "outside.py"
            outside.write_text("VALUE = 1\n", encoding="utf-8")
            link = root / "link.py"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable")

            with self.assertRaisesRegex(harness_context.ContextError, "link-like"):
                harness_context.resolve(context_args(root, paths=["link.py"]))
            context = harness_context.resolve(context_args(root, paths=["."]))
            self.assertNotIn("link.py", [item["path"] for item in context["inventory"]["files"]])
            self.assertTrue(any(item["code"] == "link_skipped" for item in context["limitations"]))

    def test_windows_reparse_attribute_is_link_like(self):
        flag = 0x400
        metadata = SimpleNamespace(st_mode=0o100644, st_file_attributes=flag)
        with mock.patch.object(Path, "lstat", return_value=metadata):
            with mock.patch.object(
                harness_context.stat,
                "FILE_ATTRIBUTE_REPARSE_POINT",
                flag,
                create=True,
            ):
                self.assertTrue(harness_context._is_link_like(Path("fixture")))

    def test_filesystem_aliases_fail_closed_across_target_and_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "target.py").write_text("VALUE = 1\n", encoding="utf-8")
            alias = root / "alias.py"
            try:
                os.link(root / "target.py", alias)
            except OSError:
                self.skipTest("hard links unavailable")

            with self.assertRaisesRegex(harness_context.ContextError, "aliases"):
                harness_context.resolve(
                    context_args(root, paths=["target.py", "alias.py"])
                )
            with self.assertRaisesRegex(harness_context.ContextError, "aliases"):
                harness_context.resolve(
                    context_args(
                        root,
                        paths=["target.py"],
                        contexts=["alias.py"],
                    )
                )

            broad = harness_context.resolve(context_args(root, paths=["."]))
            self.assertFalse(broad["inventory"]["complete"])
            self.assertEqual(1, len(broad["inventory"]["files"]))
            self.assertTrue(
                any(item["code"] == "inventory_incomplete" for item in broad["limitations"])
            )

            selected_directory = root / "selected"
            selected_directory.mkdir()
            os.link(root / "target.py", selected_directory / "alias.py")
            explicit_and_broad = harness_context.resolve(
                context_args(root, paths=["target.py", "selected"])
            )
            self.assertFalse(explicit_and_broad["inventory"]["complete"])
            self.assertTrue(
                any(
                    "Explicit and broad" in item["message"]
                    for item in explicit_and_broad["limitations"]
                )
            )

            harness_directory = root / "harness"
            harness_directory.mkdir()
            (harness_directory / "check.py").write_text("VALUE = 2\n", encoding="utf-8")
            os.link(harness_directory / "check.py", root / "context-alias.py")
            with self.assertRaisesRegex(harness_context.ContextError, "harness and context aliases"):
                harness_context.resolve(
                    context_args(
                        root,
                        paths=["harness"],
                        contexts=["context-alias.py"],
                    )
                )

    def test_git_classifies_tracked_untracked_and_excludes_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
            (root / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "untracked.py").write_text("VALUE = 2\n", encoding="utf-8")
            (root / "ignored.txt").write_text("private cache\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", ".gitignore", "tracked.py"], check=True)

            context = harness_context.resolve(context_args(root, paths=["."]))
            tracking = {item["path"]: item["tracking"] for item in context["inventory"]["files"]}
            self.assertEqual("tracked", tracking["tracked.py"])
            self.assertEqual("untracked", tracking["untracked.py"])
            self.assertNotIn("ignored.txt", tracking)
            ignored = [item for item in context["limitations"] if item["code"] == "ignored_path"]
            self.assertTrue(ignored)
            self.assertIn("ignored.txt", ignored[0]["affected_paths"])

    def test_git_tracking_uses_literal_pathspecs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            special = root / "test[1].py"
            special.write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            environment = dict(os.environ)
            environment["GIT_LITERAL_PATHSPECS"] = "1"
            subprocess.run(
                ["git", "-C", str(root), "add", "--", "test[1].py"],
                check=True,
                env=environment,
            )

            context = harness_context.resolve(
                context_args(root, paths=["test[1].py"])
            )
            self.assertEqual("tracked", context["inventory"]["files"][0]["tracking"])

    def test_global_guidance_is_external_no_link_and_precedes_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            make_fixture(root)
            global_review = base / "REVIEW.md"
            global_review.write_bytes(b"Global rule.\r\n")

            context = harness_context.resolve(
                context_args(root, global_review_file=str(global_review))
            )
            kinds = [source["source_kind"] for source in context["guidance"][0]["sources"]]
            self.assertEqual(["skill", "user_global", "repository", "repository"], kinds)
            global_source = context["guidance"][0]["sources"][1]
            self.assertEqual(hashlib.sha256(b"Global rule.\n").hexdigest(), global_source["sha256"])

            with self.assertRaisesRegex(harness_context.ContextError, "outside"):
                harness_context.resolve(
                    context_args(root, global_review_file=str(root / "REVIEW.md"))
                )

    def test_external_authority_file_is_bound_to_preflight_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            make_fixture(root)
            global_review = base / "global-review.md"
            global_review.write_text("Original rule.\n", encoding="utf-8")
            before = global_review.stat()
            object_identity = harness_context._filesystem_identity(
                global_review,
                before,
            )
            original_read = harness_context._read_regular
            replaced = False

            def replace_before_open(path, maximum, **kwargs):
                nonlocal replaced
                if Path(path) == global_review and not replaced:
                    global_review.write_text("Modified rule.\n", encoding="utf-8")
                    os.utime(
                        global_review,
                        ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000),
                    )
                    replaced = True
                return original_read(path, maximum, **kwargs)

            with mock.patch.object(
                harness_context,
                "_read_regular",
                side_effect=replace_before_open,
            ):
                with self.assertRaisesRegex(
                    harness_context.ContextError,
                    "snapshot changed",
                ):
                    harness_context.resolve(
                        context_args(
                            root,
                            global_review_file=str(global_review),
                        )
                    )
            self.assertTrue(replaced)
            self.assertEqual(
                object_identity,
                harness_context._filesystem_identity(global_review),
            )

    def test_command_plan_is_frozen_but_never_executed(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            make_fixture(root)
            plan = base / "plan.json"
            plan.write_text(
                json.dumps(
                    [
                        {
                            "argv": ["python", "-m", "unittest"],
                            "cwd": ".",
                            "reason": "Check the selected harness.",
                            "expected_effects": ["Read repository files and create bounded temporary output."],
                            "timeout_seconds": 60,
                            "repetitions": 1,
                            "authorization_kind": "caller",
                            "authorization_source": "Caller approved this exact plan.",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            context = harness_context.resolve(context_args(root, command_plan=str(plan)))
            record = context["execution"][0]
            self.assertEqual("not_run", record["outcome"])
            self.assertEqual("caller", record["authorization"]["kind"])
            self.assertIsNone(record["exit_code"])

    def test_duplicate_json_members_and_repository_authority_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            make_fixture(root)
            duplicate = base / "duplicate.json"
            duplicate.write_text('[{"kind":"timing","kind":"failure"}]', encoding="utf-8")
            with self.assertRaisesRegex(harness_context.ContextError, "duplicate member"):
                harness_context.resolve(
                    context_args(root, evidence_metadata=str(duplicate))
                )

            in_repo = root / "plan.json"
            in_repo.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(harness_context.ContextError, "outside"):
                harness_context.resolve(context_args(root, command_plan=str(in_repo)))

            hardlink = base / "hardlink.json"
            try:
                os.link(duplicate, hardlink)
            except OSError:
                self.skipTest("hard links unavailable")
            with self.assertRaisesRegex(harness_context.ContextError, "hard-linked"):
                harness_context.resolve(
                    context_args(root, evidence_metadata=str(hardlink))
                )

    def test_duplicate_targets_context_and_inspection_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)

            with self.assertRaisesRegex(harness_context.ContextError, "duplicate requested"):
                harness_context.resolve(
                    context_args(
                        root,
                        paths=["tests/test_parser.py", "tests/test_parser.py"],
                    )
                )
            with self.assertRaisesRegex(harness_context.ContextError, "duplicate context"):
                harness_context.resolve(
                    context_args(
                        root,
                        contexts=["src/parser.py", "src/parser.py"],
                    )
                )
            with self.assertRaisesRegex(harness_context.ContextError, "duplicate inspection"):
                harness_context.resolve(
                    context_args(
                        root,
                        paths=["tests"],
                        inspections=[
                            "tests/test_parser.py",
                            "tests/test_parser.py",
                        ],
                    )
                )

    def test_caller_evidence_records_bounded_freshness_without_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            make_fixture(root)
            metadata = base / "evidence.json"
            metadata.write_text(
                json.dumps(
                    [
                        {
                            "kind": "timing",
                            "source_label": "Local timing summary",
                            "source_sha256": "a" * 64,
                            "observed_at": "2026-09-01T20:00:00Z",
                            "supplied_at": "2026-09-01T20:01:00Z",
                            "freshness": "fresh",
                            "freshness_basis": "Observed during the current working-tree audit.",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            context = harness_context.resolve(
                context_args(root, evidence_metadata=str(metadata))
            )
            source = context["evidence_sources"][0]
            self.assertEqual("S001", source["evidence_source_id"])
            self.assertNotIn("content", source)

            value = json.loads(metadata.read_text(encoding="utf-8"))
            value[0]["supplied_at"] = "2026-09-01T20:01:00"
            metadata.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(harness_context.ContextError, "RFC 3339"):
                harness_context.resolve(
                    context_args(root, evidence_metadata=str(metadata))
                )

            for invalid in [
                "20260901T200100Z",
                "2026-09-01 20:01:00Z",
                "2026-01-01T12:34:60Z",
                "2026-09-01T20:01:00+01:60",
                "2026-09-01T20:01:00+24:00",
            ]:
                value[0]["supplied_at"] = invalid
                metadata.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(harness_context.ContextError, "RFC 3339"):
                    harness_context.resolve(
                        context_args(root, evidence_metadata=str(metadata))
                    )

    def test_maximum_guidance_source_line_count_is_schema_representable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "REVIEW.md").write_bytes(
                b"\n" * harness_context.MAX_GUIDANCE_SOURCE_BYTES
            )

            context = harness_context.resolve(
                context_args(
                    root,
                    paths=["sample.py"],
                    max_guidance_bytes=harness_context.MAX_GUIDANCE_BYTES,
                )
            )
            source = next(
                item
                for item in context["guidance"][0]["sources"]
                if item["source_kind"] == "repository"
            )
            self.assertEqual(
                harness_context.MAX_GUIDANCE_SOURCE_BYTES,
                source["lines"],
            )

    def test_guidance_cardinality_ceiling_covers_inventory_and_empty_targets(self):
        schema = json.loads(
            (
                ROOT
                / "skills"
                / "verification-harness-audit"
                / "references"
                / "verification-harness-result.schema.json"
            ).read_text(encoding="utf-8")
        )
        expected = harness_context.MAX_FILES + harness_context.MAX_REQUESTED_TARGETS
        self.assertEqual(expected, harness_context.MAX_GUIDANCE_CHAINS)
        self.assertEqual(expected, harness_context.MAX_GUIDANCE_PATHS_PER_CHAIN)
        self.assertEqual(expected, schema["properties"]["guidance"]["maxItems"])
        self.assertEqual(
            expected,
            schema["$defs"]["guidance_chain"]["properties"]["paths"]["maxItems"],
        )

    def test_sparse_file_size_remains_schema_representable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            sparse = root / "sparse.bin"
            try:
                with sparse.open("wb") as handle:
                    handle.truncate((1 << 40) + 1)
            except OSError:
                self.skipTest("filesystem cannot create a sparse file above 1 TiB")

            context = harness_context.resolve(
                context_args(root, paths=["sparse.bin"])
            )
            record = context["inventory"]["files"][0]
            self.assertEqual((1 << 40) + 1, record["bytes"])
            schema = json.loads(
                (
                    ROOT
                    / "skills"
                    / "verification-harness-audit"
                    / "references"
                    / "verification-harness-result.schema.json"
                ).read_text(encoding="utf-8")
            )
            self.assertGreaterEqual(
                schema["$defs"]["inventory_file"]["properties"]["bytes"]["maximum"],
                record["bytes"],
            )

    def test_output_is_exclusive_and_control_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            context = harness_context.resolve(context_args(root))
            output = Path(temporary) / "context.json"

            harness_context._write(context, str(output))
            with self.assertRaises(harness_context.ContextError):
                harness_context._write(context, str(output))
            with self.assertRaisesRegex(harness_context.ContextError, "control"):
                harness_context.resolve(context_args(root, paths=["tests/\ntest.py"]))

            with self.assertRaisesRegex(harness_context.ContextError, "cannot resolve"):
                harness_context.resolve(context_args(root / "missing"))

    def test_installed_resolver_has_no_repository_script_dependency(self):
        source = (
            ROOT / "skills" / "verification-harness-audit" / "scripts" / "harness_context.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("from scripts", source)
        self.assertNotIn("import scripts", source)


if __name__ == "__main__":
    unittest.main()
