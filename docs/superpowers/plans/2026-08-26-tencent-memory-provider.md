# 记忆系统 Provider 化（内置 / 腾讯可切换）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在系统设置中新增"记忆系统"选择（内置 / 腾讯 TencentDB-Agent-Memory），应用配置可覆盖；内置路径行为零变化，腾讯路径走腾讯 SDK 记忆流水线。

**Architecture:** 新增 `internal/service/memory_provider/`：`MemoryProvider` 抽象接口（`get_user_profile` / `get_read_context` / `get_memory_tools` / `trigger_write` 四方法，均携带 `app_config`）+ `BuiltinMemoryProvider`（现有三个记忆 service + MemoryTools 的薄封装）+ `TencentMemoryProvider`（懒加载腾讯 SDK，缺失自动回退）+ `MemoryProviderResolver`（应用 `long_term_memory.provider` > 系统 `MEMORY_PROVIDER` > builtin）。`ChatRunner` / `WebAppService` / `AppService` 五处记忆触达点统一走 provider。腾讯 SDK 差异全部隔离在 `tencent_client.py` 单文件内。

**Tech Stack:** Python 3.12 / Flask / injector / langchain-core / pytest（真实 Postgres + 事务回滚）；前端 Vue 3 + Arco Design（`ai-code-llmops-web`，yarn 构建）。

**Spec:** `docs/superpowers/specs/2026-08-26-tencent-memory-provider-design.md`

## Global Constraints

- Python 3.12；新增依赖仅允许腾讯记忆 SDK（包名/安装方式以 Task 6 验证为准），其余沿用 `requirements.txt` 既有包
- 数据库迁移使用 flask-migrate；本计划无新表（腾讯记忆用 SDK 本地存储，不落业务库）
- 测试遵循仓库模式：`test/conftest.py` 的 `db` fixture（真实 DB + 事务回滚）、`injector.get(Service)` 取真实服务、`monkeypatch` 替换 LLM/依赖
- 所有既有 HTTP 接口响应结构向后兼容：只允许新增字段
- `AgentConfig` / `AgentState` / SSE 事件格式保持兼容
- 每个 Task 结束运行 `pytest test/ -x`（或该任务指定用例）确认无回归后提交
- 提交到 `release_20260829` 分支（本计划已在分支上）
- **内置路径行为零变化**：情景召回不随 `enable` 门控（现状如此），记忆工具/程序记忆/写侧随 `enable` 门控——refactor 必须保留这两条语义

## File Structure

**后端新增（`internal/service/memory_provider/`）：**
- `base.py`：`MemoryProvider` ABC + `MemoryReadContext`（episodic_memory / procedural_instructions）
- `builtin_provider.py`：`BuiltinMemoryProvider`（含写侧两个抽取线程）
- `tencent_client.py`：`TencentMemoryClient` ABC + `SdkTencentMemoryClient`（唯一接触 SDK 的模块，懒加载）
- `tencent_llm.py`：`TencentLlmAdapter`（项目 BaseLanguageModel → SDK chat 接口）
- `tencent_provider.py`：`TencentMemoryProvider`
- `resolver.py`：`MemoryProviderResolver` + 常量 `BUILTIN`/`TENCENT`/`SYSTEM_MEMORY_PROVIDER_KEY`
- `__init__.py`：导出 `MemoryProvider`、`MemoryReadContext`、`BuiltinMemoryProvider`、`TencentMemoryProvider`、`MemoryProviderResolver`

**后端修改：**
- `internal/service/chat_runner.py`：移除记忆 service 字段，注入 resolver；读/写侧改走 provider；删除 `_trigger_memory_extraction` / `_trigger_episodic_extraction`
- `internal/service/web_app_service.py`：user_profile 走 provider；移除 `user_memory_service` 字段
- `internal/service/app_service.py`：`debug_chat` user_profile 走 provider；`long_term_memory` 校验放宽（Task 5）
- `internal/service/__init__.py`：末尾追加 memory_provider 导出
- `requirements.txt`：腾讯 SDK（Task 6 验证后）

**后端测试新增：**
- `test/internal/service/memory_provider/test_base.py`
- `test/internal/service/memory_provider/test_builtin_provider.py`
- `test/internal/service/memory_provider/test_resolver.py`
- `test/internal/service/memory_provider/test_tencent_provider.py`

**后端测试修改：**
- `test/internal/service/test_chat_runner.py`、`test_chat_runner_orchestrator.py`、`test_chat_error_handling.py`：记忆相关 monkeypatch 改为 stub resolver（Task 4）

**前端修改（`ai-code-llmops-web/`）：**
- `src/views/settings/SystemSettings.vue`：新增"记忆系统"tab + envConfig 两个键
- `src/views/settings/components/MemoryConfig.vue`：新增（Task 8）
- `src/views/space/apps/components/abilities/LongTermMemoryAbilityItem.vue`：记忆系统下拉（Task 9）
- `src/models/app.ts`：`long_term_memory` 补 `provider?`（Task 9）

---

## Task 1: MemoryProvider 抽象 + MemoryReadContext

**Files:**
- Create: `internal/service/memory_provider/__init__.py`
- Create: `internal/service/memory_provider/base.py`
- Test: `test/internal/service/memory_provider/test_base.py`

**Interfaces:**
- Produces（后续所有 Task 依赖的契约）:
  - `MemoryReadContext`（dataclass）: 字段 `episodic_memory: str = ""`、`procedural_instructions: str = ""`
  - `MemoryProvider`（ABC）: `get_user_profile(app_config: dict, app_id: UUID, user_id: UUID) -> str`；`get_read_context(app_config: dict, app_id: UUID, user_id: UUID, query: str) -> MemoryReadContext`；`get_memory_tools(app_config: dict, app_id: UUID, user_id: UUID) -> list`；`trigger_write(*, app_config: dict, app_id: UUID, user_id: UUID, query: str, answer: str) -> None`

- [ ] **Step 1: 写失败测试**

Create `test/internal/service/memory_provider/test_base.py`:

```python
#!/usr/bin/env python
"""MemoryProvider 抽象契约测试：ABC 方法签名 + MemoryReadContext 默认值"""
import pytest
from uuid import UUID

from internal.service.memory_provider.base import MemoryProvider, MemoryReadContext


def test_read_context_defaults_empty():
    ctx = MemoryReadContext()
    assert ctx.episodic_memory == ""
    assert ctx.procedural_instructions == ""


def test_provider_abstract_cannot_instantiate():
    with pytest.raises(TypeError):
        MemoryProvider()


def test_provider_requires_all_four_methods():
    """缺一个抽象方法就实例化失败（契约完整性的守卫）"""
    class Partial(MemoryProvider):
        def get_user_profile(self, app_config, app_id, user_id):
            return ""

    with pytest.raises(TypeError):
        Partial()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/memory_provider/test_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'internal.service.memory_provider'`

- [ ] **Step 3: 实现**

Create `internal/service/memory_provider/base.py`:

```python
#!/usr/bin/env python
"""记忆系统 Provider 抽象：MemoryProvider 接口 + MemoryReadContext"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass
class MemoryReadContext:
    """对话前注入 Agent 的记忆提示词块（情景记忆 + 程序记忆）"""
    episodic_memory: str = ""
    procedural_instructions: str = ""


class MemoryProvider(ABC):
    """记忆提供者：读侧（画像/情景/程序/工具）与写侧（对话后抽取）统一入口。

    四个方法均携带 app_config：内置实现忽略它；腾讯实现从中取 model_config 构建 LLM。
    """

    @abstractmethod
    def get_user_profile(self, app_config: dict, app_id: UUID, user_id: UUID) -> str:
        """语义记忆画像文本（<用户画像> 块）"""

    @abstractmethod
    def get_read_context(self, app_config: dict, app_id: UUID, user_id: UUID, query: str) -> MemoryReadContext:
        """对话前召回情景记忆与程序记忆"""

    @abstractmethod
    def get_memory_tools(self, app_config: dict, app_id: UUID, user_id: UUID) -> list:
        """Agent 可用的记忆工具列表（list[BaseTool]）"""

    @abstractmethod
    def trigger_write(self, *, app_config: dict, app_id: UUID, user_id: UUID, query: str, answer: str) -> None:
        """对话结束后异步执行记忆写侧管道（实现内部自行起子线程）"""
```

Create `internal/service/memory_provider/__init__.py`:

```python
#!/usr/bin/env python
"""记忆系统 Provider 包：抽象 + 内置/腾讯实现 + 解析器"""
from .base import MemoryProvider, MemoryReadContext

__all__ = ["MemoryProvider", "MemoryReadContext"]
```

