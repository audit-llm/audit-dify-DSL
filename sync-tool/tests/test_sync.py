from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from dify_sync.config import ENV_KEY_RE, load_config
from dify_sync.dify_client import DifyConsoleClient
from dify_sync.exporter import export_environment
from dify_sync.store import (
    compare_environments,
    load_metadata,
    sanitize_filename,
)


TOKEN = "test-token"
APPS = [
    {
        "id": "app-a",
        "name": "数据分析工作流1",
        "mode": "workflow",
        "updated_at": 1786200000,
    },
    {
        "id": "app-b",
        "name": "工作方案-审计目标",
        "mode": "workflow",
        "updated_at": 1786100000,
    },
]


class FakeDifyHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/console/api/login":
            return self._send(
                {"result": "success", "data": {"access_token": TOKEN, "refresh_token": "r"}}
            )
        self._send({"error": "not found"}, 404)

    def do_GET(self):
        if self.path.startswith("/console/api/apps?"):
            page = int(self.path.split("page=")[1].split("&")[0])
            items = APPS if page == 1 else []
            return self._send(
                {
                    "page": page,
                    "limit": 100,
                    "total": len(APPS),
                    "has_more": False,
                    "data": items,
                }
            )
        if self.path.startswith("/console/api/apps/app-a/workflows/draft"):
            return self._send({"id": "app-a", "updated_at": 1786207958, "version": "draft"})
        if self.path.startswith("/console/api/apps/app-b/workflows/draft"):
            return self._send({"id": "app-b", "updated_at": 1786100000, "version": "draft"})
        if self.path.startswith("/console/api/apps/app-a/export"):
            return self._send({"data": "app:\n  name: 数据分析工作流1\n  mode: workflow\n"})
        if self.path.startswith("/console/api/apps/app-b/export"):
            return self._send({"data": "app:\n  name: 工作方案-审计目标\n  mode: workflow\n"})
        self._send({"error": "not found"}, 404)


class SyncToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeDifyHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.cfg_path = self.repo / "config.json"
        self.cfg_path.write_text(
            json.dumps(
                {
                    "environments": {
                        "dev": {
                            "name": "开发环境",
                            "base_url": self.base,
                            "email": "a@b.c",
                            "password": "p",
                        },
                        "prod": {
                            "name": "生产环境",
                            "base_url": self.base,
                            "email": "a@b.c",
                            "password": "p",
                        },
                    },
                    "export": {"include_secret": False, "only_modes": ["workflow"]},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_config_load(self):
        cfg = load_config(self.cfg_path)
        self.assertEqual(set(cfg.environments), {"dev", "prod"})
        self.assertTrue(ENV_KEY_RE.match("dev"))
        self.assertFalse(ENV_KEY_RE.match("dev/../x"))

    def test_client_login_list_and_export(self):
        client = DifyConsoleClient(self.base, "a@b.c", "p")
        self.assertEqual(client.login(), TOKEN)
        apps = client.list_apps()
        self.assertEqual([a["name"] for a in apps], ["数据分析工作流1", "工作方案-审计目标"])
        self.assertEqual(client.get_workflow_updated_at("app-a"), 1786207958)
        dsl = client.export_app("app-a")
        self.assertIn("name: 数据分析工作流1", dsl)

    def test_export_environment_writes_files_and_metadata(self):
        cfg = load_config(self.cfg_path)
        result = export_environment(cfg, "dev", repo=self.repo)
        self.assertEqual(result["app_count"], 2)
        self.assertEqual(len(result["exported"]), 2)
        self.assertEqual(result["errors"], [])
        self.assertTrue((self.repo / "environments/dev/数据分析工作流1.yml").exists())
        meta = load_metadata(self.repo, "dev")
        self.assertEqual(meta["apps"]["数据分析工作流1"]["dify_updated_at"], 1786207958)
        self.assertEqual(meta["apps"]["工作方案-审计目标"]["dify_updated_at"], 1786100000)

    def test_compare_statuses(self):
        meta_dev = {
            "env": "dev",
            "apps": {
                "新": {"name": "新", "dify_updated_at": 200},
                "两侧都有": {"name": "两侧都有", "dify_updated_at": 200},
                "双方一致": {"name": "双方一致", "dify_updated_at": 100},
            },
        }
        meta_prod = {
            "env": "prod",
            "apps": {
                "生产独有": {"name": "生产独有", "dify_updated_at": 1},
                "两侧都有": {"name": "两侧都有", "dify_updated_at": 100},
                "双方一致": {"name": "双方一致", "dify_updated_at": 100},
            },
        }
        rows, warnings = compare_environments(meta_dev, meta_prod, "dev", "prod")
        status_map = {r["name"]: r["status"] for r in rows}
        self.assertEqual(status_map["新"], "missing_b")
        self.assertEqual(status_map["生产独有"], "missing_a")
        self.assertEqual(status_map["两侧都有"], "a_newer")
        self.assertEqual(status_map["双方一致"], "same")
        self.assertTrue(warnings)

    def test_compare_both_unrecorded(self):
        meta = {"env": "x", "apps": {"A": {"dify_updated_at": None}}}
        rows, warnings = compare_environments(meta, meta, "dev", "prod")
        self.assertEqual(rows[0]["status"], "unknown")
        self.assertIn("两侧均未记录", warnings[0]["text"])

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename('a/b:c*?"<>|'), "a_b_c______.yml")
        self.assertEqual(sanitize_filename("   "), "未命名工作流.yml")


if __name__ == "__main__":
    unittest.main()
