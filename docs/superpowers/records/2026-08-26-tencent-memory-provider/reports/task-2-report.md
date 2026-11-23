# Task 2 Report: BuiltinMemoryProvider（内置实现，行为零变化）

**Status:** DONE_WITH_CONCERNS
**Commit:** `a94465c` — `feat(memory): BuiltinMemoryProvider 内置实现（行为零变化）`
**Branch:** `release_20260829`（在 0682315 之上直接提交）

## 1. What I implemented

- **`internal/service/memory_provider/builtin_provider.py`**（新建，88 行）：`BuiltinMemoryProvider(MemoryProvider)`，`@inject @dataclass`，注入 `UserMemoryService` / `EpisodicMemoryService` / `ProceduralMemoryService` / `MemoryTools`。四个抽象方法实现 + 两个写侧线程目标：
  - `get_user_profile`：`get_current_facts(min_trust=0.3)` → `_render_current_facts`
  - `get_read_context`：`search_episodes(top_k=3)` 失败时 catch 并 log（情景记忆为空，程序记忆照常返回）
  - `get_memory_tools`：委托 `MemoryTools.get_tools(flask_app=current_app._get_current_object(), ...)`
  - `trigger_write`：起两个子线程（`_extract_user_facts` / `_extract_episodes`），线程内 `flask_app.app_context()` + try/except 与现状一致
- **`internal/service/memory_provider/__init__.py`**（修改）：追加 `from .builtin_provider import BuiltinMemoryProvider`，`__all__` 增加 `"BuiltinMemoryProvider"`（保留原有文件头）。
- **`test/internal/service/memory_provider/test_builtin_provider.py`**（新建，75 行）：5 个用例。

**实现前接口核对**（无 NEEDS_CONTEXT 触发点，全部签名与 brief 一致）：
- `UserMemoryService.get_current_facts(app_id, user_id, *, min_trust)` ✓、`_render_current_facts(facts)` ✓、`expire_overdue_facts` ✓、`extract_user_facts(query, answer, current_profile)` ✓、`upsert_facts` ✓
- `EpisodicMemoryService.search_episodes(app_id, user_id, query, top_k=3)` ✓（返回带 `.content` 的对象列表）、`get_recent_text` / `extract_episodes(query, answer, existing)` / `upsert_episodes` ✓
- `ProceduralMemoryService.get_instructions(app_id, user_id) -> str` ✓
- `MemoryTools.get_tools(*, flask_app, app_id, user_id) -> list[BaseTool]` ✓
- `injector.get(BuiltinMemoryProvider)` 可解析：injector 绑定 SQLAlchemy/Weaviate 等，各 service 为 `@inject` dataclass（`test_memory_tools.py` 已证明 `injector.get(MemoryTools)` 模式可用）

## 2. TDD Evidence

### RED（Step 2）
命令：`.\venv\Scripts\python.exe -m pytest test/internal/service/memory_provider/test_builtin_provider.py -v`

输出（截取）：
```
test\internal\service\memory_provider\test_builtin_provider.py:7: in <module>
    from internal.service.memory_provider import BuiltinMemoryProvider
E   ImportError: cannot import name 'BuiltinMemoryProvider' from 'internal.service.memory_provider' (H:\ai-code-llmops\internal\service\memory_provider\__init__.py)
=========================== short test summary info ===========================
ERROR test/internal/service/memory_provider/test_builtin_provider.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```
与 brief 预期完全一致。附带 2 条已知无害的 `PytestCacheWarning (WinError 5)`，已忽略。

### GREEN（Step 4）
命令：`.\venv\Scripts\python.exe -m pytest test/internal/service/memory_provider/test_builtin_provider.py -v`

