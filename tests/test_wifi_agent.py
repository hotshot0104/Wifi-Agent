from __future__ import annotations

import hashlib
import io
import json
import logging
from pathlib import Path
import plistlib
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import wifi_agent as app


def test_logger() -> logging.Logger:
    logger = logging.getLogger("wifi-agent-tests")
    logger.handlers[:] = [logging.NullHandler()]
    return logger


class FakeResponse:
    def __init__(self, content: bytes):
        self.stream = io.BytesIO(content)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)


class FakeOpener:
    def __init__(self, content: bytes):
        self.content = content
        self.requests = []

    def open(self, request, timeout: float):
        self.requests.append((request, timeout))
        return FakeResponse(self.content)


class ConfigTests(unittest.TestCase):
    def test_defaults_migrate_old_configuration(self) -> None:
        config = app.validate_config({"username": "student"}, require_username=True)
        self.assertEqual(config["portal_scheme"], "https")
        self.assertEqual(config["login_backoff_max_seconds"], 600)

    def test_ipv6_authority_is_bracketed(self) -> None:
        self.assertEqual(app._portal_authority("2001:db8::1", 8090), "[2001:db8::1]:8090")

    def test_rejects_url_in_host_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "hostname or IP"):
            app.validate_config({"portal_host": "https://portal.example/login"})

    def test_rejects_unsafe_ranges(self) -> None:
        for change in ({"portal_port": 0}, {"check_interval_seconds": 2}, {"login_backoff_max_seconds": 9000}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                app.validate_config(change)

    def test_config_file_never_persists_unknown_password_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(app, "app_dir", return_value=root),
                patch.object(app, "CONFIG_PATH", root / "config.json"),
            ):
                app.save_config({**app.DEFAULT_CONFIG, "username": "student", "password": "not-for-disk"})
                stored = (root / "config.json").read_text(encoding="utf-8")
                self.assertNotIn("password", stored.casefold())
                if sys.platform != "win32":
                    self.assertEqual((root / "config.json").stat().st_mode & 0o777, 0o600)

    def test_malformed_status_pid_is_treated_as_not_running(self) -> None:
        self.assertFalse(app.snapshot_process_running({"process_id": "not-a-pid"}))

    def test_ui_pane_state_is_private_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "ui-state.json"
            with patch.object(app, "app_dir", return_value=root), patch.object(app, "UI_STATE_PATH", state_path):
                app.save_ui_state({"last_pane": "diagnostics"})
                self.assertEqual(app.load_ui_state()["last_pane"], "diagnostics")
                if sys.platform != "win32":
                    self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)


