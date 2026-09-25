from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.server import (
    APP_VERSION,
    HEARTBEAT_ACTIVE_SECONDS,
    HeartbeatTracker,
    _heartbeat_origin_allowed,
    stop_idle_services,
    stop_service,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class HeartbeatTrackerTest(unittest.TestCase):
    def test_application_version_matches_launcher_contract(self) -> None:
        self.assertEqual(APP_VERSION, "0.2.0")

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

    @patch("app.server.os.kill")
    @patch("app.server._pid_belongs_to_service", return_value=False)
    @patch("app.server._service_pid", return_value=4242)
    def test_stop_refuses_unverified_pid(self, _pid, _belongs, kill) -> None:
        service = {
            "runtimePidFile": "../activity-checker/.runtime/web.pid",
            "repository": "../activity-checker",
        }
        with self.assertRaisesRegex(RuntimeError, "посторонний процесс"):
            stop_service(service)
        kill.assert_not_called()

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