输出（截取）：
```
test/internal/service/memory_provider/test_builtin_provider.py::TestBuiltinMemoryProvider::test_get_user_profile_delegates_to_user_memory_service PASSED
test/internal/service/memory_provider/test_builtin_provider.py::TestBuiltinMemoryProvider::test_get_read_context_episodic_and_procedural PASSED
test/internal/service/memory_provider/test_builtin_provider.py::TestBuiltinMemoryProvider::test_get_read_context_episodic_failure_keeps_procedural PASSED
test/internal/service/memory_provider/test_builtin_provider.py::TestBuiltinMemoryProvider::test_get_memory_tools_returns_four_tools PASSED
test/internal/service/memory_provider/test_builtin_provider.py::TestBuiltinMemoryProvider::test_trigger_write_spawns_two_extraction_threads PASSED
======================== 5 passed, 1 warning in 0.03s =========================
```
（failure 用例中的 "情景记忆召回失败" ERROR 日志行是预期的 catch-and-log 行为。）

### 全量 `pytest test/ -x`（Step 4 之后，提交前）
命令：`.\venv\Scripts\python.exe -m pytest test/ -x`

输出：
```
=========================== short test summary info ===========================
FAILED test/internal/service/test_episodic_memory_service.py::TestEpisodicSearch::test_search_fuses_and_ranks
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!
================= 1 failed, 144 passed, 11 warnings in 21.65s =================
```

**该失败为预先存在、与本任务无关**，证据链：
1. 失败点是 `test_episodic_memory_service.py::test_search_fuses_and_ranks`（情景检索/Weaviate 路径），本任务未触碰该文件及 `EpisodicMemoryService` 任何代码；
2. 根因：该测试的 fake `_recall_vector`/`_recall_bm25` 返回的是 DB 行 `.id`，而 `search_episodes` 现按 `embedding_id` 匹配（代码内注释明确记录了这次改动："注意：不能用 EpisodicMemory.id 匹配——那是数据库生成的 UUID"），查询 `WHERE embedding_id IN (行id)` 恒为空 → `assert 0 >= 1`；
3. 决定性验证：`git stash push -u`（仅暂存本任务 3 个路径）后在干净树上单独重跑同一用例，**同样失败**（`assert 0 >= 1`），随后 `git stash pop` 恢复。

排除该用例后的全量复跑：
```
.\venv\Scripts\python.exe -m pytest test/ -x -k "not test_search_fuses_and_ranks"
=============== 182 passed, 1 deselected, 10 warnings in 20.58s ===============
```
（exit code 0）

## 3. Files changed

- `internal/service/memory_provider/builtin_provider.py`（新建）
- `internal/service/memory_provider/__init__.py`（修改，+2/-1）
- `test/internal/service/memory_provider/test_builtin_provider.py`（新建）

仅此 3 个路径被 `git add`/提交（`git add internal/service/memory_provider/ test/internal/service/memory_provider/`）。

## 4. Self-review findings

- **转录 fidelity**：用 PowerShell 从 brief 提取 3 个 ```python 代码块并与实际文件逐字节比对（归一化 CRLF/末尾换行）——测试文件与 provider 文件 **EXACT MATCH**；`__init__.py` 的 import/`__all__` 段与 brief 完全一致，仅保留 brief 指示 "Append" 语义下原有的 shebang + 包 docstring 头（该头为 Task 1 遗留，非本次新增）。
- **测试断言真实行为**：委托（fake facts → profile 渲染）、失败容忍（episodic 抛错时 procedural 保留）、真实工具名集合、双线程语义（SyncThread 同步执行 + kwargs 校验），不是空壳断言。
- **无多余内容（YAGNI）**：未添加 brief 之外的任何代码/文件；提交 diff 仅 165 insertions / 1 deletion。
- **无循环导入风险**：grep 确认目前无生产代码 import `memory_provider`（仅测试），`builtin_provider.py` 的依赖链（memory_tools → services）在启动路径上无环。

## 5. Concerns

1. **全量 `pytest test/ -x` 无法全绿**：`test/internal/service/test_episodic_memory_service.py::TestEpisodicSearch::test_search_fuses_and_ranks` 在干净树上同样失败（测试的 fake 召回返回行 id 与 service 按 embedding_id 匹配的实现不匹配），属预先存在的过期测试，与本任务无关，未在本任务内修复（超出 brief 路径约束）。建议由后续任务/负责人单独处理该测试（改 fake 返回 `embedding_id` 或改断言）。
2. 无其他 concern；已知 `PytestCacheWarning (WinError 5)` 为环境无害告警。
