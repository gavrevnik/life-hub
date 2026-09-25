from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent.resolve()
STATIC_DIR = ROOT / "app" / "static"
REGISTRY_PATH = ROOT / "registry.json"
PID_FILE = ROOT / ".runtime" / "server.pid"
APPLICATION_ID = "life-hub"
APP_VERSION = "0.2.0"
DEFAULT_PORT = 8790
DEFAULT_IDLE_TIMEOUT_SECONDS = 5 * 60
HEARTBEAT_ACTIVE_SECONDS = 45
SERVICE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def load_registry() -> list[dict]:
    services = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(services, list):
        raise ValueError("registry.json must contain a list")
    seen: set[str] = set()
    for service in services:
        service_id = str(service.get("id") or "")
        if not SERVICE_ID.fullmatch(service_id) or service_id in seen:
            raise ValueError(f"Invalid or duplicate service id: {service_id}")
        seen.add(service_id)
        for key in ("name", "description", "repository", "url", "healthUrl", "launcher", "runtimePidFile"):
            if not str(service.get(key) or "").strip():
                raise ValueError(f"{service_id}: missing {key}")
        if not isinstance(service.get("stopWhenBrowserIdle"), bool):
            raise ValueError(f"{service_id}: stopWhenBrowserIdle must be boolean")
        resolve_workspace_path(service["repository"])
        resolve_workspace_path(service["launcher"])
        resolve_workspace_path(service["runtimePidFile"])
    return services


def resolve_workspace_path(relative_path: str) -> Path:
    candidate = (ROOT / relative_path).resolve()
    candidate.relative_to(WORKSPACE_ROOT)
    return candidate


