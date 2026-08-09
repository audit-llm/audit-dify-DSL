# audit-dify-DSL

审计业务 Dify 工作流 DSL 仓库，按部署环境分目录管理。每个 DSL 文件对应 Dify 中的一条工作流，开发环境与生产环境仅在模型、数据库连接等参数上不同，业务逻辑应保持一致。

## 目录结构

```text
environments/  当前各环境的工作流 DSL，文件名即 Dify 工作流名
  dev/         开发环境，新逻辑先在此验证
  prod/        生产环境，生产导出快照
archive/     历史快照，仅归档保留，不再维护
  YYYY-MM-DD-<说明>/
docs/        辅助文档与转换说明
```

## 环境参数差异

| 项目 | dev | prod |
| ---- | --- | ---- |
| LLM | 通义 qwen3.5-flash（tongyi 插件） | Qwen3.5-27B / DeepSeek（openai_api_compatible） |
| MySQL | host.docker.internal:3307 / audit_flow | 100.81.13.52:3306 / audit_flow |
| 插件形式 | 新版本 marketplace 插件 | 依赖生产环境已安装插件 |

## 数据分析工作流1 快照

| 环境 | 文件 | 快照时间 | 说明 |
| ---- | ---- | -------- | ---- |
| dev | `environments/dev/数据分析工作流1.yml` | 2026-08-09 | 当前最新，含 sql_batch 多 SQL 迭代逻辑 |
| prod | `environments/prod/数据分析工作流1.yml` | 2026-07-22 | 生产快照，尚未同步 sql_batch 新逻辑 |

## 更新规范

1. 从 Dify 导出某环境工作流后，直接覆盖 `environments/<环境>/<工作流名>.yml`。
2. 被替换的旧版本默认由 git 历史承载；需要长期留档的按 `archive/YYYY-MM-DD-说明/` 归档。
3. 不要新建 `transfer/`、`trasnfered/` 这类无时间语义的临时目录，转换中间产物统一放 `archive/`。
4. 环境差异只允许出现在模型、插件、数据库连接等明确参数上，业务节点结构必须保持一致。
