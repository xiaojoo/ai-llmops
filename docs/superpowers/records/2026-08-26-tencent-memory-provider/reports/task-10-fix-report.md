# Task 10 — 最终全分支审查修复报告（记忆系统 Provider 化）

- 分支：`release_20260829`
- 提交：`ddb44f6` — `fix(memory): 最终审查修复——TENCENT_MEMORY_API_KEY 进 SENSITIVE_KEYS / ImportError 测试加固 / 清除死字段与无用导入`
- 变更：10 个文件，+20 / -10
- 环境：Python 3.12（项目 `venv`，`.\venv\Scripts\python.exe`）；SDK `tencentdb_agent_memory` 未安装（已确认 `find_spec` 返回 NOT_INSTALLED）

---

## C1（CRITICAL）— `TENCENT_MEMORY_API_KEY` 进 `SENSITIVE_KEYS`

**问题**：`internal/service/system_config_service.py` 的 `SENSITIVE_KEYS` 缺失该键，导致腾讯记忆 API Key 以明文入库、`GET /settings/config` 明文回显（handler 只掩码 SENSITIVE_KEYS 内的键），前端掩码依赖后端返回 `'********'`。

**修复**：`internal/service/system_config_service.py` — `SENSITIVE_KEYS` 集合末尾新增一行：

```python
    "API_KEY", "FEISHU_APP_ID", "FEISHU_APP_SECRET", "LLMOPS_ACCESS_TOKEN",
    "TENCENT_MEMORY_API_KEY",
}
```

修复后该键走既有加密路径：`save_configs` 中 `is_sensitive = key in SENSITIVE_KEYS` → `_encrypt_value` AES 加密入库、`is_encrypted=True`，读取时解密，GET 回显被 handler 掩码。**仅此一处运行时行为变更（预期修复）。**

**测试**：`test/internal/service/` 下无既有 `test_system_config_service.py`（glob 确认），新建 `test/internal/service/test_system_config_service.py`（不依赖 DB）：

- `test_tencent_memory_api_key_is_sensitive`：`assert "TENCENT_MEMORY_API_KEY" in SENSITIVE_KEYS`
- `test_tencent_memory_api_key_aes_round_trip`：`enc = SystemConfigService._encrypt_value("sk-secret")`；`assert enc != "sk-secret"`；`assert SystemConfigService._decrypt_value(enc) == "sk-secret"`

**证据**（focused 测试输出节选）：

```
======================== 41 passed, 1 warning in 0.17s ========================
```

（该次运行包含新测试文件，2/2 通过。）

---

## I1（IMPORTANT）— `test_missing_sdk_raises_import_error` 与 SDK 安装解耦

**问题**：`test/internal/service/memory_provider/test_tencent_client.py:20-22` 假设 SDK 未安装；一旦装上 SDK，构造不再抛 `ImportError`，测试即失效。

**修复**：测试签名增加 `monkeypatch`，开头 `monkeypatch.delitem(sys.modules, "tencentdb_agent_memory", raising=False)` 清除 sys.modules 缓存后再断言 `pytest.raises(ImportError)`：

```python
def test_missing_sdk_raises_import_error(monkeypatch):
    # 与 SDK 是否已安装解耦：先清掉 sys.modules 缓存，确保走真实 import 路径
    monkeypatch.delitem(sys.modules, "tencentdb_agent_memory", raising=False)
    with pytest.raises(ImportError):
        SdkTencentMemoryClient(endpoint="http://127.0.0.1:8420", api_key="sk-test", service_id="mem-test")
```

**证据**：全仓库 grep `tencentdb_agent_memory` 仅命中本测试文件自身（`_install_fake_sdk` 的 `monkeypatch.setitem`，自动清理），无其他来源把该模块塞进 `sys.modules`；当前环境 SDK 未安装（`find_spec` → NOT_INSTALLED），delitem 为无副作用守卫，测试通过。说明：若未来环境真实安装且可 import 该 SDK，仅靠 delitem 无法令 `ImportError` 成立——此为审查方指定修复方案，按方案原样落地；当前及 CI 现状（SDK 缺失）下测试稳定通过。

**证据**（focused 测试）：`memory_provider/` 全绿（见上 41 passed）。

---

## D1（dead code）— `AppService.user_memory_service` 死字段

**问题**：`internal/service/app_service.py` 保留 `user_memory_service: UserMemoryService` 字段（原 102 行）与 import（原 81 行），Task 4 已把该职责迁至 `MemoryProviderResolver` / `BuiltinMemoryProvider`，字段无人使用。

**修复**：

1. `internal/service/app_service.py`：删除 `from .user_memory_service import UserMemoryService` 与 `user_memory_service: UserMemoryService` 字段声明。
2. 三个直接构造 `AppService(...)` 并传 `user_memory_service=MagicMock()` 的测试移除该 kwarg：
   - `test/internal/service/test_app_service_draft_config.py`（`_build_service()`）
   - `test/internal/service/test_app_service_publish_orchestrator.py`（`_build_service()`）
   - `test/internal/service/test_app_logical_delete.py`（`APP_SERVICE_DEPS` 列表）
