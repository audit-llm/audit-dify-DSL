# Dify 工作流版本同步台

以 `audit-dify-DSL` 仓库为版本中心，解决开发/生产网络物理隔离时工作流 DSL 的
导出、归档和版本对比问题。

## 解决什么问题

- 开发和生产环境网络隔离，不能在机器上同时访问两边 Dify。
- 导出只能人工触发，仓库不校验线上版本是否与仓库一致。
- 但“上一次更改工作流的时间”可以从 Dify 拿到并写入仓库元数据，跨环境对比时
  直接给出提示：哪个环境的哪个工作流更新了、差多久，提醒你手动导出迁移。

## 数据流

```text
开发网络内:  sync-tool 一键导出 dev -> environments/dev/*.yml + metadata/dev.json -> git push
开发网络外:  pull 仓库 -> sync-tool 本地页面自动对比 dev/prod 时间 -> 有更新则提示
生产网络内:  sync-tool 一键导出 prod -> environments/prod/*.yml + metadata/prod.json -> git push
```

工具**不会**自动导入或发布 Dify，只做导出与对比；DSL 进入生产环境仍由你在生产
Dify 里手动导入，符合“导出需人工触发”的边界。

## 环境要求

- Python 3.10+，仅使用标准库，无需安装依赖。
- 能访问目标 Dify 的 Console API（`/console/api/login`、`/apps`、
  `/apps/{id}/workflows/draft`、`/apps/{id}/export`），Dify 1.7.2 已实测。

## 快速开始

```bash
cd sync-tool
cp config.example.json config.json
# 编辑 config.json，填入各环境 base_url / email / password
python3 -m dify_sync.cli check-config
python3 -m dify_sync.cli serve
```

浏览器打开 `http://127.0.0.1:8642`，每张环境卡片上点“一键导出全部”即可。
服务只监听本机，不会对外网开放。

## 命令行

```bash
# 一键导出某环境全部工作流（本命令需要能访问该环境的网络）
python3 -m dify_sync.cli export dev

# 离线对比仓库中两个环境的时间记录
python3 -m dify_sync.cli compare

# 用仓库现有 yml 生成无 Dify 时间信息的基线元数据（适合首次初始化另一环境）
python3 -m dify_sync.cli init-metadata prod
```

## 仓库里新增了什么

```text
sync-tool/
  dify_sync/            核心代码（配置、Dify 客户端、导出、对比、服务、CLI）
  web/                  本地可视化页面（原生 JS，无构建）
  config.example.json   配置模板（提交）
  config.json           本地真实配置（被 .gitignore 忽略，不要提交）
  tests/                离线测试（内置假 Dify）
metadata/
  dev.json / prod.json  各环境工作流清单与 Dify 更新时间（提交，作为版本中心数据）
```

## 时间语义

- 每个环境导出时，从 Dify 的 `workflows/draft` 读取该应用草稿的
  `updated_at`（epoch 秒），写入 `metadata/<env>.json`。
- 跨环境对比只比较仓库里两边的元数据，**不联网**；只有“一键导出”需要联网。
- 若某环境从未导出（例如生产网络尚未跑过工具），对比会提示“一侧未记录 Dify
  更新时间”，这符合“仓库只记录人工触发过的导出”的约定。

## 安全说明

- `config.json` 含 Console 密码，已在仓库 `.gitignore` 中忽略。
- 服务默认只监听 `127.0.0.1`。
- 导出时默认 `include_secret=false`，避免把敏感字段写进 DSL 文件。
- 工具只读 Dify（登录、列举、读草稿、导出），不执行发布或删除。
