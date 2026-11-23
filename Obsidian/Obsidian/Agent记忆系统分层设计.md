---
tags: [ai/llmops, memory, design]
date: 2026-08-24
status: designing
---

# Agent 记忆系统分层设计

> 关联代码：`internal/service/app_service.py`、`internal/service/web_app_service.py`、`internal/memory/token_buffer_memory.py`
> 实施计划：[[2026-08-24-memory-system 实施计划]]

## 背景

原实现只有"滑动窗口 + 整段连续摘要"单一记忆模型：`TokenBufferMemory`（按 `dialog_round` 取最近 N 轮原文 + token 预算 `trim_messages`）+ `conversation.summary`（整段对话连续重写摘要）。存在 6 条设计问题，且缺少写侧管道、双时间机制、向量召回、工具化。

## 分层架构

### 短期记忆 —— 滑动窗口 + 滚动摘要互斥

```
System Prompt
├── <预设提示> preset_prompt
├── <长期记忆> conversation.summary（只覆盖窗口外归档内容）
├── <用户画像> 语义记忆（当前有效事实）
├── <情景记忆> 向量召回 top-3 经历
├── <行为规则> 程序记忆（Agent 规则/人设）
└── 窗口段：最近 dialog_round 轮原文（未归档消息，成对 Human/AI）
```

- **窗口与摘要互斥**：`Message.is_archived` 标记压缩出窗口的轮次，摘要只聚合归档内容，避免信息重复
- **惰性压缩**：窗口 token > 预算×60% 时，把最旧轮次归档并入滚动摘要
- **预算公式**：`context_window − max_tokens − 15% 余量`，保底 1000

### 语义记忆 —— 用户画像卡片（双时间机制）

- 表：`user_memory_fact`（按 `app_id × user_id` 命名空间隔离）
- **双时间机制**：
  - 有效区间（现实世界）：`valid_from` / `valid_to`（NULL=当前有效）
  - 事务时间（系统写入/作废）：`tx_created_at` / `tx_invalidated_at`
  - 旧事实作废不删除，保留历史，支持时间点回溯与审计
- **写侧管道**：LLM 从对话抽取用户特征（含隐式推断，如"询问北京天气+规划行程 → location=北京"），输出 `fact_key/fact_value/confidence/is_implicit/evidence`
- **冲突检测**：
  - 值相同 → 原地合并（提升置信度）
  - 显式新事实 → 直接胜出（用户明说）
  - 隐式新事实 → 高置信度（≥0.85 覆盖显式；>旧置信度覆盖隐式）才替换
- **默认检索**：只取 `valid_to IS NULL AND tx_invalidated_at IS NULL`

### 情景记忆 —— 经历向量召回 + RRF

- 表：`episodic_memory` + Weaviate 集合（`vectorizer="none"`，复用 `EmbeddingsService`）
- 写侧管道：对话后异步抽取"完整经历"（长期任务/成功交互/行为模式），LLM 打重要性分
- 检索：**向量 + BM25 双路召回 → `rrf_fusion` → 最终分 = RRF + 0.3×新近度(exp(-0.05·age_days)) + 0.4×重要性** → top-k
- 召回太多是噪声、太少会漏：top-k 召回 → 融合 → 截断 top-N，带来源与时间标注

### 程序记忆 —— 规则/人设工具化

- 表：`procedural_memory`（`version` 每次改写 +1）
- **工具化（MemGPT/LangMem 模式）**：`search_memory` / `write_memory` / `update_memory` / `forget_memory` 作为 Agent 工具注入
- **反馈反思**：dislike 反馈异步触发 LLM 反思，提炼改进规则写入程序记忆

## 治理

| 问题 | 方案 |
|---|---|
| 记忆无界膨胀 | 惰性压缩归档 + 向量集合去重合并（后续） |
| 记忆过期 | TTL：`expires_at` / `valid_to`，惰性清理 |
| 记忆被投毒 | 来源标签 `source` + 信任加权 `trust_score` + 写入校验（LLM 拒绝指令性内容） |
| 多用户混乱 | 所有记忆按 `(app_id, user_id)` 命名空间隔离 |

## 两个会话接口

| 维度 | 调试会话 `/apps/{id}/conversations` | WebApp `/web_apps/{token}/chat` |
|---|---|---|
| 配置来源 | 草稿配置（未发布可调） | 发布配置（必须 PUBLISHED） |
| 会话 | 每账号每应用唯一，自动复用 | conversation_id 可选，校验归属 |
| invoke_from | DEBUGGER | WEB_APP |
| 上下文组装 | 共用 `ChatRunner`（抽取去重后） | 同左 |

## 前端展示

- 压缩（归档）后的消息不展示原文，显示"该轮对话已归档，查看历史"占位
- 历史查询 = 既有分页接口（DB 原文永不删除）
- 消息响应新增 `is_archived` 字段
