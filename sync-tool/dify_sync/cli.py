from __future__ import annotations

import argparse
import json
import sys

from .config import load_config, repo_root
from .exporter import export_environment
from .store import compare_environments, init_metadata_from_repo, load_metadata


def _load_cfg():
    return load_config()


def cmd_check_config(_args) -> int:
    cfg = _load_cfg()
    for key, env in cfg.environments.items():
        print(f"{key}: {env.name} -> {env.base_url} (账号 {env.email})")
    print(f"导出模式: {','.join(cfg.only_modes)}")
    return 0


def cmd_export(args) -> int:
    cfg = _load_cfg()
    if args.env not in cfg.environments:
        print(f"未知环境: {args.env}，可用: {','.join(cfg.environments)}", file=sys.stderr)
        return 2
    result = export_environment(
        cfg, args.env, progress=lambda msg: print(msg, flush=True)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_compare(args) -> int:
    cfg = _load_cfg()
    repo = repo_root()
    keys = list(cfg.environments)
    if len(keys) < 2:
        print("至少需要两个环境才能对比", file=sys.stderr)
        return 2
    meta = {}
    for key in keys:
        m = load_metadata(repo, key)
        m["label"] = cfg.environments[key].name
        meta[key] = m
    pairs = list(zip(keys, keys[1:])) if args.all_pairs else [(keys[0], keys[1])]
    output = {"envs": {k: v["label"] for k, v in meta.items()}}
    for a, b in pairs:
        rows, warnings = compare_environments(meta[a], meta[b], a, b)
        output[f"{a}_{b}"] = {"rows": rows, "warnings": warnings}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_init_metadata(args) -> int:
    repo = repo_root()
    meta = init_metadata_from_repo(repo, args.env)
    print(f"已生成 metadata/{args.env}.json，共 {len(meta['apps'])} 条基线记录")
    return 0


def cmd_serve(args) -> int:
    from .server import serve

    return serve(host=args.host, port=args.port, open_browser=not args.no_browser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dify 工作流跨环境导出与版本对比工具")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check-config", help="校验 config.json").set_defaults(func=cmd_check_config)

    p_export = sub.add_parser("export", help="一键导出某环境全部工作流")
    p_export.add_argument("env")
    p_export.set_defaults(func=cmd_export)

    p_compare = sub.add_parser("compare", help="对比仓库中两个环境的工作流更新时间")
    p_compare.add_argument("--all-pairs", action="store_true")
    p_compare.set_defaults(func=cmd_compare)

    p_init = sub.add_parser("init-metadata", help="用仓库现有文件生成无时间信息的基线元数据")
    p_init.add_argument("env")
    p_init.set_defaults(func=cmd_init_metadata)

    p_serve = sub.add_parser("serve", help="启动本地可视化管理页面")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8642)
    p_serve.add_argument("--no-browser", action="store_true")
    p_serve.set_defaults(func=cmd_serve)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
