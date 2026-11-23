# 腾讯记忆（TencentDB-Agent-Memory）接入说明

- 日期：2026-08-26
- 分支：`release_20260829`（后端）+ `ai-llmops-web` 同分支（前端）
- 设计文档：`docs/superpowers/specs/2026-08-26-tencent-memory-provider-design.md`
- 实现计划：`docs/superpowers/plans/2026-08-26-tencent-memory-provider.md`

## 1. 功能概述

在**系统设置**中新增"记忆系统"选择：**内置记忆系统**（现有实现，行为不变）/ **腾讯记忆**（TencentDB-Agent-Memory）。应用配置可单独覆盖（跟随系统默认 / 内置 / 腾讯）。切换即时生效，存量记忆数据不迁移（切回内置后原数据原样可用）。

抽象层 `MemoryProvider`（`internal/service/memory_provider/`）统一读写入口：

| 方法 | 职责 |
|---|---|
| `get_user_profile(app_config, app_id, user_id)` | 语义记忆画像（`<用户画像>` 块 / 应用详情） |
| `get_read_context(app_config, app_id, user_id, query)` | 对话前召回：情景记忆 + 程序记忆 |
| `get_memory_tools(app_config, app_id, user_id)` | Agent 记忆工具（仅内置模式注入） |
| `trigger_write(app_config=..., app_id=..., user_id=..., query=..., answer=...)` | 对话后异步写侧管道（子线程） |

解析优先级（`MemoryProviderResolver`）：应用 `long_term_memory.provider`（default/builtin/tencent）> 系统 `MEMORY_PROVIDER` > 缺省 builtin。

**行为保持不变约束**（内置路径与改造前逐字节等价）：情景召回不随 `enable` 门控；记忆工具 / 程序记忆 / 写侧随 `enable` 门控。

## 2. 使用方式

### 2.1 系统级（全部应用默认）

系统设置 → **记忆系统** tab：

| 配置键 | 说明 | 敏感 |
|---|---|---|
| `MEMORY_PROVIDER` | `builtin` / `tencent` | 否 |
| `TENCENT_MEMORY_ENDPOINT` | Memory Core 服务地址（如 `http://127.0.0.1:8420`） | 否 |
| `TENCENT_MEMORY_API_KEY` | Memory 实例 Bearer token | **是**（AES 加密入库，GET 脱敏回显 `********`） |
| `TENCENT_MEMORY_SERVICE_ID` | Memory 空间/实例 ID | 否 |

### 2.2 应用级（覆盖系统默认）

应用配置 → 能力 → 长期记忆 → 开启后选择"记忆系统"：跟随系统默认 / 内置记忆系统 / 腾讯记忆。存储于 `long_term_memory.provider`（`AppConfig` JSON 列）。

## 3. 腾讯 SDK v2 验证事实（2026-08-26，GitHub v2.0.1 tag 源码确认）

> **重要架构事实**：v2 为**客户端-服务端架构**，与最初假设的"嵌入式全本地框架"不同。

- 仓库：`TencentCloud/TencentDB-Agent-Memory`，MIT 协议。组件：`MemoryCore`（记忆服务端）+ `MemoryHub` + `MemoryProxy` + `MemoryPanel` + `sdk/`（python/typescript 客户端）。
- **记忆流水线（L0 Conversation → L1 Atom → L2 Scenario → L3 Persona）运行在 MemoryCore 服务端**，SDK 是纯 HTTP 客户端（依赖 `httpx>=0.24.0`），**不接受 LLM 参数**——"复用应用模型"决策因此不适用，`TencentLlmAdapter` 已作为死代码删除。
- Python SDK：模块 `tencentdb_agent_memory`；同步客户端 `MemoryClient(endpoint, api_key, service_id, *, timeout=30, verify=False, stub=None)`。
- 本接入使用的两个方法：
  - 读：`search_atomic(query, *, limit=...)` → `{"items": [{id, type, content, score, ...}]}`（L1 原子记忆检索）
  - 写：`add_conversation(session_id, messages=[{role, content}], ...)`（L0 追加对话，服务端异步触发流水线）
- 隔离映射：`session_id = f"{app_id}:{user_id}"`（v2 的 team/agent/user 隔离字段留待后续透传）。
- **包名状态**：官方尚未发布 PyPI 包（SDK README 标注 "after publish"，版本为 beta `1.0.1-beta.1`，腾讯 PyPI 镜像两候选名均查无此包）。**已采用 vendor 方案**：SDK 源码（`sdk/memory-core/python/tencentdb_agent_memory/`，v2.0.1 tag，13 文件 180KB）原样拷入仓库根 `tencentdb_agent_memory/`，离线可用；`requirements.txt` 补充其唯一外部依赖 `httpx>=0.24.0`（其余均为标准库）。若官方发布后想改用 pip 安装，替换 requirements 注释行即可（模块 import 路径 `tencentdb_agent_memory` 不变）。

