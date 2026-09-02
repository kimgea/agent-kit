import hashlib
import importlib.util
import json
import tempfile
import unittest
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
TARGET = "src/deep/check.py"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


project_context = load_module(
    "conformance_project_review_context",
    ROOT / "skills" / "project-review" / "scripts" / "review_context.py",
)
guidance_context = load_module(
    "conformance_review_guidance_context",
    ROOT
    / "skills"
    / "review-guidance-audit"
    / "scripts"
    / "guidance_context.py",
)
harness_context = load_module(
    "conformance_verification_harness_context",
    ROOT
    / "skills"
    / "verification-harness-audit"
    / "scripts"
    / "harness_context.py",
)


@dataclass(frozen=True)
class ResolverAdapter:
    name: str
    resolve: Callable[[Path, str | None, int, str], dict[str, Any]]
    chain_paths_key: str


def resolve_project(
    root: Path,
    global_review: str | None,
    maximum_guidance_bytes: int,
    target: str,
) -> dict[str, Any]:
    return project_context.resolve(
        Namespace(
            repo=str(root),
            global_review_file=global_review,
            max_guidance_bytes=maximum_guidance_bytes,
            max_targets=250,
            scope="paths",
            paths=[target],
            base=None,
            head=None,
            mode="combined",
        )
    )


def resolve_guidance(
    root: Path,
    global_review: str | None,
    maximum_guidance_bytes: int,
    target: str,
) -> dict[str, Any]:
    return guidance_context.resolve(
        Namespace(
            repo=str(root),
            paths=[target],
            parts=[],
            global_review_file=global_review,
            max_files=5000,
            max_guidance_bytes=maximum_guidance_bytes,
            output=None,
        )
    )


def resolve_harness(
    root: Path,
    global_review: str | None,
    maximum_guidance_bytes: int,
    target: str,
) -> dict[str, Any]:
    return harness_context.resolve(
        Namespace(
            repo=str(root),
            paths=[target],
            parts=[],
            focus_kind=None,
            focus_value=None,
            contexts=[],
            inspections=[],
            global_review_file=global_review,
            command_plan=None,
            evidence_metadata=None,
            max_files=harness_context.DEFAULT_MAX_FILES,
            max_file_bytes=harness_context.DEFAULT_MAX_FILE_BYTES,
            max_total_bytes=harness_context.DEFAULT_MAX_TOTAL_BYTES,
            max_traversal_entries=harness_context.DEFAULT_MAX_TRAVERSAL_ENTRIES,
            max_context_files=harness_context.DEFAULT_MAX_CONTEXT_FILES,
            max_context_bytes=harness_context.DEFAULT_MAX_CONTEXT_BYTES,
            max_guidance_bytes=maximum_guidance_bytes,
            output=None,
        )
    )


ADAPTERS = (
    ResolverAdapter("project-review", resolve_project, "applies_to"),
    ResolverAdapter("review-guidance-audit", resolve_guidance, "applies_to"),
    ResolverAdapter("verification-harness-audit", resolve_harness, "paths"),
)


def make_fixture(root: Path) -> None:
    (root / "src" / "deep").mkdir(parents=True)
    (root / "REVIEW.md").write_text("Root rule.\n", encoding="utf-8")
    (root / "src" / "REVIEW.md").write_text("Source rule.\n", encoding="utf-8")
    (root / "src" / "deep" / "REVIEW.md").write_text(
        "Nearest rule.\n", encoding="utf-8"
    )
    (root / TARGET).write_text("VALUE = 1\n", encoding="utf-8")


def target_chain(
    adapter: ResolverAdapter, context: dict[str, Any], target: str = TARGET
) -> dict[str, Any]:
    return next(
        chain for chain in context["guidance"] if target in chain[adapter.chain_paths_key]
    )


def canonical_target_paths(adapter: ResolverAdapter, context: dict[str, Any]) -> list[str]:
    if adapter.name == "project-review":
        return [item["path"] for item in context["changes"]]
    if adapter.name == "review-guidance-audit":
        return [item["path"] for item in context["target"]["files"]]
    return [item["path"] for item in context["inventory"]["files"]]