def is_service_running(service: dict) -> bool:
    request = urllib.request.Request(
        service["healthUrl"],
        headers={"User-Agent": "life-hub/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=0.6) as response:
            payload = json.loads(response.read(128_000).decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return False
    expected = service.get("healthExpected") or {}
    return response.status == HTTPStatus.OK and all(
        payload.get(key) == value for key, value in expected.items()
    )


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _service_pid(service: dict) -> int | None:
    pid_file = resolve_workspace_path(service["runtimePidFile"])
    try:
        value = pid_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not value.isdigit():
        return None
    pid = int(value)
    return pid if pid > 1 and _process_exists(pid) else None


def _process_command(pid: int) -> str:
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "command="],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def _process_cwd(pid: int) -> Path | None:
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in result.stdout.splitlines():
        if line.startswith("n"):
            try:
                return Path(line[1:]).resolve()
            except OSError:
                return None
    return None


def _pid_belongs_to_service(pid: int, service: dict) -> bool:
    repository = resolve_workspace_path(service["repository"])
    cwd = _process_cwd(pid)
    if cwd is not None:
        try:
            cwd.relative_to(repository)
            return True
        except ValueError:
            pass
    return str(repository) in _process_command(pid)


def _descendant_pids(root_pid: int) -> list[int]:
    try:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pid=,ppid="],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2 or not all(field.isdigit() for field in fields):
            continue
        pid, parent = map(int, fields)
        children.setdefault(parent, []).append(pid)
    descendants: list[int] = []
    pending = list(children.get(root_pid, []))
    while pending:
        pid = pending.pop()
        descendants.append(pid)
        pending.extend(children.get(pid, []))
    return descendants


def stop_service(service: dict, timeout: float = 5.0) -> bool:
    pid_file = resolve_workspace_path(service["runtimePidFile"])
    pid = _service_pid(service)
    if pid is None:
        if not is_service_running(service):
            try:
                pid_file.unlink()
            except OSError:
                pass
            return False
        raise RuntimeError("Сервис запущен без проверяемого PID-файла")
    if not _pid_belongs_to_service(pid, service):
        raise RuntimeError("PID-файл указывает на посторонний процесс; остановка отменена")

    descendants = _descendant_pids(pid)
    targets = [pid, *descendants]
    for target in targets:
        try:
            os.kill(target, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError as error:
            raise RuntimeError(f"Нет прав для остановки процесса {target}") from error

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and any(_process_exists(target) for target in targets):
        time.sleep(0.05)
    for target in targets:
        if _process_exists(target):
            try:
                os.kill(target, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError as error:
                raise RuntimeError(f"Нет прав для завершения процесса {target}") from error

    try:
        if pid_file.read_text(encoding="utf-8").strip() == str(pid):
            pid_file.unlink()
    except OSError:
        pass
    return True


class HeartbeatTracker:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._last_activity = clock()
        self._tabs: dict[tuple[str, str], float] = {}

    def touch(self, service_id: str, tab_id: str) -> None:
        now = self._clock()
        with self._lock:
            self._last_activity = now
            self._tabs[(service_id, tab_id)] = now
            cutoff = now - HEARTBEAT_ACTIVE_SECONDS
            self._tabs = {key: seen for key, seen in self._tabs.items() if seen >= cutoff}

    def idle_seconds(self) -> float:
        with self._lock:
            return max(0.0, self._clock() - self._last_activity)

    def active_tabs(self) -> int:
        now = self._clock()
        with self._lock:
            return sum(
                1 for seen in self._tabs.values() if now - seen <= HEARTBEAT_ACTIVE_SECONDS
            )


def public_service(service: dict) -> dict:
    running = is_service_running(service)
    return {
        "id": service["id"],
        "name": service["name"],
        "icon": service.get("icon", "•"),
        "description": service["description"],
        "githubUrl": service.get("githubUrl", ""),
        "url": service["url"],
        "running": running,
        "stoppable": running and _service_pid(service) is not None,
        "stopWhenBrowserIdle": service["stopWhenBrowserIdle"],
        "repositoryAvailable": resolve_workspace_path(service["repository"]).is_dir(),
        "launcherAvailable": resolve_workspace_path(service["launcher"]).is_dir(),
    }


def launch_service(service: dict) -> None:
    launcher = resolve_workspace_path(service["launcher"])
    if not launcher.is_dir():
        raise FileNotFoundError(f"Launcher not found: {launcher.name}")
    subprocess.run(
        ["/usr/bin/open", str(launcher)],
        check=True,
        timeout=10,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_idle_services(services: list[dict] | None = None) -> None:
    selected_services = services if services is not None else load_registry()
    for service in selected_services:
        if not service["stopWhenBrowserIdle"]:
            continue
        try:
            stop_service(service)
        except RuntimeError as error:
            print(f"[life-hub] Could not stop {service['id']}: {error}")


def _url_origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _heartbeat_origin_allowed(
    service_id: str,
    origin: str | None,
    hub_port: int = DEFAULT_PORT,
) -> bool:
    if origin is None:
        return True
    if service_id == APPLICATION_ID:
        return origin in {
            f"http://127.0.0.1:{hub_port}",
            f"http://localhost:{hub_port}",
        }
    service = next((item for item in load_registry() if item["id"] == service_id), None)
    return service is not None and origin == _url_origin(service["url"])


class Handler(BaseHTTPRequestHandler):
    server_version = "LifeHub/0.2"

    @property
    def hub_port(self) -> int:
        return int(self.server.server_port)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[life-hub] {self.address_string()} {fmt % args}")

    def valid_host(self) -> bool:
        host = self.headers.get("Host", "")
        return host in {
            f"127.0.0.1:{self.hub_port}",
            f"localhost:{self.hub_port}",
            f"[::1]:{self.hub_port}",
        }

    def valid_origin(self) -> bool:
        origin = self.headers.get("Origin")
        return origin in {
            None,
            f"http://127.0.0.1:{self.hub_port}",
            f"http://localhost:{self.hub_port}",
        }

    def send_json(
        self,
        payload: object,
        status: int = HTTPStatus.OK,
        cors_origin: str | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cors_origin:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self.valid_host():
            self.send_json({"error": "Invalid Host"}, HTTPStatus.FORBIDDEN)
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            tracker = self.server.heartbeat_tracker
            self.send_json(
                {
                    "ok": True,
                    "application": APPLICATION_ID,
                    "version": APP_VERSION,
                    "activeTabs": tracker.active_tabs(),
                    "idleSeconds": round(tracker.idle_seconds()),
                    "idleTimeoutSeconds": self.server.idle_timeout_seconds,
                }
            )
            return
        if parsed.path == "/api/services":
            self.send_json({"services": [public_service(item) for item in load_registry()]})
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        if not self.valid_host():
            self.send_json({"error": "Request rejected"}, HTTPStatus.FORBIDDEN)
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/heartbeat":
            self.handle_heartbeat()
            return
        if not self.valid_origin():
            self.send_json({"error": "Request rejected"}, HTTPStatus.FORBIDDEN)
            return
        match = re.fullmatch(r"/api/services/([a-z0-9-]+)/(launch|stop)", parsed.path)
        if not match:
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        service = next(
            (item for item in load_registry() if item["id"] == match.group(1)),
            None,
        )
        if service is None:
            self.send_json({"error": "Unknown service"}, HTTPStatus.NOT_FOUND)
            return
        action = match.group(2)
        if action == "launch":
            try:
                launch_service(service)
            except (OSError, subprocess.SubprocessError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json({"ok": True, "url": service["url"]}, HTTPStatus.ACCEPTED)
            return
        try:
            stopped = stop_service(service)
        except RuntimeError as error:
            self.send_json({"error": str(error)}, HTTPStatus.CONFLICT)
            return
        self.send_json({"ok": True, "stopped": stopped})

    def handle_heartbeat(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 2 or length > 2048:
            self.send_json({"error": "Invalid heartbeat"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self.send_json({"error": "Invalid heartbeat"}, HTTPStatus.BAD_REQUEST)
            return
        service_id = str(payload.get("serviceId") or "")
        tab_id = str(payload.get("tabId") or "")
        origin = self.headers.get("Origin")
        if (
            not SERVICE_ID.fullmatch(service_id)
            or not re.fullmatch(r"[a-zA-Z0-9-]{8,80}", tab_id)
            or not _heartbeat_origin_allowed(service_id, origin, self.hub_port)
        ):
            self.send_json({"error": "Heartbeat rejected"}, HTTPStatus.FORBIDDEN)
            return
        self.server.heartbeat_tracker.touch(service_id, tab_id)
        self.send_json({"ok": True}, cors_origin=origin)

    def serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else unquote(request_path).lstrip("/")
        candidate = (STATIC_DIR / relative).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Life Hub")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("LIFE_HUB_PORT", DEFAULT_PORT)),
    )
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=int(
            os.environ.get(
                "LIFE_HUB_IDLE_TIMEOUT_SECONDS", DEFAULT_IDLE_TIMEOUT_SECONDS
            )
        ),
        help="Stop opted-in services and the hub after this many seconds without browser heartbeats",
    )
    args = parser.parse_args()
    if args.idle_timeout < 1:
        parser.error("--idle-timeout must be at least 1 second")
    load_registry()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.heartbeat_tracker = HeartbeatTracker()
    server.idle_timeout_seconds = args.idle_timeout
    lifecycle_stop = threading.Event()

    def monitor_browser_idle() -> None:
        while not lifecycle_stop.wait(1):
            if server.heartbeat_tracker.idle_seconds() < args.idle_timeout:
                continue
            print("[life-hub] Browser idle timeout reached; stopping services")
            stop_idle_services()
            server.shutdown()
            return

    monitor = threading.Thread(
        target=monitor_browser_idle,
        name="life-hub-idle-monitor",
        daemon=True,
    )
    monitor.start()
    print(f"Life Hub · http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        lifecycle_stop.set()
        server.server_close()
        try:
            if PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
                PID_FILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
