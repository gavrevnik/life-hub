#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import plistlib
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.server import APPLICATION_ID, APP_VERSION, DEFAULT_PORT  # noqa: E402


LABEL = "local.gavrevnik.life-hub"
ENTRYPOINT = ROOT / "app" / "server.py"
RUNTIME_DIR = ROOT / ".runtime"
LOG_PATH = RUNTIME_DIR / "server.log"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
DOMAIN = f"gui/{os.getuid()}"
TARGET = f"{DOMAIN}/{LABEL}"
HEALTH_URL = f"http://127.0.0.1:{DEFAULT_PORT}/api/health"


def launch_agent_config() -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/python3", str(ENTRYPOINT)],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 10,
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
    }


def run_launchctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["/bin/launchctl", *arguments],
            check=check,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or str(error)
        raise RuntimeError(f"launchctl: {detail}") from error


def bootout() -> None:
    run_launchctl("bootout", TARGET, check=False)


def listener_pid() -> int | None:
    result = subprocess.run(
        [
            "/usr/sbin/lsof",
            f"-tiTCP:{DEFAULT_PORT}",
            "-sTCP:LISTEN",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    first_line = result.stdout.splitlines()[:1]
    return int(first_line[0]) if first_line and first_line[0].isdigit() else None


def process_command(pid: int) -> str:
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def stop_existing_hub(*, reject_foreign: bool = True) -> None:
    pid = listener_pid()
    if pid is None:
        return
    if str(ENTRYPOINT) not in process_command(pid):
        if reject_foreign:
            raise RuntimeError(
                f"Порт {DEFAULT_PORT} занят посторонним процессом {pid}; установка отменена"
            )
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    raise RuntimeError(f"Не удалось остановить предыдущий Life Hub (PID {pid})")


def hub_ready() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1) as response:
            health = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return (
        health.get("application") == APPLICATION_ID
        and health.get("version") == APP_VERSION
    )


def install() -> None:
    if sys.platform != "darwin":
        raise RuntimeError("Автозапуск Life Hub поддерживается только на macOS")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    bootout()
    stop_existing_hub()

    temporary_path = PLIST_PATH.with_suffix(".plist.tmp")
    try:
        with temporary_path.open("wb") as stream:
            plistlib.dump(
                launch_agent_config(), stream, fmt=plistlib.FMT_XML, sort_keys=False
            )
        temporary_path.replace(PLIST_PATH)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass

    try:
        run_launchctl("bootstrap", DOMAIN, str(PLIST_PATH))
        run_launchctl("kickstart", TARGET)
    except RuntimeError:
        PLIST_PATH.unlink(missing_ok=True)
        raise
    for _ in range(100):
        if hub_ready():
            print(f"Life Hub запущен и добавлен в автозапуск: {PLIST_PATH}")
            return
        time.sleep(0.1)
    bootout()
    PLIST_PATH.unlink(missing_ok=True)
    raise RuntimeError(f"Life Hub не запустился; проверьте журнал {LOG_PATH}")


def uninstall() -> None:
    bootout()
    try:
        PLIST_PATH.unlink()
    except FileNotFoundError:
        pass
    stop_existing_hub(reject_foreign=False)
    print("Автозапуск Life Hub удалён")


def main() -> None:
    parser = argparse.ArgumentParser(description="Установить автозапуск Life Hub")
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="выключить и удалить пользовательский LaunchAgent",
    )
    args = parser.parse_args()
    try:
        uninstall() if args.uninstall else install()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Ошибка: {error}\n")


if __name__ == "__main__":
    main()
