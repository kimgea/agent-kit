import contextlib
import io
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


artifact_host = load_module(
    "artifact_host", ROOT / "skills" / "serve-artifacts" / "scripts" / "artifact_host.py"
)


def free_port():
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return handle.getsockname()[1]


def request(url, method="GET", headers=None):
    value = urllib.request.Request(url, method=method, headers=headers or {})
    return urllib.request.urlopen(value, timeout=3)


class UpstreamHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "https://example.invalid/never-follow")
            self.end_headers()
            return
        payload = f"upstream:{self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@contextlib.contextmanager
def upstream_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class ArtifactStoreTests(unittest.TestCase):
    def make_site(self, base):
        site = Path(base) / "site"
        site.mkdir()
        (site / "index.html").write_text(
            '<!doctype html><script src="app.js"></script><a href="page.html">Page</a>',
            encoding="utf-8",
        )
        (site / "page.html").write_text("<!doctype html><h1>Second page</h1>", encoding="utf-8")
        (site / "app.js").write_text("document.body.dataset.ready = 'yes';", encoding="utf-8")
        return site

    def test_state_paths_are_os_native_and_override_must_be_absolute(self):
        if os.name == "nt":
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:/Agent Data"}, clear=False):
                self.assertEqual(
                    Path("C:/Agent Data") / "AgentKit" / "artifacts",
                    artifact_host.state_root(),
                )
        elif sys.platform == "darwin":
            self.assertIn(
                "Library/Application Support/AgentKit/artifacts",
                artifact_host.state_root().as_posix(),
            )
        else:
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/tmp/state base"}, clear=False):
                self.assertEqual(
                    Path("/tmp/state base/agent-kit/artifacts"), artifact_host.state_root()
                )
        with self.assertRaisesRegex(artifact_host.ArtifactError, "absolute"):
            artifact_host.state_root("relative/state")

    def test_publish_reserve_expire_and_revoke_touch_only_owned_copies(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "private state"
            site = self.make_site(base)
            reserved = artifact_host.reserve_artifact(root, "5m", "Reserved")
            published = artifact_host.publish_static(
                root, site, "10m", "Published", "index.html", False, reserved["id"]
            )
            self.assertEqual(reserved["id"], published["id"])
            self.assertLessEqual(
                artifact_host.parse_time(published["expires_at"]),
                artifact_host.parse_time(reserved["expires_at"]),
            )
            copied = root / "content" / published["id"] / "index.html"
            self.assertTrue(copied.is_file())
            (site / "index.html").write_text("changed source", encoding="utf-8")
            self.assertNotEqual("changed source", copied.read_text(encoding="utf-8"))

            self.assertTrue(artifact_host.revoke_artifact(root, published["id"]))
            self.assertFalse(copied.exists())
            self.assertTrue((site / "index.html").exists())
            self.assertFalse(artifact_host.revoke_artifact(root, published["id"]))

            expiring = artifact_host.reserve_artifact(root, "1s", "Soon gone")
            removed = artifact_host.cleanup_expired(
                root, artifact_host.utc_now() + artifact_host.dt.timedelta(seconds=2)
            )
            self.assertEqual([expiring["id"]], removed)

    def test_bundle_validation_rejects_links_executables_limits_and_bad_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "state"
            site = self.make_site(base)
            (site / "run.sh").write_text("#!/bin/sh", encoding="utf-8")
            with self.assertRaisesRegex(artifact_host.ArtifactError, "blocked executable"):
                artifact_host.publish_static(root, site, "1h", "Bad", "index.html", False)
            (site / "run.sh").unlink()
            with self.assertRaisesRegex(artifact_host.ArtifactError, "entry file"):
                artifact_host.publish_static(root, site, "1h", "Bad", "missing.html", False)

            if hasattr(os, "symlink"):
                outside = base / "outside.html"
                outside.write_text("outside", encoding="utf-8")
                link = site / "linked.html"
                try:
                    link.symlink_to(outside)
                except OSError:
                    pass
                else:
                    with self.assertRaisesRegex(artifact_host.ArtifactError, "linked"):
                        artifact_host.publish_static(
                            root, site, "1h", "Bad", "index.html", False
                        )
                    link.unlink()
                root_link = base / "site-link"
                try:
                    root_link.symlink_to(site, target_is_directory=True)
                except OSError:
                    pass
                else:
                    with self.assertRaisesRegex(artifact_host.ArtifactError, "symlinked"):
                        artifact_host.publish_static(
                            root, root_link, "1h", "Bad", "index.html", False
                        )

            with mock.patch.object(artifact_host, "MAX_FILES", 2):
                with self.assertRaisesRegex(artifact_host.ArtifactError, "exceeds 2 files"):
                    artifact_host.inspect_bundle(site, "index.html")

    def test_proxy_targets_are_loopback_only(self):
        self.assertEqual(
            "http://127.0.0.1:3000/base",
            artifact_host.normalize_proxy_target("http://localhost:3000/base/"),
        )
        for target in (
            "https://127.0.0.1:3000",
            "http://0.0.0.0:3000",
            "http://example.com:3000",
            "http://localhost",
            "http://user:pass@localhost:3000",
        ):
            with self.subTest(target=target):
                with self.assertRaises(artifact_host.ArtifactError):
                    artifact_host.normalize_proxy_target(target)

    def test_direct_binding_requires_one_explicit_interface_and_confirmation(self):
        self.assertEqual(
            "127.0.0.1", artifact_host.normalize_bind_address("127.0.0.1")
        )
        self.assertEqual(
            "192.0.2.10",
            artifact_host.normalize_bind_address("192.0.2.10", allow_remote=True),
        )
        with self.assertRaisesRegex(artifact_host.ArtifactError, "--allow-remote"):
            artifact_host.normalize_bind_address("192.0.2.10")
        for value in ("0.0.0.0", "::", "::1", "host.example", "224.0.0.1"):
            with self.subTest(value=value):
                with self.assertRaises(artifact_host.ArtifactError):
                    artifact_host.normalize_bind_address(value, allow_remote=True)

    def test_advertise_url_is_provider_neutral_and_path_bounded(self):
        self.assertEqual(
            "https://artifacts.work.example/agent-artifacts",
            artifact_host.normalize_advertise_url(
                "https://artifacts.work.example/agent-artifacts/"
            ),
        )
        self.assertEqual(
            "http://vpn-host:4177",
            artifact_host.normalize_advertise_url("http://vpn-host:4177"),
        )
        for value in (
            "ftp://vpn-host:4177",
            "http://user:pass@vpn-host:4177",
            "http://vpn-host:4177/other",
            "http://vpn-host:4177?token=secret",
            "http://vpn host:4177",
        ):
            with self.subTest(value=value):
                with self.assertRaises(artifact_host.ArtifactError):
                    artifact_host.normalize_advertise_url(value)

    def test_artifact_urls_prefer_an_explicit_provider_neutral_browser_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "state"
            artifact_host.ensure_private_dir(root)
            artifact_host.atomic_write_json(
                artifact_host.runtime_path(root),
                {
                    "port": 4177,
                    "bind_address": "192.0.2.10",
                    "advertise_url": "https://artifacts.work.example/agent-artifacts",
                },
            )
            artifact_id = artifact_host.new_id()
            urls = artifact_host.artifact_urls(root, {"id": artifact_id}, 4177)
            expected = (
                f"https://artifacts.work.example/agent-artifacts/a/{artifact_id}/"
            )
            self.assertEqual(expected, urls["shared_url"])
            self.assertEqual(expected, urls["browser_url"])
            self.assertNotIn("local_url", urls)
            self.assertEqual(
                f"{artifact_host.PUBLIC_PREFIX}/c/{artifact_id}",
                urls["content_base_path"],
            )

    def test_remote_browser_handoff_stays_client_owned(self):
        skill = (ROOT / "skills" / "serve-artifacts" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        reference = (
            ROOT / "skills" / "serve-artifacts" / "references" / "remote-access.md"
        ).read_text(encoding="utf-8")
        combined = skill + reference
        self.assertNotIn("termux-open-url", combined)
        self.assertNotIn("terminal-onclick-url-open", combined)
        self.assertNotIn("OSC 52", reference)
        self.assertIn("full bare `browser_url`", reference)
        self.assertIn("outside this skill", reference)

    def test_owned_adapter_blocks_incompatible_server_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "state"
            artifact_host.ensure_private_dir(root)
            artifact_host.atomic_write_json(
                artifact_host.tailscale_path(root),
                {"target": "http://127.0.0.1:4177"},
            )
            with mock.patch.object(artifact_host.subprocess, "Popen") as popen:
                with self.assertRaisesRegex(
                    artifact_host.ArtifactError, "remove it before restarting"
                ):
                    artifact_host.start_server(
                        root,
                        4177,
                        "10.23.45.67",
                        allow_remote=True,
                    )
            popen.assert_not_called()

    def test_invalid_publish_does_not_start_the_background_service(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "state"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = artifact_host.main(
                    ["--state-dir", str(root), "publish", str(Path(temporary) / "missing")]
                )
            self.assertEqual(2, result)
            self.assertFalse(artifact_host.runtime_path(root).exists())
            self.assertIn("does not exist", stderr.getvalue())

    def test_remote_start_arguments_are_gated_before_process_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "state"
            stderr = io.StringIO()
            with mock.patch.object(artifact_host.subprocess, "Popen") as popen:
                with contextlib.redirect_stderr(stderr):
                    result = artifact_host.main(
                        [
                            "--state-dir",
                            str(root),
                            "start",
                            "--bind-address",
                            "10.23.45.67",
                            "--json",
                        ]
                    )
            self.assertEqual(2, result)
            popen.assert_not_called()
            self.assertFalse(artifact_host.runtime_path(root).exists())
            self.assertIn("--allow-remote", stderr.getvalue())

            with mock.patch.object(
                artifact_host,
                "start_server",
                return_value={"running": True},
            ) as start:
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = artifact_host.main(
                        [
                            "--state-dir",
                            str(root),
                            "start",
                            "--bind-address",
                            "10.23.45.67",
                            "--allow-remote",
                            "--advertise-url",
                            "http://private-host:4177",
                            "--json",
                        ]
                    )
            self.assertEqual(0, result)
            start.assert_called_once_with(
                artifact_host.state_root(str(root)),
                artifact_host.DEFAULT_PORT,
                "10.23.45.67",
                True,
                "http://private-host:4177",
            )

    def test_symlinked_state_files_and_lock_are_refused(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "state"
            root.mkdir()
            outside = Path(temporary) / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            registry = artifact_host.registry_path(root)
            try:
                registry.symlink_to(outside)
            except OSError:
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(artifact_host.ArtifactError, "symlinked state file"):
                artifact_host.load_registry(root)
            registry.unlink()
            lock = root / ".lock"
            lock.symlink_to(outside)
            with self.assertRaisesRegex(artifact_host.ArtifactError, "symlinked state lock"):
                with artifact_host.store_lock(root):
                    pass


class ArtifactServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "state"
        self.site = ArtifactStoreTests().make_site(self.base)
        self.port = free_port()
        self.status = artifact_host.start_server(self.root, self.port)

    def tearDown(self):
        with contextlib.suppress(Exception):
            artifact_host.stop_server(self.root)
        self.temporary.cleanup()

    def test_static_multipage_spa_prefix_headers_and_no_management_surface(self):
        record = artifact_host.publish_static(
            self.root, self.site, "1h", "Test visual", "index.html", True
        )
        base = f"http://127.0.0.1:{self.port}"
        with request(f"{base}/a/{record['id']}/") as response:
            body = response.read().decode()
            self.assertIn("Test visual", body)
            self.assertIn(f"../../c/{record['id']}/index.html", body)
            self.assertIn("sandbox=", body)
            self.assertEqual("no-store", response.headers["Cache-Control"])
        with request(f"{base}/c/{record['id']}/page.html") as response:
            self.assertIn("Second page", response.read().decode())
            self.assertIn("connect-src 'self'", response.headers["Content-Security-Policy"])
            self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
        with request(
            f"{base}{artifact_host.PUBLIC_PREFIX}/c/{record['id']}/client/route"
        ) as response:
            self.assertIn("script", response.read().decode())
        for path in ("/", "/list", "/api/artifacts", f"/c/{record['id']}/../registry.json"):
            with self.subTest(path=path):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    request(base + path)
                self.assertEqual(404, caught.exception.code)
                caught.exception.close()

    def test_proxy_relays_loopback_without_following_external_redirects(self):
        with upstream_server() as upstream_port:
            record = artifact_host.publish_proxy(
                self.root,
                f"http://localhost:{upstream_port}",
                "1h",
                "Local app",
                False,
            )
            base = f"http://127.0.0.1:{self.port}/c/{record['id']}"
            with request(base + "/hello?x=1") as response:
                self.assertEqual("upstream:/hello?x=1", response.read().decode())
                self.assertIn("connect-src 'self'", response.headers["Content-Security-Policy"])
            no_redirect = urllib.request.build_opener(artifact_host.NoRedirect)
            with self.assertRaises(urllib.error.HTTPError) as caught:
                no_redirect.open(base + "/redirect", timeout=3)
            self.assertEqual(302, caught.exception.code)
            self.assertEqual("https://example.invalid/never-follow", caught.exception.headers["Location"])
            caught.exception.close()

    def test_diagram_starter_is_self_contained_and_publishable(self):
        starter = (
            ROOT / "skills" / "build-interactive-diagram" / "assets" / "starter"
        )
        index = (starter / "index.html").read_text(encoding="utf-8")
        script = (starter / "app.js").read_text(encoding="utf-8")
        styles = (starter / "styles.css").read_text(encoding="utf-8")
        self.assertIn('href="styles.css"', index)
        self.assertIn('src="app.js"', index)
        self.assertNotIn("innerHTML", script)
        self.assertNotRegex(index + styles, r"https?://")

        record = artifact_host.publish_static(
            self.root, starter, "1h", "Starter", "index.html", False
        )
        base = f"http://127.0.0.1:{self.port}/c/{record['id']}"
        for relative, marker in (
            ("index.html", "Interactive system map"),
            ("styles.css", "prefers-reduced-motion"),
            ("app.js", "ResizeObserver"),
        ):
            with self.subTest(relative=relative):
                with request(f"{base}/{relative}") as response:
                    self.assertIn(marker, response.read().decode())

    def test_next_export_shape_works_under_a_reserved_prefix(self):
        reserved = artifact_host.reserve_artifact(self.root, "1h", "Next export")
        urls = artifact_host.artifact_urls(self.root, reserved, self.port)
        content_base_path = urls["content_base_path"]
        self.assertFalse(content_base_path.endswith("/"))

        exported = self.base / "next-out"
        (exported / "about").mkdir(parents=True)
        (exported / "_next" / "static" / "chunks").mkdir(parents=True)
        (exported / "index.html").write_text(
            f'<a href="{content_base_path}/about/">About</a>'
            f'<script src="{content_base_path}/_next/static/chunks/app.js"></script>',
            encoding="utf-8",
        )
        (exported / "about" / "index.html").write_text(
            "Next secondary route", encoding="utf-8"
        )
        (exported / "_next" / "static" / "chunks" / "app.js").write_text(
            "window.nextFixture = true;", encoding="utf-8"
        )
        artifact_host.publish_static(
            self.root,
            exported,
            "1h",
            "Next export",
            "index.html",
            False,
            reserved["id"],
        )

        origin = f"http://127.0.0.1:{self.port}{content_base_path}"
        for relative, marker in (
            ("/", "About"),
            ("/about/", "Next secondary route"),
            ("/_next/static/chunks/app.js", "nextFixture"),
        ):
            with self.subTest(relative=relative):
                with request(origin + relative) as response:
                    self.assertIn(marker, response.read().decode())

    def test_background_lifecycle_is_idempotent_and_owned(self):
        second = artifact_host.start_server(self.root, self.port)
        self.assertTrue(second["running"])
        self.assertEqual(self.status["instance_id"], second["instance_id"])
        self.assertEqual("127.0.0.1", second["bind_address"])
        self.assertEqual(second["local_base_url"], second["browser_base_url"])
        with self.assertRaisesRegex(artifact_host.ArtifactError, "already runs"):
            artifact_host.start_server(self.root, free_port())
        with self.assertRaisesRegex(artifact_host.ArtifactError, "network settings"):
            artifact_host.start_server(
                self.root,
                self.port,
                advertise_url="https://artifacts.work.example/agent-artifacts",
            )
        runtime = artifact_host.read_runtime(self.root)
        self.assertNotIn("token", artifact_host.server_status(self.root))
        self.assertTrue(artifact_host.health(runtime))
        self.assertTrue(artifact_host.stop_server(self.root))
        self.assertFalse(artifact_host.stop_server(self.root))


class TailscaleBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "state"
        artifact_host.ensure_private_dir(self.root)
        artifact_host.atomic_write_json(
            artifact_host.runtime_path(self.root),
            {"port": 4177, "token": "token", "instance_id": "instance"},
        )
        self.patches = [
            mock.patch.object(artifact_host, "tailscale_binary", return_value="/usr/bin/tailscale"),
            mock.patch.object(artifact_host, "health", return_value=True),
            mock.patch.object(artifact_host, "tailscale_serve_status", return_value={}),
            mock.patch.object(
                artifact_host,
                "tailscale_status",
                return_value={"Self": {"DNSName": "dev.example.ts.net."}},
            ),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temporary.cleanup()

    def test_setup_dry_run_is_non_mutating_and_apply_is_exact(self):
        with mock.patch.object(artifact_host, "run_command") as run:
            plan = artifact_host.tailscale_setup(
                self.root, 4177, 443, "/agent-artifacts", False, False
            )
            run.assert_not_called()
        self.assertFalse(artifact_host.tailscale_path(self.root).exists())
        self.assertFalse(plan["applied"])
        self.assertEqual(
            [
                "/usr/bin/tailscale",
                "serve",
                "--bg",
                "--yes",
                "--https=443",
                "--set-path=/agent-artifacts",
                "http://127.0.0.1:4177",
            ],
            plan["command"],
        )
        self.assertNotIn("funnel", " ".join(plan["command"]).lower())
        self.assertIn("certificate", plan["certificate_notice"].lower())

        completed = subprocess.CompletedProcess(plan["command"], 0, "ok", "")
        with mock.patch.object(artifact_host, "run_command", return_value=completed) as run:
            applied = artifact_host.tailscale_setup(
                self.root, 4177, 443, "/agent-artifacts", True, True
            )
        run.assert_called_once_with(
            plan["command"], timeout=artifact_host.NETWORK_APPLY_TIMEOUT_SECONDS
        )
        self.assertTrue(applied["applied"])
        state = json.loads(artifact_host.tailscale_path(self.root).read_text(encoding="utf-8"))
        self.assertEqual("https://dev.example.ts.net/agent-artifacts", state["base_url"])

    def test_remove_requires_owned_state_and_removes_only_exact_path(self):
        absent = artifact_host.tailscale_remove(self.root, False, False)
        self.assertFalse(absent["configured"])
        state = {
            "schema_version": 1,
            "path": "/agent-artifacts",
            "https_port": 443,
            "target": "http://127.0.0.1:4177",
            "base_url": "https://dev.example.ts.net/agent-artifacts",
        }
        artifact_host.atomic_write_json(artifact_host.tailscale_path(self.root), state)
        preview = artifact_host.tailscale_remove(self.root, False, False)
        self.assertTrue(artifact_host.tailscale_path(self.root).exists())
        self.assertEqual("off", preview["command"][-1])
        self.assertIn("--set-path=/agent-artifacts", preview["command"])
        self.assertNotIn("reset", preview["command"])

        completed = subprocess.CompletedProcess(preview["command"], 0, "ok", "")
        with mock.patch.object(artifact_host, "run_command", return_value=completed):
            result = artifact_host.tailscale_remove(self.root, True, True)
        self.assertTrue(result["applied"])
        self.assertFalse(artifact_host.tailscale_path(self.root).exists())

    def test_setup_refuses_unowned_conflict_and_confirmation_shortcuts(self):
        with self.assertRaisesRegex(artifact_host.ArtifactError, "--yes requires"):
            artifact_host.tailscale_setup(
                self.root, 4177, 443, "/agent-artifacts", False, True
            )
        with self.assertRaisesRegex(artifact_host.ArtifactError, "requires --apply --yes"):
            artifact_host.tailscale_setup(
                self.root, 4177, 443, "/agent-artifacts", True, False
            )
        with mock.patch.object(
            artifact_host,
            "tailscale_serve_status",
            return_value={"Handlers": {"/agent-artifacts/": {"Proxy": "http://127.0.0.1:9000"}}},
        ):
            with self.assertRaisesRegex(artifact_host.ArtifactError, "not owned"):
                artifact_host.tailscale_plan(
                    self.root, 4177, 443, "/agent-artifacts"
                )

        artifact_host.atomic_write_json(
            artifact_host.runtime_path(self.root),
            {
                "port": 4177,
                "bind_address": "192.0.2.10",
                "token": "token",
                "instance_id": "instance",
            },
        )
        with self.assertRaisesRegex(artifact_host.ArtifactError, "loopback-bound"):
            artifact_host.tailscale_plan(self.root, 4177, 443, "/agent-artifacts")

    def test_setup_rolls_back_exact_route_when_ownership_write_fails(self):
        plan = artifact_host.tailscale_plan(self.root, 4177, 443, "/agent-artifacts")
        completed = subprocess.CompletedProcess(plan["command"], 0, "ok", "")
        with mock.patch.object(
            artifact_host, "run_command", side_effect=[completed, completed]
        ) as run:
            with mock.patch.object(
                artifact_host, "atomic_write_json", side_effect=OSError("disk full")
            ):
                with self.assertRaisesRegex(OSError, "disk full"):
                    artifact_host.tailscale_setup(
                        self.root, 4177, 443, "/agent-artifacts", True, True
                    )
        self.assertEqual(2, run.call_count)
        rollback = run.call_args_list[1].args[0]
        self.assertEqual("off", rollback[-1])
        self.assertIn("--set-path=/agent-artifacts", rollback)
        self.assertNotIn("reset", rollback)

    def test_command_timeout_is_a_concise_user_facing_error(self):
        command = ["/usr/bin/tailscale", "serve"]
        expired = subprocess.TimeoutExpired(
            command, 60, output="enable Serve at https://login.example/enable"
        )
        with mock.patch.object(artifact_host.subprocess, "run", side_effect=expired):
            with self.assertRaisesRegex(
                artifact_host.ArtifactError, "timed out after 60 seconds.*enable Serve"
            ):
                artifact_host.run_command(command, timeout=60)


if __name__ == "__main__":
    unittest.main()