class UpdateTests(unittest.TestCase):
    def release_payload(self, version: str, *, digest: str | None = None) -> dict:
        asset_name = f"WiFiAgent-{version}-Windows-x64-Setup.exe"
        return {
            "tag_name": f"v{version}",
            "html_url": f"https://github.com/akshajtiwari/Wifi-Agent/releases/tag/v{version}",
            "assets": [
                {
                    "name": asset_name,
                    "state": "uploaded",
                    "size": 123,
                    "digest": digest or "sha256:" + "a" * 64,
                    "browser_download_url": (
                        f"https://github.com/akshajtiwari/Wifi-Agent/releases/download/v{version}/{asset_name}"
                    ),
                }
            ],
        }

    def test_selects_platform_specific_installer_names(self) -> None:
        self.assertEqual(
            app._update_asset_name("1.4.0", "win32", "AMD64"),
            "WiFiAgent-1.4.0-Windows-x64-Setup.exe",
        )
        self.assertEqual(
            app._update_asset_name("1.4.0", "darwin", "arm64"),
            "WiFiAgent-1.4.0-macOS-arm64.pkg",
        )
        self.assertEqual(
            app._update_asset_name("1.4.0", "darwin", "x86_64"),
            "WiFiAgent-1.4.0-macOS-x86_64.pkg",
        )

    def test_latest_release_returns_verified_compatible_update(self) -> None:
        payload = self.release_payload("1.4.0")
        opener = FakeOpener(json.dumps(payload).encode())
        update = app.check_for_update(opener=opener, system="win32", machine="AMD64")
        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.version, "1.4.0")
        self.assertEqual(update.sha256, "a" * 64)
        self.assertEqual(opener.requests[0][0].get_header("X-github-api-version"), app.GITHUB_API_VERSION)

    def test_current_release_does_not_offer_an_update(self) -> None:
        payload = self.release_payload(app.APP_VERSION)
        self.assertIsNone(
            app.check_for_update(
                opener=FakeOpener(json.dumps(payload).encode()),
                system="win32",
                machine="AMD64",
            )
        )

    def test_release_without_digest_is_rejected(self) -> None:
        payload = self.release_payload("1.4.0")
        payload["assets"][0]["digest"] = None
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            app.check_for_update(
                opener=FakeOpener(json.dumps(payload).encode()),
                system="win32",
                machine="AMD64",
            )

    def test_untrusted_release_download_url_is_rejected(self) -> None:
        payload = self.release_payload("1.4.0")
        payload["assets"][0]["browser_download_url"] = "https://example.com/update.exe"
        with self.assertRaisesRegex(RuntimeError, "trusted GitHub"):
            app.check_for_update(
                opener=FakeOpener(json.dumps(payload).encode()),
                system="win32",
                machine="AMD64",
            )

    def test_oversized_update_is_rejected(self) -> None:
        payload = self.release_payload("1.4.0")
        payload["assets"][0]["size"] = app.MAX_UPDATE_SIZE + 1
        with self.assertRaisesRegex(RuntimeError, "safety limit"):
            app.check_for_update(
                opener=FakeOpener(json.dumps(payload).encode()),
                system="win32",
                machine="AMD64",
            )

    def test_download_is_saved_only_after_digest_verification(self) -> None:
        content = b"verified native installer"
        digest = hashlib.sha256(content).hexdigest()
        update = app.UpdateInfo(
            "1.3.0",
            "WiFiAgent-1.3.0-Windows-x64-Setup.exe",
            "https://github.com/akshajtiwari/Wifi-Agent/releases/download/v1.3.0/test.exe",
            "https://github.com/akshajtiwari/Wifi-Agent/releases/tag/v1.3.0",
            len(content),
            digest,
        )
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "app_dir", return_value=Path(directory)):
            installer = app.download_update(update, opener=FakeOpener(content))
            self.assertEqual(installer.read_bytes(), content)
            self.assertFalse(installer.with_suffix(".exe.part").exists())

    def test_digest_mismatch_deletes_partial_download(self) -> None:
        content = b"tampered installer"
        update = app.UpdateInfo(
            "1.3.0",
            "WiFiAgent-1.3.0-Windows-x64-Setup.exe",
            "https://github.com/akshajtiwari/Wifi-Agent/releases/download/v1.3.0/test.exe",
            "https://github.com/akshajtiwari/Wifi-Agent/releases/tag/v1.3.0",
            len(content),
            "0" * 64,
        )
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "app_dir", return_value=Path(directory)):
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                app.download_update(update, opener=FakeOpener(content))
            self.assertEqual(list((Path(directory) / "updates").glob("*")), [])

    def test_windows_update_uses_silent_forced_close_installer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = root / "updates" / "update.exe"
            installer.parent.mkdir()
            installer.write_bytes(b"installer")
            with (
                patch.object(app, "app_dir", return_value=root),
                patch.object(app.sys, "platform", "win32"),
                patch.object(app.subprocess, "Popen") as popen,
            ):
                app.install_downloaded_update(installer)
        arguments = popen.call_args.args[0]
        self.assertEqual(arguments[0], str(installer))
        self.assertIn("/VERYSILENT", arguments)
        self.assertIn("/FORCECLOSEAPPLICATIONS", arguments)

    def test_macos_update_uses_native_administrator_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = root / "updates" / "update.pkg"
            installer.parent.mkdir()
            installer.write_bytes(b"installer")
            with (
                patch.object(app, "app_dir", return_value=root),
                patch.object(app.sys, "platform", "darwin"),
                patch.object(app.subprocess, "run") as run,
            ):
                app.install_downloaded_update(installer)
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[0], "osascript")
        self.assertIn("administrator privileges", arguments[2])
        self.assertEqual(arguments[-1], str(installer))


class PortalTests(unittest.TestCase):
    def test_namespaced_xml_is_understood(self) -> None:
        success, message = app.PortalClient._response_summary(
            '<r xmlns="urn:test"><status>LIVE</status><message>Signed in</message></r>'
        )
        self.assertTrue(success)
        self.assertIn("Signed in", message)

    def test_failure_response_is_not_accepted(self) -> None:
        success, _ = app.PortalClient._response_summary(
            "<response><status>ERROR</status><message>Invalid credentials</message></response>"
        )
        self.assertFalse(success)

    def test_nominal_ack_with_logged_out_message_is_not_accepted(self) -> None:
        success, _ = app.PortalClient._response_summary(
            "<response><status>ACK</status><message>User is not logged in</message></response>"
        )
        self.assertFalse(success)

    def test_portal_message_redacts_password_and_controls(self) -> None:
        client = app.PortalClient(app.validate_config({"username": "student"}), "top-secret")
        self.assertEqual(client._safe_message("Error\nfor top-secret"), "Error for [redacted]")

    def test_connectivity_redirects_are_never_followed(self) -> None:
        handler = app._NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "http://portal.local"))


