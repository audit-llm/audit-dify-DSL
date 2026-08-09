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

EXPORT_REQUEST_TIMEOUT = 120
PUBLISHED_FIELDS = (
    "published_hash",
    "published_at",
    "published_version",
    "published_version_id",
    "draft_matches_published",
    "version_count",
    "version_history",
)


def _compact_version(version: dict) -> dict:
    """把 Dify 版本历史压缩成可入库的轻量记录。"""
    created_by = version.get("created_by") or {}
    updated_by = version.get("updated_by") or {}
    return {
        "version": version.get("version"),
        "id": version.get("id"),
        "hash": version.get("hash"),
        "created_at": version.get("created_at"),
        "updated_at": version.get("updated_at"),
        "created_by": created_by.get("name") if isinstance(created_by, dict) else None,
        "created_by_email": created_by.get("email") if isinstance(created_by, dict) else None,
        "updated_by": updated_by.get("name") if isinstance(updated_by, dict) else None,
        "marked_name": version.get("marked_name") or "",
        "marked_comment": version.get("marked_comment") or "",
    }


def _derive_version_meta(versions: list[dict], app: dict, draft_hash):
    """从 Dify 版本历史中提取草稿外的发布元数据。"""
    published_id = (app.get("workflow") or {}).get("id")
    published = next((v for v in versions if v.get("id") == published_id), None)
    if published is None:
        published = next((v for v in versions if v.get("version") != "draft"), None)
    published_hash = (published or {}).get("hash")
    return {
        "published_hash": published_hash,
        "published_at": (published or {}).get("updated_at"),
        "published_version": (published or {}).get("version"),
        "published_version_id": (published or {}).get("id"),
        "draft_matches_published": (
            draft_hash == published_hash if draft_hash and published_hash else None
        ),
        "version_count": len([v for v in versions if v.get("version") != "draft"]),
        "version_history": [_compact_version(v) for v in versions],
    }


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
        timeout=EXPORT_REQUEST_TIMEOUT,
    )

    client.login()
    apps = [a for a in client.list_apps() if a.get("mode") in cfg.only_modes]

    out_dir = repo / "environments" / env
    out_dir.mkdir(parents=True, exist_ok=True)
    exported: list[dict] = []
    errors: list[dict] = []
    # 失败的应用保留旧记录，避免单点超时导致整个环境的元数据丢失。
    new_apps: dict = {k: dict(v) for k, v in old_meta.get("apps", {}).items()}
    exported_at = now_iso()

    for index, app in enumerate(apps, start=1):
        name = str(app.get("name") or app.get("id") or "未命名")
        if progress:
            progress(f"[{index}/{len(apps)}] {name}")
        try:
            dsl_text = client.export_app(str(app["id"]))
            draft = client.get_draft(str(app["id"]))
            draft_hash = (draft or {}).get("hash")
            ts = (draft or {}).get("updated_at")
            if ts is None:
                ts = app.get("updated_at")
            old_record = old_meta.get("apps", {}).get(name) or {}
            need_history = not old_record.get("draft_hash") or bool(
                draft_hash and old_record.get("draft_hash") != draft_hash
            )
            if need_history:
                versions = client.list_workflow_versions(str(app["id"]))
                published_meta = _derive_version_meta(versions, app, draft_hash)
            else:
                published_meta = {k: old_record.get(k) for k in PUBLISHED_FIELDS}
            extra = {
                "draft_hash": draft_hash,
                **published_meta,
            }
            record, target = build_app_record(
                repo,
                env,
                app_id=str(app["id"]),
                name=name,
                mode=app.get("mode"),
                dify_updated_at=ts,
                exported_at=exported_at,
                dsl_text=dsl_text,
                extra=extra,
            )
            target.write_text(dsl_text, encoding="utf-8")
            time_changed = (
                old_record.get("dify_updated_at") is not None
                and ts is not None
                and old_record.get("dify_updated_at") != ts
            )
            hash_changed = bool(
                old_record.get("draft_hash")
                and draft_hash
                and old_record.get("draft_hash") != draft_hash
            )
            changed = time_changed or hash_changed
            new_apps[name] = record
            exported.append(
                {
                    "name": name,
                    "file": record["file"],
                    "dify_updated_at": ts,
                    "draft_hash": draft_hash,
                    "published_at": record.get("published_at"),
                    "published_hash": record.get("published_hash"),
                    "draft_matches_published": record.get("draft_matches_published"),
                    "version_count": record.get("version_count"),
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
