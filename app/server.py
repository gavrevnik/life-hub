from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
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
APPLICATION_ID = "life-hub"
DEFAULT_PORT = 8790
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
        for key in ("name", "description", "repository", "url", "healthUrl", "launcher"):
            if not str(service.get(key) or "").strip():
                raise ValueError(f"{service_id}: missing {key}")
        resolve_workspace_path(service["repository"])
        resolve_workspace_path(service["launcher"])
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


def public_service(service: dict) -> dict:
    return {
        "id": service["id"],
        "name": service["name"],
        "icon": service.get("icon", "•"),
        "description": service["description"],
        "githubUrl": service.get("githubUrl", ""),
        "url": service["url"],
        "running": is_service_running(service),
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


class Handler(BaseHTTPRequestHandler):
    server_version = "LifeHub/0.1"

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

    def send_json(self, payload: object, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self.valid_host():
            self.send_json({"error": "Invalid Host"}, HTTPStatus.FORBIDDEN)
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "application": APPLICATION_ID})
            return
        if parsed.path == "/api/services":
            self.send_json({"services": [public_service(item) for item in load_registry()]})
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        if not self.valid_host() or not self.valid_origin():
            self.send_json({"error": "Request rejected"}, HTTPStatus.FORBIDDEN)
            return
        parsed = urlparse(self.path)
        match = re.fullmatch(r"/api/services/([a-z0-9-]+)/launch", parsed.path)
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
        try:
            launch_service(service)
        except (OSError, subprocess.SubprocessError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json({"ok": True, "url": service["url"]}, HTTPStatus.ACCEPTED)

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
    args = parser.parse_args()
    load_registry()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Life Hub · http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