class MonitorTests(unittest.TestCase):
    def make_monitor(self, client) -> tuple[app.AgentMonitor, dict]:
        config = app.validate_config({"username": "student", "check_interval_seconds": 30})
        client.host = str(config["portal_host"])
        client.port = int(config["portal_port"])
        monitor = app.AgentMonitor(logger=test_logger())
        monitor._load_client = Mock(return_value=(config, client))
        return monitor, config

    def test_offline_reachable_portal_logs_in_and_verifies_internet(self) -> None:
        client = types.SimpleNamespace(
            login=Mock(return_value=(True, "LIVE")),
            keep_alive=Mock(return_value=(False, "DEAD")),
        )
        monitor, _ = self.make_monitor(client)
        with (
            patch.object(app, "wired_interfaces", return_value=["Ethernet"]),
            patch.object(app, "portal_port_open", return_value=True),
            patch.object(app, "internet_available", side_effect=[False, True]),
            patch.object(app, "write_status"),
            patch.object(monitor.stop_event, "wait", return_value=False),
        ):
            self.assertTrue(monitor.check_once())
        client.login.assert_called_once_with()
        self.assertEqual(monitor.snapshot.phase, "online")

    def test_login_failures_use_bounded_backoff(self) -> None:
        client = types.SimpleNamespace(
            login=Mock(return_value=(False, "DENIED")),
            keep_alive=Mock(return_value=(False, "DEAD")),
        )
        monitor, config = self.make_monitor(client)
        config["login_backoff_max_seconds"] = 60
        with (
            patch.object(app, "wired_interfaces", return_value=["Ethernet"]),
            patch.object(app, "portal_port_open", return_value=True),
            patch.object(app, "internet_available", return_value=False),
            patch.object(app, "write_status"),
            patch.object(app.random, "uniform", return_value=1.0),
        ):
            monitor.check_once()
            monitor._next_login_at = 0
            monitor.check_once()
            monitor._next_login_at = 0
            monitor.check_once()
        self.assertEqual(client.login.call_count, 3)
        self.assertEqual(monitor.snapshot.retry_in_seconds, 60)

    def test_live_portal_session_is_connected_when_public_probe_fails(self) -> None:
        client = types.SimpleNamespace(
            login=Mock(),
            keep_alive=Mock(return_value=(True, "LIVE Signed in")),
        )
        monitor, _ = self.make_monitor(client)
        with (
            patch.object(app, "wired_interfaces", return_value=["Ethernet"]),
            patch.object(app, "portal_port_open", return_value=True),
            patch.object(app, "internet_available", return_value=False),
            patch.object(app, "write_status"),
        ):
            self.assertTrue(monitor.check_once())
        client.login.assert_not_called()
        self.assertEqual(monitor.snapshot.phase, "connected")
        self.assertTrue(monitor.snapshot.portal_authenticated)

    def test_accepted_login_stays_connected_when_public_probe_fails(self) -> None:
        client = types.SimpleNamespace(
            login=Mock(return_value=(True, "ACK Signed in")),
            keep_alive=Mock(return_value=(False, "DEAD")),
        )
        monitor, _ = self.make_monitor(client)
        with (
            patch.object(app, "wired_interfaces", return_value=["Ethernet"]),
            patch.object(app, "portal_port_open", return_value=True),
            patch.object(app, "internet_available", return_value=False),
            patch.object(app, "write_status"),
            patch.object(monitor.stop_event, "wait", return_value=False),
        ):
            self.assertTrue(monitor.check_once())
        self.assertEqual(monitor.snapshot.phase, "connected")
        self.assertTrue(monitor.snapshot.portal_authenticated)
        self.assertEqual(monitor.snapshot.consecutive_login_failures, 0)

    def test_unreachable_port_resets_retry_storm(self) -> None:
        client = types.SimpleNamespace(login=Mock(), keep_alive=Mock())
        monitor, _ = self.make_monitor(client)
        monitor._login_failures = 4
        monitor._next_login_at = 999999
        with (
            patch.object(app, "wired_interfaces", return_value=["Ethernet"]),
            patch.object(app, "portal_port_open", return_value=False),
            patch.object(app, "internet_available", return_value=False),
            patch.object(app, "write_status"),
        ):
            monitor.check_once()
        self.assertEqual(monitor._login_failures, 0)
        client.login.assert_not_called()

    def test_pause_prevents_network_activity(self) -> None:
        monitor = app.AgentMonitor(logger=test_logger())
        monitor.pause_event.set()
        with patch.object(app, "wired_interfaces") as interfaces, patch.object(app, "write_status"):
            self.assertFalse(monitor.check_once())
        interfaces.assert_not_called()


