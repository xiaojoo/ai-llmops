# SDD ledger — plan: docs/superpowers/plans/2026-08-26-tencent-memory-provider.md

Spec: docs/superpowers/specs/2026-08-26-tencent-memory-provider-design.md
Branch: release_20260829 (HEAD ff5f7e2 = Task 1 BASE)

## Preflight conflict scan (table)

| Task pair | Interface shared | Finding |
|---|---|---|
| T2 → T3 | BuiltinMemoryProvider 注入 resolver | 一致：resolver.py 注入 builtin_provider + tencent_provider |
| T3 → T4 | MemoryProviderResolver 注入 ChatRunner/WebAppService/AppService | 一致：三者新增字段 memory_provider_resolver |
| T1 → T2/3/4/7 | MemoryProvider 四方法签名 / MemoryReadContext | 一致：app_config 显式参数、无 user_profile 字段 |
| T3 → T7 | tencent_provider.py 骨架 → 整体替换 | 一致：T7 替换全文 |
| T2 ↔ T4 | trigger_write kwargs | 一致：app_config/app_id/user_id/query/answer |
| T4 ↔ T5 | app_service.py（不同方法）+ test_app_service_draft_config.py（构造 vs 新用例） | 无重叠，顺序执行 |
| T6 → T7 | SdkTencentMemoryClient 被 _build_client 消费 | 一致 |
| T8 ↔ T9 | 前端不同文件 | 无共享 |

每 Task 自洽：T4 签名（_stream_and_persist 新参 memory_provider、read_ctx 复用）、T5 校验（键集 {enable,provider} + 取值枚举）、T7 测试（_build_client 返回 None 路径、SyncThread 同步线程）均在计划自查时核对过。

## Rulings

- Ruling: 不使用 git worktree，直接在 release_20260829 分支实现 — 用户明确要求最终代码提交该分支，仓库惯例即分支直提（历史计划均如此），且前端是嵌套独立仓库 — 若错：仅在分支上留可回退提交，成本低。
- Ruling: test_episodic_memory_service.py::TestEpisodicSearch::test_search_fuses_and_ranks 失败为既有问题（git diff 证实本计划零触碰 episodic/weaviate 相关文件；失败为 RRF 融合断言 0>=1，fake 集合 embedding_id 语义不匹配）— 不在本计划范围，最终 review/汇报时告知用户 — 若错：用户多知道一个既有失败，无成本。
- Ruling: TencentDB-Agent-Memory **v2 为客户端-服务端架构**（GitHub v2.0.1 tag 源码已克隆验证）：`MemoryClient(endpoint, api_key, service_id)` 纯 HTTP 客户端，L0→L3 流水线在 MemoryCore 服务端执行，SDK 不接受 LLM。因此：①"复用应用模型"决策不再适用（spec 已更新）；②`TencentLlmAdapter` 为死代码，**删除 tencent_llm.py**；③配置面改为 TENCENT_MEMORY_ENDPOINT / API_KEY（敏感，进 SENSITIVE_KEYS）/ SERVICE_ID，TENCENT_MEMORY_STORAGE_DIR 作废；④session_id=f"{app_id}:{user_id}" 做隔离；⑤腾讯模式需可访问的 MemoryCore 服务（部署边界，spec 已更新）— 若错：集成方向与真实 SDK 不符，返工集中在 tencent_client.py 单文件，成本低。
- Ruling: Task 6 实现者按 brief 成功路径（"验证出真实包名/API 则同步修改"）适配真实 API 是正确行为，非偏差 — 若错：无。
- Ruling: 前端仓库（ai-code-llmops-web，独立 git）同样建 release_20260829 分支提交 — 与用户"提交 release_20260829"意图及仓库 release_YYYYMMDD 惯例一致 — 若错：前端分支命名不同步，可重命名，成本低。
- Ruling: PyPI 包名待用户机器确认（pyproject 名 tencentdb-agent-memory-sdk-python-v2 vs README 宣称发布名 tencentdb-agent-memory-sdk-python），requirements.txt 仅注释占位，不启用活跃依赖 — 若错：腾讯模式无法安装 SDK，回退为无记忆（安全）

