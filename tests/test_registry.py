from __future__ import annotations

import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CADDYFILE = ROOT / "Caddyfile"
sys.path.insert(0, str(ROOT))

from app.server import load_registry, resolve_workspace_path


class RegistryTest(unittest.TestCase):
    def test_registry_has_unique_ids_urls_and_existing_paths(self) -> None:
        services = load_registry()
        self.assertGreaterEqual(len(services), 4)
        self.assertEqual(len({item["id"] for item in services}), len(services))
        self.assertEqual(len({item["url"] for item in services}), len(services))
        caddyfile = CADDYFILE.read_text(encoding="utf-8")
        for service in services:
            self.assertTrue(urlparse(service["url"]).hostname.endswith(".localhost"))
            self.assertEqual(urlparse(service["directUrl"]).hostname, "127.0.0.1")
            self.assertEqual(urlparse(service["healthUrl"]).hostname, "127.0.0.1")
            self.assertIn(urlparse(service["url"]).hostname, caddyfile)
            self.assertIn(urlparse(service["directUrl"]).netloc, caddyfile)
            self.assertTrue(resolve_workspace_path(service["repository"]).is_dir())
            self.assertTrue(resolve_workspace_path(service["launcher"]).is_dir())
            self.assertEqual(resolve_workspace_path(service["runtimePidFile"]).suffix, ".pid")
            self.assertIsInstance(service["stopWhenBrowserIdle"], bool)


if __name__ == "__main__":
    unittest.main()
