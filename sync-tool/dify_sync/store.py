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


def build_app_record(
    repo: Path,
    env: str,
    app_id: str,
    name: str,
    mode: str | None,
    dify_updated_at,
    exported_at: str,
    dsl_text: str,
) -> tuple[dict, Path]:
    rel = f"environments/{env}/{sanitize_filename(name)}"
    target = repo / rel
    return (
        {
            "app_id": app_id,
            "name": name,
            "mode": mode,
            "dify_updated_at": dify_updated_at,
            "exported_at": exported_at,
            "file": rel,
            "sha256": sha256_of_text(dsl_text),
        },
        target,
    )


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
) -> tuple[list[dict], list[dict]]:
    """返回 (行列表, 提示列表)。行含 a/b 两边时间与差异状态。"""
    rows: list[dict] = []
    warnings: list[dict] = []
    names = sorted(set(meta_a.get("apps", {})) | set(meta_b.get("apps", {})))
    label_a = meta_a.get("label") or env_a
    label_b = meta_b.get("label") or env_b

    for name in names:
        ra = meta_a.get("apps", {}).get(name)
        rb = meta_b.get("apps", {}).get(name)
        ta = (ra or {}).get("dify_updated_at")
        tb = (rb or {}).get("dify_updated_at")
        ta_txt = format_ts(ta) or "未记录"
        tb_txt = format_ts(tb) or "未记录"

        if ra is None:
            status, delta, hint = "missing_a", None, f"仅存在于 {label_b}"
        elif rb is None:
            status, delta, hint = "missing_b", None, f"仅存在于 {label_a}"
        elif ta is None or tb is None:
            if ta is None and tb is None:
                status, delta, hint = "unknown", None, "两侧均未记录 Dify 更新时间"
            else:
                status, delta, hint = "unknown", None, "一侧未记录 Dify 更新时间"
        elif abs(ta - tb) <= 5:
            status, delta, hint = "same", 0, "两环境时间一致"
        elif ta > tb:
            status, delta, hint = "a_newer", ta - tb, f"{label_a} 更新 {human_delta(ta - tb)}"
        else:
            status, delta, hint = "b_newer", tb - ta, f"{label_b} 更新 {human_delta(tb - ta)}"

        rows.append(
            {
                "name": name,
                "a_time": ta_txt,
                "b_time": tb_txt,
                "a_file_exists": bool(ra and (repo_file_exists(repo, ra))),
                "b_file_exists": bool(rb and (repo_file_exists(repo, rb))),
                "status": status,
                "delta_seconds": delta,
                "delta_text": hint,
            }
        )

        if status == "a_newer":
            warnings.append(
                {"level": "info", "text": f"「{name}」在 {label_a}（{ta_txt}）比 {label_b}（{tb_txt}）新，迁移回 {label_b} 前请确认"}
            )
        elif status == "b_newer":
            warnings.append(
                {"level": "info", "text": f"「{name}」在 {label_b}（{tb_txt}）比 {label_a}（{ta_txt}）新，迁移回 {label_a} 前请确认"}
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
