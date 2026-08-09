from __future__ import annotations

import json
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import load_config, repo_root
from .exporter import export_environment
from .store import (
    compare_environments,
    load_metadata,
    load_sync_state,
    mark_workflow_synced,
)


def _git_state(repo: Path) -> dict:
    try:
        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True, text=True, timeout=3,
        ).stdout.count("\n")
        return {"branch": branch, "sha": sha, "dirty_count": dirty}
    except Exception:
        return {"branch": None, "sha": None, "dirty_count": -1}


class SyncHandler(BaseHTTPRequestHandler):
    server_version = "DifySync/0.1"

    @property
    def app(self):
        return self.server.app  # type: ignore[attr-defined]

    def _send_json(self, obj, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, name: str):
        web_dir = self.app["web_dir"]
        path = (web_dir / name).resolve()
        if name not in {"index.html", "app.js", "style.css"} or not path.is_file():
            self.send_error(404)
            return
        ctype = {
            "index.html": "text/html; charset=utf-8",
            "app.js": "application/javascript; charset=utf-8",
            "style.css": "text/css; charset=utf-8",
        }[name]
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _state(self) -> dict:
        app = self.app
        cfg = app["cfg"]
        repo = app["repo"]
        sync_state = load_sync_state(repo)
        synced_map = sync_state.get("workflows", {})
        metas = {}
        for key, env in cfg.environments.items():
            meta = load_metadata(repo, key)
            meta["label"] = env.name
            metas[key] = meta
        envs = {
            key: {
                **env.masked(),
                "apps_count": len(metas[key].get("apps", {})),
                "last_export": metas[key].get("updated_at"),
                "unpublished_changes": sum(
                    1
                    for rec in metas[key].get("apps", {}).values()
                    if rec.get("draft_matches_published") is False
                ),
                "baseline_count": sum(
                    1 for _name, rec in metas[key].get("apps", {}).items()
                    if rec.get("draft_hash")
                    and synced_map.get(_name, {}).get("synced_hash") == rec["draft_hash"]
                ),
                "version_count": sum(
                    int(rec.get("version_count") or 0)
                    for rec in metas[key].get("apps", {}).values()
                ),
            }
            for key, env in cfg.environments.items()
        }

        comparisons = {}
        keys = list(cfg.environments)
        aligned_count = 0
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = keys[i], keys[j]
                rows, warnings = compare_environments(
                    metas[a], metas[b], a, b, repo=repo, sync_state=sync_state
                )
                aligned_count += sum(1 for row in rows if row["status"] == "synced")
                comparisons[f"{a}_{b}"] = {
                    "env_a": {"key": a, "label": cfg.environments[a].name},
                    "env_b": {"key": b, "label": cfg.environments[b].name},
                    "rows": rows,
                    "warnings": warnings,
                }
        return {
            "git": _git_state(repo),
            "environments": envs,
            "comparisons": comparisons,
            "export_modes": list(cfg.only_modes),
            "include_secret": cfg.include_secret,
            "aligned_count": aligned_count,
            "synced_total": len(synced_map),
        }

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._send_static("index.html")
        if path == "/app.js":
            return self._send_static("app.js")
        if path == "/style.css":
            return self._send_static("style.css")
        if path == "/api/state":
            return self._send_json(self._state())
        self.send_error(404, "Not Found")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/export":
            return self._export_handler()
        if path == "/api/sync-mark":
            return self._sync_mark_handler()
        self._send_json({"error": "Not Found"}, 404)
        return

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") or "{}"
        return json.loads(raw)

    def _export_handler(self):
        try:
            payload = self._read_json()
            env = payload.get("env")
            cfg = self.app["cfg"]
            if env not in cfg.environments:
                self._send_json(
                    {"error": f"未知环境: {env}，可用: {','.join(cfg.environments)}"},
                    400,
                )
                return
            logs: list[str] = []
            result = export_environment(
                cfg, env, repo=self.app["repo"], progress=logs.append
            )
            result["logs"] = logs
            result["state"] = self._state()
            self._send_json(result)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 502)

    def _sync_mark_handler(self):
        try:
            payload = self._read_json()
            name = payload.get("name")
            env = payload.get("env")
            note = payload.get("note") or ""
            cfg = self.app["cfg"]
            if not name or env not in cfg.environments:
                self._send_json({"error": "缺少工作流名称或环境"}, 400)
                return
            meta = load_metadata(self.app["repo"], env)
            record = meta.get("apps", {}).get(name)
            draft_hash = (record or {}).get("draft_hash")
            if not draft_hash:
                self._send_json(
                    {"error": f"「{name}」在 {env} 还没有可用的内容 hash，请先一键导出"},
                    400,
                )
                return
            mark_workflow_synced(self.app["repo"], name, draft_hash, env, note)
            self._send_json({"ok": True, "state": self._state()})
        except Exception as exc:
            self._send_json({"error": str(exc)}, 502)

    def log_message(self, fmt, *args):
        print("[sync-tool] %s" % (fmt % args), flush=True)


def serve(host: str = "127.0.0.1", port: int = 8642, open_browser: bool = True) -> int:
    cfg = load_config()
    repo = repo_root()
    web_dir = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer((host, port), SyncHandler)
    server.app = {"cfg": cfg, "repo": repo, "web_dir": web_dir}  # type: ignore[attr-defined]
    url = f"http://{host}:{port}"
    print(f"Dify 工作流版本同步台: {url}")
    print("环境:", ", ".join(f"{k}({v.name})" for k, v in cfg.environments.items()))
    print("按 Ctrl+C 停止。仅监听本机，不会对外网开放。")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
    return 0