（后续 Task 逐一向 `__init__.py` 追加导出。）

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/memory_provider/test_base.py -v`
Expected: PASS（3 个用例）

- [ ] **Step 5: 提交**

```bash
git add internal/service/memory_provider/ test/internal/service/memory_provider/
git commit -m "feat(memory): MemoryProvider 抽象接口与 MemoryReadContext"
```

---

## Task 2: BuiltinMemoryProvider（内置实现，行为零变化）

**Files:**
- Create: `internal/service/memory_provider/builtin_provider.py`
- Modify: `internal/service/memory_provider/__init__.py`（导出 BuiltinMemoryProvider）
- Test: `test/internal/service/memory_provider/test_builtin_provider.py`

**Interfaces:**
- Consumes: `UserMemoryService.get_current_facts(app_id, user_id, *, min_trust)`、`UserMemoryService._render_current_facts(facts)`、`EpisodicMemoryService.search_episodes(app_id, user_id, query, top_k=3)`（返回带 `.content` 的对象列表）、`ProceduralMemoryService.get_instructions(app_id, user_id) -> str`、`MemoryTools.get_tools(*, flask_app, app_id, user_id) -> list[BaseTool]`、`UserMemoryService.expire_overdue_facts / extract_user_facts(query, answer, current_profile) / upsert_facts`、`EpisodicMemoryService.get_recent_text / extract_episodes(query, answer, existing) / upsert_episodes`
- Produces: `BuiltinMemoryProvider(MemoryProvider)`（四个方法实现；内部 `_extract_user_facts` / `_extract_episodes` 写侧线程）

- [ ] **Step 1: 写失败测试**

Create `test/internal/service/memory_provider/test_builtin_provider.py`：

```python
#!/usr/bin/env python
"""BuiltinMemoryProvider 测试：四方法委托现有 service，行为与现状一致"""
from unittest.mock import MagicMock
from uuid import uuid4

from app.http.module import injector
from internal.service.memory_provider import BuiltinMemoryProvider
from internal.service.memory_provider.base import MemoryReadContext


class SyncThread:
    """测试替身：start() 时同步执行 target，避免子线程竞态"""
    def __init__(self, target=None, kwargs=None):
        self._target = target
        self._kwargs = kwargs or {}

    def start(self):
        self._target(**self._kwargs)


class TestBuiltinMemoryProvider:
    def test_get_user_profile_delegates_to_user_memory_service(self, app, monkeypatch):
        provider = injector.get(BuiltinMemoryProvider)
        app_id, user_id = uuid4(), uuid4()
        fake_facts = [MagicMock(fact_key="location", fact_value={"city": "北京"},
                                source="user_explicit", confidence=0.9)]
        monkeypatch.setattr(provider.user_memory_service, "get_current_facts",
                            lambda a, u, **kw: fake_facts)
        profile = provider.get_user_profile({"model_config": {}}, app_id, user_id)
        assert "location" in profile and "北京" in profile

    def test_get_read_context_episodic_and_procedural(self, app, monkeypatch):
        provider = injector.get(BuiltinMemoryProvider)
        app_id, user_id = uuid4(), uuid4()
        monkeypatch.setattr(provider.episodic_memory_service, "search_episodes",
                            lambda a, u, q, **kw: [MagicMock(content="用户正在准备搬家到北京")])
        monkeypatch.setattr(provider.procedural_memory_service, "get_instructions",
                            lambda a, u: "先给结论再给细节")
        ctx = provider.get_read_context({"model_config": {}}, app_id, user_id, "搬家")
        assert isinstance(ctx, MemoryReadContext)
        assert "用户正在准备搬家到北京" in ctx.episodic_memory
        assert ctx.procedural_instructions == "先给结论再给细节"

    def test_get_read_context_episodic_failure_keeps_procedural(self, app, monkeypatch):
        provider = injector.get(BuiltinMemoryProvider)
        app_id, user_id = uuid4(), uuid4()
        def boom(a, u, q, **kw):
            raise RuntimeError("weaviate down")
        monkeypatch.setattr(provider.episodic_memory_service, "search_episodes", boom)
        monkeypatch.setattr(provider.procedural_memory_service, "get_instructions",
                            lambda a, u: "规则还在")
        ctx = provider.get_read_context({"model_config": {}}, app_id, user_id, "q")
        assert ctx.episodic_memory == ""
        assert ctx.procedural_instructions == "规则还在"

    def test_get_memory_tools_returns_four_tools(self, app):
        provider = injector.get(BuiltinMemoryProvider)
        app_id, user_id = uuid4(), uuid4()
        with app.app_context():
            tools = provider.get_memory_tools({"model_config": {}}, app_id, user_id)
        assert {t.name for t in tools} == {"search_memory", "write_memory", "update_memory", "forget_memory"}

    def test_trigger_write_spawns_two_extraction_threads(self, app, monkeypatch):
        provider = injector.get(BuiltinMemoryProvider)
        app_id, user_id = uuid4(), uuid4()
        monkeypatch.setattr("internal.service.memory_provider.builtin_provider.Thread", SyncThread)
        calls = []
        monkeypatch.setattr(provider, "_extract_user_facts", lambda **kw: calls.append(("facts", kw)))
        monkeypatch.setattr(provider, "_extract_episodes", lambda **kw: calls.append(("episodes", kw)))
        with app.app_context():
            provider.trigger_write(app_config={"model_config": {}}, app_id=app_id,
                                   user_id=user_id, query="你好", answer="你好！")
        assert len(calls) == 2
        assert {c[0] for c in calls} == {"facts", "episodes"}
        assert all(c[1]["app_id"] == app_id and c[1]["user_id"] == user_id for c in calls)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/memory_provider/test_builtin_provider.py -v`
Expected: FAIL with `ImportError: cannot import name 'BuiltinMemoryProvider'`

- [ ] **Step 3: 实现**

Create `internal/service/memory_provider/builtin_provider.py`：

```python
#!/usr/bin/env python
"""内置记忆提供者：现有语义/情景/程序记忆的薄封装，行为与现状完全一致"""
import logging
from dataclasses import dataclass
from threading import Thread
from uuid import UUID

from flask import current_app
from injector import inject

from internal.core.tools.memory_tools import MemoryTools
from internal.service.episodic_memory_service import EpisodicMemoryService
from internal.service.procedural_memory_service import ProceduralMemoryService
from internal.service.user_memory_service import UserMemoryService

from .base import MemoryProvider, MemoryReadContext

logger = logging.getLogger(__name__)


@inject
@dataclass
class BuiltinMemoryProvider(MemoryProvider):
    """内置记忆系统：委托现有三个记忆 service 与 MemoryTools，行为零变化"""
    user_memory_service: UserMemoryService
    episodic_memory_service: EpisodicMemoryService
    procedural_memory_service: ProceduralMemoryService
    memory_tools: MemoryTools

    def get_user_profile(self, app_config: dict, app_id: UUID, user_id: UUID) -> str:
        return self.user_memory_service._render_current_facts(
            self.user_memory_service.get_current_facts(app_id, user_id, min_trust=0.3)
        )

    def get_read_context(self, app_config: dict, app_id: UUID, user_id: UUID, query: str) -> MemoryReadContext:
        ctx = MemoryReadContext()
        try:
            episodes = self.episodic_memory_service.search_episodes(app_id, user_id, query, top_k=3)
            ctx.episodic_memory = "\n".join(f"- {e.content}" for e in episodes)
        except Exception:
            logger.exception("情景记忆召回失败")
        ctx.procedural_instructions = self.procedural_memory_service.get_instructions(app_id, user_id)
        return ctx

    def get_memory_tools(self, app_config: dict, app_id: UUID, user_id: UUID) -> list:
        return self.memory_tools.get_tools(
            flask_app=current_app._get_current_object(),
            app_id=app_id,
            user_id=user_id,
        )

    def trigger_write(self, *, app_config: dict, app_id: UUID, user_id: UUID, query: str, answer: str) -> None:
        """写侧管道：起两个子线程（用户特征抽取 + 情景经历抽取），与现状一致"""
        flask_app = current_app._get_current_object()
        Thread(
            target=self._extract_user_facts,
            kwargs={"flask_app": flask_app, "app_id": app_id, "user_id": user_id,
                    "query": query, "answer": answer},
        ).start()
        Thread(
            target=self._extract_episodes,
            kwargs={"flask_app": flask_app, "app_id": app_id, "user_id": user_id,
                    "query": query, "answer": answer},
        ).start()

    def _extract_user_facts(self, *, flask_app, app_id, user_id, query, answer) -> None:
        """写侧管道：从本轮对话抽取用户特征并写入语义记忆（子线程，仅持纯值）"""
        with flask_app.app_context():
            try:
                self.user_memory_service.expire_overdue_facts(app_id, user_id)
                current_facts = self.user_memory_service.get_current_facts(app_id, user_id)
                current_profile = self.user_memory_service._render_current_facts(current_facts)
                extracted = self.user_memory_service.extract_user_facts(query, answer, current_profile)
                if extracted:
                    self.user_memory_service.upsert_facts(app_id, user_id, extracted)
            except Exception:
                logger.exception("用户特征抽取写入失败，app_id=%s, user_id=%s", app_id, user_id)

    def _extract_episodes(self, *, flask_app, app_id, user_id, query, answer) -> None:
        """情景记忆写侧管道：从本轮对话抽取经历并向量入库（子线程，仅持纯值）"""
        with flask_app.app_context():
            try:
                existing = self.episodic_memory_service.get_recent_text(app_id, user_id)
                episodes = self.episodic_memory_service.extract_episodes(query, answer, existing)
                if episodes:
                    self.episodic_memory_service.upsert_episodes(app_id, user_id, episodes)
            except Exception:
                logger.exception("情景记忆抽取写入失败，app_id=%s, user_id=%s", app_id, user_id)
```

Append to `internal/service/memory_provider/__init__.py`:

```python
from .base import MemoryProvider, MemoryReadContext
from .builtin_provider import BuiltinMemoryProvider

