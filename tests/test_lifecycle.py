from __future__ import annotations

import sys
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = ROOT / "Life Hub.app" / "Contents" / "MacOS" / "Life Hub"
sys.path.insert(0, str(ROOT))

from app.server import (
    APP_VERSION,
    HEARTBEAT_ACTIVE_SECONDS,
    HeartbeatTracker,
    IdleCleanupPolicy,
    _heartbeat_origin_allowed,
    _listener_pids,
    stop_idle_services,
    stop_service,
)
from scripts.install_autostart import (
    ENTRYPOINT,
    LABEL,
    launch_agent_config,
    stop_existing_hub,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class HeartbeatTrackerTest(unittest.TestCase):
    def test_application_version_matches_launcher_contract(self) -> None:
        self.assertEqual(APP_VERSION, "0.4.0")
        self.assertIn(
            f'EXPECTED_VERSION="{APP_VERSION}"',
            LAUNCHER_PATH.read_text(encoding="utf-8"),
        )

    def test_heartbeat_resets_idle_timer_and_tracks_tabs(self) -> None:
        clock = FakeClock()
        tracker = HeartbeatTracker(clock)
        clock.now += 12
        self.assertEqual(tracker.idle_seconds(), 12)

        tracker.touch("life-hub", "tab-12345678")
        self.assertEqual(tracker.idle_seconds(), 0)
        self.assertEqual(tracker.active_tabs(), 1)

        clock.now += HEARTBEAT_ACTIVE_SECONDS + 1
        self.assertEqual(tracker.active_tabs(), 0)
        self.assertEqual(tracker.idle_seconds(), HEARTBEAT_ACTIVE_SECONDS + 1)

    def test_idle_cleanup_runs_once_and_rearms_after_activity(self) -> None:
        policy = IdleCleanupPolicy()

        self.assertFalse(policy.should_cleanup(299, 300))
        self.assertTrue(policy.should_cleanup(300, 300))
        self.assertFalse(policy.should_cleanup(600, 300))
        self.assertFalse(policy.should_cleanup(0, 300))
        self.assertTrue(policy.should_cleanup(300, 300))

    def test_autostart_keeps_the_local_server_running(self) -> None:
        config = launch_agent_config()

        self.assertEqual(config["Label"], LABEL)
        self.assertEqual(config["ProgramArguments"], ["/usr/bin/python3", str(ENTRYPOINT)])
        self.assertTrue(config["RunAtLoad"])
        self.assertTrue(config["KeepAlive"])

    @patch("scripts.install_autostart.os.kill")
    @patch("scripts.install_autostart.process_command", return_value="other-server")
    @patch("scripts.install_autostart.listener_pid", return_value=4242)
    def test_autostart_never_stops_a_foreign_listener(
        self, _listener_pid, _process_command, kill
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "посторонним процессом"):
            stop_existing_hub()
        stop_existing_hub(reject_foreign=False)
        kill.assert_not_called()

    def test_heartbeat_origin_is_limited_to_matching_service(self) -> None:
        self.assertTrue(
            _heartbeat_origin_allowed(
                "activity-checker", "http://127.0.0.1:4318"
            )
        )
        self.assertFalse(
            _heartbeat_origin_allowed(
                "activity-checker", "https://untrusted.example"
            )
        )
        self.assertTrue(
            _heartbeat_origin_allowed("life-hub", "http://localhost:9876", 9876)
        )
        self.assertTrue(
            _heartbeat_origin_allowed(
                "activity-checker", "http://activity-checker.localhost"
            )
        )

    @patch("app.server.os.kill")
    @patch("app.server._pid_belongs_to_service", return_value=False)
    @patch("app.server._listener_pids", return_value=[])
    @patch("app.server._service_pid", return_value=4242)
    def test_stop_refuses_unverified_pid(
        self, _pid, _listeners, _belongs, kill
    ) -> None:
        service = {
            "runtimePidFile": "../activity-checker/.runtime/web.pid",
            "repository": "../activity-checker",
        }
        with self.assertRaisesRegex(RuntimeError, "посторонний процесс"):
            stop_service(service)
        kill.assert_not_called()

    @patch("app.server.subprocess.run")
    def test_listener_pid_comes_only_from_declared_local_port(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="98650\n98650\n", stderr=""
        )
        self.assertEqual(
            _listener_pids({"directUrl": "http://127.0.0.1:4318/"}),
            [98650],
        )
        self.assertEqual(
            _listener_pids({"directUrl": "https://example.com:4318/"}),
            [],
        )
        run.assert_called_once()

    @patch("app.server.stop_service")
    def test_idle_shutdown_honors_per_service_policy(self, stop) -> None:
        stop_idle_services(
            [
                {"id": "foreground", "stopWhenBrowserIdle": True},
                {"id": "background", "stopWhenBrowserIdle": False},
            ]
        )
        stop.assert_called_once_with(
            {"id": "foreground", "stopWhenBrowserIdle": True}
        )


if __name__ == "__main__":
    unittest.main()
