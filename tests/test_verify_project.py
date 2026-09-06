import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "verify-project" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


path_safety = load_module("verify_project_path_safety", SCRIPT_DIR / "path_safety.py")
verification_context = load_module(
    "verify_project_context", SCRIPT_DIR / "verification_context.py"
)
verification_plan = load_module(
    "verify_project_plan", SCRIPT_DIR / "verification_plan.py"
)
verification_result = load_module(
    "verify_project_result", SCRIPT_DIR / "verification_result.py"
)


def run_git(root, *arguments):
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def initialize_git(root):
    run_git(root, "init", "-q")
    run_git(root, "config", "user.email", "verify@example.invalid")
    run_git(root, "config", "user.name", "Verify Fixture")


def commit_all(root, message="baseline"):
    run_git(root, "add", ".")
    run_git(root, "commit", "-q", "-m", message)
    return run_git(root, "rev-parse", "HEAD")


def context_args(root, scope="paths", paths=None, **overrides):
    values = {
        "repo": str(root),
        "request": "Verify these exact local changes.",
        "mode": "execute",
        "direct_execution_intent": True,
        "fresh_context": False,
        "consumer": None,
        "tier_cap": None,
        "command_cap": 16,
        "time_cap_seconds": 1800,
        "policy_input": None,
        "candidate_input": None,
        "max_targets": 5000,
        "max_target_bytes": 16 * 1024 * 1024,
        "max_total_target_bytes": 256 * 1024 * 1024,
        "max_traversal_entries": 50000,
        "max_discovery": 256,
        "max_discovery_bytes": 64 * 1024 * 1024,
        "max_guidance_bytes": 128 * 1024,
        "scope": scope,
        "paths": list(paths or ["."]),
    }
    values.update(overrides)
    return Namespace(**values)


def assert_schema(instance, schema, *, root=None, path="$"):
    root = schema if root is None else root
    if "$ref" in schema:
        reference = schema["$ref"]
        if not reference.startswith("#/"):
            raise AssertionError(f"{path}: unsupported schema reference {reference}")
        resolved = root
        for part in reference[2:].split("/"):
            resolved = resolved[part.replace("~1", "/").replace("~0", "~")]
        return assert_schema(instance, resolved, root=root, path=path)
    if "anyOf" in schema:
        errors = []
        for option in schema["anyOf"]:
            try:
                assert_schema(instance, option, root=root, path=path)
                break
            except AssertionError as exc:
                errors.append(str(exc))
        else:
            raise AssertionError(f"{path}: no anyOf branch matched: {errors}")
    if "const" in schema and instance != schema["const"]:
        raise AssertionError(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise AssertionError(f"{path}: value {instance!r} is outside enum")
    expected_type = schema.get("type")
    if expected_type is not None:
        names = [expected_type] if isinstance(expected_type, str) else expected_type
        matches = {
            "object": lambda value: isinstance(value, dict),
            "array": lambda value: isinstance(value, list),
            "string": lambda value: isinstance(value, str),
            "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
            "boolean": lambda value: isinstance(value, bool),
            "null": lambda value: value is None,
        }
        if not any(matches[name](instance) for name in names):
            raise AssertionError(f"{path}: expected schema type {names}")
    if isinstance(instance, dict):
        required = set(schema.get("required", []))
        missing = required - set(instance)
        if missing:
            raise AssertionError(f"{path}: missing keys {sorted(missing)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            if extra:
                raise AssertionError(f"{path}: extra keys {sorted(extra)}")
        for key, value in instance.items():
            if key in properties:
                assert_schema(value, properties[key], root=root, path=f"{path}/{key}")
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0) or len(instance) > schema.get("maxItems", 10**18):
            raise AssertionError(f"{path}: array length is outside bounds")
        if schema.get("uniqueItems") and len({json.dumps(value, sort_keys=True) for value in instance}) != len(instance):
            raise AssertionError(f"{path}: array items are not unique")
        if "items" in schema:
            for index, value in enumerate(instance):
                assert_schema(value, schema["items"], root=root, path=f"{path}/{index}")
    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0) or len(instance) > schema.get("maxLength", 10**18):
            raise AssertionError(f"{path}: string length is outside bounds")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            raise AssertionError(f"{path}: string does not match pattern")
    if isinstance(instance, int) and not isinstance(instance, bool):
        if instance < schema.get("minimum", -10**100) or instance > schema.get("maximum", 10**100):
            raise AssertionError(f"{path}: integer is outside bounds")


