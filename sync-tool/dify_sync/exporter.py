from __future__ import annotations

from pathlib import Path

from .config import AppConfig, repo_root
from .dify_client import DifyConsoleClient
from .store import (
    build_app_record,
    load_metadata,
    now_iso,
    save_metadata,
)


def export_environment(
    cfg: AppConfig,
    env: str,
    repo: Path | None = None,
    progress=None,
) -> dict:
    """一键导出指定环境的全部工作流并刷新该环境元数据。"""
    repo = repo or repo_root()
    env_cfg = cfg.environments[env]
    old_meta = load_metadata(repo, env)
    client = DifyConsoleClient(
        env_cfg.base_url,
        env_cfg.email,
        env_cfg.password,
        include_secret=cfg.include_secret,
    )

    client.login()
    apps = [a for a in client.list_apps() if a.get("mode") in cfg.only_modes]

    out_dir = repo / "environments" / env
    out_dir.mkdir(parents=True, exist_ok=True)
    exported: list[dict] = []
    errors: list[dict] = []
    new_apps: dict = {}
    exported_at = now_iso()

    for index, app in enumerate(apps, start=1):
        name = str(app.get("name") or app.get("id") or "未命名")
        if progress:
            progress(f"[{index}/{len(apps)}] {name}")
        try:
            ts = client.get_workflow_updated_at(str(app["id"]))
            if ts is None:
                ts = app.get("updated_at")
            dsl_text = client.export_app(str(app["id"]))
            record, target = build_app_record(
                repo,
                env,
                app_id=str(app["id"]),
                name=name,
                mode=app.get("mode"),
                dify_updated_at=ts,
                exported_at=exported_at,
                dsl_text=dsl_text,
            )
            target.write_text(dsl_text, encoding="utf-8")
            old_record = old_meta.get("apps", {}).get(name) or {}
            changed = (
                old_record.get("dify_updated_at") is not None
                and ts is not None
                and old_record.get("dify_updated_at") != ts
            )
            new_apps[name] = record
            exported.append(
                {
                    "name": name,
                    "file": record["file"],
                    "dify_updated_at": ts,
                    "previous_dify_updated_at": old_record.get("dify_updated_at"),
                    "changed": changed,
                }
            )
        except Exception as exc:  # 单个应用失败不中断整体导出
            errors.append({"name": name, "error": str(exc)})

    meta = {
        "env": env,
        "label": env_cfg.name,
        "updated_at": exported_at,
        "apps": new_apps,
    }
    save_metadata(repo, env, meta)
    return {
        "env": env,
        "label": env_cfg.name,
        "app_count": len(apps),
        "exported": exported,
        "errors": errors,
        "metadata_file": f"metadata/{env}.json",
        "repo_dir": str(repo),
    }
