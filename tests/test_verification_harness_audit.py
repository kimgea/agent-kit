import hashlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
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
harness_result = load_module(
    "verification_harness_result",
    ROOT / "skills" / "verification-harness-audit" / "scripts" / "harness_result.py",
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


def same_path(left, right):
    try:
        return os.path.samefile(left, right)
    except OSError:
        pass
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(
        str(Path(right).resolve())
    )


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
                if not replaced and (
                    os.name == "nt"
                    or os.path.normcase(Path(path).name)
                    == os.path.normcase(target.name)
                ):
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
                        if same_path(path, changed_path) and not changed:
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

    def test_single_hard_link_alias_target_remains_inspectable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "target.py").write_text("VALUE = 1\n", encoding="utf-8")
            try:
                os.link(root / "target.py", root / "unselected-alias.py")
            except OSError:
                self.skipTest("hard links unavailable")

            context = harness_context.resolve(
                context_args(root, paths=["target.py"])
            )
            self.assertEqual(
                ["target.py"],
                [item["path"] for item in context["inventory"]["files"]],
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
                if same_path(path, global_review) and not replaced:
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

    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "O_NOFOLLOW"),
        "descriptor-relative race probe requires POSIX no-follow support",
    )
    def test_context_reads_and_output_remain_bound_during_parent_swap(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            trusted = base / "trusted"
            moved = base / "moved"
            outside = base / "outside"
            trusted.mkdir()
            outside.mkdir()
            source = trusted / "source.txt"
            source.write_text("trusted\n", encoding="utf-8")
            (outside / "source.txt").write_text("outside\n", encoding="utf-8")
            snapshot = harness_context._filesystem_snapshot(source, source.lstat())
            original_open = os.open
            raced = False

            def swap_before_read(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal raced
                if path == "source.txt" and dir_fd is not None and not raced:
                    raced = True
                    trusted.rename(moved)
                    trusted.symlink_to(outside, target_is_directory=True)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(
                harness_context.os, "open", side_effect=swap_before_read
            ):
                with self.assertRaisesRegex(
                    harness_context.ContextError, "snapshot changed"
                ):
                    harness_context._read_regular(
                        source,
                        64,
                        expected_snapshot=snapshot,
                    )

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            trusted = base / "trusted"
            moved = base / "moved"
            outside = base / "outside"
            trusted.mkdir()
            outside.mkdir()
            original_open = os.open
            raced = False

            def swap_before_write(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal raced
                if path == "context.json" and dir_fd is not None and not raced:
                    raced = True
                    trusted.rename(moved)
                    trusted.symlink_to(outside, target_is_directory=True)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(
                harness_context.os, "open", side_effect=swap_before_write
            ):
                harness_context._write_created_output(
                    trusted / "context.json", b"bound\n"
                )
            self.assertEqual(
                b"bound\n", (moved / "context.json").read_bytes()
            )
            self.assertFalse((outside / "context.json").exists())

    @unittest.skipUnless(os.name == "nt", "Windows handle-boundary probe")
    def test_windows_context_parent_handles_bind_swaps_and_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            trusted = base / "trusted"
            moved = base / "moved"
            outside_data = b"outside\n"
            trusted.mkdir()
            source = trusted / "source.txt"
            source.write_bytes(b"trusted\n")
            original_descriptor = harness_context._windows_file_descriptor
            swap_attempts = []

            def attempt_swap_before_open(*args, **kwargs):
                if swap_attempts:
                    return original_descriptor(*args, **kwargs)
                try:
                    trusted.rename(moved)
                except OSError:
                    swap_attempts.append("blocked")
                else:
                    swap_attempts.append("escaped")
                    trusted.mkdir()
                    (trusted / "source.txt").write_bytes(outside_data)
                return original_descriptor(*args, **kwargs)

            with mock.patch.object(
                harness_context,
                "_windows_file_descriptor",
                side_effect=attempt_swap_before_open,
            ):
                _, data = harness_context._read_regular(source, 64)
            self.assertEqual(b"trusted\n", data)
            self.assertIn(swap_attempts, (["blocked"], ["escaped"]))
            if swap_attempts == ["escaped"]:
                self.assertEqual(outside_data, source.read_bytes())
                source.unlink()
                trusted.rmdir()
                moved.rename(trusted)
            else:
                trusted.rename(moved)
                moved.rename(trusted)

            swap_attempts.clear()
            with mock.patch.object(
                harness_context,
                "_windows_file_descriptor",
                side_effect=attempt_swap_before_open,
            ):
                harness_context._write_created_output(
                    trusted / "context.json", b"bound\n"
                )
            self.assertIn(swap_attempts, (["blocked"], ["escaped"]))
            output_parent = moved if swap_attempts == ["escaped"] else trusted
            self.assertEqual(
                b"bound\n", (output_parent / "context.json").read_bytes()
            )
            if swap_attempts == ["escaped"]:
                self.assertFalse((trusted / "context.json").exists())
                (trusted / "source.txt").unlink()
                trusted.rmdir()
                moved.rename(trusted)
            else:
                trusted.rename(moved)
                moved.rename(trusted)

    def test_read_only_target_and_canonical_output_preserve_platform_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            make_fixture(root)
            target = root / "tests" / "test_parser.py"
            target.chmod(stat.S_IREAD)
            before_mode = stat.S_IMODE(target.stat().st_mode)
            output = base / "context.json"
            try:
                context = harness_context.resolve(context_args(root))
                harness_context._write(context, str(output))
                self.assertEqual(before_mode, stat.S_IMODE(target.stat().st_mode))
            finally:
                target.chmod(stat.S_IREAD | stat.S_IWRITE)

            encoded = output.read_bytes()
            self.assertTrue(encoded.endswith(b"\n"))
            self.assertNotIn(b"\r\n", encoded)
            if os.name == "posix":
                self.assertEqual(0o600, stat.S_IMODE(output.stat().st_mode))

    def test_all_resolver_material_limitation_classes_are_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            observed = set()

            truncated = harness_context.resolve(
                context_args(root, paths=["."], max_traversal_entries=1)
            )
            observed.update(
                item["code"] for item in truncated["limitations"] if item["material"]
            )

            binary = root / "tests" / "binary.bin"
            binary.write_bytes(b"\xff\x00")
            unreadable = harness_context.resolve(
                context_args(root, paths=["tests/binary.bin"])
            )
            observed.update(
                item["code"] for item in unreadable["limitations"] if item["material"]
            )
            part = harness_context.resolve(
                context_args(
                    root,
                    paths=[],
                    parts=["tests/binary.bin:1:1"],
                )
            )
            observed.update(
                item["code"] for item in part["limitations"] if item["material"]
            )

            context_unavailable = harness_context.resolve(
                context_args(root, contexts=["tests/binary.bin"])
            )
            observed.update(
                item["code"]
                for item in context_unavailable["limitations"]
                if item["material"]
            )

            (root / "REVIEW.md").write_bytes(
                b"x" * (harness_context.MAX_GUIDANCE_SOURCE_BYTES + 1)
            )
            guidance_unreadable = harness_context.resolve(context_args(root))
            observed.update(
                item["code"]
                for item in guidance_unreadable["limitations"]
                if item["material"]
            )

            (root / "REVIEW.md").write_text("r" * 700 + "\n", encoding="utf-8")
            (root / "tests" / "REVIEW.md").write_text(
                "t" * 700 + "\n", encoding="utf-8"
            )
            guidance_budget = harness_context.resolve(
                context_args(root, max_guidance_bytes=1024)
            )
            observed.update(
                item["code"]
                for item in guidance_budget["limitations"]
                if item["material"]
            )

            synthetic_inventory_limit = harness_context._limitation(
                "inventory_incomplete",
                "Tracking classification could not be completed.",
                [],
                True,
            )
            with mock.patch.object(
                harness_context,
                "_tracking",
                return_value=(
                    {"tests/test_parser.py": "unknown"},
                    [synthetic_inventory_limit],
                ),
            ):
                inventory_incomplete = harness_context.resolve(context_args(root))
            observed.update(
                item["code"]
                for item in inventory_incomplete["limitations"]
                if item["material"]
            )

            self.assertTrue(
                {
                    "scope_truncated",
                    "target_unreadable",
                    "part_unreadable",
                    "inventory_incomplete",
                    "guidance_unreadable",
                    "guidance_budget",
                    "context_unavailable",
                }
                <= observed,
                observed,
            )

    def test_installed_resolver_has_no_repository_script_dependency(self):
        source = (
            ROOT / "skills" / "verification-harness-audit" / "scripts" / "harness_context.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("from scripts", source)
        self.assertNotIn("import scripts", source)


def audit_draft(*, strength="essential", claim="observed_defect"):
    return {
        "summary": {
            "conclusion": "The selected harness has one bounded verification improvement."
        },
        "coverage": {
            "complete": True,
            "inspected_targets": ["T001"],
            "inspected_harness_paths": ["tests/test_parser.py"],
            "classified_non_harness_paths": [],
            "excluded": [],
            "context_paths": [],
        },
        "recommendations": [
            {
                "kind": "weak_assertion",
                "action": "strengthen",
                "strength": strength,
                "impact": "high",
                "confidence": "high",
                "decision": "ready",
                "decision_reason": "The existing required workflow fixes the intended outcome.",
                "claim": claim,
                "basis": "required_workflow",
                "basis_reference": "The selected test is the documented routine parser check.",
                "title": "Strengthen the parser assertion",
                "problem": "The selected assertion does not reject a documented invalid parser value.",
                "reason": "The routine check can remain green while the existing parser contract is broken.",
                "impact_summary": "A parser regression can escape the routine feedback loop.",
                "affected_targets": ["T001"],
                "affected_locations": [
                    {
                        "path": "tests/test_parser.py",
                        "start_line": 1,
                        "end_line": 2,
                    }
                ],
                "related_context": [],
                "evidence": [
                    {
                        "kind": "test",
                        "description": "The selected test contains only the shallow assertion.",
                        "location": {
                            "path": "tests/test_parser.py",
                            "start_line": 1,
                            "end_line": 2,
                        },
                        "source_id": None,
                    }
                ],
                "current_tier": "routine",
                "recommended_tier": "routine",
                "safe_direction": {
                    "outcome": "Make the routine assertion fail for the documented invalid value.",
                    "acceptance_evidence": [
                        "The routine test fails when the invalid value is accepted."
                    ],
                    "alternatives": [],
                    "suggested_paths": ["tests/test_parser.py"],
                },
            }
        ],
        "limitations": [],
    }


class ResultTests(unittest.TestCase):
    def make_context(self, root, **overrides):
        return harness_context.resolve(context_args(root, **overrides))

    def test_finalizer_derives_improvements_ids_fingerprints_and_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            context = self.make_context(root)

            result = harness_result.finalize(context, audit_draft())

            self.assertEqual("IMPROVEMENTS", result["status"])
            self.assertEqual("R001", result["recommendations"][0]["recommendation_id"])
            self.assertRegex(result["recommendations"][0]["fingerprint"], r"^[0-9a-f]{64}$")
            self.assertEqual(1, result["summary"]["recommendation_counts"]["essential"])
            self.assertEqual(1, result["summary"]["ready"])
            self.assertEqual(1, result["summary"]["observed_defects"])
            self.assertTrue(all("content" not in source for chain in result["guidance"] for source in chain["sources"]))
            self.assertIs(result, harness_result._validate_result(result))

    def test_advisory_only_complete_result_is_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            draft = audit_draft(strength="strong", claim="improvement_opportunity")

            result = harness_result.finalize(self.make_context(root), draft)

            self.assertEqual("PASS", result["status"])
            self.assertEqual(1, result["summary"]["recommendation_counts"]["strong"])

    def test_material_limitation_precedes_known_essential_recommendation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            draft = audit_draft()
            draft["coverage"]["complete"] = False
            draft["limitations"] = [
                {
                    "code": "evidence_missing",
                    "message": "A required local contract source was unavailable.",
                    "affected_paths": ["tests/test_parser.py"],
                    "material": True,
                }
            ]

            result = harness_result.finalize(self.make_context(root), draft)

            self.assertEqual("INCOMPLETE", result["status"])
            self.assertEqual("essential", result["recommendations"][0]["strength"])

    def test_draft_cannot_own_authority_or_expand_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            context = self.make_context(root)
            draft = audit_draft()
            draft["target"] = context["target"]
            with self.assertRaisesRegex(harness_result.ResultError, "unknown fields"):
                harness_result.finalize(context, draft)

            for field, value in {
                "inventory": context["inventory"],
                "guidance": context["guidance"],
                "execution": context["execution"],
                "evidence_sources": context["evidence_sources"],
                "status": "PASS",
                "context_sha256": "0" * 64,
            }.items():
                with self.subTest(forged_field=field):
                    forged = audit_draft()
                    forged[field] = value
                    with self.assertRaisesRegex(
                        harness_result.ResultError, "unknown fields"
                    ):
                        harness_result.finalize(context, forged)

            draft = audit_draft()
            draft["recommendations"][0]["safe_direction"]["suggested_paths"] = [
                "outside/new_test.py"
            ]
            with self.assertRaisesRegex(harness_result.ResultError, "expands"):
                harness_result.finalize(context, draft)

            context_with_evidence = self.make_context(
                root,
                contexts=["src/parser.py"],
            )
            for evidence_only_path in ("src/parser.py", "REVIEW.md"):
                draft = audit_draft()
                if evidence_only_path == "src/parser.py":
                    draft["coverage"]["context_paths"] = ["src/parser.py"]
                draft["recommendations"][0]["safe_direction"]["suggested_paths"] = [
                    evidence_only_path
                ]
                with self.assertRaisesRegex(harness_result.ResultError, "expands"):
                    harness_result.finalize(context_with_evidence, draft)

    def test_every_semantic_material_limitation_derives_incomplete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            context = self.make_context(root)
            semantic_codes = sorted(
                harness_result.LIMITATION_CODES
                - harness_result.RESOLVER_LIMITATION_CODES
            )

            for code in semantic_codes:
                with self.subTest(code=code):
                    draft = audit_draft(
                        strength="strong",
                        claim="improvement_opportunity",
                    )
                    draft["coverage"]["complete"] = False
                    draft["limitations"] = [
                        {
                            "code": code,
                            "message": f"Material {code} fixture.",
                            "affected_paths": ["tests/test_parser.py"],
                            "material": True,
                        }
                    ]
                    result = harness_result.finalize(context, draft)
                    self.assertEqual("INCOMPLETE", result["status"])

    def test_private_guidance_content_is_omitted_from_canonical_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            make_fixture(root)
            global_review = base / "global-review.md"
            private_text = "private machine guidance fixture"
            global_review.write_text(private_text + "\n", encoding="utf-8")

            result = harness_result.finalize(
                self.make_context(
                    root,
                    global_review_file=str(global_review),
                ),
                audit_draft(),
            )
            serialized = json.dumps(result, sort_keys=True)

            self.assertNotIn(private_text, serialized)
            global_source = next(
                source
                for chain in result["guidance"]
                for source in chain["sources"]
                if source["source_kind"] == "user_global"
            )
            self.assertEqual(str(global_review.resolve()), global_source["path"])
            self.assertRegex(global_source["sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn("content", global_source)

    def test_user_global_command_authority_is_bound_to_resolved_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            make_fixture(root)
            global_review = base / "global-review.md"
            global_review.write_text(
                "The exact bounded unit command may run when requested.\n",
                encoding="utf-8",
            )
            plan = base / "plan.json"

            def write_plan(source: str) -> None:
                plan.write_text(
                    json.dumps(
                        [
                            {
                                "argv": [sys.executable, "-m", "unittest"],
                                "cwd": ".",
                                "reason": "Run the globally authorized bounded unit check.",
                                "expected_effects": ["Read repository files only."],
                                "timeout_seconds": 60,
                                "repetitions": 1,
                                "authorization_kind": "user_global",
                                "authorization_source": source,
                            }
                        ]
                    ),
                    encoding="utf-8",
                )

            write_plan(str(global_review))
            context = self.make_context(
                root,
                global_review_file=str(global_review),
                command_plan=str(plan),
            )
            global_source = next(
                source
                for chain in context["guidance"]
                for source in chain["sources"]
                if source["source_kind"] == "user_global"
            )
            authorization = context["execution"][0]["authorization"]
            self.assertEqual("user_global", authorization["kind"])
            self.assertEqual(str(global_review.resolve()), authorization["source"])
            self.assertEqual(global_source["sha256"], authorization["source_sha256"])

            result = harness_result.finalize(context, audit_draft())
            self.assertEqual(
                global_source["sha256"],
                result["execution"][0]["authorization"]["source_sha256"],
            )

            with self.assertRaisesRegex(
                harness_context.ContextError,
                "requires --global-review-file",
            ):
                self.make_context(root, command_plan=str(plan))

            write_plan(str(base / "wrong-global-review.md"))
            with self.assertRaisesRegex(
                harness_context.ContextError,
                "must reference the resolved global source path",
            ):
                self.make_context(
                    root,
                    global_review_file=str(global_review),
                    command_plan=str(plan),
                )

            forged = json.loads(json.dumps(context))
            forged["execution"][0]["authorization"]["source_sha256"] = "0" * 64
            with self.assertRaisesRegex(
                harness_result.ResultError,
                "does not match resolved guidance",
            ):
                harness_result._validate_context(forged)

    def test_timeout_recording_is_process_independent_and_target_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            make_fixture(root)
            marker = base / "command-must-not-run"
            plan = base / "plan.json"
            plan.write_text(
                json.dumps(
                    [
                        {
                            "argv": [
                                sys.executable,
                                "-c",
                                f"open({str(marker)!r}, 'w').write('ran')",
                            ],
                            "cwd": ".",
                            "reason": "Exercise the bounded timeout record contract.",
                            "expected_effects": ["Read the selected fixture only."],
                            "timeout_seconds": 1,
                            "repetitions": 1,
                            "authorization_kind": "caller",
                            "authorization_source": "Caller authorized this exact fixture plan.",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            context = self.make_context(root, command_plan=str(plan))
            record = context["execution"][0]
            record.update(
                {
                    "outcome": "timed_out",
                    "exit_code": None,
                    "duration_ms": 1001,
                    "output_sha256": hashlib.sha256(
                        b"bounded timeout summary"
                    ).hexdigest(),
                    "summary": "The authorized check reached its one-second timeout.",
                }
            )

            harness_result._validate_context(context)
            result = harness_result.finalize(context, audit_draft())

            self.assertEqual("timed_out", result["execution"][0]["outcome"])
            self.assertEqual(1001, result["execution"][0]["duration_ms"])
            self.assertFalse(marker.exists())

    def test_canonical_result_expansion_is_bounded_before_validation_succeeds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            result = harness_result.finalize(self.make_context(root), audit_draft())
            compact_bytes = len(harness_result._canonical_json(result))
            rendered_bytes = len(
                (harness_result._json_result_text(result) + "\n").encode("utf-8")
            )
            self.assertGreater(rendered_bytes, compact_bytes)
            bounded_limit = (compact_bytes + rendered_bytes) // 2

            with mock.patch.object(
                harness_result,
                "MAX_JSON_BYTES",
                bounded_limit,
            ):
                with self.assertRaisesRegex(
                    harness_result.ResultError,
                    "machine-readable size ceiling",
                ):
                    harness_result._validate_result(result)

    def test_essential_and_observed_slow_claims_require_supported_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            context = self.make_context(root)

            draft = audit_draft()
            item = draft["recommendations"][0]
            item["basis"] = "new_policy"
            item["decision"] = "decision_required"
            with self.assertRaisesRegex(harness_result.ResultError, "essential strength"):
                harness_result.finalize(context, draft)

            draft = audit_draft()
            item = draft["recommendations"][0]
            item["kind"] = "slow_feedback"
            with self.assertRaisesRegex(harness_result.ResultError, "measured evidence"):
                harness_result.finalize(context, draft)

            evidence_file = Path(temporary) / "evidence.json"
            evidence_file.write_text(
                json.dumps(
                    [
                        {
                            "kind": "timing",
                            "source_label": "Fresh local timing",
                            "source_sha256": "a" * 64,
                            "observed_at": "2026-09-01T20:00:00Z",
                            "supplied_at": "2026-09-01T20:01:00Z",
                            "freshness": "fresh",
                            "freshness_basis": "Measured for this exact working-tree snapshot.",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            measured_context = self.make_context(
                root,
                evidence_metadata=str(evidence_file),
            )
            draft = audit_draft()
            item = draft["recommendations"][0]
            item["kind"] = "slow_feedback"
            item["evidence"] = [
                {
                    "kind": "caller_supplied",
                    "description": "The exact routine check exceeded the accepted feedback window.",
                    "location": None,
                    "source_id": "S001",
                }
            ]
            self.assertEqual(
                "IMPROVEMENTS",
                harness_result.finalize(measured_context, draft)["status"],
            )

            other_file = Path(temporary) / "other-evidence.json"
            other_file.write_text(
                json.dumps(
                    [
                        {
                            "kind": "other",
                            "source_label": "Unclassified observation",
                            "source_sha256": "b" * 64,
                            "observed_at": "2026-09-01T20:00:00Z",
                            "supplied_at": "2026-09-01T20:01:00Z",
                            "freshness": "fresh",
                            "freshness_basis": "Supplied for this snapshot.",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            other_context = self.make_context(
                root,
                evidence_metadata=str(other_file),
            )
            with self.assertRaisesRegex(harness_result.ResultError, "measured evidence"):
                harness_result.finalize(other_context, draft)

            flaky_draft = audit_draft()
            flaky_draft["recommendations"][0]["kind"] = "flakiness"
            flaky_draft["recommendations"][0]["evidence"] = [
                {
                    "kind": "caller_supplied",
                    "description": "The supplied timing record does not establish variable outcomes.",
                    "location": None,
                    "source_id": "S001",
                }
            ]
            with self.assertRaisesRegex(harness_result.ResultError, "measured evidence"):
                harness_result.finalize(measured_context, flaky_draft)

    def test_part_findings_stay_within_the_selected_line_range(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            context = self.make_context(
                root,
                paths=[],
                parts=["tests/test_parser.py:1:1"],
            )
            draft = audit_draft()

            with self.assertRaisesRegex(harness_result.ResultError, "affected_targets"):
                harness_result.finalize(context, draft)

            for field in ("affected_locations", "evidence"):
                location = (
                    draft["recommendations"][0][field][0]
                    if field == "affected_locations"
                    else draft["recommendations"][0][field][0]["location"]
                )
                location["end_line"] = 1
            self.assertEqual("IMPROVEMENTS", harness_result.finalize(context, draft)["status"])

    def test_coverage_cannot_mark_an_excluded_file_target_as_inspected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            draft = audit_draft()
            draft["coverage"]["complete"] = False
            draft["coverage"]["inspected_harness_paths"] = []
            draft["coverage"]["excluded"] = [
                {
                    "path": "tests/test_parser.py",
                    "reason": "The selected target was unavailable for semantic inspection.",
                    "material": True,
                }
            ]

            with self.assertRaisesRegex(harness_result.ResultError, "excluded target"):
                harness_result.finalize(self.make_context(root), draft)

            non_harness = audit_draft()
            non_harness["coverage"]["inspected_harness_paths"] = []
            non_harness["coverage"]["classified_non_harness_paths"] = [
                "tests/test_parser.py"
            ]
            non_harness["recommendations"] = []
            result = harness_result.finalize(self.make_context(root), non_harness)
            self.assertEqual("PASS", result["status"])

    def test_evidence_requires_content_that_was_actually_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            context = self.make_context(root)
            draft = audit_draft()
            draft["recommendations"][0]["evidence"][0]["location"] = None
            with self.assertRaisesRegex(harness_result.ResultError, "location is required"):
                harness_result.finalize(context, draft)

            known = harness_result._known_location_paths(
                context["inventory"],
                context["context_inventory"],
                context["guidance"],
                audit_draft()["coverage"],
            )
            self.assertIn("tests/test_parser.py", known)
            self.assertIn("REVIEW.md", known)
            review_source = next(
                source
                for source in context["guidance"][0]["sources"]
                if source["path"] == "tests/REVIEW.md"
            )
            review_source["loaded"] = False
            known = harness_result._known_location_paths(
                context["inventory"],
                context["context_inventory"],
                context["guidance"],
                audit_draft()["coverage"],
            )
            self.assertNotIn("tests/REVIEW.md", known)

    def test_nested_guidance_only_supports_its_applicable_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            context = self.make_context(
                root,
                paths=["src/parser.py", "tests/test_parser.py"],
            )
            target_by_path = {
                item["path"]: item["target_id"]
                for item in context["target"]["requested"]
            }
            draft = audit_draft()
            draft["coverage"]["inspected_targets"] = sorted(target_by_path.values())
            draft["coverage"]["inspected_harness_paths"] = [
                "src/parser.py",
                "tests/test_parser.py",
            ]
            item = draft["recommendations"][0]
            item["affected_targets"] = [target_by_path["src/parser.py"]]
            item["affected_locations"] = [
                {"path": "src/parser.py", "start_line": 1, "end_line": 2}
            ]
            item["safe_direction"]["suggested_paths"] = ["src/parser.py"]
            item["evidence"] = [
                {
                    "kind": "guidance",
                    "description": "A nested test rule was presented as parser guidance.",
                    "location": {
                        "path": "tests/REVIEW.md",
                        "start_line": 1,
                        "end_line": 1,
                    },
                    "source_id": None,
                }
            ]
            with self.assertRaisesRegex(harness_result.ResultError, "does not apply"):
                harness_result.finalize(context, draft)

            item["evidence"] = [
                {
                    "kind": "code",
                    "description": "The parser implementation is the affected artifact.",
                    "location": {
                        "path": "src/parser.py",
                        "start_line": 1,
                        "end_line": 2,
                    },
                    "source_id": None,
                }
            ]
            item["related_context"] = [
                {
                    "path": "tests/REVIEW.md",
                    "start_line": 1,
                    "end_line": 1,
                }
            ]
            with self.assertRaisesRegex(harness_result.ResultError, "does not apply"):
                harness_result.finalize(context, draft)

    def test_fingerprints_handle_nullable_ranges_and_totally_order_ties(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            context = self.make_context(root)
            first = audit_draft()
            item = first["recommendations"][0]
            item["affected_locations"].append(
                {
                    "path": "tests/test_parser.py",
                    "start_line": None,
                    "end_line": None,
                }
            )
            other = json.loads(json.dumps(item))
            other["safe_direction"]["outcome"] = (
                "Make an equivalent existing-contract assertion fail for the invalid value."
            )
            first["recommendations"].append(other)
            reversed_draft = json.loads(json.dumps(first))
            reversed_draft["recommendations"].reverse()

            ordered = harness_result.finalize(context, first)["recommendations"]
            reversed_ordered = harness_result.finalize(context, reversed_draft)[
                "recommendations"
            ]
            self.assertEqual(
                [entry["fingerprint"] for entry in ordered],
                [entry["fingerprint"] for entry in reversed_ordered],
            )
            human = harness_result.render_human(
                harness_result.finalize(context, first)
            )
            self.assertIn("tests/test\\_parser\\.py:1-2", human)
            self.assertIn("  - tests/test\\_parser\\.py\n", human)

    def test_project_root_suggestion_matches_the_public_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            context = self.make_context(root, paths=["."])
            draft = {
                "summary": {"conclusion": "The empty selected project has no harness yet."},
                "coverage": {
                    "complete": True,
                    "inspected_targets": ["T001"],
                    "inspected_harness_paths": [],
                    "classified_non_harness_paths": [],
                    "excluded": [],
                    "context_paths": [],
                },
                "recommendations": [
                    {
                        "kind": "missing_coverage",
                        "action": "add",
                        "strength": "strong",
                        "impact": "medium",
                        "confidence": "medium",
                        "decision": "decision_required",
                        "decision_reason": "The project has no existing requirement selecting a check.",
                        "claim": "inferred_risk",
                        "basis": "uncertain",
                        "basis_reference": "The selected project contains no harness artifacts.",
                        "title": "Decide whether the project needs a routine check",
                        "problem": "No local verification harness is present in the selected project.",
                        "reason": "There is no automated feedback path to inspect.",
                        "impact_summary": "Future changes may lack routine automated feedback.",
                        "affected_targets": ["T001"],
                        "affected_locations": [
                            {"path": ".", "start_line": None, "end_line": None}
                        ],
                        "related_context": [],
                        "evidence": [
                            {
                                "kind": "reasoning",
                                "description": "The bounded inventory is empty.",
                                "location": None,
                                "source_id": None,
                            }
                        ],
                        "current_tier": "absent",
                        "recommended_tier": "unknown",
                        "safe_direction": {
                            "outcome": "Choose an existing requirement before adding a routine check.",
                            "acceptance_evidence": [
                                "A project requirement identifies the behavior a check should protect."
                            ],
                            "alternatives": [],
                            "suggested_paths": ["."],
                        },
                    }
                ],
                "limitations": [],
            }

            result = harness_result.finalize(context, draft)
            self.assertEqual(["."], result["recommendations"][0]["safe_direction"]["suggested_paths"])
            schema = json.loads(
                (
                    ROOT
                    / "skills"
                    / "verification-harness-audit"
                    / "references"
                    / "verification-harness-result.schema.json"
                ).read_text(encoding="utf-8")
            )
            path_items = schema["$defs"]["safe_direction"]["properties"][
                "suggested_paths"
            ]["items"]["anyOf"]
            self.assertIn({"const": "."}, path_items)

    def test_stale_resolver_context_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            context = self.make_context(root)
            (root / "tests" / "test_parser.py").write_text(
                "def test_parse():\n    assert False\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(harness_result.ResultError, "stale"):
                harness_result.finalize(context, audit_draft())

    def test_context_rejects_forged_caller_authority_and_time_order(self):
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
                            "reason": "Run the selected routine tests.",
                            "expected_effects": ["Read tests and create temporary output."],
                            "timeout_seconds": 60,
                            "repetitions": 1,
                            "authorization_kind": "caller",
                            "authorization_source": "Caller approved this exact plan.",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            context = self.make_context(root, command_plan=str(plan))
            context["execution"][0]["authorization"]["source_sha256"] = "0" * 64
            with self.assertRaisesRegex(harness_result.ResultError, "digest"):
                harness_result._validate_context(context)

            evidence = base / "evidence.json"
            evidence.write_text(
                json.dumps(
                    [
                        {
                            "kind": "history",
                            "source_label": "Local history",
                            "source_sha256": "b" * 64,
                            "observed_at": "2026-09-01T20:02:00Z",
                            "supplied_at": "2026-09-01T20:01:00Z",
                            "freshness": "fresh",
                            "freshness_basis": "Bounded local record.",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            context = self.make_context(root, evidence_metadata=str(evidence))
            with self.assertRaisesRegex(harness_result.ResultError, "after supplied_at"):
                harness_result._validate_context(context)

    def test_validation_and_human_rendering_are_canonical_and_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            draft = audit_draft()
            draft["recommendations"][0]["title"] = (
                "<script>alert(1)</script>\nnext **bold** ```"
            )
            result = harness_result.finalize(self.make_context(root), draft)

            human = harness_result.render_human(result)
            self.assertIn(
                "&lt;script&gt;alert\\(1\\)&lt;/script&gt;\\nnext \\*\\*bold\\*\\* \\`\\`\\`",
                human,
            )
            self.assertNotIn("<script>", human)
            self.assertIn("- Basis reference:", human)
            self.assertIn("- Tier: routine → routine", human)
            self.assertIn("- Evidence:", human)
            self.assertIn("The selected test contains only the shallow assertion", human)
            self.assertIn("tests/test\\_parser\\.py:1-2", human)
            both = harness_result._format_result(result, "both")
            self.assertIn(human, both)
            self.assertIn("Canonical JSON", both)
            self.assertNotIn("```\"", both)

            malformed = json.loads(json.dumps(result))
            malformed["summary"]["ready"] = 0
            with self.assertRaisesRegex(harness_result.ResultError, "counts"):
                harness_result._validate_result(malformed)
            malformed = json.loads(json.dumps(result))
            malformed["recommendations"][0]["fingerprint"] = "0" * 64
            with self.assertRaisesRegex(harness_result.ResultError, "fingerprint"):
                harness_result._validate_result(malformed)

    def test_canonical_result_rejects_reordered_recommendations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            draft = audit_draft()
            advisory = json.loads(json.dumps(draft["recommendations"][0]))
            advisory["strength"] = "strong"
            advisory["claim"] = "improvement_opportunity"
            advisory["kind"] = "discoverability"
            advisory["action"] = "document"
            advisory["title"] = "Document the routine parser command"
            draft["recommendations"].append(advisory)
            result = harness_result.finalize(self.make_context(root), draft)

            result["recommendations"].reverse()
            for index, item in enumerate(result["recommendations"], 1):
                item["recommendation_id"] = f"R{index:03d}"
            with self.assertRaisesRegex(harness_result.ResultError, "canonical order"):
                harness_result._validate_result(result)

    def test_json_reader_rejects_duplicate_depth_and_link_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            duplicate = base / "duplicate.json"
            duplicate.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaisesRegex(harness_result.ResultError, "duplicate"):
                harness_result._read_json(str(duplicate))

            deep = base / "deep.json"
            deep.write_text("[" * 101 + "0" + "]" * 101, encoding="utf-8")
            with self.assertRaisesRegex(harness_result.ResultError, "nesting limit"):
                harness_result._read_json(str(deep))

            link = base / "link.json"
            try:
                link.symlink_to(duplicate)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(harness_result.ResultError, "link-like"):
                harness_result._read_json(str(link))

    def test_output_rejects_input_aliases_and_hardlink_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source.json"
            source.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(harness_result.ResultError, "input file"):
                harness_result._write_output(
                    "result",
                    str(source),
                    True,
                    input_paths=[source],
                )

            destination = base / "destination.json"
            alias = base / "alias.json"
            destination.write_text("old", encoding="utf-8")
            try:
                os.link(destination, alias)
            except OSError:
                self.skipTest("hard links unavailable")
            with self.assertRaisesRegex(harness_result.ResultError, "unsafe"):
                harness_result._write_output(
                    "result",
                    str(destination),
                    True,
                    input_paths=[],
                )

            fresh = base / "fresh.json"
            harness_result._write_output("result", str(fresh), False, input_paths=[])
            self.assertEqual("result\n", fresh.read_text(encoding="utf-8"))

    @unittest.skipUnless(os.name == "posix", "final-entry race probe requires POSIX rename semantics")
    def test_output_never_replaces_or_cleans_up_a_swapped_final_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            destination = base / "result.json"
            moved = base / "opened.json"
            destination.write_text("owned", encoding="utf-8")
            original_write = harness_result._write_descriptor

            def swap_then_write(descriptor, data):
                destination.rename(moved)
                destination.write_text("unrelated", encoding="utf-8")
                original_write(descriptor, data)

            with mock.patch.object(
                harness_result,
                "_write_descriptor",
                side_effect=swap_then_write,
            ):
                with self.assertRaisesRegex(harness_result.ResultError, "entry changed"):
                    harness_result._write_output(
                        "replacement",
                        str(destination),
                        True,
                        input_paths=[],
                    )
            self.assertEqual("unrelated", destination.read_text(encoding="utf-8"))
            self.assertEqual("replacement\n", moved.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            destination = base / "result.json"
            moved = base / "opened.json"

            def swap_then_fail(descriptor, data):
                del descriptor, data
                destination.rename(moved)
                destination.write_text("unrelated", encoding="utf-8")
                raise OSError("simulated write failure")

            with mock.patch.object(
                harness_result,
                "_write_descriptor",
                side_effect=swap_then_fail,
            ):
                with self.assertRaisesRegex(OSError, "simulated"):
                    harness_result._write_output(
                        "partial",
                        str(destination),
                        False,
                        input_paths=[],
                    )
            self.assertEqual("unrelated", destination.read_text(encoding="utf-8"))
            self.assertTrue(moved.exists())

    def test_stdout_uses_utf8_even_with_a_legacy_text_encoding(self):
        raw = io.BytesIO()
        legacy_stdout = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
        with mock.patch.object(harness_result.sys, "stdout", legacy_stdout):
            harness_result._write_output(
                "ready — routine → release",
                None,
                False,
                input_paths=[],
            )
            self.assertEqual(
                "ready — routine → release\n".encode("utf-8"),
                raw.getvalue(),
            )
        legacy_stdout.detach()

    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "O_NOFOLLOW"),
        "descriptor-relative race probe requires POSIX no-follow support",
    )
    def test_input_and_output_remain_bound_when_parent_path_is_swapped(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            trusted = base / "trusted"
            moved = base / "moved"
            outside = base / "outside"
            trusted.mkdir()
            outside.mkdir()
            (trusted / "input.json").write_text('{"origin":"trusted"}', encoding="utf-8")
            (outside / "input.json").write_text('{"origin":"outside"}', encoding="utf-8")
            original_open = os.open
            raced = False

            def swap_before_input_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal raced
                if path == "input.json" and dir_fd is not None and not raced:
                    raced = True
                    trusted.rename(moved)
                    trusted.symlink_to(outside, target_is_directory=True)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(harness_result.os, "open", side_effect=swap_before_input_open):
                value = harness_result._read_json(str(trusted / "input.json"))
            self.assertEqual("trusted", value["origin"])

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            trusted = base / "trusted"
            moved = base / "moved"
            outside = base / "outside"
            trusted.mkdir()
            outside.mkdir()
            original_open = os.open
            raced = False

            def swap_before_output_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal raced
                if path == "result.json" and dir_fd is not None and not raced:
                    raced = True
                    trusted.rename(moved)
                    trusted.symlink_to(outside, target_is_directory=True)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(harness_result.os, "open", side_effect=swap_before_output_open):
                harness_result._write_output(
                    "bound",
                    str(trusted / "result.json"),
                    False,
                    input_paths=[],
                )
            self.assertEqual("bound\n", (moved / "result.json").read_text(encoding="utf-8"))
            self.assertFalse((outside / "result.json").exists())

    @unittest.skipUnless(os.name == "nt", "Windows handle-boundary probe")
    def test_windows_parent_handles_bind_swaps_reject_reparse_and_are_released(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            trusted = base / "trusted"
            moved = base / "moved"
            trusted.mkdir()
            input_file = trusted / "input.json"
            input_file.write_text('{"bound":true}', encoding="utf-8")
            original_descriptor = harness_result._windows_file_descriptor
            swap_attempts = []

            def attempt_swap_before_open(*args, **kwargs):
                if swap_attempts:
                    return original_descriptor(*args, **kwargs)
                try:
                    trusted.rename(moved)
                except OSError:
                    swap_attempts.append("blocked")
                else:
                    swap_attempts.append("escaped")
                    trusted.mkdir()
                    (trusted / "input.json").write_text(
                        '{"bound":false}', encoding="utf-8"
                    )
                return original_descriptor(*args, **kwargs)

            with mock.patch.object(
                harness_result,
                "_windows_file_descriptor",
                side_effect=attempt_swap_before_open,
            ):
                self.assertTrue(harness_result._read_json(str(input_file))["bound"])
            self.assertIn(swap_attempts, (["blocked"], ["escaped"]))
            if swap_attempts == ["escaped"]:
                self.assertFalse(harness_result._read_json(str(input_file))["bound"])
                input_file.unlink()
                trusted.rmdir()
                moved.rename(trusted)
            else:
                trusted.rename(moved)
                moved.rename(trusted)

            output = trusted / "result.json"
            swap_attempts.clear()
            with mock.patch.object(
                harness_result,
                "_windows_file_descriptor",
                side_effect=attempt_swap_before_open,
            ):
                harness_result._write_output(
                    "bound",
                    str(output),
                    False,
                    input_paths=[],
                )
            self.assertIn(swap_attempts, (["blocked"], ["escaped"]))
            output_parent = moved if swap_attempts == ["escaped"] else trusted
            self.assertEqual(
                "bound\n", (output_parent / output.name).read_text(encoding="utf-8")
            )
            if swap_attempts == ["escaped"]:
                self.assertFalse(output.exists())
                input_file.unlink()
                trusted.rmdir()
                moved.rename(trusted)
            else:
                trusted.rename(moved)
                moved.rename(trusted)

            failed_output = trusted / "failed.json"
            with mock.patch.object(
                harness_result,
                "_write_descriptor",
                side_effect=OSError("simulated write failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated"):
                    harness_result._write_output(
                        "partial",
                        str(failed_output),
                        False,
                        input_paths=[],
                    )
            self.assertTrue(failed_output.exists())
            trusted.rename(moved)
            moved.rename(trusted)

            real_parent = base / "real-parent"
            linked_parent = base / "linked-parent"
            real_parent.mkdir()
            (real_parent / "input.json").write_text("{}", encoding="utf-8")
            try:
                linked_parent.symlink_to(real_parent, target_is_directory=True)
            except OSError:
                with mock.patch.object(
                    harness_result,
                    "_windows_create_handle",
                    return_value=123,
                ), mock.patch.object(
                    harness_result,
                    "_windows_handle_attributes",
                    return_value=(0x00000010 | 0x00000400, 1),
                ), mock.patch.object(
                    harness_result,
                    "_windows_close_handle",
                ) as close_handle:
                    with self.assertRaisesRegex(
                        harness_result.ResultError,
                        "link-like|reparse",
                    ):
                        with harness_result._windows_locked_parent(input_file):
                            pass
                    close_handle.assert_called_once_with(123)
            else:
                with self.assertRaisesRegex(harness_result.ResultError, "link-like|reparse"):
                    harness_result._read_json(str(linked_parent / "input.json"))

            with mock.patch.object(
                harness_result,
                "_windows_create_handle",
                side_effect=harness_result.ResultError("safe Windows primitive unavailable"),
            ):
                with self.assertRaisesRegex(harness_result.ResultError, "unavailable"):
                    harness_result._read_json(str(input_file))

    def test_cli_finalize_validate_and_render_share_one_canonical_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            make_fixture(root)
            context_file = base / "context.json"
            draft_file = base / "draft.json"
            result_file = base / "result.json"
            context_file.write_text(
                json.dumps(self.make_context(root)),
                encoding="utf-8",
            )
            draft_file.write_text(json.dumps(audit_draft()), encoding="utf-8")
            script = (
                ROOT
                / "skills"
                / "verification-harness-audit"
                / "scripts"
                / "harness_result.py"
            )

            finalized = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "finalize",
                    "--context",
                    str(context_file),
                    "--draft",
                    str(draft_file),
                    "--format",
                    "json",
                    "--output",
                    str(result_file),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(0, finalized.returncode, finalized.stderr)
            self.assertEqual("", finalized.stdout)

            validated = subprocess.run(
                [sys.executable, str(script), "validate", "--input", str(result_file)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(0, validated.returncode, validated.stderr)
            self.assertIn("valid verification-harness-audit result", validated.stdout)

            rendered = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "render",
                    "--input",
                    str(result_file),
                    "--format",
                    "human",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(0, rendered.returncode, rendered.stderr)
            self.assertIn("Verification harness audit: IMPROVEMENTS", rendered.stdout)

    def test_installed_result_helper_has_no_repository_script_dependency(self):
        source = (
            ROOT / "skills" / "verification-harness-audit" / "scripts" / "harness_result.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("from scripts", source)
        self.assertNotIn("import scripts", source)

    def test_canonical_shape_mutations_never_escape_as_unexpected_exceptions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            make_fixture(root)
            result = harness_result.finalize(self.make_context(root), audit_draft())

            paths = []
            pending = [((), result)]
            while pending:
                path, value = pending.pop()
                if isinstance(value, dict):
                    for key, child in value.items():
                        paths.append((*path, key))
                        pending.append(((*path, key), child))
                elif isinstance(value, list):
                    for index, child in enumerate(value):
                        paths.append((*path, index))
                        pending.append(((*path, index), child))

            for path in paths:
                mutated = json.loads(json.dumps(result))
                parent = mutated
                for component in path[:-1]:
                    parent = parent[component]
                original = parent[path[-1]]
                for replacement in (None, [], {}, True, 0, ""):
                    if replacement == original and type(replacement) is type(original):
                        continue
                    candidate = json.loads(json.dumps(mutated))
                    target = candidate
                    for component in path[:-1]:
                        target = target[component]
                    target[path[-1]] = replacement
                    try:
                        harness_result._validate_result(candidate)
                    except harness_result.ResultError:
                        pass
                    except Exception as exc:  # pragma: no cover - assertion details the path
                        self.fail(f"unexpected {type(exc).__name__} at {path}: {exc}")

                if isinstance(parent, dict):
                    candidate = json.loads(json.dumps(result))
                    target = candidate
                    for component in path[:-1]:
                        target = target[component]
                    del target[path[-1]]
                    try:
                        harness_result._validate_result(candidate)
                    except harness_result.ResultError:
                        pass
                    except Exception as exc:  # pragma: no cover - assertion details the path
                        self.fail(f"unexpected {type(exc).__name__} deleting {path}: {exc}")


if __name__ == "__main__":
    unittest.main()
