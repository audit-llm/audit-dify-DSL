from __future__ import annotations

import json
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import load_config, repo_root
from .exporter import export_environment
from .store import compare_environments, load_metadata


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
        envs = {
            key: {
                **env.masked(),
                "apps_count": len(load_metadata(repo, key).get("apps", {})),
                "last_export": (load_metadata(repo, key) or {}).get("updated_at"),
            }
            for key, env in cfg.environments.items()
        }
        metas = {}
        for key, env in cfg.environments.items():
            meta = load_metadata(repo, key)
            meta["label"] = env.name
            metas[key] = meta

        comparisons = {}
        keys = list(cfg.environments)
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = keys[i], keys[j]
                rows, warnings = compare_environments(
                    metas[a], metas[b], a, b, repo=repo
                )
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
        if self.path.split("?", 1)[0] != "/api/export":
            self._send_json({"error": "Not Found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
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