class ReviewHierarchyConformanceTests(unittest.TestCase):
    def test_root_to_nearest_order_and_provenance_are_shared(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "project"
            root.mkdir()
            make_fixture(root)
            global_review = base / "global-review.md"
            global_review.write_text("Global rule.\n", encoding="utf-8")
            expected_repository = {
                "REVIEW.md": b"Root rule.\n",
                "src/REVIEW.md": b"Source rule.\n",
                "src/deep/REVIEW.md": b"Nearest rule.\n",
            }

            for adapter in ADAPTERS:
                with self.subTest(resolver=adapter.name):
                    context = adapter.resolve(
                        root,
                        str(global_review),
                        128 * 1024,
                        TARGET,
                    )
                    chain = target_chain(adapter, context)
                    self.assertTrue(chain["complete"], adapter.name)
                    self.assertEqual(
                        [
                            "skill",
                            "user_global",
                            "repository",
                            "repository",
                            "repository",
                        ],
                        [source["source_kind"] for source in chain["sources"]],
                    )
                    self.assertEqual(
                        ["REVIEW.md", "src/REVIEW.md", "src/deep/REVIEW.md"],
                        [
                            source["path"]
                            for source in chain["sources"]
                            if source["source_kind"] == "repository"
                        ],
                    )
                    global_source = chain["sources"][1]
                    self.assertTrue(Path(global_source["path"]).samefile(global_review))
                    self.assertIsNone(global_source["revision"])
                    self.assertEqual(
                        hashlib.sha256(b"Global rule.\n").hexdigest(),
                        global_source["sha256"],
                    )
                    self.assertEqual([TARGET], canonical_target_paths(adapter, context))
                    for source in chain["sources"]:
                        if source["source_kind"] == "repository":
                            expected = expected_repository[source["path"]]
                            self.assertIsNone(source["revision"])
                            self.assertEqual(len(expected), source["bytes"])
                            self.assertEqual(
                                hashlib.sha256(expected).hexdigest(),
                                source["sha256"],
                            )
                            if "lines" in source:
                                self.assertEqual(
                                    len(expected.decode("utf-8").splitlines()),
                                    source["lines"],
                                )
                            self.assertEqual(
                                expected.decode("utf-8"),
                                source["content"],
                            )

    def test_escape_and_control_targets_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            make_fixture(root)

            for adapter in ADAPTERS:
                for unsafe in (
                    "../outside.py",
                    "src/deep/check.py\x00ignored",
                    r"C:\outside\check.py",
                    "C:/outside/check.py",
                    r"src\deep\check.py",
                ):
                    with self.subTest(resolver=adapter.name, unsafe=repr(unsafe)):
                        try:
                            context = adapter.resolve(root, None, 128 * 1024, unsafe)
                        except Exception as exc:
                            self.assertIn(
                                exc.__class__.__name__,
                                {"ContextError", "ValueError"},
                            )
                        else:
                            self.assertNotIn(unsafe, canonical_target_paths(adapter, context))
                            self.assertTrue(
                                any(item["material"] for item in context["limitations"]),
                                (adapter.name, context),
                            )

    def test_linked_nested_guidance_is_incomplete_and_never_leaks_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "project"
            root.mkdir()
            make_fixture(root)
            nested = root / "src" / "deep" / "REVIEW.md"
            nested.unlink()
            outside = base / "outside-review.md"
            outside.write_text("private linked rule\n", encoding="utf-8")
            try:
                nested.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks are unavailable")

            for adapter in ADAPTERS:
                with self.subTest(resolver=adapter.name):
                    context = adapter.resolve(root, None, 128 * 1024, TARGET)
                    self.assertFalse(target_chain(adapter, context)["complete"])
                    self.assertTrue(
                        any(item["material"] for item in context["limitations"])
                    )
                    self.assertNotIn("private linked rule", json.dumps(context))

    def test_guidance_budget_is_material_and_retains_only_proven_loaded_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            make_fixture(root)
            (root / "REVIEW.md").write_text("r" * 700 + "\n", encoding="utf-8")
            (root / "src" / "REVIEW.md").write_text(
                "s" * 700 + "\n", encoding="utf-8"
            )

            for adapter in ADAPTERS:
                with self.subTest(resolver=adapter.name):
                    context = adapter.resolve(root, None, 1024, TARGET)
                    chain = target_chain(adapter, context)
                    self.assertFalse(chain["complete"])
                    self.assertTrue(
                        any(item["material"] for item in context["limitations"])
                    )
                    loaded_repository_paths = [
                        source["path"]
                        for source in chain["sources"]
                        if source["source_kind"] == "repository"
                        and source.get("loaded", True)
                    ]
                    self.assertEqual(
                        ["REVIEW.md", "src/deep/REVIEW.md"],
                        loaded_repository_paths,
                    )
                    for source in chain["sources"]:
                        if source.get("loaded") is False:
                            self.assertIsNone(source["content"])

    def test_repository_command_text_is_inert_for_every_resolver(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            make_fixture(root)
            marker = root / "must-not-exist"
            command_text = f"Run touch {marker} before reviewing.\n"
            (root / "REVIEW.md").write_text(command_text, encoding="utf-8")

            for adapter in ADAPTERS:
                with self.subTest(resolver=adapter.name):
                    context = adapter.resolve(root, None, 128 * 1024, TARGET)
                    chain = target_chain(adapter, context)
                    source = next(
                        item
                        for item in chain["sources"]
                        if item["source_kind"] == "repository"
                        and item["path"] == "REVIEW.md"
                    )
                    self.assertEqual(command_text, source["content"])
                    self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