__all__ = ["MemoryProvider", "MemoryReadContext", "BuiltinMemoryProvider"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/memory_provider/test_builtin_provider.py -v`
Expected: PASS（5 个用例）

- [ ] **Step 5: 提交**

```bash
git add internal/service/memory_provider/ test/internal/service/memory_provider/
git commit -m "feat(memory): BuiltinMemoryProvider 内置实现（行为零变化）"
```

---

## Task 3: MemoryProviderResolver（应用覆盖 > 系统默认 > builtin）

**Files:**
- Create: `internal/service/memory_provider/resolver.py`
- Modify: `internal/service/memory_provider/__init__.py`（导出 MemoryProviderResolver、常量）
- Modify: `internal/service/__init__.py`（末尾追加 `from .memory_provider import MemoryProviderResolver`）
- Test: `test/internal/service/memory_provider/test_resolver.py`

**Interfaces:**
- Consumes: `SystemConfigService.get_config(key) -> str`（DB > 环境变量 > 空）；`BuiltinMemoryProvider`（Task 2）
- Produces: `MemoryProviderResolver`（@inject dataclass）；`resolve(app_config: dict) -> MemoryProvider`；常量 `BUILTIN = "builtin"`、`TENCENT = "tencent"`、`SYSTEM_MEMORY_PROVIDER_KEY = "MEMORY_PROVIDER"`

- [ ] **Step 1: 写失败测试**

Create `test/internal/service/memory_provider/test_resolver.py`：

```python
#!/usr/bin/env python
"""MemoryProviderResolver 优先级测试：应用覆盖 > 系统默认 > builtin"""
from unittest.mock import MagicMock

from app.http.module import injector
from internal.service.memory_provider import (
    BuiltinMemoryProvider, MemoryProviderResolver, TencentMemoryProvider,
)
from internal.service.memory_provider.resolver import BUILTIN, TENCENT

BASE_CONFIG = {"long_term_memory": {"enable": True}}


def _make_resolver(monkeypatch, system_value=""):
    resolver = injector.get(MemoryProviderResolver)
    monkeypatch.setattr(resolver.system_config_service, "get_config",
                        lambda key: system_value if key == "MEMORY_PROVIDER" else "")
    return resolver


class TestResolver:
    def test_defaults_to_builtin(self, monkeypatch):
        resolver = _make_resolver(monkeypatch)
        assert isinstance(resolver.resolve(BASE_CONFIG), BuiltinMemoryProvider)

    def test_system_tencent(self, monkeypatch):
        resolver = _make_resolver(monkeypatch, system_value=TENCENT)
        assert isinstance(resolver.resolve(BASE_CONFIG), TencentMemoryProvider)

    def test_app_override_tencent_beats_system_builtin(self, monkeypatch):
        resolver = _make_resolver(monkeypatch, system_value=BUILTIN)
        config = {"long_term_memory": {"enable": True, "provider": TENCENT}}
        assert isinstance(resolver.resolve(config), TencentMemoryProvider)

    def test_app_default_follows_system(self, monkeypatch):
        resolver = _make_resolver(monkeypatch, system_value=TENCENT)
        config = {"long_term_memory": {"enable": True, "provider": "default"}}
        assert isinstance(resolver.resolve(config), TencentMemoryProvider)

    def test_invalid_system_value_falls_back_to_builtin(self, monkeypatch):
        resolver = _make_resolver(monkeypatch, system_value="unknown")
        assert isinstance(resolver.resolve(BASE_CONFIG), BuiltinMemoryProvider)

    def test_invalid_app_provider_falls_back_to_system(self, monkeypatch):
        resolver = _make_resolver(monkeypatch, system_value=TENCENT)
        config = {"long_term_memory": {"enable": True, "provider": "bad"}}
        assert isinstance(resolver.resolve(config), TencentMemoryProvider)

    def test_missing_long_term_memory_config(self, monkeypatch):
        resolver = _make_resolver(monkeypatch)
        assert isinstance(resolver.resolve({}), BuiltinMemoryProvider)
```

（注：`TencentMemoryProvider` 尚不存在，本测试在 Task 3 会 ImportError——本任务先建最小 `tencent_provider.py` 骨架（仅类与四方法 `NotImplementedError`），让 resolver 分支可测，Task 7 填充真实实现。）

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/memory_provider/test_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: 实现**

Create `internal/service/memory_provider/tencent_provider.py`（Task 3 骨架，Task 7 填充）：

```python
#!/usr/bin/env python
"""腾讯记忆提供者：包装 TencentDB-Agent-Memory（懒加载）。Task 7 填充实现。"""
import logging
from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.service.language_model_service import LanguageModelService
from internal.service.system_config_service import SystemConfigService

from .base import MemoryProvider, MemoryReadContext

logger = logging.getLogger(__name__)


@inject
@dataclass
class TencentMemoryProvider(MemoryProvider):
    """腾讯记忆提供者：实现见 Task 7"""
    language_model_service: LanguageModelService
    system_config_service: SystemConfigService

    def get_user_profile(self, app_config: dict, app_id: UUID, user_id: UUID) -> str:
        raise NotImplementedError("Task 7 填充")

    def get_read_context(self, app_config: dict, app_id: UUID, user_id: UUID, query: str) -> MemoryReadContext:
        raise NotImplementedError("Task 7 填充")

    def get_memory_tools(self, app_config: dict, app_id: UUID, user_id: UUID) -> list:
        raise NotImplementedError("Task 7 填充")

    def trigger_write(self, *, app_config: dict, app_id: UUID, user_id: UUID, query: str, answer: str) -> None:
        raise NotImplementedError("Task 7 填充")
```

Create `internal/service/memory_provider/resolver.py`：

```python
#!/usr/bin/env python
"""记忆系统 Provider 解析器：应用配置 > 系统默认 > builtin"""
import logging
from dataclasses import dataclass

from injector import inject

from internal.service.system_config_service import SystemConfigService

from .base import MemoryProvider
from .builtin_provider import BuiltinMemoryProvider
from .tencent_provider import TencentMemoryProvider

logger = logging.getLogger(__name__)

BUILTIN = "builtin"
TENCENT = "tencent"
SYSTEM_MEMORY_PROVIDER_KEY = "MEMORY_PROVIDER"


@inject
@dataclass
class MemoryProviderResolver:
    system_config_service: SystemConfigService
    builtin_provider: BuiltinMemoryProvider
    tencent_provider: TencentMemoryProvider

    def resolve(self, app_config: dict) -> MemoryProvider:
        # 1) 应用覆盖：long_term_memory.provider（default/缺失则跟随系统）
        long_term_memory = app_config.get("long_term_memory") or {}
        provider = long_term_memory.get("provider")
        if provider == BUILTIN:
            return self.builtin_provider
        if provider == TENCENT:
            return self.tencent_provider
        # 2) 系统默认：MEMORY_PROVIDER（DB > 环境变量 > 空）
        system_provider = self.system_config_service.get_config(SYSTEM_MEMORY_PROVIDER_KEY)
        if system_provider == TENCENT:
            return self.tencent_provider
        if system_provider and system_provider != BUILTIN:
            logger.warning("未知 MEMORY_PROVIDER=%s，回退内置记忆系统", system_provider)
        # 3) 缺省 builtin
        return self.builtin_provider
```

Update `internal/service/memory_provider/__init__.py`:

```python
from .base import MemoryProvider, MemoryReadContext
from .builtin_provider import BuiltinMemoryProvider
from .tencent_provider import TencentMemoryProvider
from .resolver import MemoryProviderResolver

__all__ = [
    "MemoryProvider", "MemoryReadContext", "BuiltinMemoryProvider",
    "TencentMemoryProvider", "MemoryProviderResolver",
]
```

Update `internal/service/__init__.py`：在文件末尾（`reflection_service` 导入之后、`__all__` 之前）追加：

```python
from .memory_provider import MemoryProviderResolver
```

并在 `__all__` 列表追加 `"MemoryProviderResolver"`。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/memory_provider/test_resolver.py -v`
Expected: PASS（7 个用例）
Run: `pytest test/internal/service/memory_provider/ -x`
Expected: PASS（Task 1-3 全部用例）

- [ ] **Step 5: 提交**

```bash
git add internal/service/memory_provider/ internal/service/__init__.py test/internal/service/memory_provider/
git commit -m "feat(memory): MemoryProviderResolver 优先级解析（应用>系统>builtin）"
```

---

## Task 4: 接入点改造（chat_runner / web_app_service / app_service）+ 测试更新

**Files:**
- Modify: `internal/service/chat_runner.py`
- Modify: `internal/service/web_app_service.py`
- Modify: `internal/service/app_service.py`（仅 debug_chat user_profile；校验改动在 Task 5）
- Modify: `test/internal/service/test_chat_runner.py`
- Modify: `test/internal/service/test_chat_runner_orchestrator.py`
- Modify: `test/internal/service/test_chat_error_handling.py`
- Test: `test/internal/service/test_chat_runner.py`（新增 provider 透传用例）

**Interfaces:**
- Consumes: `MemoryProviderResolver`（Task 3）；`MemoryProvider` 四方法（Task 1）
- Produces: `ChatRunner` 新字段 `memory_provider_resolver: MemoryProviderResolver`；`_stream_and_persist` 新增参数 `memory_provider=None`；`WebAppService` / `AppService` 新字段 `memory_provider_resolver`

- [ ] **Step 1: 改 chat_runner.py（实现）**

1.1 导入区：删除 `from internal.core.tools.memory_tools import MemoryTools`、`from .episodic_memory_service import EpisodicMemoryService`、`from .procedural_memory_service import ProceduralMemoryService`、`from .user_memory_service import UserMemoryService`，追加：

```python
from .memory_provider import MemoryProvider, MemoryProviderResolver
```

1.2 字段：`ChatRunner` dataclass 中删除 `user_memory_service` / `episodic_memory_service` / `procedural_memory_service` / `memory_tools`，追加：

```python
    memory_provider_resolver: MemoryProviderResolver
```

1.3 `run()` 开头（`llm` 加载之后、情景召回之前）解析 provider：

```python
        # 2、短期记忆：窗口快满时先惰性压缩（归档最旧轮次并入滚动摘要）
        self.conversation_service.compact_if_needed(conversation.id, llm)
        history = self._build_history(llm, conversation, app_config["dialog_round"])

        # 2.0、解析记忆系统 Provider（应用覆盖 > 系统默认 > builtin）
        memory_provider = self.memory_provider_resolver.resolve(app_config)

        # 2.1、情景记忆：对话前按当前提问召回 top-k 经历（现状：不随 enable 门控）
        read_ctx = None
        if not episodic_memory:
            try:
                read_ctx = memory_provider.get_read_context(
                    app_config, conversation.app_id, account.id, message.query,
                )
                episodic_memory = read_ctx.episodic_memory
            except Exception:
                logger.exception("情景记忆召回失败")
```

1.4 工具/程序记忆段（原 3.1 / 3.2）替换为：

```python
        # 3.1、长期记忆开启时注入记忆工具（Agent 主动读写记忆）
        enable_memory = app_config.get("long_term_memory", {}).get("enable")
        if enable_memory:
            tools.extend(memory_provider.get_memory_tools(
                app_config, conversation.app_id, account.id,
            ))
        # 3.2、程序记忆（行为规则/人设）渲染文本
        if enable_memory:
            if read_ctx is None:
                try:
                    read_ctx = memory_provider.get_read_context(
                        app_config, conversation.app_id, account.id, message.query,
                    )
                except Exception:
                    logger.exception("程序记忆读取失败")
            procedural_instructions = read_ctx.procedural_instructions if read_ctx else ""
```

（删除原来的 `procedural_instructions = (... if enable_memory else "")` 赋值，参数名保持 `procedural_instructions` 不变。）

1.5 `_stream_and_persist` 签名追加参数 `memory_provider: MemoryProvider | None = None`（放在 `procedural_instructions` 之后）：

```python
            user_profile: str,
            episodic_memory: str = "",
            procedural_instructions: str = "",
            memory_provider: MemoryProvider | None = None,
```

1.6 `run()` 调用 `_stream_and_persist` 时追加 `memory_provider=memory_provider`。

1.7 `_stream_and_persist` 写侧（原两段 `if app_config.get("long_term_memory", {}).get("enable"): Thread(...)` 删除）替换为：

```python
            # 12、长期记忆开启时，异步触发记忆写侧管道（由 Provider 实现，线程内仅持纯值）
            if memory_provider is not None:
                memory_provider.trigger_write(
                    app_config=app_config,
                    app_id=app.id,
                    user_id=account.id,
                    query=message.query,
                    answer=message.answer,
                )
```

1.8 删除 `_trigger_memory_extraction` / `_trigger_episodic_extraction` 两个方法（连同 `from threading import Thread` 若不再使用——`Thread` 已迁入 BuiltinMemoryProvider，chat_runner 不再需要）。

- [ ] **Step 2: 改 web_app_service.py（实现）**

2.1 导入：删除 `from .user_memory_service import UserMemoryService`，追加 `from .memory_provider import MemoryProviderResolver`。
2.2 字段：删除 `user_memory_service: UserMemoryService`，追加 `memory_provider_resolver: MemoryProviderResolver`。
2.3 第 121-124 行替换为：

```python
        # 4、加载用户画像（语义记忆：当前有效事实 -> 画像文本）
        user_profile = self.memory_provider_resolver.resolve(app_config).get_user_profile(
            app_config, app.id, account.id,
        )
```

- [ ] **Step 3: 改 app_service.py（实现）**

3.1 字段：在 `AppService` dataclass 追加 `memory_provider_resolver: MemoryProviderResolver`（`user_memory_service` 保留——458/472 行仍使用）。
3.2 `debug_chat` 第 555-558 行替换为：

```python
        # 3、加载用户画像（语义记忆：当前有效事实 -> 画像文本）
        user_profile = self.memory_provider_resolver.resolve(draft_app_config).get_user_profile(
            draft_app_config, app_id, account.id,
        )
```

3.3 由于 `AppService` 新增 `memory_provider_resolver` 字段，两个**直接构造 `AppService(...)`** 的测试文件的 `_build_service()` 必须同步补字段（否则 dataclass 构造报缺参）：
- `test/internal/service/test_app_service_draft_config.py` `_build_service()` 的 `AppService(...)` 调用追加 `memory_provider_resolver=MagicMock(),`
- `test/internal/service/test_app_service_publish_orchestrator.py` `_build_service()` 同样追加

- [ ] **Step 4: 更新受影响测试（先改后跑）**

4.1 `test/internal/service/test_chat_runner.py`：模块级追加 StubProvider、导入与 SimpleNamespace：

```python
from types import SimpleNamespace

from internal.service.memory_provider.base import MemoryReadContext


class StubProvider:
    """记忆 Provider 测试替身：可控读侧/写侧行为"""
    def __init__(self, *, user_profile="", episodic_memory="", procedural_instructions="", tools=None):
        self.user_profile = user_profile
        self.episodic_memory = episodic_memory
        self.procedural_instructions = procedural_instructions
        self.tools = tools or []
        self.triggered = None

    def get_user_profile(self, app_config, app_id, user_id):
        return self.user_profile

    def get_read_context(self, app_config, app_id, user_id, query):
        return MemoryReadContext(
            episodic_memory=self.episodic_memory,
            procedural_instructions=self.procedural_instructions,
        )

    def get_memory_tools(self, app_config, app_id, user_id):
        return self.tools

    def trigger_write(self, **kwargs):
        self.triggered = kwargs
```

4.2 逐用例替换（搜索旧 monkeypatch 行，替换为下面两行的组合）：

- `test_run_streams_sse_and_persists`（第 70 行 `runner.episodic_memory_service.search_episodes`）→
  `monkeypatch.setattr(runner.memory_provider_resolver, "resolve", lambda app_config: StubProvider())`
- `test_run_passes_user_profile_to_agent`（第 105 行）→ 同上
- `test_run_passes_episodic_memory_to_agent`（第 148-153 行）→

```python
        stub = StubProvider(episodic_memory="用户正在准备搬家到北京")
        monkeypatch.setattr(runner.memory_provider_resolver, "resolve", lambda app_config: stub)
```

- `test_extraction_triggered_after_stream`（第 193-205 行 `search_episodes` / `get_instructions` / `Thread` / `_trigger_*` 四段 monkeypatch）→

```python
        # 写侧管道由 Provider 承担：stub trigger_write 捕获纯值参数
        stub = StubProvider()
        monkeypatch.setattr(runner.memory_provider_resolver, "resolve", lambda app_config: stub)
```

  并将断言段（第 220-226 行）改为：

```python
        assert stub.triggered is not None
        assert stub.triggered.get("app_config", {}).get("long_term_memory", {}).get("enable") is True
        # I-1：抽取线程只收纯值，不再持有请求线程的 ORM 对象
        assert "conversation" not in stub.triggered and "message" not in stub.triggered
        assert stub.triggered.get("app_id") == mock_app.id
        assert stub.triggered.get("user_id") == account.id
        assert stub.triggered.get("query") == message.query
        assert stub.triggered.get("answer") is not None
```

  （`SyncThread` 类与 `internal.service.chat_runner.Thread` 的 monkeypatch 一并删除——线程逻辑已迁入 BuiltinMemoryProvider，本用例不再涉及。）

- `test_tools_injected_when_long_term_memory_enabled`（第 241-246、259-262 行）→

```python
        stub = StubProvider(
            procedural_instructions="回答用户时先给结论再给细节",
            tools=[SimpleNamespace(name=n) for n in
                   ("search_memory", "write_memory", "update_memory", "forget_memory")],
        )
        monkeypatch.setattr(runner.memory_provider_resolver, "resolve", lambda app_config: stub)
```

4.3 `test/internal/service/test_chat_runner_orchestrator.py`：第 62 行 `runner.episodic_memory_service.search_episodes` 替换为：

```python
    monkeypatch.setattr(runner.memory_provider_resolver, "resolve", lambda app_config: StubProvider())
```

文件顶部追加（紧随 imports）：

```python
from internal.service.memory_provider.base import MemoryReadContext


class StubProvider:
    def get_user_profile(self, app_config, app_id, user_id):
        return ""

    def get_read_context(self, app_config, app_id, user_id, query):
        return MemoryReadContext()

    def get_memory_tools(self, app_config, app_id, user_id):
        return []

    def trigger_write(self, **kwargs):
        return None
```

4.4 `test/internal/service/test_chat_error_handling.py`：第 81 行替换为：

```python
        monkeypatch.setattr(
            service.chat_runner.memory_provider_resolver, "resolve",
            lambda app_config: StubProvider(),
        )
```

文件顶部追加与 4.3 相同的 `StubProvider` 定义。

- [ ] **Step 5: 新增 provider 透传用例（追加到 test_chat_runner.py 末尾）**

```python
class TestChatRunnerMemoryProvider:
    def test_run_reads_and_writes_through_resolved_provider(self, app, monkeypatch):
        runner = injector.get(ChatRunner)
        account = MagicMock(id=uuid4())
        conversation = MagicMock(id=uuid4(), summary="")
        message = MagicMock(id=uuid4(), query="北京天气怎么样", image_urls=[])

        monkeypatch.setattr(runner.language_model_service, "load_language_model", lambda cfg: FakeLLM())
        monkeypatch.setattr(runner.app_config_service, "get_langchain_tools_by_tools_config", lambda cfg: [])
        monkeypatch.setattr(runner, "_build_history", lambda llm, conv, r: [])
        monkeypatch.setattr(runner.conversation_service, "compact_if_needed", lambda *a, **k: False)
        monkeypatch.setattr(runner.conversation_service, "save_agent_thoughts", lambda **kw: None)

        stub = StubProvider(
            episodic_memory="用户正在准备搬家到北京",
            procedural_instructions="先给结论",
            tools=[SimpleNamespace(name="search_memory")],
        )
        monkeypatch.setattr(runner.memory_provider_resolver, "resolve", lambda app_config: stub)

        captured = {}
        class CapturingAgent(FakeAgent):
            def stream(self, *args, **kwargs):
                captured["input"] = args[0] if args else kwargs.get("input")
                yield from super().stream(*args, **kwargs)

        monkeypatch.setattr("internal.service.chat_runner.FunctionCallAgent", CapturingAgent)

        config = dict(MOCK_CONFIG)
        config["long_term_memory"] = {"enable": True}

        with app.app_context():
            list(runner.run(
                app=MagicMock(id=uuid4()),
                app_config=config,
                conversation=conversation,
                message=message,
                account=account,
                invoke_from=InvokeFrom.WEB_APP,
            ))

        assert "用户正在准备搬家到北京" in captured["input"].get("episodic_memory", "")
        assert captured["input"].get("procedural_instructions") == "先给结论"
        assert stub.triggered is not None
        assert stub.triggered.get("app_id") is not None
```

（`from types import SimpleNamespace` 已在 4.1 加入文件顶部。）

- [ ] **Step 6: 运行测试**

Run: `pytest test/internal/service/test_chat_runner.py test/internal/service/test_chat_runner_orchestrator.py test/internal/service/test_chat_error_handling.py -x -v`
Expected: PASS（含新增用例）

- [ ] **Step 7: 全量回归**

Run: `pytest test/ -x`
Expected: PASS（如有个别用例因注入字段变化报错，按 4.2-4.4 同法 stub resolver 后复跑）

- [ ] **Step 8: 提交**

```bash
git add internal/service/ test/internal/service/
git commit -m "feat(memory): chat_runner/web_app_service/app_service 接入 MemoryProvider"
```

---

## Task 5: 应用配置校验更新（long_term_memory.provider）

**Files:**
- Modify: `internal/service/app_service.py:996-1000`
- Modify: `test/internal/service/test_app_service_draft_config.py`
- Test: `test/internal/service/memory_provider/`（新增校验用例，或并入 test_app_service_draft_config.py）

**Interfaces:**
- Consumes: `AppService` 草稿配置校验方法（`_validate_draft_app_config` 相关，位于 `app_service.py` 989-1000）
- Produces: `long_term_memory` 合法键集 `{enable, provider}`；`provider ∈ {default, builtin, tencent}`

- [ ] **Step 1: 写失败测试**

在 `test/internal/service/test_app_service_draft_config.py` 末尾追加（沿用该文件的 `_build_service()` + `_validate_draft_app_config(payload, MagicMock())` 模式，方法签名为 `_validate_draft_app_config(draft_app_config, account)`，位于 `app_service.py:678`）：

```python
class TestLongTermMemoryProviderValidation:
    def test_validate_accepts_provider_tencent(self):
        svc = _build_service()
        payload = {"long_term_memory": {"enable": True, "provider": "tencent"}}
        result = svc._validate_draft_app_config(payload, MagicMock())
        assert result == payload

    def test_validate_accepts_provider_builtin(self):
        svc = _build_service()
        payload = {"long_term_memory": {"enable": False, "provider": "builtin"}}
        result = svc._validate_draft_app_config(payload, MagicMock())
        assert result == payload

    def test_validate_accepts_enable_only_still_valid(self):
        """存量格式（仅 enable）保持兼容"""
        svc = _build_service()
        payload = {"long_term_memory": {"enable": True}}
        result = svc._validate_draft_app_config(payload, MagicMock())
        assert result == payload

    def test_validate_rejects_unknown_provider(self):
        svc = _build_service()
        with pytest.raises(ValidateException):
            svc._validate_draft_app_config(
                {"long_term_memory": {"enable": True, "provider": "unknown"}}, MagicMock(),
            )

    def test_validate_rejects_missing_enable(self):
        """enable 必填：只有 provider 不合法"""
        svc = _build_service()
        with pytest.raises(ValidateException):
            svc._validate_draft_app_config(
                {"long_term_memory": {"provider": "tencent"}}, MagicMock(),
            )
```

（`ValidateException` 已在文件顶部导入。）

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_app_service_draft_config.py::TestLongTermMemoryProviderValidation -v`
Expected: FAIL（`provider` 键触发"长期记忆设置格式错误"）

- [ ] **Step 3: 实现**

`app_service.py` 989-1000 替换为：

```python
        # 10、校验long_term_memory长期记忆配置
        if "long_term_memory" in draft_app_config:
            long_term_memory = draft_app_config["long_term_memory"]
            # 10.1 校验长期记忆格式（键集 {enable, provider}，enable 必填布尔）
            if not long_term_memory or not isinstance(long_term_memory, dict):
                raise ValidateException("长期记忆设置格式错误")
            keys = set(long_term_memory.keys())
            if (
                    not {"enable"} <= keys <= {"enable", "provider"}
                    or not isinstance(long_term_memory["enable"], bool)
            ):
                raise ValidateException("长期记忆设置格式错误")
            # 10.2 校验记忆系统取值（default/builtin/tencent）
            provider = long_term_memory.get("provider", "default")
            if provider not in ("default", "builtin", "tencent"):
                raise ValidateException("长期记忆记忆系统设置错误")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_app_service_draft_config.py -x -v`
Expected: PASS
Run: `pytest test/ -x`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/service/app_service.py test/internal/service/test_app_service_draft_config.py
git commit -m "feat(memory): 应用配置校验支持 long_term_memory.provider（default/builtin/tencent）"
```

---

## Task 6: 腾讯 SDK 验证 + TencentMemoryClient + LLM 适配器 + 依赖

**Files:**
- Create: `internal/service/memory_provider/tencent_client.py`
- ~~Create: `internal/service/memory_provider/tencent_llm.py`~~ **（删除——真实 v2 SDK 为纯 HTTP 客户端不接受 LLM，适配器是死代码，controller ruling 2026-08-26）**
- Modify: `requirements.txt`（腾讯 SDK 注释占位行）
- Test: `test/internal/service/memory_provider/test_tencent_client.py`

**Interfaces:**
- Produces（Task 7 依赖）:
  - `TencentMemoryClient`（ABC）: `recall(query: str, top_k: int = 5) -> list[dict]`（元素 `{type, content, score}`）；`write_round(query: str, answer: str) -> None`
  - `SdkTencentMemoryClient(TencentMemoryClient)`：懒加载 `from tencentdb_agent_memory import MemoryClient`；构造 `(endpoint, api_key, service_id, *, session_id="default")`；SDK 缺失时构造抛 `ImportError`（已验证 v2.0.1 真实 API：`search_atomic(query, limit)` / `add_conversation(session_id, messages)`）

- [ ] **Step 1: 验证 SDK 获取方式（尽力而为，不阻塞）**

依次执行（按顺序，第一个成功即停）：

```bash
# a) PyPI 官方源
pip index versions tencentdb-agent-memory
# b) 腾讯云 PyPI 镜像（项目 Docker 构建源）
pip index versions tencentdb-agent-memory -i https://mirrors.tencent.com/pypi/simple --trusted-host mirrors.tencent.com
# c) GitHub 可达性
git ls-remote https://github.com/TencentCloud/TencentDB-Agent-Memory.git
```

结果处理：
- 成功（得到包名/版本或仓库可达）→ 按 SDK 实际 README / 源码确认：安装方式、初始化类名与参数（LLM 接口、存储路径参数）、召回与写入方法签名。把验证结果写进本 Task 的提交说明。
- 全部失败（本环境无外网）→ 记录"SDK 获取待用户机器验证"，本 Task 继续用**假 SDK 模块**实现与测试；`SdkTencentMemoryClient` 保持"SDK 缺失抛 ImportError"的安全态（运行时会话由 `TencentMemoryProvider` 回退，见 Task 7）。提交说明里标注「待验证」。
- **无论验证结果如何：本文件 `tencent_client.py` 是唯一接触 SDK 的模块，SDK API 与下列代码不一致时仅改本文件方法体（类名/方法名/参数），`recall` / `write_round` 接口与 `TencentMemoryProvider` 保持不变。**

- [ ] **Step 2: 写失败测试（假 SDK 模块）**

Create `test/internal/service/memory_provider/test_tencent_client.py`：

```python
#!/usr/bin/env python
"""SdkTencentMemoryClient 测试：用假 SDK 模块验证懒加载与接口形态（SDK 差异隔离点）"""
import sys
import types
from unittest.mock import MagicMock

import pytest

from internal.service.memory_provider.tencent_client import SdkTencentMemoryClient


def _install_fake_sdk(monkeypatch):
    """向 sys.modules 注入假 agent_memory 模块（SDK 未安装环境可测）"""
    fake = types.ModuleType("agent_memory")
    fake.AgentMemory = MagicMock()
    monkeypatch.setitem(sys.modules, "agent_memory", fake)
    return fake


def test_missing_sdk_raises_import_error():
    with pytest.raises(ImportError):
        SdkTencentMemoryClient(llm=MagicMock(), storage_dir="/tmp/mem")


def test_client_builds_and_recalls(monkeypatch):
    fake = _install_fake_sdk(monkeypatch)
    client = SdkTencentMemoryClient(llm=MagicMock(), storage_dir="/tmp/mem")
    fake.AgentMemory.assert_called_once()
    fake.AgentMemory.return_value.recall.return_value = [
        {"type": "scene", "content": "用户准备搬家", "score": 0.9},
    ]
    items = client.recall("搬家", top_k=5)
    assert items[0]["content"] == "用户准备搬家"
    fake.AgentMemory.return_value.recall.assert_called_once()


def test_client_writes_round(monkeypatch):
    fake = _install_fake_sdk(monkeypatch)
    client = SdkTencentMemoryClient(llm=MagicMock(), storage_dir="/tmp/mem")
    client.write_round(query="你好", answer="你好！")
    fake.AgentMemory.return_value.save_round.assert_called_once()
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest test/internal/service/memory_provider/test_tencent_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'internal.service.memory_provider.tencent_client'`

- [ ] **Step 4: 实现（注：`tencent_llm.py` 已按 controller ruling 删除——真实 v2 SDK 不接受 LLM，该文件为死代码；以下仅实现 `tencent_client.py`）**

Create `internal/service/memory_provider/tencent_client.py`：

```python
#!/usr/bin/env python
"""腾讯记忆 SDK 的 LLM 适配器：把项目 BaseLanguageModel 适配成 SDK 需要的 chat 接口"""
from dataclasses import dataclass


@dataclass
class TencentLlmAdapter:
    """薄适配：SDK 通过 chat(messages) 调用 LLM；内部走 langchain invoke。

    messages: [{"role": "system"|"user"|"assistant", "content": str}, ...]
    """
    llm: object  # internal.core.language_model.entities.model_entity.BaseLanguageModel

    def chat(self, messages: list[dict]) -> str:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        langchain_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                langchain_messages.append(SystemMessage(content=content))
            elif role == "assistant":
                langchain_messages.append(AIMessage(content=content))
            else:
                langchain_messages.append(HumanMessage(content=content))
        response = self.llm.invoke(langchain_messages)
        return response.content if hasattr(response, "content") else str(response)
```

Create `internal/service/memory_provider/tencent_client.py`：

```python
#!/usr/bin/env python
"""腾讯记忆客户端：唯一接触 TencentDB-Agent-Memory SDK 的模块（懒加载）。

SDK 确切 API 以 Task 6 验证结果为准；与下列代码不一致时仅修改本文件方法体，
recall / write_round 接口与 TencentMemoryProvider 保持不变。
SDK 缺失时构造抛 ImportError，由 TencentMemoryProvider 捕获回退为无记忆。
"""
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class TencentMemoryClient(ABC):
    """内部客户端接口：TencentMemoryProvider 只依赖此接口"""

    @abstractmethod
    def recall(self, query: str, top_k: int = 5) -> list[dict]:
        """记忆召回，返回 [{type: "core"|"scene", content: str, score: float}, ...]"""

    @abstractmethod
    def write_round(self, query: str, answer: str) -> None:
        """写入一轮对话并触发记忆流水线（提取→整合→反思→复盘）"""


class SdkTencentMemoryClient(TencentMemoryClient):
    """基于 TencentDB-Agent-Memory SDK 的实现（懒加载，SDK 缺失抛 ImportError）"""

    def __init__(self, llm: object, storage_dir: str):
        # 懒加载：SDK 未安装时抛 ImportError（包名以 Task 6 验证结果为准）
        from agent_memory import AgentMemory  # noqa: PLC0415
        self._client = AgentMemory(llm=llm, storage_path=storage_dir)

    def recall(self, query: str, top_k: int = 5) -> list[dict]:
        # SDK API 以验证结果为准；此处按公开文档 recall 语义实现
        result = self._client.recall(query=query, top_k=top_k)
        return [dict(item) for item in result]

    def write_round(self, query: str, answer: str) -> None:
        self._client.save_round(query=query, answer=answer)
```

（若 Task 6 Step 1 验证出真实包名/API，同步修改 `from agent_memory import AgentMemory` 与两个方法体。）

- [ ] **Step 5: 更新 requirements.txt**

若 Step 1 验证出包名与版本：

```text
tencentdb-agent-memory==<验证出的版本>
```

若无法验证，追加一行注释并跳过（不阻塞其他任务）：

```text
# tencentdb-agent-memory  # 待用户机器验证包名/安装方式后启用（腾讯记忆模式）
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest test/internal/service/memory_provider/test_tencent_client.py -v`
Expected: PASS（3 个用例）

- [ ] **Step 7: 提交**

```bash
git add internal/service/memory_provider/tencent_client.py internal/service/memory_provider/tencent_llm.py test/internal/service/memory_provider/ requirements.txt
git commit -m "feat(memory): 腾讯记忆 SDK 客户端与 LLM 适配器（懒加载，SDK 差异隔离）"
```

---

## Task 7: TencentMemoryProvider（填充 Task 3 骨架）

**Files:**
- Modify: `internal/service/memory_provider/tencent_provider.py`（替换 Task 3 骨架）
- Modify: `test/internal/service/memory_provider/test_tencent_provider.py`（新增）
- Test: `test/internal/service/memory_provider/test_resolver.py`（复用）

**Interfaces:**
- Consumes: `TencentMemoryClient` / `SdkTencentMemoryClient`（Task 6，已按真实 API 适配：构造 `(endpoint, api_key, service_id, *, session_id="default")`）；`SystemConfigService.get_config(key)`（DB > 环境变量 > 空）
- Produces: `TencentMemoryProvider` 完整实现（四方法）；常量 `ENDPOINT_KEY = "TENCENT_MEMORY_ENDPOINT"`、`API_KEY_KEY = "TENCENT_MEMORY_API_KEY"`、`SERVICE_ID_KEY = "TENCENT_MEMORY_SERVICE_ID"`；**不构造 LLM、无存储目录**（v2 架构：流水线在 MemoryCore 服务端）

- [ ] **Step 1: 写失败测试**

Create `test/internal/service/memory_provider/test_tencent_provider.py`：

```python
#!/usr/bin/env python
"""TencentMemoryProvider 测试：配置缺失/客户端不可用回退、假客户端读写调用、session 映射"""
from unittest.mock import MagicMock
from uuid import uuid4

from app.http.module import injector
from internal.service.memory_provider import TencentMemoryProvider
from internal.service.memory_provider.base import MemoryReadContext
from internal.service.memory_provider.tencent_provider import (
    API_KEY_KEY, ENDPOINT_KEY, SERVICE_ID_KEY,
)


class FakeClient:
    """假腾讯记忆客户端：不依赖真实 SDK"""
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.recalled = []
        self.written = []

    def recall(self, query, top_k=5):
        self.recalled.append((query, top_k))
        return [
            {"type": "core", "content": "用户喜欢简洁回复", "score": 0.9},
            {"type": "scene", "content": "用户准备搬家到北京", "score": 0.8},
        ]

    def write_round(self, query, answer):
        self.written.append((query, answer))


class SyncThread:
    """测试替身：start() 时同步执行 target，避免子线程竞态"""
    def __init__(self, target=None, kwargs=None):
        self._target = target
        self._kwargs = kwargs or {}

    def start(self):
        self._target(**self._kwargs)


class TestTencentMemoryProvider:
    def test_client_unavailable_falls_back_empty(self, app, monkeypatch):
        """_build_client 返回 None（SDK 缺失/配置不全）时：空上下文/空画像/空工具"""
        provider = injector.get(TencentMemoryProvider)
        monkeypatch.setattr(provider, "_build_client", lambda app_config: None)
        app_id, user_id = uuid4(), uuid4()
        ctx = provider.get_read_context({"model_config": {}}, app_id, user_id, "q")
        assert isinstance(ctx, MemoryReadContext)
        assert ctx.episodic_memory == ""
        assert provider.get_user_profile({"model_config": {}}, app_id, user_id) == ""
        assert provider.get_memory_tools({"model_config": {}}, app_id, user_id) == []

    def test_read_context_renders_core_and_scene(self, app, monkeypatch):
        provider = injector.get(TencentMemoryProvider)
        fake = FakeClient()
        monkeypatch.setattr(provider, "_build_client", lambda app_config: fake)
        app_id, user_id = uuid4(), uuid4()
        ctx = provider.get_read_context({"model_config": {}}, app_id, user_id, "搬家")
        assert "用户准备搬家到北京" in ctx.episodic_memory
        assert "用户喜欢简洁回复" in ctx.procedural_instructions
        assert fake.recalled[-1][0] == "搬家"

    def test_user_profile_from_core_memory(self, app, monkeypatch):
        provider = injector.get(TencentMemoryProvider)
        fake = FakeClient()
        monkeypatch.setattr(provider, "_build_client", lambda app_config: fake)
        profile = provider.get_user_profile({"model_config": {}}, uuid4(), uuid4())
        assert "用户喜欢简洁回复" in profile

    def test_build_client_reads_config_and_maps_session(self, app, monkeypatch):
        provider = injector.get(TencentMemoryProvider)
        built = {}
        class FakeSdkClient:
            def __init__(self, endpoint, api_key, service_id, *, session_id="default"):
                built["endpoint"] = endpoint
                built["api_key"] = api_key
                built["service_id"] = service_id
                built["session_id"] = session_id
        monkeypatch.setattr(
            "internal.service.memory_provider.tencent_provider.SdkTencentMemoryClient",
            FakeSdkClient,
        )
        monkeypatch.setattr(
            provider.system_config_service, "get_config",
            lambda key: {
                ENDPOINT_KEY: "http://127.0.0.1:8420",
                API_KEY_KEY: "sk-test",
                SERVICE_ID_KEY: "mem-1",
            }.get(key, ""),
        )
        app_id, user_id = uuid4(), uuid4()
        provider._build_client({"model_config": {}}, app_id, user_id)
        assert built["endpoint"] == "http://127.0.0.1:8420"
        assert built["api_key"] == "sk-test"
        assert built["service_id"] == "mem-1"
        assert built["session_id"] == f"{app_id}:{user_id}"

    def test_build_client_missing_config_returns_none(self, app, monkeypatch):
        provider = injector.get(TencentMemoryProvider)
        monkeypatch.setattr(provider.system_config_service, "get_config", lambda key: "")
        assert provider._build_client({"model_config": {}}, uuid4(), uuid4()) is None

    def test_trigger_write_spawns_write_round_thread(self, app, monkeypatch):
        provider = injector.get(TencentMemoryProvider)
        fake = FakeClient()
        monkeypatch.setattr(provider, "_build_client", lambda app_config, app_id, user_id: fake)
        monkeypatch.setattr("internal.service.memory_provider.tencent_provider.Thread", SyncThread)
        app_id, user_id = uuid4(), uuid4()
        with app.app_context():
            provider.trigger_write(app_config={"model_config": {}}, app_id=app_id,
                                   user_id=user_id, query="你好", answer="你好！")
        assert fake.written == [("你好", "你好！")]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/memory_provider/test_tencent_provider.py -v`
Expected: FAIL（`NotImplementedError: Task 7 填充`）

- [ ] **Step 3: 实现**

替换 `internal/service/memory_provider/tencent_provider.py` 全部内容：

```python
#!/usr/bin/env python
"""腾讯记忆提供者：包装 TencentDB-Agent-Memory SDK（懒加载，配置缺失/SDK 缺失回退为无记忆）。

v2 架构：SDK 是纯 HTTP 客户端，记忆流水线（L0→L3）运行在 MemoryCore 服务端，
因此本 provider 不构造 LLM，只读三个系统配置（endpoint/api_key/service_id）。
"""
import logging
from dataclasses import dataclass
from threading import Thread
from uuid import UUID

from flask import current_app
from injector import inject

from internal.service.system_config_service import SystemConfigService

from .base import MemoryProvider, MemoryReadContext
from .tencent_client import SdkTencentMemoryClient, TencentMemoryClient

logger = logging.getLogger(__name__)

ENDPOINT_KEY = "TENCENT_MEMORY_ENDPOINT"
API_KEY_KEY = "TENCENT_MEMORY_API_KEY"
SERVICE_ID_KEY = "TENCENT_MEMORY_SERVICE_ID"


@inject
@dataclass
class TencentMemoryProvider(MemoryProvider):
    """腾讯记忆提供者：SDK/配置不可用回退为无记忆（等效关闭长期记忆）"""
    system_config_service: SystemConfigService

    def _build_client(self, app_config: dict, app_id: UUID, user_id: UUID) -> TencentMemoryClient | None:
        """按系统配置构建 SDK 客户端；配置缺失/SDK 缺失/初始化失败返回 None"""
        endpoint = self.system_config_service.get_config(ENDPOINT_KEY)
        api_key = self.system_config_service.get_config(API_KEY_KEY)
        service_id = self.system_config_service.get_config(SERVICE_ID_KEY)
        if not endpoint or not api_key or not service_id:
            logger.warning("腾讯记忆配置不完整（endpoint/api_key/service_id），回退为无记忆")
            return None
        try:
            return SdkTencentMemoryClient(
                endpoint=endpoint, api_key=api_key, service_id=service_id,
                session_id=f"{app_id}:{user_id}",
            )
        except ImportError:
            logger.warning("腾讯记忆 SDK 未安装，回退为无记忆（等效关闭长期记忆）")
            return None
        except Exception:
            logger.exception("腾讯记忆初始化失败，回退为无记忆")
            return None

    def get_user_profile(self, app_config: dict, app_id: UUID, user_id: UUID) -> str:
        client = self._build_client(app_config, app_id, user_id)
        if client is None:
            return ""
        try:
            items = client.recall(query="", top_k=10)
            return "\n".join(f"- {i['content']}" for i in items if i.get("type") == "core")
        except Exception:
            logger.exception("腾讯记忆画像读取失败")
            return ""

    def get_read_context(self, app_config: dict, app_id: UUID, user_id: UUID, query: str) -> MemoryReadContext:
        client = self._build_client(app_config, app_id, user_id)
        if client is None:
            return MemoryReadContext()
        ctx = MemoryReadContext()
        try:
            items = client.recall(query=query, top_k=5)
            ctx.episodic_memory = "\n".join(f"- {i['content']}" for i in items if i.get("type") == "scene")
            ctx.procedural_instructions = "\n".join(
                f"- {i['content']}" for i in items if i.get("type") == "core"
            )
        except Exception:
            logger.exception("腾讯记忆召回失败")
        return ctx

    def get_memory_tools(self, app_config: dict, app_id: UUID, user_id: UUID) -> list:
        logger.info("腾讯记忆模式下不注入内置记忆工具（流水线自管理，避免双写）")
        return []

    def trigger_write(self, *, app_config: dict, app_id: UUID, user_id: UUID, query: str, answer: str) -> None:
        flask_app = current_app._get_current_object()
        Thread(
            target=self._write_round,
            kwargs={"flask_app": flask_app, "app_config": app_config,
                    "app_id": app_id, "user_id": user_id,
                    "query": query, "answer": answer},
        ).start()

    def _write_round(self, *, flask_app, app_config, app_id, user_id, query, answer) -> None:
        """写侧管道：子线程内调用腾讯记忆 L0 写入（仅持纯值）"""
        with flask_app.app_context():
            client = self._build_client(app_config, app_id, user_id)
            if client is None:
                return
            try:
                client.write_round(query=query, answer=answer)
            except Exception:
                logger.exception("腾讯记忆写入失败")
```

（注：`_build_client` 签名变为 `(app_config, app_id, user_id)` —— 腾讯实现需要 app_id/user_id 拼 session_id；ABC 的 `trigger_write` 方法签名不变。）

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/memory_provider/ -x -v`
Expected: PASS（含 resolver tencent 分支用例——resolver 不调用 provider 方法，仅 isinstance 判断，不受签名变化影响）

- [ ] **Step 5: 提交**

```bash
git add internal/service/memory_provider/tencent_provider.py test/internal/service/memory_provider/test_tencent_provider.py
git commit -m "feat(memory): TencentMemoryProvider 完整实现（配置读取/懒加载/回退/读写渲染）"
```

---

## Task 8: 前端系统设置"记忆系统"tab

**Files:**
- Create: `ai-code-llmops-web/src/views/settings/components/MemoryConfig.vue`
- Modify: `ai-code-llmops-web/src/views/settings/SystemSettings.vue`

**Interfaces:**
- Consumes: `getSystemConfig()` / `saveSystemConfig(configs)`（`src/services/system-config.ts`，已有）
- Produces: `envConfig` 新增键 `MEMORY_PROVIDER`（默认 `'builtin'`）、`TENCENT_MEMORY_ENDPOINT`（默认 `''`）、`TENCENT_MEMORY_API_KEY`（默认 `''`，敏感）、`TENCENT_MEMORY_SERVICE_ID`（默认 `''`）；`SENSITIVE` 集合追加 `TENCENT_MEMORY_API_KEY`；新 tab `memory`「记忆系统」

- [ ] **Step 1: 新建 MemoryConfig.vue**

Create `ai-code-llmops-web/src/views/settings/components/MemoryConfig.vue`：

```vue
<script setup lang="ts">
const props = defineProps<{ modelValue: Record<string, string> }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: Record<string, string>): void }>()