class StartupTests(unittest.TestCase):
    def test_initial_setup_requires_credentials_and_startup(self) -> None:
        config = app.validate_config({"username": "student"})
        self.assertFalse(app.initial_setup_complete(config, startup_installed=False))
        with patch.object(app, "get_password", return_value="secret"):
            self.assertTrue(app.initial_setup_complete(config, startup_installed=True))

    def test_initial_setup_detects_missing_vault_password(self) -> None:
        config = app.validate_config({"username": "student"})
        with patch.object(app, "get_password", side_effect=RuntimeError("missing")):
            self.assertFalse(app.initial_setup_complete(config, startup_installed=True))

    def test_frozen_application_commands_do_not_reference_source_script(self) -> None:
        executable = Path("/Applications/WiFi Agent.app/Contents/MacOS/WiFi Agent")
        with (
            patch.object(app.sys, "frozen", True, create=True),
            patch.object(app.sys, "executable", str(executable)),
            patch.object(app.sys, "platform", "darwin"),
        ):
            self.assertEqual(app._service_command(), [str(executable), "tray"])
            self.assertEqual(app._application_working_directory(), executable.parent)

    def test_macos_install_at_login_rejects_app_running_from_disk_image(self) -> None:
        with (
            patch.object(app.sys, "frozen", True, create=True),
            patch.object(app.sys, "executable", "/Volumes/WiFi Agent/WiFi Agent.app/Contents/MacOS/WiFi Agent"),
            patch.object(app.sys, "platform", "darwin"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Applications folder"):
                app.install_startup()

    @unittest.skipIf(sys.platform == "win32", "Unix lock behavior")
    def test_single_instance_lock_rejects_duplicate_monitor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(app, "app_dir", return_value=root), patch.object(app, "LOCK_PATH", root / "agent.lock"):
                with app.SingleInstance():
                    with self.assertRaisesRegex(RuntimeError, "already running"):
                        with app.SingleInstance():
                            self.fail("duplicate instance unexpectedly acquired the lock")

    def test_windows_service_runs_tray_with_restart_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captured: dict[str, bytes] = {}

            def fake_run(arguments, **kwargs):
                if "/XML" in arguments:
                    task_path = Path(arguments[arguments.index("/XML") + 1])
                    captured["task"] = task_path.read_bytes()
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch.object(app.sys, "platform", "win32"),
                patch.object(app, "app_dir", return_value=root),
                patch.object(app, "load_config", return_value=app.validate_config({"username": "student"})),
                patch.object(app, "get_password", return_value="secret"),
                patch.object(app.subprocess, "run", side_effect=fake_run),
            ):
                app.install_startup()

            task = ET.fromstring(captured["task"])
            namespace = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
            arguments = task.findtext(".//t:Arguments", namespaces=namespace) or ""
            self.assertIn("tray", arguments)
            self.assertIsNotNone(task.find(".//t:RestartOnFailure", namespace))
            self.assertEqual(task.findtext(".//t:MultipleInstancesPolicy", namespaces=namespace), "IgnoreNew")

    def test_macos_launch_agent_runs_menu_bar_and_stays_quit_after_clean_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_result = types.SimpleNamespace(returncode=0, stdout="", stderr="")
            with (
                patch.object(app.sys, "platform", "darwin"),
                patch.object(app.Path, "home", return_value=root),
                patch.object(app, "app_dir", return_value=root / "config"),
                patch.object(app, "load_config", return_value=app.validate_config({"username": "student"})),
                patch.object(app, "get_password", return_value="secret"),
                patch.object(app.subprocess, "run", return_value=fake_result),
            ):
                app.install_startup()

            plist_path = root / "Library" / "LaunchAgents" / "com.local.wifi-agent.plist"
            with plist_path.open("rb") as handle:
                payload = plistlib.load(handle)
            self.assertEqual(payload["ProgramArguments"][-1], "tray")
            self.assertEqual(payload["KeepAlive"], {"SuccessfulExit": False})


if __name__ == "__main__":
    unittest.main()