## Progress

Task 1: complete (commits ff5f7e2..0682315, review clean)
Task 1: minor (deferred): test_base.py:4 UUID 导入未使用（plan-mandated，brief 原文）; 报告未附全量 pytest test/ -x 输出（聚焦目录运行已绿，风险可忽略）; 覆盖率可再宽（plan-mandated 测试集）
Task 2: complete (commits 0682315..a94465c, review clean)
Task 2: minor (deferred): 写侧线程体（_extract_*）无直接单测（plan-mandated，可后续补）; builtin_provider.py 两处签名行超 100 字符（plan-mandated 转录）; 读侧异常日志缺 app_id/user_id 上下文（转录自 brief）
Task 3: complete (commits a94465c..8d56da5, review clean)
Task 3: minor (deferred): test_resolver.py MagicMock 导入未使用（plan-mandated 转录）; tencent_provider.py 骨架 logger 未使用（Task 7 会用，plan-mandated）
Task 4: fix round 1/5 (1 addressed, 0 open — 写侧 enable 门控恢复 + 2 回归测试; commits f0c56f8..0be64ed)
Task 4: complete (commits 8d56da5..0be64ed, review clean)
Task 4: minor (deferred): app_service.py:102 user_memory_service 字段已成死依赖（brief 所述 458/472 行实际无关；reviewer 建议最终 review 波次删除字段+import+三个 _build_service 的 MagicMock 参数）; chat_runner.py:110-118 enable=False 时保留调用方传入的 procedural_instructions（现状无调用方传非空值，不可观察）; 写侧 app_id 统一用 app.id（各调用路径等价）
Task 5: complete (commits 0be64ed..7869b6e, review clean)
Task 5: minor (deferred): 两个 reject 测试未断言具体错误文案（brief 原文，可后续加固）; 未覆盖 "default" 显式值与多余键场景（superset 边界已覆盖，足够）
Task 6: complete (commits 7869b6e..cd6ceb4, review clean; 含死代码删除与文档同步)
Task 6: minor (deferred): test_tencent_client.py 仅 assert_called_once 未钉死 SDK kwargs（可改 assert_called_once_with）; recall 归一化兜底未测（低风险，schema 已核实）; ImportError 测试依赖 SDK 未安装（PyPI 可装后需 revisit）
Task 7: complete (commits cd6ceb4..bd16fbc, review clean)
Task 7: minor (deferred): test_tencent_provider.py MagicMock 导入未使用 + FakeClient.kwargs 无测试读取（均 brief 继承，无功能影响）
Task 8: complete (frontend commits 0128ed8..ff047c2, review clean; yarn build 由 controller 以 danger-full-access 升级后跑通 22.44s)
Task 8: minor (deferred): MemoryConfig 用原生 input 布局与其余 tab 的 ConfigGroup/ConfigRow 风格不一致（brief 原文）; radio 缺 name 属性（a11y，可加 name="memory-provider"）; 敏感项 '********' 字面量可被编辑成损坏值（系统既有模式，brief 原文）
Task 9: complete (frontend commits ff047c2..dfc67ba, review clean)
Task 9: minor (deferred): provider 类型为 loose string（brief 原文，可改 union）; Boolean(value) 依赖数字 doption 值（既有模式）; provider 选择无 no-op 守卫（一次冗余 PATCH）
Task 10: 全量回归 206 passed + 1 既有失败（test_search_fuses_and_ranks）; 前端 yarn build 19.85s 成功; 无新提交（工作树仅剩既有未跟踪文件）
Task 10: Ruling: 计划 Step 4 的 `git add -A && git commit` 不执行——工作树只剩与本次无关的既有未跟踪文件（PDF/Obsidian/tmp 脚本等），`git add -A` 会把垃圾扫进提交 — 若错：无，最终审查包已覆盖全部本计划提交
Task 10: 最终全分支审查已派发（review-FINAL-branch.diff）