const update = (key: string, value: string) => {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>

<template>
  <div class="space-y-5 pb-4">
    <div>
      <div class="text-sm font-medium text-gray-700 mb-2">记忆系统</div>
      <div class="flex gap-6">
        <label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="radio"
            value="builtin"
            :checked="(modelValue.MEMORY_PROVIDER || 'builtin') === 'builtin'"
            @change="update('MEMORY_PROVIDER', 'builtin')"
          />
          内置记忆系统（当前实现，行为不变）
        </label>
        <label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="radio"
            value="tencent"
            :checked="modelValue.MEMORY_PROVIDER === 'tencent'"
            @change="update('MEMORY_PROVIDER', 'tencent')"
          />
          腾讯记忆（TencentDB-Agent-Memory）
        </label>
      </div>
      <p class="text-xs text-gray-400 mt-1">
        应用配置里可单独覆盖；切换即时生效；存量记忆数据不迁移。
      </p>
    </div>
    <div v-if="modelValue.MEMORY_PROVIDER === 'tencent'" class="space-y-4">
      <div>
        <div class="text-sm font-medium text-gray-700 mb-2">Memory Core 服务地址</div>
        <input
          class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
          :value="modelValue.TENCENT_MEMORY_ENDPOINT"
          placeholder="http://127.0.0.1:8420"
          @input="update('TENCENT_MEMORY_ENDPOINT', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div>
        <div class="text-sm font-medium text-gray-700 mb-2">API Key（敏感，已配置时回显 ********）</div>
        <input
          class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
          :value="modelValue.TENCENT_MEMORY_API_KEY"
          placeholder="sk-..."
          @input="update('TENCENT_MEMORY_API_KEY', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div>
        <div class="text-sm font-medium text-gray-700 mb-2">Memory 空间 ID（service_id）</div>
        <input
          class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
          :value="modelValue.TENCENT_MEMORY_SERVICE_ID"
          placeholder="mem-..."
          @input="update('TENCENT_MEMORY_SERVICE_ID', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <p class="text-xs text-gray-400">
        腾讯记忆需可访问的 Memory Core 服务（自托管 docker 或腾讯云实例）且后端已安装 SDK；配置不完整时该模式等效关闭记忆。
      </p>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 改 SystemSettings.vue**

2.1 script：import 追加 `import MemoryConfig from './components/MemoryConfig.vue'`。
2.2 `envConfig` 追加四个初始键（放在"// 飞书"段之后）：

```ts
  // 记忆系统
  MEMORY_PROVIDER: 'builtin',
  TENCENT_MEMORY_ENDPOINT: '',
  TENCENT_MEMORY_API_KEY: '',
  TENCENT_MEMORY_SERVICE_ID: '',
```

2.3 `SENSITIVE` 集合追加 `'TENCENT_MEMORY_API_KEY'`（敏感项：保存时若为 `********` 跳过提交，保持原配置）。

2.4 `tabs` 追加：

```ts
  { key: 'memory', label: '记忆系统' },
```

2.5 template 内容区追加：

```vue
      <memory-config v-if="activeTab === 'memory'" v-model="envConfig" />
```

- [ ] **Step 3: 构建验证**

Run（在 `ai-code-llmops-web/` 目录）：

```bash
yarn build
```

Expected: 构建成功（vue-tsc 类型检查 + vite build 均通过）

- [ ] **Step 4: 手动验证（可选，浏览器可用时）**

启动前端 dev（`yarn dev`）+ 后端，进入 系统设置 → 记忆系统：切换单选、腾讯模式下出现存储目录输入框、保存后刷新仍回显。

- [ ] **Step 5: 提交**

```bash
git add ai-code-llmops-web/src/views/settings/
git commit -m "feat(web): 系统设置新增记忆系统 tab（内置/腾讯 + 存储目录）"
```

---

## Task 9: 前端应用配置长期记忆下拉

**Files:**
- Modify: `ai-code-llmops-web/src/views/space/apps/components/abilities/LongTermMemoryAbilityItem.vue`
- Modify: `ai-code-llmops-web/src/models/app.ts`

**Interfaces:**
- Consumes: `useUpdateDraftAppConfig().handleUpdateDraftAppConfig(app_id, {long_term_memory})`（已有 hook）
- Produces: `long_term_memory` 对象含 `provider`（`'default' | 'builtin' | 'tencent'`）

- [ ] **Step 1: 改 LongTermMemoryAbilityItem.vue**

将文件整体替换为：

```vue
<script setup lang="ts">
import type { PropType } from 'vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'

type LongTermMemory = { enable: boolean; provider?: string }

const props = defineProps({
  app_id: { type: String, required: true },
  long_term_memory: {
    type: Object as PropType<LongTermMemory>,
    required: true,
    default: () => ({ enable: false, provider: 'default' }),
  },
})

const emits = defineEmits(['update:long_term_memory'])

const { handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()

const MEMORY_PROVIDERS = [
  { value: 'default', label: '跟随系统默认' },
  { value: 'builtin', label: '内置记忆系统' },
  { value: 'tencent', label: '腾讯记忆' },
]

const onSelectLongTermMemory = async (value: unknown) => {
  const enable = Boolean(value)
  if (enable === props.long_term_memory?.enable) return
  const next = { enable, provider: props.long_term_memory?.provider ?? 'default' }
  emits('update:long_term_memory', next)
  await handleUpdateDraftAppConfig(props.app_id, { long_term_memory: next })
}

const onSelectMemoryProvider = async (value: unknown) => {
  const provider = String(value)
  const next = { enable: props.long_term_memory?.enable ?? false, provider }
  emits('update:long_term_memory', next)
  await handleUpdateDraftAppConfig(props.app_id, { long_term_memory: next })
}
</script>

<template>
  <div>
    <a-collapse-item key="long_term_memory" class="app-ability-item">
      <template #header>
        <div class="text-gray-700 font-bold">长期记忆</div>
      </template>
      <template #extra>
        <a-dropdown @select="onSelectLongTermMemory">
          <a-button size="mini" class="rounded-lg flex items-center gap-1 px-1" @click.stop>
            {{ props.long_term_memory.enable ? '开启' : '关闭' }}
            <icon-down />
          </a-button>
          <template #content>
            <a-doption :value="1" class="text-xs py-1.5 text-gray-700">开启</a-doption>
            <a-doption :value="0" class="text-xs py-1.5 text-red-700">关闭</a-doption>
          </template>
        </a-dropdown>
      </template>
      <div class="text-xs text-gray-500 leading-[28px]">
        总结聊天对话内容，并用于更好的响应用户的信息。
      </div>
      <div v-if="props.long_term_memory.enable" class="mt-2 flex items-center gap-2">
        <span class="text-xs text-gray-500">记忆系统</span>
        <a-select
          :model-value="props.long_term_memory.provider ?? 'default'"
          size="mini"
          style="width: 140px"
          @change="onSelectMemoryProvider"
        >
          <a-option v-for="p in MEMORY_PROVIDERS" :key="p.value" :value="p.value" class="text-xs">
            {{ p.label }}
          </a-option>
        </a-select>
      </div>
    </a-collapse-item>
  </div>
</template>

<style scoped></style>
```

- [ ] **Step 2: 改 models/app.ts**

`src/models/app.ts` 两处 `long_term_memory: { enable: boolean }` 改为：

```ts
  long_term_memory: {
    enable: boolean
    provider?: string
  }
```

- [ ] **Step 3: 构建验证**

Run（在 `ai-code-llmops-web/` 目录）：

```bash
yarn build
```

Expected: 构建成功

- [ ] **Step 4: 手动验证（可选）**

应用配置 → 能力 → 长期记忆：开启后出现"记忆系统"下拉，选择腾讯记忆并保存，刷新后回显。

- [ ] **Step 5: 提交**

```bash
git add ai-code-llmops-web/src/
git commit -m "feat(web): 应用配置长期记忆支持记忆系统下拉（跟随系统/内置/腾讯）"
```

---

## Task 10: 全量回归与收尾提交

**Files:**
- 无新增；验证与提交

- [ ] **Step 1: 后端全量回归**

Run: `pytest test/ -x`
Expected: PASS（全部用例）

- [ ] **Step 2: 前端构建**

Run（`ai-code-llmops-web/` 目录）: `yarn build`
Expected: 构建成功

- [ ] **Step 3: 规格一致性自查**

对照 Spec 逐项核对：
- [ ] 系统设置"记忆系统"tab 与 `MEMORY_PROVIDER` / `TENCENT_MEMORY_STORAGE_DIR` 已落地（Task 8）
- [ ] 应用配置 `long_term_memory.provider` 覆盖 + 校验（Task 5、9）
- [ ] 五个记忆触达点全部走 provider（Task 4）
- [ ] 内置路径行为零变化（Task 2、4 回归）
- [ ] 腾讯模式懒加载 + 回退（Task 7）
- [ ] 存量数据不迁移、审计页边界已记录（Spec 已知边界）

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "feat(memory): 记忆系统 Provider 化完整落地（内置/腾讯可切换）"
git log --oneline -15
```

- [ ] **Step 5: 汇报**

向用户汇报：分支 `release_20260829`、commit 列表、腾讯 SDK 验证状态（Task 6 Step 1 结果）、需要用户在可联网机器上完成的验证项（包名/安装方式/API 核对）。