3. `test_app_logical_delete.py` 中 `WebAppService` 构造（87-91 行）本就未传 `user_memory_service`（grep 确认），仅保留 Task 4 已加的 `memory_provider_resolver=MagicMock()`，无改动。

**删除前验证（grep 证据）**：

- `grep user_memory_service|UserMemoryService internal/`：`app_service.py` 仅命中 import(81) + 字段(102) 两行；其余命中均为其他类的自有字段/依赖（`app_handler.py` 的 `AppHandler.user_memory_service`、`builtin_provider.py`、`memory_tools.py`、`__init__.py` 导出）——**无任何 `app_service.user_memory_service` / `web_app_service.user_memory_service` 引用**。
- `grep user_memory_service|UserMemoryService test/`：除上述三个构造点外，仅 `test_user_memory_service.py`（测 UserMemoryService 自身）与 `test_builtin_provider.py`（`provider.user_memory_service`，是 BuiltinMemoryProvider 的字段）——均不受影响。

`AppService`/`WebAppService` 为 `@inject` dataclass，删字段不影响 DI（injector 按剩余字段注入）；`WebAppService` 本身无该字段。

**证据**（focused 测试）：三个文件全绿（见上 41 passed，含 `test_app_logical_delete.py` 的 DB 用例）。

---

## D2（unused imports）— 三个测试文件无用导入

逐一 grep 确认仅 import 行命中、正文零使用后删除：

| 文件 | 删除 | grep 证据 |
|---|---|---|
| `test/internal/service/memory_provider/test_base.py` | `from uuid import UUID`（原第 4 行） | `UUID` 仅命中第 4 行 |
| `test/internal/service/memory_provider/test_resolver.py` | `from unittest.mock import MagicMock`（原第 3 行） | `MagicMock` 仅命中第 3 行 |
| `test/internal/service/memory_provider/test_tencent_provider.py` | `from unittest.mock import MagicMock`（原第 3 行） | `MagicMock` 仅命中第 3 行 |

---

## 测试

**Focused**（`-x` 优先，含新测试文件）：

```
.\venv\Scripts\python.exe -m pytest test/internal/service/memory_provider/ test/internal/service/test_system_config_service.py test/internal/service/test_app_service_draft_config.py test/internal/service/test_app_service_publish_orchestrator.py test/internal/service/test_app_logical_delete.py -x -q
======================== 41 passed, 1 warning in 0.17s ========================
```

（1 warning 为已知无害 `PytestCacheWarning: WinError 5`，忽略。）

**Full**：

```
.\venv\Scripts\python.exe -m pytest test/ -x -q
FAILED test/internal/service/test_episodic_memory_service.py::TestEpisodicSearch::test_search_fuses_and_ranks
================= 1 failed, 168 passed, 11 warnings in 21.26s =================
```

唯一失败 `test_episodic_memory_service.py::TestEpisodicSearch::test_search_fuses_and_ranks`（`test_episodic_memory_service.py:117: AssertionError`）为任务说明中预知的既有失败，与本批修复无关。

## 变更文件（10）

- `internal/service/system_config_service.py`（C1）
- `test/internal/service/test_system_config_service.py`（C1，新建）
- `test/internal/service/memory_provider/test_tencent_client.py`（I1）
- `internal/service/app_service.py`（D1）
- `test/internal/service/test_app_service_draft_config.py`（D1）
- `test/internal/service/test_app_service_publish_orchestrator.py`（D1）
- `test/internal/service/test_app_logical_delete.py`（D1）
- `test/internal/service/memory_provider/test_base.py`（D2）
- `test/internal/service/memory_provider/test_resolver.py`（D2）
- `test/internal/service/memory_provider/test_tencent_provider.py`（D2）

## 提交

- SHA：`ddb44f6`（`release_20260829`）
- 消息：`fix(memory): 最终审查修复——TENCENT_MEMORY_API_KEY 进 SENSITIVE_KEYS / ImportError 测试加固 / 清除死字段与无用导入`
- 10 files changed, 20 insertions(+), 10 deletions(-)

**说明**：未使用任务给定的字面 `git add -A internal test`（那会把既存未跟踪文件 `internal/migrations/versions/a1b2c3d4e5f6_add_message_agent_thought_trace.py` 一并纳入本提交）；该文件与本次四项修复无关，按"Do NOT touch anything else"保留未跟踪，仅显式暂存 10 个修复文件。

## 边界确认

- 无新增依赖、无 Python 版本变更；唯一运行时变更即 C1 的 API Key 加密（预期修复）。
- 前端仓库 `ai-code-llmops-web` 零改动。
- `.superpowers/sdd/2026-08-26-tencent-memory-provider/` 下仅新增本报告文件，未改动其他工件。