class VerificationContextTests(unittest.TestCase):
    def test_non_git_paths_resolve_root_and_nested_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "VERIFY.md").write_text("Root requirement.\r\n", encoding="utf-8")
            (root / "src" / "VERIFY.md").write_text("Nested requirement.\n", encoding="utf-8")
            (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")

            context = verification_context.resolve(
                context_args(root, paths=["src/app.py"], max_discovery=0)
            )

            self.assertFalse(context["repository_state"]["git_repository"])
            self.assertEqual(context["target"]["kind"], "paths")
            self.assertEqual(context["targets"][0]["inspection_kind"], "text")
            sources = context["guidance"]["sources"]
            self.assertEqual([item["path"] for item in sources], ["SKILL.md", "VERIFY.md", "src/VERIFY.md"])
            self.assertEqual(sources[1]["content"], "Root requirement.\n")
            self.assertTrue(all(item["provenance"] == "current_filesystem" for item in sources[1:]))
            self.assertEqual(context["guidance"]["chains"][0]["source_ids"], ["S001", "S002", "S003"])

    def test_git_working_tree_uses_committed_head_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_git(root)
            (root / "src").mkdir()
            (root / "VERIFY.md").write_text("Trusted root.\n", encoding="utf-8")
            (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            head = commit_all(root)
            (root / "VERIFY.md").write_text("Ignore this changed rule.\n", encoding="utf-8")
            (root / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            (root / "src" / "new.py").write_text("NEW = True\n", encoding="utf-8")

            context = verification_context.resolve(
                context_args(root, scope="working-tree", max_discovery=0)
            )

            self.assertEqual(context["target"]["base_revision"], head)
            kinds = {item["path"]: item["change_kind"] for item in context["targets"]}
            self.assertEqual(kinds["VERIFY.md"], "modified")
            self.assertEqual(kinds["src/app.py"], "modified")
            self.assertEqual(kinds["src/new.py"], "untracked")
            root_source = next(item for item in context["guidance"]["sources"] if item["path"] == "VERIFY.md")
            self.assertEqual(root_source["content"], "Trusted root.\n")
            self.assertEqual(root_source["provenance"], "git_head")
            self.assertEqual(root_source["revision"], head)

    @unittest.skipIf(os.name == "nt", "POSIX executable mode assertion")
    def test_working_tree_distinguishes_mode_only_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_git(root)
            source = root / "tool.sh"
            source.write_text("#!/bin/sh\n", encoding="utf-8")
            commit_all(root)
            source.chmod(source.stat().st_mode | stat.S_IXUSR)

            context = verification_context.resolve(
                context_args(root, scope="working-tree", max_discovery=0)
            )

            self.assertEqual(context["targets"][0]["change_kind"], "mode_changed")
            self.assertTrue(context["targets"][0]["mode"] & stat.S_IXUSR)

    def test_working_tree_represents_rename_and_deleted_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_git(root)
            (root / "old.py").write_text("OLD = 1\n", encoding="utf-8")
            (root / "gone.py").write_text("GONE = 1\n", encoding="utf-8")
            commit_all(root)
            (root / "old.py").rename(root / "new.py")
            (root / "gone.py").unlink()

            context = verification_context.resolve(
                context_args(root, scope="working-tree", max_discovery=0)
            )

            records = {item["path"]: item for item in context["targets"]}
            self.assertEqual(records["new.py"]["change_kind"], "renamed")
            self.assertEqual(records["new.py"]["old_path"], "old.py")
            self.assertEqual(records["gone.py"]["presence"], "absent")
            self.assertIsNone(records["gone.py"]["sha256"])

    def test_rename_retains_distinct_source_and_destination_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_git(root)
            (root / "old").mkdir()
            (root / "new").mkdir()
            (root / "old" / "VERIFY.md").write_text("Old subtree check.\n", encoding="utf-8")
            (root / "new" / "VERIFY.md").write_text("New subtree check.\n", encoding="utf-8")
            (root / "old" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            commit_all(root)
            (root / "old" / "module.py").rename(root / "new" / "module.py")

            context = verification_context.resolve(
                context_args(root, scope="working-tree", max_discovery=0)
            )

            record = next(item for item in context["targets"] if item["path"] == "new/module.py")
            self.assertIsNotNone(record["old_guidance_chain_id"])
            self.assertNotEqual(record["guidance_chain_id"], record["old_guidance_chain_id"])
            chains = {item["chain_id"]: item for item in context["guidance"]["chains"]}
            sources = {item["source_id"]: item["path"] for item in context["guidance"]["sources"]}
            destination_paths = [sources[item] for item in chains[record["guidance_chain_id"]]["source_ids"]]
            source_paths = [sources[item] for item in chains[record["old_guidance_chain_id"]]["source_ids"]]
            self.assertIn("new/VERIFY.md", destination_paths)
            self.assertIn("old/VERIFY.md", source_paths)

    def test_directory_scope_excludes_gitignored_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_git(root)
            (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "kept.py").write_text("KEPT = 1\n", encoding="utf-8")
            (root / "src" / "ignored.txt").write_text("private\n", encoding="utf-8")
            commit_all(root)

            context = verification_context.resolve(
                context_args(root, paths=["src"], max_discovery=0)
            )

            self.assertEqual([item["path"] for item in context["targets"]], ["src/kept.py"])

    def test_non_git_project_scope_is_a_complete_bounded_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "app.py").write_text("APP = 1\n", encoding="utf-8")
            (root / "src" / "module.py").write_text("MODULE = 1\n", encoding="utf-8")

            context = verification_context.resolve(
                context_args(root, paths=["."], max_discovery=0)
            )

            self.assertEqual(context["target"]["kind"], "paths")
            self.assertEqual(
                [value["path"] for value in context["targets"]],
                ["app.py", "src/module.py"],
            )
            self.assertTrue(all(value["change_kind"] == "snapshot" for value in context["targets"]))
            self.assertFalse(any(value["material"] for value in context["limitations"]))

    def test_multiple_paths_keep_distinct_effective_guidance_chains(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one").mkdir()
            (root / "two").mkdir()
            (root / "VERIFY.md").write_text("Root.\n", encoding="utf-8")
            (root / "one" / "VERIFY.md").write_text("One.\n", encoding="utf-8")
            (root / "two" / "VERIFY.md").write_text("Two.\n", encoding="utf-8")
            (root / "one" / "app.py").write_text("ONE = 1\n", encoding="utf-8")
            (root / "two" / "app.py").write_text("TWO = 2\n", encoding="utf-8")

            context = verification_context.resolve(
                context_args(root, paths=["one/app.py", "two/app.py"], max_discovery=0)
            )

            self.assertEqual(len(context["targets"]), 2)
            self.assertNotEqual(
                context["targets"][0]["guidance_chain_id"],
                context["targets"][1]["guidance_chain_id"],
            )
            self.assertEqual(len(context["guidance"]["chains"]), 2)

    def test_explicit_link_and_hard_link_targets_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            link = root / "link.py"
            try:
                link.symlink_to(source)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(verification_context.ContextError, "link-like"):
                verification_context.resolve(context_args(root, paths=["link.py"]))
            hard = root / "hard.py"
            try:
                os.link(source, hard)
            except OSError:
                self.skipTest("hard links unavailable")
            with self.assertRaisesRegex(verification_context.ContextError, "hard-linked"):
                verification_context.resolve(context_args(root, paths=["source.py"]))

    @unittest.skipIf(os.name == "nt", "directory symlink setup is platform-specific")
    def test_repository_root_rejects_link_like_ancestor(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            real = base / "real" / "project"
            real.mkdir(parents=True)
            (real / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            alias = base / "alias"
            alias.symlink_to(base / "real", target_is_directory=True)

            with self.assertRaisesRegex(verification_context.ContextError, "link-like"):
                verification_context.resolve(
                    context_args(alias / "project", paths=["app.py"])
                )

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor-relative output probe")
    def test_created_output_stays_bound_when_parent_path_is_swapped(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            trusted = base / "trusted"
            moved = base / "moved"
            outside = base / "outside"
            trusted.mkdir()
            outside.mkdir()
            original_open = path_safety.os.open
            raced = False

            def swap_before_leaf_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal raced
                if path == "result.json" and dir_fd is not None and not raced:
                    raced = True
                    trusted.rename(moved)
                    trusted.symlink_to(outside, target_is_directory=True)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            try:
                with mock.patch.object(path_safety.os, "open", side_effect=swap_before_leaf_open):
                    path_safety.write_created_output(
                        trusted / "result.json", b"bound\n"
                    )
                self.assertTrue(raced)
                self.assertEqual((moved / "result.json").read_bytes(), b"bound\n")
                self.assertFalse((outside / "result.json").exists())
            finally:
                if trusted.is_symlink():
                    trusted.unlink()
                if moved.exists():
                    moved.rename(trusted)

    @unittest.skipUnless(os.name == "nt", "Windows handle-boundary probe")
    def test_windows_parent_chain_rejects_raced_reparse(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            trusted = base / "trusted"
            moved = base / "moved"
            outside = base / "outside"
            trusted.mkdir()
            outside.mkdir()
            source = trusted / "source.txt"
            source.write_bytes(b"trusted\n")
            (outside / source.name).write_bytes(b"outside\n")
            probe = base / "probe-link"
            try:
                probe.symlink_to(outside, target_is_directory=True)
                probe.unlink()
            except OSError:
                self.skipTest("directory symlinks unavailable")
            original_absolute = path_safety._windows_create_handle
            original_relative = path_safety._windows_relative_handle

            def restore_parent():
                if trusted.is_symlink():
                    trusted.unlink()
                if moved.exists():
                    moved.rename(trusted)

            def exercise(action):
                raced = False

                def replace_unopened_child(parent_handle, name, **kwargs):
                    nonlocal raced
                    if kwargs.get("directory") and name == trusted.name and not raced:
                        trusted.rename(moved)
                        trusted.symlink_to(outside, target_is_directory=True)
                        raced = True
                    return original_relative(parent_handle, name, **kwargs)

                try:
                    with mock.patch.object(
                        path_safety, "_windows_create_handle", wraps=original_absolute
                    ) as absolute_open, mock.patch.object(
                        path_safety,
                        "_windows_relative_handle",
                        side_effect=replace_unopened_child,
                    ):
                        with self.assertRaises(path_safety.SafetyError):
                            action()
                    self.assertTrue(raced)
                    self.assertEqual(absolute_open.call_count, 1)
                    self.assertEqual(
                        Path(source.absolute().anchor),
                        Path(absolute_open.call_args.args[0]),
                    )
                finally:
                    restore_parent()

            exercise(lambda: path_safety.read_regular(source, 64))
            output = trusted / "result.json"
            exercise(lambda: path_safety.write_created_output(output, b"bound\n"))
            self.assertFalse((outside / output.name).exists())

    def test_paths_reject_escape_controls_and_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "file.py").write_text("VALUE = 1\n", encoding="utf-8")
            for value in ("../file.py", "/tmp/file.py", "src\\file.py", "bad\nfile.py"):
                with self.subTest(value=value):
                    with self.assertRaises((verification_context.ContextError, path_safety.SafetyError)):
                        verification_context.resolve(context_args(root, paths=[value]))
            with self.assertRaisesRegex(verification_context.ContextError, "duplicate"):
                verification_context.resolve(context_args(root, paths=["file.py", "file.py"]))

    def test_candidate_authority_is_derived_from_lead_owned_input(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            candidate_file = Path(lead_directory) / "candidates.json"
            candidates = [
                {
                    "argv": ["python", "-m", "unittest"],
                    "cwd": ".",
                    "provenance": ["caller"],
                    "timeout_seconds": 60,
                    "repetitions": 1,
                    "expected_effects": ["repository_read", "local_process"],
                    "artifact_boundaries": [],
                },
                {
                    "argv": ["tool", "--online"],
                    "cwd": ".",
                    "provenance": ["caller"],
                    "timeout_seconds": 60,
                    "repetitions": 1,
                    "expected_effects": ["network_access"],
                    "artifact_boundaries": [],
                },
            ]
            candidate_file.write_text(json.dumps(candidates), encoding="utf-8")

            context = verification_context.resolve(
                context_args(root, paths=["app.py"], candidate_input=str(candidate_file), max_discovery=0)
            )

            self.assertTrue(context["command_candidates"][0]["authority"]["authorized"])
            self.assertEqual(context["command_candidates"][0]["authority"]["source_kind"], "caller")
            self.assertFalse(context["command_candidates"][1]["authority"]["authorized"])
            self.assertEqual(context["command_candidates"][1]["authority"]["source_kind"], "none")

    def test_project_policy_cannot_grant_candidate_authority(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            policy_file = Path(lead_directory) / "policy.json"
            policy_file.write_text(
                json.dumps([{"kind": "project", "label": "repo policy", "content": "Run the check."}]),
                encoding="utf-8",
            )
            candidate_file = Path(lead_directory) / "candidates.json"
            candidate_file.write_text(
                json.dumps([{
                    "argv": ["tool", "check"],
                    "cwd": ".",
                    "provenance": ["repo policy"],
                    "authority_policy": "repo policy",
                    "timeout_seconds": 60,
                    "repetitions": 1,
                    "expected_effects": ["repository_read", "local_process"],
                    "artifact_boundaries": [],
                }]),
                encoding="utf-8",
            )

            context = verification_context.resolve(
                context_args(
                    root,
                    paths=["app.py"],
                    policy_input=str(policy_file),
                    candidate_input=str(candidate_file),
                    max_discovery=0,
                )
            )

            self.assertFalse(context["command_candidates"][0]["authority"]["authorized"])
            self.assertEqual(context["command_candidates"][0]["authority"]["source_kind"], "none")

    def test_consequential_effect_classes_never_receive_verify_project_authority(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            consequential = sorted(verification_context.ALL_EFFECTS - verification_context.ORDINARY_EFFECTS)
            candidate_file = Path(lead_directory) / "candidates.json"
            candidate_file.write_text(
                json.dumps([
                    {
                        "argv": ["tool", effect],
                        "cwd": ".",
                        "provenance": ["caller"],
                        "timeout_seconds": 60,
                        "repetitions": 1,
                        "expected_effects": [effect],
                        "artifact_boundaries": [],
                    }
                    for effect in consequential
                ]),
                encoding="utf-8",
            )

            context = verification_context.resolve(
                context_args(
                    root,
                    paths=["app.py"],
                    candidate_input=str(candidate_file),
                    max_discovery=0,
                )
            )

            self.assertEqual(len(context["command_candidates"]), len(consequential))
            self.assertTrue(all(
                not value["authority"]["authorized"]
                and value["authority"]["source_kind"] == "none"
                for value in context["command_candidates"]
            ))

    def test_inline_evaluation_and_generic_dispatch_are_inert_unauthorized_candidates(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            commands = [
                ["bash", "-c", "echo injected"],
                ["cmd.exe", "/c", "echo injected"],
                ["powershell", "-EncodedCommand", "AAAA"],
                ["python", "-c", "print('injected')"],
                ["node", "--eval", "console.log('injected')"],
                ["env", "python", "-m", "unittest"],
            ]
            candidate_file = Path(lead_directory) / "candidates.json"
            candidate_file.write_text(
                json.dumps([
                    {
                        "argv": argv,
                        "cwd": ".",
                        "provenance": ["caller"],
                        "timeout_seconds": 60,
                        "repetitions": 1,
                        "expected_effects": ["repository_read", "local_process"],
                        "artifact_boundaries": [],
                    }
                    for argv in commands
                ]),
                encoding="utf-8",
            )

            context = verification_context.resolve(
                context_args(
                    root,
                    paths=["app.py"],
                    candidate_input=str(candidate_file),
                    max_discovery=0,
                )
            )

            self.assertTrue(all(
                not value["authority"]["authorized"]
                for value in context["command_candidates"]
            ))
            self.assertEqual(
                len([value for value in context["limitations"] if value["code"] == "unsafe_candidate"]),
                len(commands),
            )
            plan = verification_plan.finalize(
                context, VerificationPlanTests.draft()
            )
            self.assertEqual(plan["checks"][0]["decision"], "authorization_required")
            self.assertEqual(plan["execution_state"], "blocked")

    def test_context_is_deterministic_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            args = context_args(root, paths=["app.py"], max_discovery=0)

            first = verification_context.resolve(args)
            second = verification_context.resolve(args)

            self.assertEqual(verification_context._canonical_json(first), verification_context._canonical_json(second))
            self.assertLessEqual(len(verification_context._canonical_json(first)), verification_context.MAX_CONTEXT_BYTES)
            self.assertEqual(first["schema_version"], "1.0.0")
            self.assertEqual(first["policy"][0]["policy_id"], "P001")
            self.assertEqual(first["targets"][0]["target_id"], "T001")

    def test_protected_git_state_binds_ignored_and_visible_files_and_directories(self):
        mutations = [
            "tracked_rewrite",
            "untracked_rewrite",
            "ignored_rewrite",
            "file_creation",
            "tracked_deletion",
            "empty_directory_creation",
        ]
        if os.name != "nt":
            mutations.append("mode_change")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                initialize_git(root)
                (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
                (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
                commit_all(root)
                (root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
                (root / "ignored").mkdir()
                (root / "ignored" / "private.txt").write_text("private\n", encoding="utf-8")
                before, _, before_limits = verification_context._protected_digest(
                    root, True, 16 * 1024 * 1024
                )
                self.assertFalse(any(value["material"] for value in before_limits))

                if mutation == "tracked_rewrite":
                    (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
                elif mutation == "untracked_rewrite":
                    (root / "untracked.txt").write_text("changed\n", encoding="utf-8")
                elif mutation == "ignored_rewrite":
                    (root / "ignored" / "private.txt").write_text("changed\n", encoding="utf-8")
                elif mutation == "file_creation":
                    (root / "created.txt").write_text("created\n", encoding="utf-8")
                elif mutation == "tracked_deletion":
                    (root / "tracked.txt").unlink()
                elif mutation == "empty_directory_creation":
                    (root / "empty").mkdir()
                elif mutation == "mode_change":
                    source = root / "tracked.txt"
                    source.chmod(source.stat().st_mode | stat.S_IXUSR)

                after, _, after_limits = verification_context._protected_digest(
                    root, True, 16 * 1024 * 1024
                )

                self.assertFalse(any(value["material"] for value in after_limits))
                self.assertNotEqual(before, after)

    def test_context_output_is_create_only(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            output = Path(lead_directory) / "context.json"
            output.write_text("keep\n", encoding="utf-8")

            status = verification_context.main([
                "--repo", str(root), "--output", str(output),
                "paths", "app.py",
            ])

            self.assertEqual(status, 2)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep\n")

    def test_unreadable_guidance_marks_chain_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            target = root / "src" / "VERIFY.md"
            try:
                target.symlink_to(root / "missing-guidance")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")

            context = verification_context.resolve(
                context_args(root, paths=["src/app.py"], max_discovery=0)
            )

            self.assertFalse(context["guidance"]["chains"][0]["complete"])
            self.assertTrue(any(item["code"] == "guidance_unavailable" and item["material"] for item in context["limitations"]))

    @unittest.skipIf(os.name == "nt", "POSIX descriptor-relative enumeration assertion")
    def test_directory_enumeration_is_bound_to_open_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / "selected"
            saved = root / "saved"
            selected.mkdir()
            (selected / "original.py").write_text("VALUE = 1\n", encoding="utf-8")
            real_scandir = os.scandir

            def swap_then_scan(descriptor):
                self.assertIsInstance(descriptor, int)
                selected.rename(saved)
                selected.mkdir()
                (selected / "replacement.py").write_text("VALUE = 2\n", encoding="utf-8")
                return real_scandir(descriptor)

            try:
                with mock.patch.object(path_safety.os, "scandir", side_effect=swap_then_scan):
                    entries, _, complete = verification_context._bounded_directory_entries(selected, 10)
                self.assertTrue(complete)
                self.assertEqual([item.name for item in entries], ["original.py"])
            finally:
                if selected.exists():
                    for child in selected.iterdir():
                        child.unlink()
                    selected.rmdir()
                if saved.exists():
                    saved.rename(selected)

    def test_write_candidate_requires_matching_artifact_boundary(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            candidate_file = Path(lead_directory) / "candidates.json"
            candidate_file.write_text(
                json.dumps([{
                    "argv": ["tool", "build"],
                    "cwd": ".",
                    "provenance": ["caller"],
                    "timeout_seconds": 60,
                    "repetitions": 1,
                    "expected_effects": ["repository_read", "local_process", "disposable_repository_write"],
                    "artifact_boundaries": [],
                }]),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(verification_context.ContextError, "no repository artifact boundary"):
                verification_context.resolve(
                    context_args(root, paths=["app.py"], candidate_input=str(candidate_file), max_discovery=0)
                )

    def test_duplicate_policy_labels_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            policy_file = Path(lead_directory) / "policy.json"
            policy_file.write_text(
                json.dumps([
                    {"kind": "user_global", "label": "same", "content": "First."},
                    {"kind": "project", "label": "same", "content": "Second."},
                ]),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(verification_context.ContextError, "duplicate policy label"):
                verification_context.resolve(
                    context_args(root, paths=["app.py"], policy_input=str(policy_file), max_discovery=0)
                )

    def test_duplicate_candidate_json_members_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            candidate_file = Path(lead_directory) / "candidates.json"
            candidate_file.write_text(
                '[{"argv":["first"],"argv":["second"],"cwd":".",'
                '"provenance":["caller"],"timeout_seconds":1,"repetitions":1,'
                '"expected_effects":["repository_read"],"artifact_boundaries":[]}]',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(verification_context.ContextError, "duplicate JSON member"):
                verification_context.resolve(
                    context_args(
                        root,
                        paths=["app.py"],
                        candidate_input=str(candidate_file),
                        max_discovery=0,
                    )
                )

    def test_reparse_attribute_is_link_like(self):
        reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        metadata = mock.Mock(st_mode=stat.S_IFREG, st_file_attributes=reparse)
        with mock.patch.object(Path, "lstat", return_value=metadata):
            with mock.patch.object(path_safety.stat, "FILE_ATTRIBUTE_REPARSE_POINT", reparse, create=True):
                self.assertTrue(path_safety.is_link_like(Path("fixture")))


class VerificationPlanTests(unittest.TestCase):
    def context_with_candidate(self, root, lead_directory, *, mode="execute", direct=True):
        candidate_file = Path(lead_directory) / "candidates.json"
        candidate_file.write_text(
            json.dumps([{
                "argv": ["python", "-m", "unittest", "tests.test_app"],
                "cwd": ".",
                "provenance": ["caller"],
                "timeout_seconds": 60,
                "repetitions": 1,
                "expected_effects": ["repository_read", "local_process"],
                "artifact_boundaries": [],
            }]),
            encoding="utf-8",
        )
        return verification_context.resolve(
            context_args(
                root,
                paths=["app.py"],
                candidate_input=str(candidate_file),
                max_discovery=0,
                mode=mode,
                direct_execution_intent=direct,
            )
        )

    @staticmethod
    def draft(*, with_check=True):
        return {
            "claims": [{
                "key": "behavior",
                "statement": "The selected module preserves its documented behavior.",
                "material": True,
                "target_ids": ["T001"],
                "basis": [{
                    "kind": "caller",
                    "description": "The caller requested verification of the selected module.",
                    "source_id": "P001",
                    "location": None,
                }],
                "evidence_requirement": "command",
            }],
            "guidance_interpretations": [],
            "checks": ([{
                "key": "focused",
                "candidate_id": "Q001",
                "tier": "focused",
                "reason": "The focused test exercises the selected module.",
                "claim_keys": ["behavior"],
                "depends_on_keys": [],
                "useful_after_failure": True,
            }] if with_check else []),
            "limitations": [],
        }

    def test_finalize_binds_exact_candidate_and_derives_ready(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context = self.context_with_candidate(root, lead_directory)

            plan = verification_plan.finalize(context, self.draft())

            self.assertEqual(plan["execution_state"], "ready")
            self.assertEqual(plan["checks"][0]["argv"], context["command_candidates"][0]["argv"])
            self.assertEqual(plan["checks"][0]["authority"], context["command_candidates"][0]["authority"])
            self.assertEqual(plan["coverage"]["uncovered_claim_ids"], [])
            self.assertEqual(plan["summary"]["material_limitation_count"], 0)
            verification_plan.validate_plan(plan)

    def test_plan_mode_derives_plan_only_without_authority(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context = self.context_with_candidate(root, lead_directory, mode="plan", direct=False)

            plan = verification_plan.finalize(context, self.draft())

            self.assertEqual(plan["execution_state"], "plan_only")
            self.assertEqual(plan["checks"][0]["decision"], "plan_only")

    def test_missing_command_coverage_blocks_plan(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context = self.context_with_candidate(root, lead_directory)

            plan = verification_plan.finalize(context, self.draft(with_check=False))

            self.assertEqual(plan["execution_state"], "blocked")
            self.assertEqual(plan["coverage"]["uncovered_claim_ids"], ["C001"])
            self.assertTrue(any(item["code"] == "coverage_gap" for item in plan["limitations"]))

    def test_semantic_draft_cannot_supply_authority_or_argv(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context = self.context_with_candidate(root, lead_directory)
            draft = self.draft()
            draft["checks"][0]["argv"] = ["dangerous", "command"]

            with self.assertRaisesRegex(verification_plan.PlanError, "fields differ"):
                verification_plan.finalize(context, draft)

    def test_target_drift_is_rejected_before_plan_finalization(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            source = root / "app.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            context = self.context_with_candidate(root, lead_directory)
            source.write_text("VALUE = 2\n", encoding="utf-8")

            with self.assertRaisesRegex(verification_plan.PlanError, "target changed"):
                verification_plan.finalize(context, self.draft())

    def test_claim_ids_are_deterministic_not_draft_ordered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context = verification_context.resolve(
                context_args(root, paths=["app.py"], max_discovery=0)
            )
            first = self.draft(with_check=False)
            first["claims"][0]["evidence_requirement"] = "static"
            second_claim = {
                "key": "format",
                "statement": "The selected file remains valid text.",
                "material": False,
                "target_ids": ["T001"],
                "basis": [{
                    "kind": "target_content",
                    "description": "The target was inspected as text.",
                    "source_id": None,
                    "location": {"path": "app.py", "start_line": 1, "end_line": 1},
                }],
                "evidence_requirement": "static",
            }
            first["claims"].append(second_claim)
            second = json.loads(json.dumps(first))
            second["claims"].reverse()

            plan_one = verification_plan.finalize(context, first)
            plan_two = verification_plan.finalize(context, second)

            self.assertEqual(plan_one["claims"], plan_two["claims"])

    def test_output_creation_refuses_replacement(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            plan = verification_plan.finalize(
                self.context_with_candidate(root, lead_directory), self.draft()
            )
            output = Path(lead_directory) / "plan.json"
            verification_plan._emit(plan, "json", str(output))
            with self.assertRaises(verification_plan.SafetyError):
                verification_plan._emit(plan, "json", str(output))

    def test_plan_limitation_can_cite_frozen_candidate(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            draft = self.draft()
            draft["limitations"] = [{
                "code": "other",
                "message": "The selected candidate has a non-material portability caveat.",
                "source_ids": ["Q001"],
                "target_ids": ["T001"],
                "claim_keys": ["behavior"],
                "material": False,
                "next_action": "none",
            }]

            plan = verification_plan.finalize(
                self.context_with_candidate(root, lead_directory), draft
            )

            self.assertEqual(plan["limitations"][0]["source_ids"], ["Q001"])

    def test_plan_validator_rejects_forged_derived_fields(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            plan = verification_plan.finalize(
                self.context_with_candidate(root, lead_directory), self.draft()
            )
            mutations = []
            forged_summary = json.loads(json.dumps(plan))
            forged_summary["summary"]["runnable_check_count"] = 0
            mutations.append(forged_summary)
            forged_fingerprint = json.loads(json.dumps(plan))
            forged_fingerprint["checks"][0]["fingerprint"] = "0" * 64
            mutations.append(forged_fingerprint)
            forged_state = json.loads(json.dumps(plan))
            forged_state["execution_state"] = "blocked"
            mutations.append(forged_state)

            for forged in mutations:
                with self.subTest(field=forged):
                    with self.assertRaises(verification_plan.PlanError):
                        verification_plan.validate_plan(forged)

    def test_plan_validator_fails_closed_on_malformed_nested_type(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            plan = verification_plan.finalize(
                self.context_with_candidate(root, lead_directory), self.draft()
            )
            plan["checks"][0]["claim_ids"] = [[]]

            with self.assertRaises(verification_plan.PlanError):
                verification_plan.validate_plan(plan)

    def test_closer_guidance_can_explicitly_replace_a_broader_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "VERIFY.md").write_text("Run the broad check.\n", encoding="utf-8")
            (root / "src" / "VERIFY.md").write_text(
                "For src, replace the broad check with the focused check.\n",
                encoding="utf-8",
            )
            (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context = verification_context.resolve(
                context_args(root, paths=["src/app.py"], max_discovery=0)
            )
            draft = self.draft(with_check=False)
            draft["claims"][0]["evidence_requirement"] = "static"
            draft["guidance_interpretations"] = [
                {
                    "key": "broad",
                    "source_id": "S002",
                    "target_ids": ["T001"],
                    "claim_keys": ["behavior"],
                    "kind": "required",
                    "requirement": "Run the broad check.",
                    "replaces_key": None,
                    "replacement_reason": None,
                },
                {
                    "key": "focused",
                    "source_id": "S003",
                    "target_ids": ["T001"],
                    "claim_keys": ["behavior"],
                    "kind": "replacement",
                    "requirement": "Run the focused check.",
                    "replaces_key": "broad",
                    "replacement_reason": "The nested rule is more specific.",
                },
            ]

            plan = verification_plan.finalize(context, draft)

            broad = next(value for value in plan["guidance_interpretations"] if value["kind"] == "required")
            focused = next(value for value in plan["guidance_interpretations"] if value["kind"] == "replacement")
            self.assertEqual(focused["replaces_interpretation_id"], broad["interpretation_id"])
            verification_plan.validate_plan(plan)

    def test_replacement_must_come_from_a_strictly_closer_guidance_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "VERIFY.md").write_text("Root.\n", encoding="utf-8")
            (root / "src" / "VERIFY.md").write_text("Nested.\n", encoding="utf-8")
            (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context = verification_context.resolve(
                context_args(root, paths=["src/app.py"], max_discovery=0)
            )
            draft = self.draft(with_check=False)
            draft["claims"][0]["evidence_requirement"] = "static"
            draft["guidance_interpretations"] = [
                {
                    "key": "nested",
                    "source_id": "S003",
                    "target_ids": ["T001"],
                    "claim_keys": ["behavior"],
                    "kind": "required",
                    "requirement": "Nested requirement.",
                    "replaces_key": None,
                    "replacement_reason": None,
                },
                {
                    "key": "root-replacement",
                    "source_id": "S002",
                    "target_ids": ["T001"],
                    "claim_keys": ["behavior"],
                    "kind": "replacement",
                    "requirement": "Root replacement.",
                    "replaces_key": "nested",
                    "replacement_reason": "Invalid broader replacement.",
                },
            ]

            with self.assertRaisesRegex(verification_plan.PlanError, "closer"):
                verification_plan.finalize(context, draft)

    def test_ambiguous_required_guidance_conflict_blocks_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "VERIFY.md").write_text("Use strategy A.\n", encoding="utf-8")
            (root / "src" / "VERIFY.md").write_text("Use strategy B.\n", encoding="utf-8")
            (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context = verification_context.resolve(
                context_args(root, paths=["src/app.py"], max_discovery=0)
            )
            draft = self.draft(with_check=False)
            draft["claims"][0]["evidence_requirement"] = "static"
            draft["limitations"] = [{
                "code": "guidance_conflict",
                "message": "The two required strategies conflict and neither replaces the other.",
                "source_ids": ["S002", "S003"],
                "target_ids": ["T001"],
                "claim_keys": ["behavior"],
                "material": True,
                "next_action": "decision",
            }]

            plan = verification_plan.finalize(context, draft)

            self.assertEqual(plan["execution_state"], "blocked")
            self.assertTrue(any(value["code"] == "guidance_conflict" for value in plan["limitations"]))

    def test_caller_tier_command_and_time_caps_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            candidate_file = Path(lead_directory) / "candidates.json"
            candidates = [
                {
                    "argv": ["check", str(index)],
                    "cwd": ".",
                    "provenance": ["caller"],
                    "timeout_seconds": 60,
                    "repetitions": 1,
                    "expected_effects": ["repository_read", "local_process"],
                    "artifact_boundaries": [],
                }
                for index in (1, 2)
            ]
            candidate_file.write_text(json.dumps(candidates), encoding="utf-8")

            command_context = verification_context.resolve(
                context_args(
                    root,
                    paths=["app.py"],
                    candidate_input=str(candidate_file),
                    max_discovery=0,
                    command_cap=1,
                )
            )
            self.assertEqual(len(command_context["command_candidates"]), 1)
            command_plan = verification_plan.finalize(
                command_context, self.draft()
            )
            self.assertEqual(command_plan["execution_state"], "blocked")
            self.assertTrue(any(
                "command cap" in value["message"]
                for value in command_plan["limitations"]
            ))

            cases = (
                ({"tier_cap": "focused"}, ["focused", "subsystem"], "tier cap"),
                ({"time_cap_seconds": 90}, ["focused", "focused"], "time cap"),
            )
            for overrides, tiers, expected in cases:
                with self.subTest(cap=expected):
                    context = verification_context.resolve(
                        context_args(
                            root,
                            paths=["app.py"],
                            candidate_input=str(candidate_file),
                            max_discovery=0,
                            **overrides,
                        )
                    )
                    draft = self.draft()
                    draft["checks"] = [
                        {
                            "key": f"check-{index}",
                            "candidate_id": f"Q{index:03d}",
                            "tier": tier,
                            "reason": "Bounded evidence.",
                            "claim_keys": ["behavior"],
                            "depends_on_keys": [],
                            "useful_after_failure": True,
                        }
                        for index, tier in enumerate(tiers, start=1)
                    ]
                    with self.assertRaisesRegex(verification_plan.PlanError, expected):
                        verification_plan.finalize(context, draft)

    def test_canonical_size_expansion_is_rejected_during_validation(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context = self.context_with_candidate(root, lead_directory)
            draft = self.draft()
            draft["claims"][0]["statement"] = "Résumé " * 200
            plan = verification_plan.finalize(context, draft)
            raw = (json.dumps(plan, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            canonical = verification_plan._canonical_json(plan)
            self.assertLess(len(raw), len(canonical))
            input_path = Path(lead_directory) / "unicode-plan.json"
            input_path.write_bytes(raw)
            ceiling = (len(raw) + len(canonical)) // 2

            with mock.patch.object(verification_plan, "MAX_JSON_BYTES", ceiling):
                loaded = verification_plan._read_json(str(input_path))
                with self.assertRaisesRegex(verification_plan.PlanError, "canonical plan"):
                    verification_plan.validate_plan(loaded)

    def test_json_readers_reject_duplicate_members(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"value":1,"value":2}', encoding="utf-8")

            for module, error in (
                (verification_plan, verification_plan.PlanError),
                (verification_result, verification_result.ResultError),
            ):
                with self.subTest(module=module.__name__):
                    with self.assertRaisesRegex(error, "duplicate JSON member"):
                        module._read_json(str(path))


class VerificationResultTests(unittest.TestCase):
    def make_plan(self, root, lead_directory, *, effects=None, boundaries=None, repetitions=1):
        effects = effects or ["repository_read", "local_process"]
        boundaries = boundaries or []
        candidate_file = Path(lead_directory) / "result-candidates.json"
        candidate_file.write_text(
            json.dumps([{
                "argv": ["python", "-m", "unittest", "tests.test_app"],
                "cwd": ".",
                "provenance": ["caller"],
                "timeout_seconds": 60,
                "repetitions": repetitions,
                "expected_effects": effects,
                "artifact_boundaries": boundaries,
            }]),
            encoding="utf-8",
        )
        context = verification_context.resolve(
            context_args(
                root,
                paths=["app.py"],
                candidate_input=str(candidate_file),
                max_discovery=0,
            )
        )
        draft = VerificationPlanTests.draft()
        return context, verification_plan.finalize(context, draft)

    def make_progressive_plan(self, root, lead_directory):
        candidate_file = Path(lead_directory) / "progressive-candidates.json"
        candidate_file.write_text(
            json.dumps([
                {
                    "argv": ["check", tier],
                    "cwd": ".",
                    "provenance": ["caller"],
                    "timeout_seconds": 60,
                    "repetitions": 1,
                    "expected_effects": ["repository_read", "local_process"],
                    "artifact_boundaries": [],
                }
                for tier in ("focused", "subsystem", "project")
            ]),
            encoding="utf-8",
        )
        context = verification_context.resolve(
            context_args(
                root,
                paths=["app.py"],
                candidate_input=str(candidate_file),
                max_discovery=0,
            )
        )
        draft = VerificationPlanTests.draft()
        draft["checks"] = [
            {
                "key": "focused",
                "candidate_id": "Q001",
                "tier": "focused",
                "reason": "Focused evidence.",
                "claim_keys": ["behavior"],
                "depends_on_keys": [],
                "useful_after_failure": True,
            },
            {
                "key": "dependent",
                "candidate_id": "Q002",
                "tier": "subsystem",
                "reason": "Dependent subsystem evidence.",
                "claim_keys": ["behavior"],
                "depends_on_keys": ["focused"],
                "useful_after_failure": False,
            },
            {
                "key": "independent",
                "candidate_id": "Q003",
                "tier": "project",
                "reason": "Independent project evidence remains useful.",
                "claim_keys": ["behavior"],
                "depends_on_keys": [],
                "useful_after_failure": True,
            },
        ]
        return context, verification_plan.finalize(context, draft)

    @staticmethod
    def empty_stream(excerpt=None):
        return {
            "byte_count": 0,
            "captured_byte_count": 0,
            "sha256": verification_result._sha256(b""),
            "truncated": False,
            "excerpt": excerpt,
            "excerpt_redacted": excerpt is not None,
        }

    def run_record(self, context, plan, *, status="passed", exit_code=0, effects=None):
        return {
            "context_sha256": plan["context_sha256"],
            "plan_sha256": verification_result._sha256(verification_result._canonical_json(plan)),
            "target_sha256": plan["target_sha256"],
            "protected_before_sha256": context["repository_state"]["protected_state_sha256"],
            "protected_after_sha256": context["repository_state"]["protected_state_sha256"],
            "run_temp_root": None,
            "run_temp_identity_sha256": None,
            "run_temp_before_sha256": None,
            "run_temp_after_sha256": None,
            "attempts": [{
                "attempt_id": "A001",
                "check_id": "K001",
                "repetition": 1,
                "status": status,
                "exit_code": exit_code,
                "duration_ms": 10,
                "argv": plan["checks"][0]["argv"],
                "cwd": plan["checks"][0]["cwd"],
                "target_before_sha256": plan["target_sha256"],
                "target_after_sha256": plan["target_sha256"],
                "protected_before_sha256": context["repository_state"]["protected_state_sha256"],
                "protected_after_sha256": context["repository_state"]["protected_state_sha256"],
                "protected_before_excluded_paths": [],
                "protected_after_excluded_paths": sorted({
                    value["path"] for value in (effects or [])
                    if value["root_kind"] == "repository" and value["classification"] == "allowed"
                }),
                "run_temp_before_sha256": None,
                "run_temp_after_sha256": None,
                "run_temp_before_path_hashes": [],
                "run_temp_after_path_hashes": [],
                "run_temp_before_excluded_paths": [],
                "run_temp_after_excluded_paths": [],
                "stdout": self.empty_stream(),
                "stderr": self.empty_stream("bounded diagnostic") if status == "failed" else self.empty_stream(),
                "observed_effects": effects or [],
            }],
            "plan_deviations": [],
            "limitations": [],
        }

    def attempt_record(self, context, plan, *, attempt_id, check_id, status, exit_code):
        check = next(value for value in plan["checks"] if value["check_id"] == check_id)
        return {
            "attempt_id": attempt_id,
            "check_id": check_id,
            "repetition": 1,
            "status": status,
            "exit_code": exit_code,
            "duration_ms": 10,
            "argv": check["argv"],
            "cwd": check["cwd"],
            "target_before_sha256": plan["target_sha256"],
            "target_after_sha256": plan["target_sha256"],
            "protected_before_sha256": context["repository_state"]["protected_state_sha256"],
            "protected_after_sha256": context["repository_state"]["protected_state_sha256"],
            "protected_before_excluded_paths": [],
            "protected_after_excluded_paths": [],
            "run_temp_before_sha256": None,
            "run_temp_after_sha256": None,
            "run_temp_before_path_hashes": [],
            "run_temp_after_path_hashes": [],
            "run_temp_before_excluded_paths": [],
            "run_temp_after_excluded_paths": [],
            "stdout": self.empty_stream(),
            "stderr": self.empty_stream("bounded diagnostic") if status != "passed" else self.empty_stream(),
            "observed_effects": [],
        }

    @staticmethod
    def result_draft(outcome, *, evidence=True, observations=None):
        return {
            "claims": [{
                "claim_id": "C001",
                "outcome": outcome,
                "evidence": ([{
                    "kind": "attempt",
                    "description": "The focused check produced relevant evidence.",
                    "source_id": None,
                    "check_id": "K001",
                    "attempt_id": "A001",
                    "location": None,
                }] if evidence else []),
                "reason": "The evidence directly addresses the selected behavior." if outcome != "unresolved" else "The passing command did not establish the material behavior.",
            }],
            "conclusion": "Verification evidence was evaluated against the planned claim.",
            "observations": observations or [],
            "limitations": [],
        }

    @staticmethod
    def empty_run_record(context, plan):
        return {
            "context_sha256": plan["context_sha256"],
            "plan_sha256": verification_result._sha256(
                verification_result._canonical_json(plan)
            ),
            "target_sha256": plan["target_sha256"],
            "protected_before_sha256": context["repository_state"]["protected_state_sha256"],
            "protected_after_sha256": context["repository_state"]["protected_state_sha256"],
            "run_temp_root": None,
            "run_temp_identity_sha256": None,
            "run_temp_before_sha256": None,
            "run_temp_after_sha256": None,
            "attempts": [],
            "plan_deviations": [],
            "limitations": [],
        }

    def test_required_guidance_claim_must_be_supported_before_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "VERIFY.md").write_text(
                "Required: verify the heading spelling.\n", encoding="utf-8"
            )
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context = verification_context.resolve(
                context_args(root, paths=["app.py"], max_discovery=0)
            )
            draft = VerificationPlanTests.draft(with_check=False)
            draft["claims"][0]["material"] = False
            draft["claims"][0]["evidence_requirement"] = "static"
            draft["guidance_interpretations"] = [{
                "key": "root-required",
                "source_id": "S002",
                "target_ids": ["T001"],
                "claim_keys": ["behavior"],
                "kind": "required",
                "requirement": "Verify the heading spelling.",
                "replaces_key": None,
                "replacement_reason": None,
            }]
            plan = verification_plan.finalize(context, draft)
            result_draft = {
                "claims": [{
                    "claim_id": "C001",
                    "outcome": "unresolved",
                    "evidence": [],
                    "reason": "No sufficient evidence was retained.",
                }],
                "conclusion": "Required guidance remains unproven.",
                "observations": [],
                "limitations": [],
            }

            result = verification_result.finalize(
                plan, self.empty_run_record(context, plan), result_draft
            )

            self.assertEqual(
                (result["completion"], result["outcome"], result["next_action"]),
                ("complete", "unknown", "plan"),
            )
            self.assertFalse(result["coverage"]["required_guidance_satisfied"])
            self.assertEqual(
                result["guidance_interpretations"],
                plan["guidance_interpretations"],
            )
            verification_result.validate_result(result)

    def test_pass_requires_relevant_supported_claim_and_unchanged_state(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)

            result = verification_result.finalize(
                plan,
                self.run_record(context, plan),
                self.result_draft("supported"),
            )

            self.assertEqual((result["completion"], result["outcome"], result["next_action"]), ("complete", "pass", "none"))
            self.assertTrue(result["mutation"]["protected_state_unchanged"])
            self.assertTrue(result["coverage"]["sufficient"])
            verification_result.validate_result(result)

    def test_snapshot_binds_target_and_allows_only_new_planned_outputs(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(
                root,
                lead_directory,
                effects=["repository_read", "local_process", "disposable_repository_write"],
                boundaries=[{"root_kind": "repository", "path": "build"}],
            )

            before = verification_result.capture_snapshot(plan, [])
            self.assertEqual(before["target_sha256"], plan["target_sha256"])
            self.assertEqual(before["protected_state_sha256"], plan["repository_state"]["protected_state_sha256"])
            (root / "build").mkdir()
            (root / "build" / "result.txt").write_text("generated\n", encoding="utf-8")
            after = verification_result.capture_snapshot(
                plan, ["build", "build/result.txt"]
            )
            self.assertEqual(after["protected_state_sha256"], plan["repository_state"]["protected_state_sha256"])
            with self.assertRaisesRegex(verification_result.ResultError, "pre-existing"):
                verification_result.capture_snapshot(plan, ["app.py"])

    def test_bounded_run_temp_is_snapshotted_and_validated(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory, tempfile.TemporaryDirectory() as run_directory:
            root = Path(directory)
            run_root = Path(run_directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(
                root,
                lead_directory,
                effects=["repository_read", "local_process", "bounded_temporary_write"],
                boundaries=[{"root_kind": "run_temp", "path": "cache"}],
            )
            before = verification_result.capture_snapshot(
                plan, [], run_temp_root=str(run_root)
            )
            (run_root / "cache").mkdir()
            output = run_root / "cache" / "result.txt"
            output.write_text("temporary\n", encoding="utf-8")
            after = verification_result.capture_snapshot(
                plan,
                [],
                run_temp_root=str(run_root),
                excluded_run_temp_paths=["cache", "cache/result.txt"],
            )
            self.assertFalse(before["limitations"])
            self.assertFalse(after["limitations"])
            self.assertEqual(before["run_temp_state_sha256"], after["run_temp_state_sha256"])
            effects = [
                {
                    "effect": "bounded_temporary_write",
                    "root_kind": "run_temp",
                    "path": "cache",
                    "before_sha256": None,
                    "after_sha256": verification_result._sha256(b"directory"),
                    "classification": "allowed",
                },
                {
                    "effect": "bounded_temporary_write",
                    "root_kind": "run_temp",
                    "path": "cache/result.txt",
                    "before_sha256": None,
                    "after_sha256": verification_result._sha256(b"temporary\n"),
                    "classification": "allowed",
                },
            ]
            run = self.run_record(context, plan, effects=effects)
            run.update({
                "run_temp_root": str(run_root),
                "run_temp_identity_sha256": before["run_temp_identity_sha256"],
                "run_temp_before_sha256": before["run_temp_state_sha256"],
                "run_temp_after_sha256": after["run_temp_state_sha256"],
            })
            attempt = run["attempts"][0]
            attempt.update({
                "run_temp_before_sha256": before["run_temp_state_sha256"],
                "run_temp_after_sha256": after["run_temp_state_sha256"],
                "run_temp_before_path_hashes": before["run_temp_path_hashes"],
                "run_temp_after_path_hashes": after["run_temp_path_hashes"],
                "run_temp_before_excluded_paths": [],
                "run_temp_after_excluded_paths": ["cache", "cache/result.txt"],
            })

            result = verification_result.finalize(
                plan, run, self.result_draft("supported")
            )

            self.assertEqual(result["outcome"], "pass")
            self.assertTrue(result["mutation"]["run_temp"]["state_unchanged"])

    def test_run_temp_snapshot_rejects_undeclared_preexisting_content(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory, tempfile.TemporaryDirectory() as run_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (Path(run_directory) / "preexisting.txt").write_text("user data\n", encoding="utf-8")
            _, plan = self.make_plan(
                root,
                lead_directory,
                effects=["repository_read", "local_process", "bounded_temporary_write"],
                boundaries=[{"root_kind": "run_temp", "path": "cache"}],
            )

            snapshot = verification_result.capture_snapshot(
                plan, [], run_temp_root=run_directory
            )

            self.assertTrue(any(value["material"] for value in snapshot["limitations"]))

    def test_unsafe_run_temp_output_does_not_taint_repository_ownership_state(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory, tempfile.TemporaryDirectory() as run_directory, tempfile.TemporaryDirectory() as outside_directory:
            root = Path(directory)
            run_root = Path(run_directory)
            outside = Path(outside_directory) / "outside.txt"
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            outside.write_text("outside\n", encoding="utf-8")
            context, plan = self.make_plan(
                root,
                lead_directory,
                effects=["repository_read", "local_process", "bounded_temporary_write"],
                boundaries=[{"root_kind": "run_temp", "path": "cache"}],
            )
            before = verification_result.capture_snapshot(
                plan, [], run_temp_root=str(run_root)
            )
            (run_root / "cache").mkdir()
            linked = run_root / "cache" / "result.txt"
            try:
                linked.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")
            effects = [
                {
                    "effect": "bounded_temporary_write",
                    "root_kind": "run_temp",
                    "path": "cache",
                    "before_sha256": None,
                    "after_sha256": verification_result._sha256(b"directory"),
                    "classification": "allowed",
                },
                {
                    "effect": "bounded_temporary_write",
                    "root_kind": "run_temp",
                    "path": "cache/result.txt",
                    "before_sha256": None,
                    "after_sha256": verification_result._sha256(b"outside\n"),
                    "classification": "allowed",
                },
            ]
            run = self.run_record(context, plan, effects=effects)
            run.update({
                "run_temp_root": str(run_root),
                "run_temp_identity_sha256": before["run_temp_identity_sha256"],
                "run_temp_before_sha256": before["run_temp_state_sha256"],
                "run_temp_after_sha256": before["run_temp_state_sha256"],
            })
            run["attempts"][0].update({
                "run_temp_before_sha256": before["run_temp_state_sha256"],
                "run_temp_after_sha256": before["run_temp_state_sha256"],
                "run_temp_before_path_hashes": before["run_temp_path_hashes"],
                "run_temp_after_path_hashes": before["run_temp_path_hashes"],
                "run_temp_before_excluded_paths": [],
                "run_temp_after_excluded_paths": ["cache", "cache/result.txt"],
            })

            result = verification_result.finalize(
                plan, run, self.result_draft("supported")
            )

            self.assertTrue(result["mutation"]["protected_state_unchanged"])
            self.assertFalse(result["mutation"]["run_temp"]["state_unchanged"])
            self.assertEqual((result["completion"], result["outcome"]), ("incomplete", "unknown"))
            verification_result.validate_result(result)

    def test_hard_linked_repository_output_is_not_accepted_as_disposable(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory, tempfile.TemporaryDirectory() as outside_directory:
            root = Path(directory)
            outside = Path(outside_directory) / "outside.txt"
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            outside.write_text("shared\n", encoding="utf-8")
            context, plan = self.make_plan(
                root,
                lead_directory,
                effects=["repository_read", "local_process", "disposable_repository_write"],
                boundaries=[{"root_kind": "repository", "path": "build"}],
            )
            (root / "build").mkdir()
            linked = root / "build" / "result.txt"
            try:
                os.link(outside, linked)
            except OSError as exc:
                self.skipTest(f"hard-link creation is unavailable: {exc}")
            effects = [
                {
                    "effect": "disposable_repository_write",
                    "root_kind": "repository",
                    "path": "build",
                    "before_sha256": None,
                    "after_sha256": verification_result._sha256(b"directory"),
                    "classification": "allowed",
                },
                {
                    "effect": "disposable_repository_write",
                    "root_kind": "repository",
                    "path": "build/result.txt",
                    "before_sha256": None,
                    "after_sha256": verification_result._sha256(b"shared\n"),
                    "classification": "allowed",
                },
            ]

            result = verification_result.finalize(
                plan,
                self.run_record(context, plan, effects=effects),
                self.result_draft("supported"),
            )

            self.assertFalse(result["mutation"]["protected_state_unchanged"])
            self.assertEqual((result["completion"], result["outcome"]), ("incomplete", "unknown"))
            verification_result.validate_result(result)

    def test_per_attempt_snapshot_drift_forces_incomplete(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)
            run = self.run_record(context, plan)
            run["attempts"][0]["protected_after_sha256"] = "0" * 64

            result = verification_result.finalize(
                plan, run, self.result_draft("supported")
            )

            self.assertEqual((result["completion"], result["outcome"]), ("incomplete", "unknown"))
            self.assertTrue(any(value["code"] == "protected_state_changed" for value in result["limitations"]))

    def test_failed_check_derives_complete_fail_and_triage(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)

            result = verification_result.finalize(
                plan,
                self.run_record(context, plan, status="failed", exit_code=1),
                self.result_draft("disproved"),
            )

            self.assertEqual((result["completion"], result["outcome"], result["next_action"]), ("complete", "fail", "triage"))
            self.assertEqual(result["checks"][0]["status"], "failed")

    def test_unavailable_check_is_incomplete_unknown_not_failed(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)

            result = verification_result.finalize(
                plan,
                self.run_record(context, plan, status="unavailable", exit_code=None),
                self.result_draft("unresolved", evidence=False),
            )

            self.assertEqual((result["completion"], result["outcome"], result["next_action"]), ("incomplete", "unknown", "retry"))
            self.assertTrue(any(item["code"] == "check_unavailable" for item in result["limitations"]))

    def test_timeout_is_incomplete_and_requests_a_bounded_retry(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)

            result = verification_result.finalize(
                plan,
                self.run_record(context, plan, status="timed_out", exit_code=None),
                self.result_draft("disproved"),
            )

            self.assertEqual((result["completion"], result["outcome"], result["next_action"]), ("incomplete", "unknown", "retry"))
            self.assertTrue(any(value["code"] == "check_timeout" for value in result["limitations"]))

    def test_failure_skips_dependents_but_preserves_useful_independent_checks(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_progressive_plan(root, lead_directory)
            run = {
                "context_sha256": plan["context_sha256"],
                "plan_sha256": verification_result._sha256(verification_result._canonical_json(plan)),
                "target_sha256": plan["target_sha256"],
                "protected_before_sha256": context["repository_state"]["protected_state_sha256"],
                "protected_after_sha256": context["repository_state"]["protected_state_sha256"],
                "run_temp_root": None,
                "run_temp_identity_sha256": None,
                "run_temp_before_sha256": None,
                "run_temp_after_sha256": None,
                "attempts": [
                    self.attempt_record(context, plan, attempt_id="A001", check_id="K001", status="failed", exit_code=1),
                    self.attempt_record(context, plan, attempt_id="A002", check_id="K003", status="passed", exit_code=0),
                ],
                "plan_deviations": [],
                "limitations": [],
            }
            draft = self.result_draft("disproved")
            draft["claims"][0]["evidence"] = [{
                "kind": "attempt",
                "description": "The focused check disproved the material claim.",
                "source_id": None,
                "check_id": "K001",
                "attempt_id": "A001",
                "location": None,
            }]

            result = verification_result.finalize(plan, run, draft)

            self.assertEqual([value["status"] for value in result["checks"]], ["failed", "skipped", "passed"])
            self.assertEqual(result["coverage"]["attempted_tiers"], ["focused", "project"])
            self.assertEqual((result["completion"], result["outcome"], result["next_action"]), ("complete", "fail", "triage"))

    def test_irrelevant_green_check_is_complete_unknown(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)

            result = verification_result.finalize(
                plan,
                self.run_record(context, plan),
                self.result_draft("unresolved", evidence=False),
            )

            self.assertEqual((result["completion"], result["outcome"], result["next_action"]), ("complete", "unknown", "plan"))
            self.assertFalse(result["coverage"]["sufficient"])

    def test_target_mutation_forces_incomplete_without_cleanup(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            source = root / "app.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)
            source.write_text("VALUE = 2\n", encoding="utf-8")
            after, _, _ = verification_context._protected_digest(root, False, 256 * 1024 * 1024)
            run = self.run_record(context, plan)
            run["protected_after_sha256"] = after

            result = verification_result.finalize(
                plan,
                run,
                self.result_draft("supported"),
            )

            self.assertEqual((result["completion"], result["outcome"]), ("incomplete", "unknown"))
            self.assertTrue(any(item["code"] == "target_drift" for item in result["limitations"]))
            self.assertEqual(source.read_text(encoding="utf-8"), "VALUE = 2\n")

    def test_unexpected_source_effect_dominates_success_failure_timeout_and_exception(self):
        scenarios = (
            ("passed", 0, "supported", True),
            ("failed", 1, "disproved", True),
            ("timed_out", None, "disproved", True),
            ("unavailable", None, "unresolved", False),
        )
        for status, exit_code, claim_outcome, include_evidence in scenarios:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
                root = Path(directory)
                source = root / "app.py"
                source.write_text("VALUE = 1\n", encoding="utf-8")
                context, plan = self.make_plan(root, lead_directory)
                effect = {
                    "effect": "source_mutation",
                    "root_kind": "repository",
                    "path": "app.py",
                    "before_sha256": plan["targets"][0]["sha256"],
                    "after_sha256": "0" * 64,
                    "classification": "unexpected",
                }
                run = self.run_record(
                    context,
                    plan,
                    status=status,
                    exit_code=exit_code,
                    effects=[effect],
                )
                draft = self.result_draft(
                    claim_outcome, evidence=include_evidence
                )

                result = verification_result.finalize(plan, run, draft)

                self.assertEqual((result["completion"], result["outcome"]), ("incomplete", "unknown"))
                self.assertFalse(result["mutation"]["protected_state_unchanged"])
                self.assertEqual(result["mutation"]["unexpected_effects"], [effect])

    def test_attempt_cannot_change_planned_argv(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)
            run = self.run_record(context, plan)
            run["attempts"][0]["argv"] = ["different", "command"]

            with self.assertRaisesRegex(verification_result.ResultError, "differs"):
                verification_result.finalize(plan, run, self.result_draft("supported"))

    def test_allowed_new_disposable_output_does_not_change_protected_state(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            source = root / "app.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(
                root,
                lead_directory,
                effects=["repository_read", "local_process", "disposable_repository_write"],
                boundaries=[{"root_kind": "repository", "path": "build"}],
            )
            (root / "build").mkdir()
            output = root / "build" / "result.txt"
            output.write_text("generated\n", encoding="utf-8")
            output_digest = verification_result._sha256(output.read_bytes())
            effect = {
                "effect": "disposable_repository_write",
                "root_kind": "repository",
                "path": "build/result.txt",
                "before_sha256": None,
                "after_sha256": output_digest,
                "classification": "allowed",
            }
            directory_effect = {
                "effect": "disposable_repository_write",
                "root_kind": "repository",
                "path": "build",
                "before_sha256": None,
                "after_sha256": verification_result._sha256(b"directory"),
                "classification": "allowed",
            }
            run = self.run_record(context, plan, effects=[directory_effect, effect])

            result = verification_result.finalize(
                plan,
                run,
                self.result_draft("supported"),
            )

            self.assertEqual(result["outcome"], "pass")
            self.assertTrue(result["mutation"]["protected_state_unchanged"])
            self.assertTrue(output.exists())

    def test_preexisting_path_cannot_be_claimed_as_disposable_output(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "build").mkdir()
            output = root / "build" / "result.txt"
            output.write_text("owned by user\n", encoding="utf-8")
            context, plan = self.make_plan(
                root,
                lead_directory,
                effects=["repository_read", "local_process", "disposable_repository_write"],
                boundaries=[{"root_kind": "repository", "path": "build"}],
            )
            effect = {
                "effect": "disposable_repository_write",
                "root_kind": "repository",
                "path": "build/result.txt",
                "before_sha256": None,
                "after_sha256": verification_result._sha256(b"replacement\n"),
                "classification": "allowed",
            }

            with self.assertRaisesRegex(verification_result.ResultError, "classification"):
                verification_result.finalize(
                    plan,
                    self.run_record(context, plan, effects=[effect]),
                    self.result_draft("supported"),
                )

    def test_observation_ids_and_fingerprints_are_derived(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)
            observation = {
                "category": "missing_coverage",
                "strength": "moderate",
                "confidence": "high",
                "title": "Add a focused contract assertion",
                "reason": "The current command proves execution but not the edge-case contract.",
                "current_run_impact": "not_affected",
                "evidence": [{
                    "kind": "attempt",
                    "description": "The focused check passed without exercising the edge case.",
                    "source_id": None,
                    "check_id": "K001",
                    "attempt_id": "A001",
                    "location": None,
                }],
                "safe_direction": "Add one focused edge-case assertion near the existing test.",
            }

            result = verification_result.finalize(
                plan,
                self.run_record(context, plan),
                self.result_draft("supported", observations=[observation]),
            )

            self.assertEqual(result["observations"][0]["observation_id"], "O001")
            self.assertRegex(result["observations"][0]["fingerprint"], r"^[0-9a-f]{64}$")

    def test_bounded_redacted_stream_and_human_render_share_canonical_state(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)
            run = self.run_record(context, plan)
            run["attempts"][0]["stdout"] = {
                "byte_count": 10000,
                "captured_byte_count": 1024,
                "sha256": verification_result._sha256(b"bounded captured bytes"),
                "truncated": True,
                "excerpt": "[redacted] bounded diagnostic",
                "excerpt_redacted": True,
            }

            result = verification_result.finalize(
                plan, run, self.result_draft("supported")
            )
            human = verification_result.render(result)

            self.assertTrue(result["checks"][0]["attempts"][0]["stdout"]["truncated"])
            self.assertIn("Verification: complete / pass / next none", human)
            self.assertIn("K001 [focused]: passed", human)
            self.assertNotIn("bounded diagnostic", human)

            forged = json.loads(json.dumps(result))
            forged["checks"][0]["attempts"][0]["stdout"]["excerpt_redacted"] = False
            with self.assertRaisesRegex(verification_result.ResultError, "redacted"):
                verification_result.validate_result(forged)

    def test_execution_cannot_retry_a_failed_repetition(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)
            run = self.run_record(context, plan, status="failed", exit_code=1)
            retried = json.loads(json.dumps(run["attempts"][0]))
            retried["attempt_id"] = "A002"
            retried["status"] = "passed"
            retried["exit_code"] = 0
            run["attempts"].append(retried)

            with self.assertRaisesRegex(verification_result.ResultError, "repetition|retried"):
                verification_result.finalize(plan, run, self.result_draft("disproved"))

    def test_static_evidence_kind_must_match_source_kind(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)
            draft = self.result_draft("supported")
            draft["claims"][0]["evidence"] = [{
                "kind": "policy",
                "description": "A target cannot masquerade as policy evidence.",
                "source_id": "T001",
                "check_id": None,
                "attempt_id": None,
                "location": {"path": "app.py", "start_line": 1, "end_line": 1},
            }]

            with self.assertRaisesRegex(verification_result.ResultError, "static evidence"):
                verification_result.finalize(plan, self.run_record(context, plan), draft)

    def test_result_validator_rejects_forged_and_malformed_fields(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)
            result = verification_result.finalize(
                plan, self.run_record(context, plan), self.result_draft("supported")
            )
            forged = json.loads(json.dumps(result))
            forged["checks"][0]["status"] = "failed"
            malformed = json.loads(json.dumps(result))
            malformed["claims"][0]["evidence"][0]["check_id"] = []

            for value in (forged, malformed):
                with self.subTest(value=value):
                    with self.assertRaises(verification_result.ResultError):
                        verification_result.validate_result(value)

    def test_result_validator_rejects_attempt_ids_out_of_encounter_order(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory, repetitions=2)
            run = self.run_record(context, plan)
            second = json.loads(json.dumps(run["attempts"][0]))
            second["attempt_id"] = "A002"
            second["repetition"] = 2
            run["attempts"].append(second)
            result = verification_result.finalize(
                plan, run, self.result_draft("supported")
            )
            result["checks"][0]["attempts"][0]["attempt_id"] = "A002"
            result["checks"][0]["attempts"][1]["attempt_id"] = "A001"

            with self.assertRaisesRegex(verification_result.ResultError, "sequential"):
                verification_result.validate_result(result)

    def test_canonical_context_plan_and_result_match_public_schemas(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as lead_directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            context, plan = self.make_plan(root, lead_directory)
            result = verification_result.finalize(
                plan, self.run_record(context, plan), self.result_draft("supported")
            )

            for name, value in (
                ("verification-context.schema.json", context),
                ("verification-plan.schema.json", plan),
                ("verification-result.schema.json", result),
            ):
                schema = json.loads(
                    (ROOT / "skills" / "verify-project" / "references" / name).read_text(
                        encoding="utf-8"
                    )
                )
                with self.subTest(schema=name):
                    assert_schema(value, schema)


if __name__ == "__main__":
    unittest.main()