## 4. 部署前提（腾讯模式）

腾讯模式需要**可访问的 MemoryCore 服务**（二选一）：

1. **自托管**：克隆仓库 → `deploy/global-images/` 下 `cp .env.example .env`（填两组 LLM 参数：memory 组 + proxy 组）→ `./start-all.sh`；Panel 端口 8125。
2. **腾讯云托管实例**：获取 endpoint / api_key / service_id。

SDK 未安装或配置不全或服务不可达时，`TencentMemoryProvider` **回退为无记忆**（等效关闭长期记忆，返回空上下文/空工具/不写），不阻塞对话。

## 5. 代码结构（后端）

```
internal/service/memory_provider/
├── base.py              # MemoryProvider ABC + MemoryReadContext
├── builtin_provider.py  # 内置实现：委托 UserMemoryService/Episodic/Procedural/MemoryTools（行为零变化）
├── tencent_client.py    # 唯一接触 SDK 的模块：TencentMemoryClient ABC + SdkTencentMemoryClient（懒加载）
├── tencent_provider.py  # 腾讯实现：读三配置 + session 映射 + 回退
└── resolver.py          # MemoryProviderResolver（应用 > 系统 > builtin）+ 常量
```

接入点：`chat_runner.py`（读侧召回/工具/程序记忆 + 写侧 trigger_write）、`web_app_service.py` / `app_service.py`（user_profile）。

## 6. 质量与测试

- 后端全量：**206 passed，1 failed**（`test_episodic_memory_service.py::TestEpisodicSearch::test_search_fuses_and_ranks`——**既有失败**，RRF 融合断言问题，与本分支无关，多次验证本分支 diff 零触碰 episodic/weaviate 代码）。
- 前端：`yarn build` ✓、`yarn type-check` ✓。
- 新增测试：resolver 优先级矩阵（7）、builtin 行为（5）、tencent provider（6）、tencent client（3）、校验（5）、SENSITIVE_KEYS 加密（2）等，均真实行为断言。
- 全过程：9 个实现任务逐任务双阶段审查（spec + quality）+ 最终全分支审查（发现 1 Critical `TENCENT_MEMORY_API_KEY` 未入 SENSITIVE_KEYS，已修复并有加密测试）→ 定向复审全绿。

## 7. 已知边界

- 应用详情的"长期记忆"审计页（`/memory/facts` 等）读内置三张表；腾讯模式下显示为空（后续迭代）。
- 腾讯模式下不注入内置记忆工具（search/write/update/forget_memory），避免双写（后续迭代可映射到腾讯 API）。
- `open_api_service` / `assistant_agent_service` 两条路径未走长期记忆读写管线，不受影响。
- 腾讯记忆需 MemoryCore 服务与三件配置；PyPI 包名待确认。

## 8. 待办（未闭环项）

| # | 事项 | 说明 |
|---|---|---|
| 1 | ~~PyPI 包名验证~~ | **已完成（2026-08-26）：改用 vendor 方案**（SDK 拷入仓库根 `tencentdb_agent_memory/`，离线可用，`httpx>=0.24.0` 已入 requirements）；官方发布 PyPI 后可替换为 pip 安装 |
| 2 | MemoryCore 部署 | 自托管或腾讯云实例，配好三个配置键 |
| 3 | 既有测试失败 | `test_search_fuses_and_ranks` 是否另行修复 |
| 4 | 发布 | 两个 `release_20260829` 分支走 Jenkins 发布流程 |

## 9. 决策记录（Rulings，执行过程中的关键裁决）

| 裁决 | 依据 |
|---|---|
| 直接在建的 `release_20260829` 分支实现，不用 worktree | 用户明确要求 + 仓库分支直提惯例 |
| 腾讯 v2 为客户端-服务端架构 → 删 LLM 适配器、改三配置键、session 映射 | GitHub v2.0.1 源码验证 |
| 写侧恢复 `enable` 门控（`enable and memory_provider is not None`） | Spec 优先于计划文本（"写侧随 enable 门控"） |
| PyPI 包名仅注释占位，不启用活跃依赖 | 沙箱无法访问 PyPI，安全回退 |
| 前端同样建 `release_20260829` 分支 | 与仓库 release_YYYYMMDD 惯例一致 |
| Task 10 不执行 `git add -A` 收尾提交 | 避免把既有未跟踪垃圾文件扫进提交 |
