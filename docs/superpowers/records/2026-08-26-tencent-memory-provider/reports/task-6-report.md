# Task 6 Report: 腾讯 SDK 验证 + TencentMemoryClient + LLM 适配器 + 依赖

**Status: DONE_WITH_CONCERNS** (deviation from the "fake-SDK" assumption — see below; the brief's own success path was followed)

**Commit:** `52fc079` — feat(memory): 腾讯记忆 SDK 客户端与 LLM 适配器（懒加载，SDK 差异隔离）

---

## 1. What I implemented

- `internal/service/memory_provider/tencent_client.py` — new. `TencentMemoryClient` (ABC, `recall`/`write_round` interface) + `SdkTencentMemoryClient` (lazy-load, SDK 缺失时构造抛 ImportError). **Adapted to the verified real SDK API** (see Step 1 + Concerns).
- `internal/service/memory_provider/tencent_llm.py` — new, transcribed verbatim from the brief (dataclass `TencentLlmAdapter.chat(messages) -> str` wrapping `llm.invoke`).
- `test/internal/service/memory_provider/test_tencent_client.py` — new, 3 tests (fake SDK via `sys.modules` injection, module `tencentdb_agent_memory`).
- `requirements.txt` — one commented placeholder line only (no active dependency).

`tencent_provider.py` (skeleton, Task 7), `__init__.py`, `base.py`, `resolver.py`, `builtin_provider.py` were **not touched**.

## 2. Step 1 verification results (each attempt, exact output)

All attempts run with bounded ~35s timeouts, in order:

| # | Command | Result | Exact output |
|---|---------|--------|--------------|
| a | `pip index versions tencentdb-agent-memory` | **FAIL (timeout)** | `(no output)` — killed by the 35s executor timeout `[timed out after 35000ms]` `[exit code: 1]`. PyPI unreachable from this sandbox. |
| b | `pip index versions tencentdb-agent-memory -i https://mirrors.tencent.com/pypi/simple --trusted-host mirrors.tencent.com` | **FAIL (timeout)** | `(no output)` — `[timed out after 35000ms]` `[exit code: 1]`. Tencent mirror also unreachable. |
| c | `git ls-remote https://github.com/TencentCloud/TencentDB-Agent-Memory.git` | **SUCCESS** | Full ref list returned (many `refs/pull/*/head|merge`, tags incl. `v0.1.4` … `v2.0.1`, `v2.0.1-beta.1`, `v2.0.1-beta.2`). Repo reachable. |

**Because (c) succeeded, the brief's success path applies** ("成功（得到包名/版本或仓库可达）→ 按 SDK 实际 README / 源码确认…；若 Task 6 Step 1 验证出真实包名/API，同步修改 `from agent_memory import AgentMemory` 与两个方法体"). I did a bounded shallow clone of tag `v2.0.1` and inspected the real SDK source (temporary clone removed afterwards; no leftovers):

**Verified SDK facts (from `sdk/memory-core/python/` in tag v2.0.1):**
- Package (pyproject.toml, authoritative build metadata): `tencentdb-agent-memory-sdk-python-v2`, version **1.0.1-beta.1**; dependency `httpx>=0.24.0`; requires-python `>=3.9`. README additionally claims a published name `tencentdb-agent-memory-sdk-python` but marks install as "从 PyPI 安装（发布后）" — i.e. publication status unconfirmed; PyPI itself unreachable here.
- Import module: `tencentdb_agent_memory` (NOT `agent_memory`). Exports `MemoryClient` / `AsyncMemoryClient` (v2) + `TDAMError` / `ParamError`.
- Init: `MemoryClient(endpoint="", api_key="", service_id=None, *, timeout=30, verify=False, stub=None)` — **no `llm`, no `storage_path`**; it is an HTTP client to a Memory Core service.
- Recall: `search_atomic(query, *, limit=None, type=None, ...)` → `{"items": [{id, type, content, score, ...}]}` (confirmed via typescript `AtomicSearchHit` types and the python `_http.post` envelope unwrap `data`).
- Write round: `add_conversation(session_id, messages=[{role, content, ...}], ...)` — server-side memory pipeline (提取→整合→反思→复盘) is triggered on the service.
- `read_core()` → `{"content": ...}` (L3 persona), `list_scenarios()` → `{"entries": [...]}`.

## 3. TDD evidence

- **RED**: created the test first, ran
  `venv\Scripts\python.exe -m pytest test/internal/service/memory_provider/test_tencent_client.py -v`
  → `ERROR … ModuleNotFoundError: No module named 'internal.service.memory_provider.tencent_client'` (collection error, exit 1). Exactly the brief's expected RED.
- **GREEN**: implemented both modules, re-ran →
  `3 passed, 1 warning` (warning = the known harmless PytestCacheWarning WinError 5).
- Package gate: `pytest test/internal/service/memory_provider/` → `18 passed`.
- Full suite: `pytest test/ -x` → `1 failed, 162 passed … stopping after 1 failures`; the only failure is the **known pre-existing** `test/internal/service/test_episodic_memory_service.py::TestEpisodicSearch::test_search_fuses_and_ranks` (ignore per instructions).
- Full suite minus that known test: `pytest test/ --deselect …test_search_fuses_and_ranks -q` → `200 passed, 1 deselected`.

## 4. Files changed (commit 52fc079, 4 files, +133)

- `internal/service/memory_provider/tencent_client.py` (new, +60)
- `internal/service/memory_provider/tencent_llm.py` (new, +28)
- `test/internal/service/memory_provider/test_tencent_client.py` (new, +43)
- `requirements.txt` (+2: blank line + comment)

## 5. Self-review findings

- **Code vs brief**: `tencent_llm.py` matches the brief verbatim. `tencent_client.py` keeps the brief's structure/docstrings, ABC, and the **stable `recall(query, top_k=5) -> list[dict]` / `write_round(query, answer) -> None` interface** (Task 7 contract unchanged); the import + two method bodies + constructor params were adapted to the verified real SDK exactly as the brief's success path directs.
- **Fake-SDK tests genuinely exercise lazy-load + ImportError**: (1) `test_missing_sdk_raises_import_error` runs against the real (absent) SDK → constructor raises ImportError; (2)/(3) inject `tencentdb_agent_memory` into `sys.modules` so the function-level import resolves → asserts `MemoryClient` constructed once, `search_atomic(query=…, limit=top_k)` called once and items normalized to `{type, content, score}`, `add_conversation(session_id=…, messages=[…])` called once.
- **requirements.txt**: contains **only** the comment line (verified via `git show HEAD -- requirements.txt`); no active/unverified dependency.
- **No extras**: only the 4 brief paths committed; temporary SDK clone and commit-message temp file removed; tencent_provider.py untouched.

## 6. Concerns

1. **Deviated from the orchestrator's "fake-SDK implementation regardless" expectation** — that assumption (all three probes fail) was wrong: attempt (c) succeeded. Per the brief's explicit success path ("若 Task 6 Step 1 验证出真实包名/API，同步修改…"), I adapted `tencent_client.py` to the real SDK: module `tencentdb_agent_memory`, class `MemoryClient`, constructor **`(endpoint, api_key, service_id, *, session_id="default")`** (the real SDK has no `llm`/`storage_path`), recall via `search_atomic(query, limit=top_k)`, write via `add_conversation(session_id, messages)`. **Task 7 must construct with `endpoint`/`api_key`/`service_id` (and optionally `session_id`), not `llm`/`storage_dir`.**
2. **requirements.txt comment uses the verified name** `tencentdb-agent-memory-sdk-python-v2` instead of the brief's placeholder `tencentdb-agent-memory` (that name is known not to exist). Still comment-only and marked 待验证 — **PyPI availability/install method still unverified** (PyPI unreachable here; repo README says "发布后"), so no active line was added.
3. **`recall` maps SDK `type`/`content`/`score` fields with fallbacks** (`type→"scene"`, `content→""`, `score→0.0`) since the real `search_atomic` item schema has `{id, type, content, score, …}`; the exact score semantics (e.g. 0–1 vs distance) should be sanity-checked against a live Memory Core service.
4. Real SDK introduces a transitive dependency (`httpx>=0.24.0`) and requires a running Memory Core endpoint — deployment/ops impact for Task 7 to plan.
5. `tencent_llm.py` is written per the brief but the real v2.0.1 SDK's `MemoryClient` does not itself call an LLM via `chat()`; the adapter is retained for Task 7's pipeline use (and harmless if unused).

## 7. Report file

This report: `.superpowers/sdd/2026-08-26-tencent-memory-provider/task-6-report.md`

---

## 8. Controller follow-up fix (2026-08-26): delete tencent_llm.py dead code

**Controller finding (Important):** `internal/service/memory_provider/tencent_llm.py` is dead code and must be deleted. The controller independently verified the v2.0.1 tag source: `MemoryClient(endpoint, api_key, service_id)` is a pure HTTP client (httpx); the L0→L3 memory pipeline runs on the MemoryCore SERVER side and the SDK accepts no LLM. The brief's `TencentLlmAdapter` premise (SDK needs an LLM) is disproven; keeping the file violates YAGNI. Plan updated to remove it.

**Fix executed:**
1. Grep for `tencent_llm`/`TencentLlmAdapter` in `internal/` and `test/` → zero external references (only hit was the class definition inside the file itself). Confirmed dead code, nothing imports it.
2. `git rm internal/service/memory_provider/tencent_llm.py` → `rm 'internal/service/memory_provider/tencent_llm.py'`.
3. Re-ran focused tests:
   - `pytest test/internal/service/memory_provider/test_tencent_client.py -x -v` → `3 passed, 1 warning` (warning = known harmless PytestCacheWarning WinError 5)
   - `pytest test/internal/service/memory_provider/ -x` → `18 passed, 1 warning`
4. Commit: `refactor(memory): 删除 tencent_llm.py 死代码（v2 SDK 为纯 HTTP 客户端不接受 LLM）` (file was previously committed in 52fc079; `git rm` + commit in one step).
