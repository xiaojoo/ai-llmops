# 全量回归报告（Plan 5 · 2026-08-29 · T6 收尾终版）

分支：`release_fastApi`（FastAPI 迁移收尾）；运行方式：`venv\Scripts\python.exe -m pytest test -q --no-header -p no:cacheprovider --tb=short`。

## 全量回归（环境恢复后终跑）

| 项 | 结果 |
|---|---|
| 全量套件（`pytest test`） | **734 passed / 0 failed**（8 分 07 秒） |
| 其中 live_server 真实 TCP 簇 | 全部通过（lifespan 触发、153 路由冒烟、认证两分支、SSE 流式、黄金契约） |
| 环境 | 内存充足（清理遗留 uvicorn/celery 后可用 16GB）、Postgres/Redis/Weaviate/代理 7890 在线 |

**首轮 733 passed / 1 failed**，唯一失败 `test_logging_idempotent` 为**测试顺序耦合**（非生产缺陷）：
- 全量运行中前面的 live_server 测试（lifespan 调 `init_logging()`）已把模块级 `_initialized` 置 True、root 已挂 handler；跑到该测试时 `before=6`，调用后 `after=6`，`assert 6 > 6` 失败；单独跑通过。
- 修复（`test/internal/extensions/test_extensions.py`）：测试内保存/清空 root handlers + 重置初始化标志，独立验证"首次挂载 + 幂等"契约，finally 恢复现场。修复后单独跑 5 passed，模拟全量顺序（先 init_logging 再跑）PASS，终跑全量 734 passed。

## 测试矩阵（与首轮一致，全绿）

| 簇 | passed | skipped | failed | 说明 |
|---|---|---|---|---|
| test/package | 41 | 0 | 0 | 含 `test_database.py` |
| test/internal/config + model + schema + server | 113 | 0 | 0 | settings/模型/schema 校验/deps 认证 |
| test/internal/core | 109 | 9 | 0 | agent/orchestrator/workflow 节点 |
| test/internal/service | 175 | 13 | 0 | 全服务层（含 SSE 黄金、chat_runner、检索工具、记忆） |
| test/internal/task + extensions + memory + container + migration | 31 | 0 | 0 | celery 装配/扩展/迁移环境 |
| test/app（含 live_server 簇：golden/401/SSE/路由注册/认证冒烟/chroma 契约） | 265 | 1 | 0 | **live_server 真实 TCP 全绿（环境恢复后）** |

## T6 收尾补审产出（T5 控制器 5 提交，补常规 subagent 审查）

- 审查对象：60e3813 → 1156656 → b8dffcd → 53abe1c → a19149c（T5 控制器直接实施，当时 subagent 执行层崩溃缺审）。
- 结论：**可合并**；核心架构（RequestSessionProxy + app 级 get_db + selectinload + .data 对齐）设计正确、转换彻底（`req.xxx.data` 全库零残留）。
- 发现并修复 **1 个重要问题**：`POST /chroma/delete` 被 T5 误标 `Annotated[ChromaFileDeleteReq, Query()]`——原 Flask 契约是 JSON body（`request.get_json`），导致 body→query 契约漂移。已改回 body 模型（`internal/handler/chroma_file_handler.py`）+ 新增契约测试 `test/app/test_chroma_delete_contract.py`（2 passed：body 携带 path 生效、query 参数不再被接受）。
- 建议级遗留（已登记，非阻塞）：app 级 get_db 波及健康/静态/文档路由（DB 挂时 /healthz 语义污染）；`register_routes_from_container` 死参数；`ApiToolProvider.tools` 默认改 `lazy="selectin"` 根治；两个 validation handler 去重；conftest 测试隔离与 fixture 作用域。

## 结论

- **全量回归 734 passed / 0 failed**，live_server 真实 TCP 簇环境恢复后全绿——此前受 OOM 阻塞的 `test_contract_401`（153 路由冒烟）与全量套件均可完整跑通。
- OOM 根因：embedding 模型反复加载内存泄漏（`create_embedding_provider` 无进程级复用，commit `37667ef` 已修复）+ 机器内存被遗留进程/IDE 占满；非沙箱内存上限（沙箱仅 kill-on-close，无任何内存限制）。
- 本次改动：测试桩修复 ×1（顺序耦合）+ 契约修复 ×1（chroma delete body）+ 新增契约测试 ×1。
