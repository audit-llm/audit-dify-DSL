from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = "未命名工作流"
    if len(cleaned) > 80:
        cleaned = cleaned[:80].rstrip()
    return cleaned + ".yml"


def metadata_path(repo: Path, env: str) -> Path:
    return repo / "metadata" / f"{env}.json"


def load_metadata(repo: Path, env: str) -> dict:
    path = metadata_path(repo, env)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"env": env, "updated_at": None, "apps": {}}


def save_metadata(repo: Path, env: str, meta: dict) -> None:
    path = metadata_path(repo, env)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sync_state_path(repo: Path) -> Path:
    return repo / "metadata" / "sync-state.json"


def load_sync_state(repo: Path) -> dict:
    """同步基线账本：每个工作流的 synced_hash 类似 git merge-base。"""
    path = sync_state_path(repo)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"updated_at": None, "workflows": {}}


def save_sync_state(repo: Path, state: dict) -> None:
    path = sync_state_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def mark_workflow_synced(
    repo: Path, name: str, hash_value: str, base_env: str, note: str = ""
) -> dict:
    """把某工作流的当前草稿 hash 记为 dev/prod 的共同对齐基线。"""
    state = load_sync_state(repo)
    workflows = state.setdefault("workflows", {})
    record = {"synced_hash": hash_value, "synced_at": now_iso(), "base_env": base_env, "note": note}
    workflows[name] = record
    state["updated_at"] = now_iso()
    save_sync_state(repo, state)
    return record


def build_app_record(
    repo: Path,
    env: str,
    app_id: str,
    name: str,
    mode: str | None,
    dify_updated_at,
    exported_at: str,
    dsl_text: str,
    extra: dict | None = None,
) -> tuple[dict, Path]:
    rel = f"environments/{env}/{sanitize_filename(name)}"
    target = repo / rel
    record = {
        "app_id": app_id,
        "name": name,
        "mode": mode,
        "dify_updated_at": dify_updated_at,
        "exported_at": exported_at,
        "file": rel,
        "sha256": sha256_of_text(dsl_text),
    }
    if extra:
        record.update(extra)
    return record, target


