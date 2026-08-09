# Dify DSL 变换方案

这是一个用于将 Dify 工作流 DSL 从旧配置转换到新配置的变换方案 skill。

## 使用场景

当需要将 Dify 工作流从以下配置转换到新配置时使用：
- 从通义千问模型转换到 DeepSeek 70B 模型
- 从 DSL 0.4.0 降级到 0.3.1 以兼容新的模型提供商
- 优化知识库检索配置（加权评分重排序）
- 处理 DeepSeek 模型的思考标签输出

## 核心变换规则

### 1. DSL 版本和插件类型变换

```yaml
# 转换前
version: 0.4.0
kind: workflow
plugins:
  - priority: 1
    provider: langgenius/tongyi:0.1.1
    type: marketplace

# 转换后
version: 0.3.1
kind: workflow
plugins:
  - priority: 1
    provider: langgenius/openai_api_compatible:0.0.30
    type: package
  - priority: 2
    provider: langgenius/ollama:0.1.2
    type: package
```

### 2. LLM 节点模型配置变换

```yaml
# 转换前
model:
  completion_params:
    temperature: 0.7
  mode: chat
  name: qwen3-32b
  provider: langgenius/tongyi/tongyi

# 转换后
model:
  completion_params:
    temperature: 0.7
    enable_thinking: false  # 新增：禁用 DeepSeek 思考模式
  mode: chat
  name: DeepSeek-R1-Distill-Llama-70B
  provider: langgenius/openai_api_compatible/openai_api_compatible
```

### 3. 知识库检索配置变换

```yaml
# 转换前
dataset_ids:
  - Ct1REzvB7Af+8a+16LwdN7R+cryWImRyBtPRtx6tcTvJ8/FX/oJtmYT5DkEOOVMg
multiple_retrieval_config:
  reranking_enable: false
  reranking_mode: reranking_model
  reranking_model:
    model: gte-rerank
    provider: langgenius/tongyi/tongyi
  top_k: 4

# 转换后
dataset_ids:
  - 28iyihUX7ji1oHur8J28VTUjBwMZVhxOCaDCEOL0sHiKu7CprlKliozQRviBuIga  # 需要更新为新的知识库ID
multiple_retrieval_config:
  reranking_enable: true  # 启用重排序
  reranking_mode: weighted_score  # 改为加权评分模式
  reranking_model:
    model: gte-rerank
    provider: langgenius/tongyi/tongyi
  top_k: 4
  weights:  # 新增权重配置
    keyword_setting:
      keyword_weight: 0.3
    vector_setting:
      embedding_model_name: bge-m3
      embedding_provider_name: langgenius/ollama/ollama
      vector_weight: 0.7
```

### 4. Tool 节点模型配置变换

对于使用 `rookie_text2data` 等 tool 的节点，需要更新模型配置：

```yaml
# 转换后
tool_configurations:
  model:
    type: constant
    value:
      completion_params:
        enable_thinking: false
      mode: chat
      model: DeepSeek-R1-Distill-Llama-70B
      model_type: llm
      provider: langgenius/openai_api_compatible/openai_api_compatible
```

### 5. 边缘场景：数据处理工作流的额外变换

对于包含 SQL 处理、数据库查询的工作流，还需要以下变换：

#### 5.1 数据库连接配置更新

```yaml
# 根据实际环境更新
host: 100.81.13.52  # 从 host.docker.internal 变更
port: 3306          # 从 3307 变更
```

#### 5.2 新增 SQL 清理节点（处理 DeepSeek 思考标签）

由于 DeepSeek-R1 模型会在输出中包含 `<think>` 和 `</think>` 标签，需要添加代码执行节点来清理 SQL：

```python
# 代码执行节点示例
def main(arg1: str) -> dict:
    import re

    # 移除思考标签及其内容
    arg1 = re.sub(r'<think>.*?</think>', '', arg1, flags=re.DOTALL)

    # 提取 SQL 代码块
    sql_match = re.search(r'```sql\s*(.*?)\s*```', arg1, re.DOTALL)
    if sql_match:
        sql = sql_match.group(1).strip()
    else:
        # 如果没有代码块标记，尝试提取第一个完整的 SQL 语句
        sql_match = re.search(r'(SELECT.*?;)', arg1, re.DOTALL | re.IGNORECASE)
        if sql_match:
            sql = sql_match.group(1).strip()
        else:
            sql = arg1.strip()

    return {
        "result": sql
    }
```

#### 5.3 新增迭代处理节点（可选）

如果需要批量执行多条 SQL，可以添加迭代节点：

```yaml
# 迭代开始节点
id: iteration_start
type: iteration-start
# ... 配置迭代逻辑 ...

# 模板变换节点（格式化输出）
id: template_transform
type: template-transform
template: |
  SQL: {{ arg2 }}

  Result: {{ arg1 }}
```

## 变换检查清单

转换前请检查：

- [ ] 确认是否需要更换模型提供商（通义千问 → OpenAI API Compatible）
- [ ] 确认新知识库的 dataset_ids
- [ ] 确认是否需要启用重排序和加权评分
- [ ] 如果是数据处理工作流，确认数据库连接信息
- [ ] 确认是否需要处理 DeepSeek 思考标签

## 变换步骤

1. **备份原始文件**
   ```bash
   cp 原始文件.yml trasnfered/原始文件.yml
   ```

2. **更新 DSL 版本和插件**
   - 修改 `version` 为 `0.3.1`
   - 将 `marketplace` 类型插件改为 `package`
   - 添加 `openai_api_compatible` 和 `ollama` 依赖

3. **更新所有 LLM 节点**
   - 将模型名称改为 `DeepSeek-R1-Distill-Llama-70B`
   - 将提供商改为 `langgenius/openai_api_compatible/openai_api_compatible`
   - 添加 `enable_thinking: false` 参数

4. **更新知识库配置**
   - 替换 `dataset_ids` 为新的知识库 ID
   - 设置 `reranking_enable: true`
   - 修改 `reranking_mode` 为 `weighted_score`
   - 添加 `weights` 配置（关键词权重 0.3，向量权重 0.7）

5. **更新 Tool 节点**（如果有）
   - 在 `tool_configurations.model.value` 中更新模型配置

6. **处理边缘场景**（如果是数据处理工作流）
   - 添加 SQL 清理节点（移除思考标签）
   - 更新数据库连接配置
   - 添加迭代处理节点（如果需要）

7. **验证转换结果**
   - 检查 YAML 语法正确性
   - 确认所有节点引用的变量 ID 正确
   - 测试导入到 Dify 平台

## 常见问题

### Q1: 为什么 DSL 版本要降级？

A: DSL 0.3.1 与新的模型提供商（OpenAI API Compatible）兼容性更好，某些高级特性在 0.4.0 中可能不支持。

### Q2: 如何获取新的知识库 ID？

A: 在 Dify 平台的"知识库"管理页面，点击对应知识库的设置，可以查看其 dataset_ids。

### Q3: 加权评分中的权重如何调整？

A: 根据实际检索效果调整：
- 如果关键词匹配更重要，提高 `keyword_weight`
- 如果语义相似度更重要，提高 `vector_weight`
- 两者之和应该为 1.0

### Q4: DeepSeek 的思考标签一定要移除吗？

A: 不是必须的。如果下游节点能够正确处理这些标签，可以保留。但对于 SQL 提取等场景，建议移除以避免干扰。

## 示例文件

参考以下文件查看实际转换效果：
- `工作方案-审计目标.yml` → `trasnfered/工作方案-审计目标.yml`
- `数据分析工作流1.yml` → `trasnfered/数据分析工作流1.yml`
