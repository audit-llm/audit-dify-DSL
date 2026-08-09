from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ENV_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def repo_root() -> Path:
    """audit-dify-DSL 仓库根目录。"""
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config.json"


def example_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config.example.json"


@dataclass(frozen=True)
class EnvConfig:
    key: str
    name: str
    base_url: str
    email: str
    password: str

    def masked(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "base_url": self.base_url,
            "email": self.email,
            "password_set": bool(self.password),
        }


@dataclass
class AppConfig:
    environments: dict[str, EnvConfig]
    include_secret: bool = False
    only_modes: tuple[str, ...] = ("workflow", "advanced-chat")


def load_config(path: str | Path | None = None) -> AppConfig:
    cfg_path = Path(path) if path else default_config_path()
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"配置文件不存在: {cfg_path}\n"
            f"请复制 config.example.json 为 config.json 并填写各环境账号。"
        )
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))

    envs: dict[str, EnvConfig] = {}
    for key, item in (raw.get("environments") or {}).items():
        if not ENV_KEY_RE.match(str(key)):
            raise ValueError(f"非法的环境 key: {key}")
        for required in ("base_url", "email", "password"):
            if not str(item.get(required) or "").strip():
                raise ValueError(f"环境 [{key}] 缺少必填项 {required}")
        envs[str(key)] = EnvConfig(
            key=str(key),
            name=str(item.get("name") or key),
            base_url=str(item["base_url"]).rstrip("/"),
            email=str(item["email"]),
            password=str(item["password"]),
        )
    if not envs:
        raise ValueError("config.json 中没有任何环境")

    export_cfg = raw.get("export") or {}
    modes = tuple(export_cfg.get("only_modes") or ["workflow", "advanced-chat"])
    return AppConfig(
        environments=envs,
        include_secret=bool(export_cfg.get("include_secret", False)),
        only_modes=modes,
    )