def init_metadata_from_repo(repo: Path, env: str) -> dict:
    """用仓库现有文件生成无 Dify 时间信息的基线元数据。"""
    meta = {"env": env, "updated_at": None, "apps": {}}
    env_dir = repo / "environments" / env
    if env_dir.exists():
        for path in sorted(env_dir.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            meta["apps"][path.stem] = {
                "app_id": None,
                "name": path.stem,
                "mode": None,
                "dify_updated_at": None,
                "exported_at": None,
                "file": str(path.relative_to(repo)),
                "sha256": sha256_of_text(text),
                "source": "repo-baseline",
            }
    save_metadata(repo, env, meta)
    return meta


def format_ts(ts) -> str | None:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return None
    return str(ts)


def human_delta(seconds: float) -> str:
    seconds = abs(int(seconds))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {seconds} 秒"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} 小时 {minutes} 分"
    days, hours = divmod(hours, 24)
    return f"{days} 天 {hours} 小时"


def compare_environments(
    meta_a: dict,
    meta_b: dict,
    env_a: str,
    env_b: str,
    repo: Path | None = None,
    sync_state: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """返回 (行列表, 提示列表)。优先用 Dify 内容 hash 判断，辅以时间。"""
    rows: list[dict] = []
    warnings: list[dict] = []
    names = sorted(set(meta_a.get("apps", {})) | set(meta_b.get("apps", {})))
    label_a = meta_a.get("label") or env_a
    label_b = meta_b.get("label") or env_b
    synced_map = (sync_state or {}).get("workflows", {})

    for name in names:
        ra = meta_a.get("apps", {}).get(name)
        rb = meta_b.get("apps", {}).get(name)
        ta = (ra or {}).get("dify_updated_at")
        tb = (rb or {}).get("dify_updated_at")
        ha = (ra or {}).get("draft_hash")
        hb = (rb or {}).get("draft_hash")
        synced_hash = (synced_map.get(name) or {}).get("synced_hash")
        ta_txt = format_ts(ta) or "未记录"
        tb_txt = format_ts(tb) or "未记录"

        if ra is None:
            status, delta, hint = "missing_a", None, f"仅存在于 {label_b}"
        elif rb is None:
            status, delta, hint = "missing_b", None, f"仅存在于 {label_a}"
        elif ha and hb:
            if synced_hash:
                if ha == hb and ha == synced_hash:
                    status, delta, hint = "synced", 0, "已同步：两侧均与对齐基线一致"
                elif ha == hb:
                    status, delta, hint = (
                        "same",
                        0,
                        "两侧内容一致，但相对同步基线领先，可标记对齐",
                    )
                elif hb == synced_hash:
                    status, delta, hint = (
                        "a_ahead",
                        None,
                        f"{label_a} 领先同步基线，可迁移到 {label_b}",
                    )
                elif ha == synced_hash:
                    status, delta, hint = (
                        "b_ahead",
                        None,
                        f"{label_b} 领先同步基线，可迁移回 {label_a}",
                    )
                else:
                    status, delta, hint = (
                        "conflict",
                        None,
                        "两侧均偏离同步基线，需人工合并",
                    )
            else:
                if ha == hb:
                    status, delta, hint = (
                        "same",
                        0,
                        "两侧内容一致，但尚未记录同步基线",
                    )
                else:
                    status, delta, hint = (
                        "diverge",
                        None,
                        "无同步基线且两侧内容不同，需人工确认基线",
                    )
        else:
            if ta is None or tb is None:
                if ta is None and tb is None:
                    status, delta, hint = "unknown", None, "两侧均未记录 Dify 更新时间"
                else:
                    status, delta, hint = "unknown", None, "一侧未记录 Dify 更新时间"
            elif abs(ta - tb) <= 5:
                status, delta, hint = "same", 0, "两环境时间一致（无内容 hash，仅按时间判断）"
            elif ta > tb:
                status, delta, hint = (
                    "a_newer",
                    ta - tb,
                    f"{label_a} 更新 {human_delta(ta - tb)}（无内容 hash）",
                )
            else:
                status, delta, hint = (
                    "b_newer",
                    tb - ta,
                    f"{label_b} 更新 {human_delta(tb - ta)}（无内容 hash）",
                )

        rows.append(
            {
                "name": name,
                "a_time": ta_txt,
                "b_time": tb_txt,
                "a_file_exists": bool(ra and (repo_file_exists(repo, ra))),
                "b_file_exists": bool(rb and (repo_file_exists(repo, rb))),
                "a_draft_hash": ha,
                "b_draft_hash": hb,
                "content_same": (ha == hb) if (ha and hb) else None,
                "synced_hash": synced_hash,
                "status": status,
                "delta_seconds": delta,
                "delta_text": hint,
            }
        )

        if status == "a_ahead":
            warnings.append(
                {"level": "info", "text": f"「{name}」{label_a} 领先同步基线，待迁移到 {label_b}"}
            )
        elif status == "b_ahead":
            warnings.append(
                {"level": "info", "text": f"「{name}」{label_b} 领先同步基线，待迁移回 {label_a}"}
            )
        elif status == "conflict":
            warnings.append(
                {"level": "warn", "text": f"「{name}」两侧均偏离同步基线，存在双向改动，需人工合并"}
            )
        elif status == "diverge":
            warnings.append(
                {"level": "warn", "text": f"「{name}」无同步基线且两侧内容不同，需先确认共同基线"}
            )
        elif status == "a_newer":
            warnings.append(
                {"level": "info", "text": f"「{name}」在 {label_a}（{ta_txt}）比 {label_b}（{tb_txt}）新"}
            )
        elif status == "b_newer":
            warnings.append(
                {"level": "info", "text": f"「{name}」在 {label_b}（{tb_txt}）比 {label_a}（{ta_txt}）新"}
            )
        elif status == "missing_b":
            warnings.append(
                {"level": "warn", "text": f"「{name}」仅存在于 {label_a}，{label_b} 无对应记录"}
            )
        elif status == "missing_a":
            warnings.append(
                {"level": "warn", "text": f"「{name}」仅存在于 {label_b}，{label_a} 无对应记录"}
            )
        elif status == "unknown":
            if ta is None and tb is None:
                warnings.append(
                    {"level": "warn", "text": f"「{name}」两侧均未记录 Dify 更新时间，需在对应环境网络内执行一键导出"}
                )
            else:
                warnings.append(
                    {"level": "warn", "text": f"「{name}」一侧未记录 Dify 更新时间，需在该环境网络内执行一键导出"}
                )
    return rows, warnings


def repo_file_exists(repo: Path | None, record: dict) -> bool:
    if repo is None:
        from .config import repo_root

        repo = repo_root()
    rel = record.get("file")
    if not rel:
        return False
    return (repo / rel).exists()
