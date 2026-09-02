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

## 综合报告（SUMMARY_REPORT）多节点 DSL

综合报告按《关于26个市县自然资源资产审计综合报告》的章节结构拆分为 4 个节点，每个节点对应一条独立 Dify 工作流（`mode: advanced-chat`），与原审计意见等文书的节点拆分方式一致。每个环境各一份：

| 节点 | WorkflowNodeKey | dev/prod 文件 |
| ---- | --------------- | ------------- |
| 前言（标题/导语/总体评价） | `SUMMARY_REPORT_PREFACE` | `environments/{dev,prod}/综合报告-前言.yml` |
| 基本情况 | `SUMMARY_REPORT_BASIC_INFO` | `environments/{dev,prod}/综合报告-基本情况.yml` |
| 主要问题 | `SUMMARY_REPORT_ISSUES` | `environments/{dev,prod}/综合报告-主要问题.yml` |
| 审计建议 | `SUMMARY_REPORT_SUGGESTION` | `environments/{dev,prod}/综合报告-审计建议.yml` |

### 输入约定（与后端统一工作流接口对齐）

- **后端自动传入**（来自工作流会话关联的项目字段）：`project_name`、`audit_year`、`audited_unit`、`region`、`description`。其中除 `project_name` 外均可能为空，DSL 不将其设置为必填。
- **后端统一附带**：`sessionId`、`nodeKey`、`documentType`、`projectId`、`year`、`lead_auditor`、`audit_members` 等上下文；综合报告提示词只依赖前一组稳定字段。
- **用户在 `query` 中粘贴**：各节点的大段原始素材（审计背景、自然资源数据、主送机关、市县数量、领导干部数量、分地区问题清单、整改要求）。LLM 只负责组织“文本形式”（公文标题/章节/语气），**所有数字与事实一律来自用户粘贴内容，禁止编造**；素材缺失处用 `【待补充】` 标注。

### 导入与接线

1. 在 Dify 中分别导入 4 个 `综合报告-*.yml`（先 dev 后 prod）。
2. 开发环境四个工作流的 API Key 已写入后端 `application.yml`；生产环境仍需在生产 Dify 导入、发布并单独填写 `application-prod.yml`。
3. 后端 `WorkflowNodeKey`（新增 4 枚举）、`WorkflowDefinitionService::SUMMARY_REPORT_NODE_ORDER` 与前端节点配置已同步为新顺序。
4. 本轮已从开发 Dify 对账并刷新四个 DSL 的布局元数据及 `metadata/dev.json`；生产环境首次导入后，再在生产网络运行同步台的 `export prod` 刷新 App ID、草稿 hash 和更新时间元数据。

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
