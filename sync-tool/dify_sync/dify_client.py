from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class DifyApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class DifyConsoleClient:
    """Dify Console API 客户端（Dify 1.7.2 实测）。"""

    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        include_secret: bool = False,
        timeout: int = 30,
    ):
        self.console_api = base_url.rstrip("/") + "/console/api"
        self.email = email
        self.password = password
        self.include_secret = include_secret
        self.timeout = timeout
        self._token: str | None = None

    def _open(self, req: urllib.request.Request):
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                try:
                    return json.loads(raw.decode("utf-8"))
                except Exception:
                    return {"__text__": raw.decode("utf-8", "replace")}
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:
                body = ""
            raise DifyApiError(
                f"HTTP {exc.code}: {body[:300]}", status=exc.code, body=body
            )

    def login(self) -> str:
        payload = json.dumps(
            {
                "email": self.email,
                "password": self.password,
                "remember_me": True,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self.console_api + "/login",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = self._open(req)
        token = (resp.get("data") or {}).get("access_token")
        if not token:
            raise DifyApiError("登录成功但响应中没有 access_token")
        self._token = token
        return token

    def _request(self, method: str, path: str, retry: bool = True):
        url = self.console_api + path
        headers = {
            "Authorization": "Bearer " + (self._token or ""),
            "Content-Type": "application/json",
        }
        req = urllib.request.Request(url, headers=headers, method=method)
        try:
            return self._open(req)
        except DifyApiError as exc:
            if retry and exc.status == 401:
                self.login()
                req = urllib.request.Request(
                    url,
                    headers={
                        "Authorization": "Bearer " + (self._token or ""),
                        "Content-Type": "application/json",
                    },
                    method=method,
                )
                return self._open(req)
            raise

    def list_apps(self) -> list[dict]:
        apps: list[dict] = []
        page = 1
        while True:
            resp = self._request("GET", f"/apps?page={page}&limit=100&name=")
            items = resp.get("data") or []
            if isinstance(items, dict):
                items = items.get("apps") or items.get("list") or []
            apps.extend(items)
            if not resp.get("has_more") or not items:
                break
            page += 1
        return apps

    def get_workflow_updated_at(self, app_id: str):
        """草稿最后修改时间（epoch 秒）；失败返回 None，回退到应用列表时间。"""
        try:
            resp = self._request("GET", f"/apps/{app_id}/workflows/draft")
        except DifyApiError:
            return None
        ts = resp.get("updated_at")
        return ts if isinstance(ts, (int, float)) else None

    def export_app(self, app_id: str) -> str:
        suffix = "" if self.include_secret else "?include_secret=false"
        resp = self._request("GET", f"/apps/{app_id}/export{suffix}")
        text = resp.get("data")
        if text is None and "__text__" in resp:
            text = resp["__text__"]
        if not isinstance(text, str) or not text.strip():
            raise DifyApiError("导出结果为空")
        return text
