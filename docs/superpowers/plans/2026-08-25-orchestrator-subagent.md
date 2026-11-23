# 编排型 Agent（Orchestrator）与子任务断点恢复 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增"编排型"应用类型：会话中给出复杂任务 → 自动分解为子任务 → 并行动态子 Agent 执行（事件实时穿插流式）→ 汇总答案；子任务中断支持断点保存与恢复（resume_mode 可配置 auto/manual）。

**Architecture:** 新增 `OrchestratorAgent`（继承 `BaseAgent`），LangGraph 图 = plan → execute（ThreadPoolExecutor 并行动态子 Agent + 队列桥接）→ summarize，0 子任务时退化 direct_answer。断点存 `sub_task_checkpoint` 表，`FunctionCallAgent` 加条件入口支持 resume 续跑。`App.app_type` + `orchestrator_config` 配置块接入应用体系。

**Tech Stack:** Python 3.12 / Flask / SQLAlchemy / LangGraph 1.2.x / LangChain / Alembic / pytest / Vue 3（ai-code-llmops-web）

**Spec:** `docs/superpowers/specs/2026-08-25-orchestrator-subagent-design.md`

## Global Constraints

- 所有新事件/字段向后兼容：`AgentThought` 新字段必须有默认值；`QueueEvent` 只增不改。
- 队列桥接必须用 `AgentQueueManager.forward()`（无 stop 副作用），禁止用 `publish()` 转发子 Agent 事件。
- 子 Agent 的 `PING / AGENT_END / STOP / TIMEOUT / ERROR` 事件不桥接；终态由执行器转成 `SUB_TASK_END`；主消息只保留编排器自己的 `AGENT_END`。
- 断点查询键 `(conversation_id, position)`，`query` 完全匹配才恢复；`resume_mode="manual"` 时仅 `resume_trigger=True` 才查断点。
- 断点保存时机：异常终止（stop/timeout/error）保存 + 运行中每 10 个桥接事件且距上次落盘 ≥10 秒周期保存 + 完成时存 complete（含最终答案缓存）。
- `AgentState` 新增字段全部带默认值（防 langgraph `map_input` 丢弃）。
- 新增/修改的 Python 代码遵循现有模式：BaseService.create/update、`from app.http.module import injector` 懒加载、线程内写库用 `current_app._get_current_object()` + `with flask_app.app_context()`。
- 前端 `QueueEvent` 常量与后端事件字符串一致；`agent_thoughts` 透传 `sub_task_id` / `sub_task_title`。
- 最终所有代码提交到分支 `release_20260828`。

---

### Task 1: 事件与实体扩展

**Files:**
- Modify: `internal/core/agent/entities/queue_entity.py`
- Modify: `internal/core/agent/entities/agent_entity.py`
- Test: `test/internal/core/agent/test_orchestrator_entities.py`

**Interfaces:**
- Consumes: 现有 `QueueEvent`、`AgentThought`、`AgentConfig`、`AgentState`、`MessageStatus`（`internal.entity.conversation_entity`）
- Produces:
  - `QueueEvent.SUB_TASK_PLAN / SUB_TASK_START / SUB_TASK_END`（字符串 `"sub_task_plan" / "sub_task_start" / "sub_task_end"`）
  - `AgentThought.sub_task_id: UUID | None`、`AgentThought.sub_task_title: str`
  - `SubTaskSpec`（order/title/role_prompt/expect_output/required_tools/task_id）、`SubTaskResult`（order/title/status/answer/error/latency/resumed）
  - `AgentState.sub_tasks / sub_results / conversation_id / query / resume / resume_trigger`
  - `AgentConfig.orchestrator_config: dict`
  - 模板常量 `ORCHESTRATOR_PLAN_SYSTEM_PROMPT_TEMPLATE`、`ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE`

- [ ] **Step 1: 写失败测试**

创建 `test/internal/core/agent/test_orchestrator_entities.py`：

```python
import uuid

from internal.core.agent.entities.agent_entity import (
    ORCHESTRATOR_PLAN_SYSTEM_PROMPT_TEMPLATE,
    ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE,
    SubTaskResult,
    SubTaskSpec,
    build_system_prompt,
)
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent


def test_queue_event_has_sub_task_events():
    assert QueueEvent.SUB_TASK_PLAN == "sub_task_plan"
    assert QueueEvent.SUB_TASK_START == "sub_task_start"
    assert QueueEvent.SUB_TASK_END == "sub_task_end"


def test_agent_thought_sub_task_fields_default():
    thought = AgentThought(id=uuid.uuid4(), task_id=uuid.uuid4(), event=QueueEvent.AGENT_MESSAGE)
    assert thought.sub_task_id is None
    assert thought.sub_task_title == ""


def test_sub_task_spec_defaults():
    spec = SubTaskSpec(order=1, title="调研", role_prompt="你是调研员", expect_output="一份报告")
    assert spec.required_tools == []
    assert spec.task_id is None


def test_sub_task_result_defaults():
    result = SubTaskResult(order=1, title="调研")
    assert result.status == "normal"
    assert result.answer == ""
    assert result.resumed is False


def test_orchestrator_prompt_templates_exist():
    assert "{max_sub_tasks}" in ORCHESTRATOR_PLAN_SYSTEM_PROMPT_TEMPLATE
    assert "{query}" in ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE
    assert "{sub_results_text}" in ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/core/agent/test_orchestrator_entities.py -v`
Expected: FAIL（ImportError / AttributeError）

- [ ] **Step 3: 实现**

`internal/core/agent/entities/queue_entity.py`：

```python
class QueueEvent(str, Enum):
    """队列事件枚举类型"""
    LONG_TERM_MEMORY_RECALL = "long_term_memory_recall"  # 长期记忆召回
    AGENT_THOUGHT = "agent_thought"  # 智能体观察事件
    AGENT_MESSAGE = "agent_message"  # 智能体消息事件
    AGENT_ACTION = "agent_action"  # 智能体动作
    DATASET_RETRIEVAL = "dataset_retrieval"  # 知识库检索事件
    AGENT_END = "agent_end"  # 智能体结束事件
    STOP = "stop"  # 智能体停止事件
    ERROR = "error"  # 智能体错误事件
    TIMEOUT = "timeout"  # 智能体超时事件
    PING = "ping"  # ping联通事件
    SUB_TASK_PLAN = "sub_task_plan"  # 编排器：任务分解计划
    SUB_TASK_START = "sub_task_start"  # 编排器：子任务开始
    SUB_TASK_END = "sub_task_end"  # 编排器：子任务结束
```

`AgentThought` 末尾（`latency` 字段之后）追加：

```python
    # 编排器子任务相关（桥接事件填充，非编排器事件为空）
    sub_task_id: UUID | None = None  # 所属子任务id
    sub_task_title: str = ""  # 所属子任务标题（前端分组展示用）
```

`internal/core/agent/entities/agent_entity.py`：

```python
# 编排器规划系统提示词模板
ORCHESTRATOR_PLAN_SYSTEM_PROMPT_TEMPLATE = """你是任务编排智能体，负责将用户的复杂任务分解为多个可并行执行的子任务。

规则：
1、只有当任务确实复杂、可以拆分为多个独立子任务时才分解；简单任务直接回答，不要分解；
2、每个子任务必须独立、可并行、边界清晰，子任务之间不得互相依赖；
3、子任务数量不超过 {max_sub_tasks} 个，每个子任务给出：标题(title)、角色提示词(role_prompt，告诉子智能体它是什么角色、要做什么)、期望输出(expect_output)；
4、如果某些子任务需要特定工具，在 required_tools 中填写工具名（来自可用工具列表），不需要则留空；
5、输出语言与用户输入保持一致。
"""

# 编排器汇总提示词模板
ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE = """你是任务汇总智能体。用户的任务被拆分为多个子任务并行执行，请综合以下子任务结果，输出一份完整、连贯的最终回答。

用户任务：
{query}

子任务结果：
{sub_results_text}

要求：
1、回答必须完整覆盖用户任务的所有要点；
2、子任务失败或缺失的部分如实说明，禁止编造；
3、输出语言与用户任务保持一致。
"""

class SubTaskSpec(BaseModel):
    """子任务定义"""
    order: int = Field(description="子任务序号（1 起）")
    title: str = Field(description="子任务标题")
    role_prompt: str = Field(description="子智能体角色提示词（作为子Agent的preset_prompt）")
    expect_output: str = Field(description="期望输出描述")
    required_tools: list[str] = Field(default_factory=list, description="需要的工具名列表，可为空")
    task_id: UUID | None = None  # execute 节点派发时赋值 uuid4()


class SubTaskResult(BaseModel):
    """子任务执行结果"""
    order: int
    title: str
    status: str = "normal"  # normal / error / stop / timeout
    answer: str = ""
    error: str = ""
    latency: float = 0.0
    resumed: bool = False  # 是否从断点恢复


class SubTaskPlan(BaseModel):
    """任务分解计划（plan 节点结构化输出）"""
    subtasks: list[SubTaskSpec] = Field(default_factory=list, description="子任务列表；任务无需分解时返回空列表")
```

注意：`SubTaskPlan` 必须定义在 `SubTaskSpec` **之后**（直接引用 `list[SubTaskSpec]`，避免 pydantic 前向引用解析问题）。

`AgentConfig` 追加字段（`review_config` 之后）：

```python
    # 编排器配置（仅 OrchestratorAgent 使用）：resume_mode / max_sub_tasks / max_parallel / sub_task_timeout
    orchestrator_config: dict = Field(default_factory=dict)
```

`AgentState` 追加字段：

```python
    # 编排器相关（带默认值，防 langgraph map_input 丢弃）
    sub_tasks: list[SubTaskSpec] = Field(default_factory=list)  # 规划结果
    sub_results: list[SubTaskResult] = Field(default_factory=list)  # 执行结果
    conversation_id: UUID | None = None  # 断点键一部分（chat_runner 注入）
    app_id: UUID | None = None  # 断点归属（chat_runner 注入）
    message_id: UUID | None = None  # 断点归属（chat_runner 注入）
    query: str = ""  # 原始用户提问，断点有效性校验
    resume: bool = False  # 恢复模式标记（FunctionCallAgent 条件入口用）
    resume_trigger: bool = False  # 请求级显式恢复标记（manual 模式）
```

注意：`SubTaskPlan` 引用 `SubTaskSpec` 需定义在 `SubTaskSpec` 之后，或使用字符串前向引用（上面已用字符串）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/core/agent/test_orchestrator_entities.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/entities/queue_entity.py internal/core/agent/entities/agent_entity.py test/internal/core/agent/test_orchestrator_entities.py
git commit -m "feat(agent): 编排器事件与实体扩展（SUB_TASK_* / SubTaskSpec / AgentState 字段）"
```

---

### Task 2: AgentQueueManager.forward()

**Files:**
- Modify: `internal/core/agent/agents/agent_queue_manager.py`
- Test: `test/internal/core/agent/test_queue_manager_forward.py`

**Interfaces:**
- Consumes: `AgentQueueManager`（现有）、`AgentThought`、`QueueEvent`
- Produces: `AgentQueueManager.forward(task_id: UUID, thought: AgentThought) -> None`——只把事件写入目标队列，不触发 `stop_listen`（区别于 `publish()`）

- [ ] **Step 1: 写失败测试**

创建 `test/internal/core/agent/test_queue_manager_forward.py`：

```python
import uuid
from unittest.mock import MagicMock

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.conversation_entity import InvokeFrom


def _make_manager(monkeypatch) -> AgentQueueManager:
    fake_redis = MagicMock()
    fake_injector = MagicMock()
    fake_injector.get.return_value = fake_redis
    monkeypatch.setattr("internal.core.agent.agents.agent_queue_manager.injector", fake_injector)
    return AgentQueueManager(user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP)


def test_forward_puts_event_without_stop_sentinel(monkeypatch):
    qm = _make_manager(monkeypatch)
    task_id = uuid.uuid4()
    event = AgentThought(id=uuid.uuid4(), task_id=task_id, event=QueueEvent.AGENT_END, answer="x")
    qm.forward(task_id, event)
    q = qm.queue(task_id)
    got = q.get(timeout=1)
    assert got is event  # 事件本身
    assert q.empty()  # 没有 None（stop 哨兵）


def test_publish_terminal_does_add_stop_sentinel(monkeypatch):
    """对照测试：publish 终态事件会 stop_listen（放 None），forward 必须没有这个行为"""
    qm = _make_manager(monkeypatch)
    task_id = uuid.uuid4()
    qm.publish(task_id, AgentThought(id=uuid.uuid4(), task_id=task_id, event=QueueEvent.AGENT_END))
    q = qm.queue(task_id)
    items = []
    while not q.empty():
        try:
            items.append(q.get(timeout=1))
        except Exception:
            break
    assert None in items
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/core/agent/test_queue_manager_forward.py -v`
Expected: FAIL（AttributeError: 'AgentQueueManager' object has no attribute 'forward'）

- [ ] **Step 3: 实现**

`internal/core/agent/agents/agent_queue_manager.py` 在 `publish` 方法前新增：

```python
    def forward(self, task_id: UUID, thought: AgentThought) -> None:
        """桥接事件到目标队列：仅写入，不触发 stop_listen 语义。

        编排器把子 Agent 事件转发到主任务队列时使用——若用 publish()，
        子任务终态事件会误触发主监听停止。
        """
        self.queue(task_id).put(thought)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/core/agent/test_queue_manager_forward.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/agents/agent_queue_manager.py test/internal/core/agent/test_queue_manager_forward.py
git commit -m "feat(agent): AgentQueueManager.forward 无stop副作用的队列桥接"
```

---

### Task 3: FunctionCallAgent 条件入口（resume）

**Files:**
- Modify: `internal/core/agent/agents/function_call_agent.py`
- Test: `test/internal/core/agent/test_agent_resume_entry.py`

**Interfaces:**
- Consumes: `AgentState`（含 `resume`）、现有图节点
- Produces: `FunctionCallAgent._entry_condition(state) -> Literal["preset_operation", "llm"]`；`_build_agent` 改用 `set_conditional_entry_point`。非编排调用不传 `resume`，行为不变。

- [ ] **Step 1: 写失败测试**

创建 `test/internal/core/agent/test_agent_resume_entry.py`：

```python
import uuid

from langchain_core.messages import HumanMessage

from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.entity.conversation_entity import InvokeFrom


def test_entry_condition_routes_resume_to_llm():
    state = {"resume": True}
    assert FunctionCallAgent._entry_condition(state) == "llm"


def test_entry_condition_routes_normal_to_preset():
    state = {"resume": False}
    assert FunctionCallAgent._entry_condition(state) == "preset_operation"


def test_build_agent_accepts_resume_state():
    """真实图编译冒烟：resume=True 的输入能跑通（消息序列不重建）"""
    from langchain_core.messages import AIMessageChunk
    from pydantic import ConfigDict

    from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
    from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent

    class FakeStreamLLM(BaseLanguageModel):
        model_config = ConfigDict(extra="allow")

        def stream(self, messages):
            yield AIMessageChunk(content="续跑完成", tool_calls=[])

        def get_num_tokens_safe(self, messages):
            return 10

        def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
            raise NotImplementedError

        async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
            raise NotImplementedError

        def invoke(self, input, config=None, **kwargs):
            raise NotImplementedError

    import threading
    import time

    class StubQueueManager:
        def __init__(self, user_id=None, invoke_from=None):
            self.events = []
            self._done = threading.Event()

        def publish(self, task_id, thought):
            self.events.append(thought)
            if thought.event in (QueueEvent.AGENT_END, QueueEvent.ERROR, QueueEvent.STOP, QueueEvent.TIMEOUT):
                self._done.set()

        def publish_error(self, task_id, error):
            self.publish(task_id, AgentThought(
                id=uuid.uuid4(), task_id=task_id,
                event=QueueEvent.ERROR, observation=str(error),
            ))

        def stop_listen(self, task_id):
            self._done.set()

        def listen(self, task_id):
            deadline = time.time() + 10
            while time.time() < deadline:
                if self._done.is_set():
                    yield from self.events
                    return
                time.sleep(0.01)
            raise AssertionError("Agent 图 10s 内未完成推理")

    import pytest
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)

    agent = FunctionCallAgent(
        name="resume-agent",
        llm=FakeStreamLLM(features=[ModelFeature.TOOL_CALL]),
        agent_config=AgentConfig(user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[]),
    )
    events = list(agent.stream({
        "messages": [HumanMessage(content="原问题")],
        "history": [],
        "iteration_count": 3,
        "resume": True,
    }))
    assert any(e.event == QueueEvent.AGENT_MESSAGE for e in events)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/core/agent/test_agent_resume_entry.py -v`
Expected: FAIL（AttributeError: _entry_condition 不存在 / set_conditional_entry_point 未生效）

- [ ] **Step 3: 实现**

`internal/core/agent/agents/function_call_agent.py` 的 `_build_agent`：

```python
    def _build_agent(self) -> CompiledStateGraph:
        graph = StateGraph(AgentState)
        # 1、添加节点
        graph.add_node("preset_operation", self._preset_operation_node)
        graph.add_node("long_term_memory_recall", self._long_term_memory_recall_node)
        graph.add_node("llm", self._llm_node)
        graph.add_node("tools", self._tools_node)

        # 2、添加边，并设置起点和终点
        # 条件入口：resume=True（编排器子任务断点恢复）时直接进 llm 节点续跑，否则走预设操作
        graph.set_conditional_entry_point(self._entry_condition)
        graph.add_conditional_edges("preset_operation", self._preset_operation_condition)
        graph.add_edge("long_term_memory_recall", "llm")
        graph.add_conditional_edges("llm", self._tools_condition)
        graph.add_edge("tools", "llm")

        return graph.compile()
```

新增类方法：

```python
    @classmethod
    def _entry_condition(cls, state: AgentState) -> Literal["preset_operation", "llm"]:
        """入口条件：恢复模式直接进 llm 节点（断点消息已含系统提示词），正常模式走预设操作"""
        return "llm" if state.get("resume") else "preset_operation"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/core/agent/test_agent_resume_entry.py -v`
Expected: PASS（3 passed）
另跑回归：`python -m pytest test/internal/core/agent/ -v`，确保现有图测试不受影响。

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/agents/function_call_agent.py test/internal/core/agent/test_agent_resume_entry.py
git commit -m "feat(agent): FunctionCallAgent 条件入口支持断点恢复续跑"
```

---

### Task 4: 数据模型与 Alembic 迁移

**Files:**
- Modify: `internal/model/app.py`
- Modify: `internal/model/conversation.py`
- Create: `internal/model/sub_task_checkpoint.py`
- Modify: `internal/model/__init__.py`
- Create: `internal/migrations/versions/<auto>_orchestrator_subagent.py`（用 `flask db revision -m "orchestrator subagent"` 生成，再按下方内容填充）

**Interfaces:**
- Consumes: 现有 `db.Model`、`DEFAULT_APP_CONFIG`
- Produces:
  - `App.app_type: str`（默认 `"agent"`，`"orchestrator"` 表示编排型）
  - `AppConfig.orchestrator_config: JSONB`、`AppConfigVersion.orchestrator_config: JSONB`
  - `MessageAgentThought.sub_task_id: UUID | None`、`sub_task_title: str`
  - `SubTaskCheckpoint` 模型（表 `sub_task_checkpoint`），列见下方；在 `internal/model/__init__.py` 导出

- [ ] **Step 1: 写失败测试**

创建 `test/internal/model/test_sub_task_checkpoint.py`：

```python
import uuid

import pytest
import sqlalchemy as sa

from internal.model import SubTaskCheckpoint


def test_sub_task_checkpoint_model_fields(db):
    """模型列冒烟：建表语句含关键列（依赖迁移已执行）"""
    from internal.extension.database_extension import db as _db

    insp = sa.inspect(_db.engine)
    if not insp.has_table("sub_task_checkpoint"):
        pytest.skip("sub_task_checkpoint 表尚未迁移")
    cols = {c["name"] for c in insp.get_columns("sub_task_checkpoint")}
    assert {"conversation_id", "position", "query", "status", "messages", "iteration_count"} <= cols
```

（同时在本任务验证迁移 `upgrade/downgrade`：见 Step 3 的命令。）

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/model/test_sub_task_checkpoint.py -v`
Expected: FAIL（表不存在 → skip 视为失败需自行判断；迁移未执行时直接报 NoSuchTableError 或 skip）

- [ ] **Step 3: 实现模型**

`internal/model/app.py` 的 `App` 类（`status` 字段后）新增：

```python
    app_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        server_default=text("'agent'::character varying"))  # 应用类型：agent / orchestrator
```

`AppConfig` 与 `AppConfigVersion` 各新增（`review_config` 字段后）：

```python
    orchestrator_config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # 编排器配置
```

`internal/model/conversation.py` 的 `MessageAgentThought`（`latency` 字段后）新增：

```python
    # 编排器子任务归属（非编排事件为空）
    sub_task_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    sub_task_title: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
```

创建 `internal/model/sub_task_checkpoint.py`：

```python
#!/usr/bin/env python
"""子任务断点模型：中断续跑 + 结果缓存"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime, Index, Integer, Numeric, PrimaryKeyConstraint, Text, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from internal.extension.database_extension import db


class SubTaskCheckpoint(db.Model):
    """子任务断点：按 (conversation_id, position) 定位，query 校验有效性"""
    __tablename__ = "sub_task_checkpoint"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_sub_task_checkpoint_id"),
        Index("idx_sub_task_checkpoint_conv_pos", "conversation_id", "position"),
    )

    id: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    created_by: Mapped[str] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
    )
    updated_by: Mapped[str] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    app_id: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    message_id: Mapped[object] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    role_prompt: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    expect_output: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    required_tools: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'running'::character varying"))
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    iteration_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    partial_answer: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    total_token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False, server_default=text("0.0"))
```

`internal/model/__init__.py`：`from .sub_task_checkpoint import SubTaskCheckpoint` 并加入 `__all__`（照现有条目格式）。

`internal/entity/app_entity.py` 的 `DEFAULT_APP_CONFIG`（`review_config` 之前）新增：

```python
    "orchestrator_config": {
        "enable": False,          # 是否启用任务分解
        "max_sub_tasks": 5,       # 子任务数上限
        "max_parallel": 3,        # 最大并行数
        "sub_task_timeout": 300,  # 单子任务超时(秒)
        "resume_mode": "auto",    # 断点恢复触发：auto 自动续跑 / manual 仅显式触发
    },
```

生成迁移：`flask db revision -m "orchestrator subagent"`，然后编辑生成的版本文件，在 `upgrade()` 中追加：

```python
def upgrade():
    # App.app_type
    with op.batch_alter_table('app', schema=None) as batch_op:
        batch_op.add_column(sa.Column('app_type', sa.String(length=50), server_default=sa.text("'agent'::character varying"), nullable=False))
    # AppConfig / AppConfigVersion .orchestrator_config
    with op.batch_alter_table('app_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('orchestrator_config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))
    with op.batch_alter_table('app_config_version', schema=None) as batch_op:
        batch_op.add_column(sa.Column('orchestrator_config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))
    # message_agent_thought 子任务归属
    with op.batch_alter_table('message_agent_thought', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sub_task_id', postgresql.UUID(as_uuid=True), nullable=True))
        batch_op.add_column(sa.Column('sub_task_title', sa.Text(), server_default=sa.text("''::text"), nullable=False))
    # 新表 sub_task_checkpoint
    op.create_table('sub_task_checkpoint',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('app_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('query', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('title', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('role_prompt', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('expect_output', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('required_tools', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('status', sa.String(length=50), server_default=sa.text("'running'::character varying"), nullable=False),
        sa.Column('messages', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('iteration_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('partial_answer', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('total_token_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('total_price', sa.Numeric(10, 7), server_default=sa.text('0.0'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_sub_task_checkpoint_id'),
    )
    op.create_index('idx_sub_task_checkpoint_conv_pos', 'sub_task_checkpoint', ['conversation_id', 'position'])

def downgrade():
    op.drop_index('idx_sub_task_checkpoint_conv_pos', table_name='sub_task_checkpoint')
    op.drop_table('sub_task_checkpoint')
    with op.batch_alter_table('message_agent_thought', schema=None) as batch_op:
        batch_op.drop_column('sub_task_title')
        batch_op.drop_column('sub_task_id')
    with op.batch_alter_table('app_config_version', schema=None) as batch_op:
        batch_op.drop_column('orchestrator_config')
    with op.batch_alter_table('app_config', schema=None) as batch_op:
        batch_op.drop_column('orchestrator_config')
    with op.batch_alter_table('app', schema=None) as batch_op:
        batch_op.drop_column('app_type')
```

（迁移文件头部需 `import sqlalchemy as sa`、`from sqlalchemy.dialects import postgresql`。）

- [ ] **Step 4: 验证迁移与模型**

Run: `flask db upgrade head && python -m pytest test/internal/model/test_sub_task_checkpoint.py -v`
Expected: PASS（迁移成功，模型测试通过）
再验证回滚：`flask db downgrade -1 && flask db upgrade head`

- [ ] **Step 5: 提交**

```bash
git add internal/model/ internal/entity/app_entity.py internal/migrations/versions/ test/internal/model/test_sub_task_checkpoint.py
git commit -m "feat(model): 编排型应用类型+子任务断点表与迁移"
```

---

### Task 5: SubTaskService（断点读写）

**Files:**
- Create: `internal/service/sub_task_service.py`
- Modify: `internal/service/__init__.py`（导出 `SubTaskService`，照现有格式）
- Test: `test/internal/service/test_sub_task_service.py`

**Interfaces:**
- Consumes: `BaseService`、`SubTaskCheckpoint` 模型、`SubTaskSpec`
- Produces:
  - `save_checkpoint(*, app_id, conversation_id, message_id, position, query, spec, status, messages, iteration_count, partial_answer, total_token_count=0, total_price=0.0) -> None`（存在则更新，不存在则创建）
  - `get_checkpoint(conversation_id, position) -> SubTaskCheckpoint | None`
  - `get_resumable_checkpoints(conversation_id, query) -> list[SubTaskCheckpoint]`（status ∈ {running, stop, timeout, error}）
  - `mark_complete(*, conversation_id, position, answer, total_token_count, total_price) -> None`
  - `clear_checkpoints(conversation_id) -> None`
  - `has_resumable_checkpoints(conversation_id, query) -> bool`（供 can_resume）

- [ ] **Step 1: 写失败测试**

创建 `test/internal/service/test_sub_task_service.py`：

```python
import uuid

from internal.core.agent.entities.agent_entity import SubTaskSpec
from internal.service.sub_task_service import SubTaskService


def _make_spec(order: int) -> SubTaskSpec:
    return SubTaskSpec(order=order, title="子任务", role_prompt="角色", expect_output="输出")


def test_save_and_get_checkpoint(app, db):
    service = SubTaskService(db=db)
    conv_id = uuid.uuid4()
    app_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    spec = _make_spec(1)

    service.save_checkpoint(
        app_id=app_id, conversation_id=conv_id, message_id=msg_id, position=1,
        query="写报告", spec=spec, status="stop",
        messages=[{"type": "human", "data": {"content": "x"}}], iteration_count=2,
        partial_answer="部分内容",
    )
    ck = service.get_checkpoint(conv_id, 1)
    assert ck is not None
    assert ck.status == "stop"
    assert ck.partial_answer == "部分内容"
    assert ck.iteration_count == 2

    # 再次保存应更新而非新增
    service.save_checkpoint(
        app_id=app_id, conversation_id=conv_id, message_id=msg_id, position=1,
        query="写报告", spec=spec, status="running",
        messages=[], iteration_count=3, partial_answer="更多",
    )
    ck2 = service.get_checkpoint(conv_id, 1)
    assert ck2.iteration_count == 3


def test_resumable_and_complete(app, db):
    service = SubTaskService(db=db)
    conv_id = uuid.uuid4()
    spec = _make_spec(1)
    service.save_checkpoint(
        app_id=uuid.uuid4(), conversation_id=conv_id, message_id=uuid.uuid4(),
        position=1, query="写报告", spec=spec, status="timeout",
        messages=[], iteration_count=1, partial_answer="",
    )
    assert service.has_resumable_checkpoints(conv_id, "写报告") is True
    assert service.has_resumable_checkpoints(conv_id, "别的任务") is False

    service.mark_complete(conversation_id=conv_id, position=1, answer="最终结果", total_token_count=10, total_price=0.01)
    assert service.get_resumable_checkpoints(conv_id, "写报告") == []
    ck = service.get_checkpoint(conv_id, 1)
    assert ck.status == "complete"
    assert ck.partial_answer == "最终结果"


def test_clear_checkpoints(app, db):
    service = SubTaskService(db=db)
    conv_id = uuid.uuid4()
    service.save_checkpoint(
        app_id=uuid.uuid4(), conversation_id=conv_id, message_id=uuid.uuid4(),
        position=1, query="q", spec=_make_spec(1), status="stop",
        messages=[], iteration_count=0, partial_answer="",
    )
    service.clear_checkpoints(conv_id)
    assert service.get_checkpoint(conv_id, 1) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_sub_task_service.py -v`
Expected: FAIL（ModuleNotFoundError: internal.service.sub_task_service）

- [ ] **Step 3: 实现**

创建 `internal/service/sub_task_service.py`：

```python
#!/usr/bin/env python
"""子任务断点服务：保存/查询/标记完成/清理"""
from dataclasses import dataclass
from uuid import UUID

from injector import inject
from sqlalchemy import select

from internal.core.agent.entities.agent_entity import SubTaskSpec
from internal.model import SubTaskCheckpoint
from package.sqlalchemy import SQLAlchemy

from .base_service import BaseService

# 可恢复状态：断点续跑的前提
RESUMABLE_STATUSES = ("running", "stop", "timeout", "error")
COMPLETE_STATUS = "complete"


@inject
@dataclass
class SubTaskService(BaseService):
    db: SQLAlchemy

    def save_checkpoint(
            self,
            *,
            app_id: UUID,
            conversation_id: UUID,
            message_id: UUID,
            position: int,
            query: str,
            spec: SubTaskSpec,
            status: str,
            messages: list,
            iteration_count: int,
            partial_answer: str,
            total_token_count: int = 0,
            total_price: float = 0.0,
    ) -> None:
        """保存（或更新）指定位置的子任务断点"""
        record = self.get_checkpoint(conversation_id, position)
        data = dict(
            title=spec.title, role_prompt=spec.role_prompt, expect_output=spec.expect_output,
            required_tools=spec.required_tools, status=status, messages=messages,
            iteration_count=iteration_count, partial_answer=partial_answer,
            total_token_count=total_token_count, total_price=total_price,
            updated_by=conversation_id,
        )
        if record is None:
            self.create(
                SubTaskCheckpoint,
                app_id=app_id, conversation_id=conversation_id, message_id=message_id,
                position=position, query=query,
                created_by=conversation_id, updated_by=conversation_id,
                **data,
            )
        else:
            self.update(record, **data)

    def get_checkpoint(self, conversation_id: UUID, position: int) -> SubTaskCheckpoint | None:
        stmt = select(SubTaskCheckpoint).where(
            SubTaskCheckpoint.conversation_id == conversation_id,
            SubTaskCheckpoint.position == position,
        )
        return self.db.session.execute(stmt).scalar_one_or_none()

    def get_resumable_checkpoints(self, conversation_id: UUID, query: str) -> list[SubTaskCheckpoint]:
        stmt = select(SubTaskCheckpoint).where(
            SubTaskCheckpoint.conversation_id == conversation_id,
            SubTaskCheckpoint.query == query,
            SubTaskCheckpoint.status.in_(RESUMABLE_STATUSES),
        )
        return list(self.db.session.execute(stmt).scalars().all())

    def has_resumable_checkpoints(self, conversation_id: UUID, query: str) -> bool:
        return len(self.get_resumable_checkpoints(conversation_id, query)) > 0

    def mark_complete(
            self,
            *,
            conversation_id: UUID,
            position: int,
            answer: str,
            total_token_count: int,
            total_price: float,
    ) -> None:
        """子任务成功完成：写入最终答案缓存并标记 complete"""
        record = self.get_checkpoint(conversation_id, position)
        if record is None:
            return
        self.update(
            record,
            status=COMPLETE_STATUS, partial_answer=answer,
            total_token_count=total_token_count, total_price=total_price,
            updated_by=conversation_id,
        )

    def clear_checkpoints(self, conversation_id: UUID) -> None:
        """删除会话下的全部断点（会话/消息删除时级联清理）"""
        stmt = select(SubTaskCheckpoint).where(SubTaskCheckpoint.conversation_id == conversation_id)
        for record in self.db.session.execute(stmt).scalars().all():
            self.db.session.delete(record)
```

`internal/service/__init__.py`：照现有条目追加 `from .sub_task_service import SubTaskService` 并加入导出列表。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_sub_task_service.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add internal/service/sub_task_service.py internal/service/__init__.py test/internal/service/test_sub_task_service.py
git commit -m "feat(service): SubTaskService 子任务断点保存/查询/清理"
```

---

### Task 6: save_agent_thoughts 白名单与透传

**Files:**
- Modify: `internal/service/conversation_service.py:250-286`
- Test: `test/internal/service/test_sub_task_thoughts.py`

**Interfaces:**
- Consumes: `QueueEvent.SUB_TASK_*`、`AgentThought.sub_task_id / sub_task_title`
- Produces: `MessageAgentThought` 行包含 `sub_task_id` / `sub_task_title`；`SUB_TASK_PLAN / SUB_TASK_START / SUB_TASK_END` 事件被持久化

- [ ] **Step 1: 写失败测试**

创建 `test/internal/service/test_sub_task_thoughts.py`：

```python
import uuid

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.conversation_entity import InvokeFrom
from internal.model import Conversation, Message, MessageAgentThought
from internal.service.conversation_service import ConversationService


def test_save_agent_thoughts_persists_sub_task_events(app, db):
    from internal.service import ConversationService as CS
    from package.sqlalchemy import SQLAlchemy

    service = CS(db=db)
    account_id = uuid.uuid4()
    app_id = uuid.uuid4()
    conversation = service.create(
        Conversation, app_id=app_id, name="测试", invoke_from=InvokeFrom.DEBUGGER,
        created_by=account_id, updated_by=account_id,
    )
    message = service.create(
        Message, app_id=app_id, conversation_id=conversation.id,
        query="写报告", created_by=account_id, updated_by=account_id,
    )
    sub_task_id = uuid.uuid4()
    thoughts = [
        AgentThought(id=uuid.uuid4(), task_id=uuid.uuid4(), event=QueueEvent.SUB_TASK_PLAN,
                     thought='[{"title": "调研"}]', message=[]),
        AgentThought(id=uuid.uuid4(), task_id=uuid.uuid4(), event=QueueEvent.SUB_TASK_START,
                     thought="调研员", sub_task_id=sub_task_id, sub_task_title="调研", message=[]),
        AgentThought(id=uuid.uuid4(), task_id=uuid.uuid4(), event=QueueEvent.SUB_TASK_END,
                     observation="完成", latency=1.2, sub_task_id=sub_task_id, sub_task_title="调研", message=[]),
    ]
    service.save_agent_thoughts(
        account_id=account_id, app_id=app_id, app_config={},
        conversation_id=conversation.id, message_id=message.id,
        agent_thoughts=thoughts, invoke_from=InvokeFrom.DEBUGGER,
    )
    rows = db.session.query(MessageAgentThought).filter_by(message_id=message.id).order_by(
        MessageAgentThought.position
    ).all()
    assert len(rows) == 3
    start_row = rows[1]
    assert start_row.sub_task_id == sub_task_id
    assert start_row.sub_task_title == "调研"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_sub_task_thoughts.py -v`
Expected: FAIL（SUB_TASK_* 不在白名单，仅 0 行被保存）

- [ ] **Step 3: 实现**

`internal/service/conversation_service.py` 的 `save_agent_thoughts`：

1) 白名单列表加入三个新事件：

```python
            if agent_thought.event in [
                QueueEvent.LONG_TERM_MEMORY_RECALL,
                QueueEvent.AGENT_THOUGHT,
                QueueEvent.AGENT_MESSAGE,
                QueueEvent.AGENT_ACTION,
                QueueEvent.DATASET_RETRIEVAL,
                QueueEvent.SUB_TASK_PLAN,
                QueueEvent.SUB_TASK_START,
                QueueEvent.SUB_TASK_END,
            ]:
```

2) `self.create(MessageAgentThought, ...)` 的参数追加：

```python
                    sub_task_id=agent_thought.sub_task_id,
                    sub_task_title=agent_thought.sub_task_title,
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_sub_task_thoughts.py -v`
Expected: PASS
回归：`python -m pytest test/internal/service/test_conversation_service.py -v`

- [ ] **Step 5: 提交**

```bash
git add internal/service/conversation_service.py test/internal/service/test_sub_task_thoughts.py
git commit -m "feat(service): save_agent_thoughts 持久化 SUB_TASK_* 事件与子任务归属"
```

---

### Task 7: OrchestratorAgent 核心（规划/并行执行/汇总，无断点）

**Files:**
- Create: `internal/core/agent/agents/orchestrator_agent.py`
- Modify: `internal/core/agent/agents/__init__.py`
- Test: `test/internal/core/agent/test_orchestrator_agent.py`

**Interfaces:**
- Consumes: `BaseAgent`、`AgentConfig`、`AgentState`、`SubTaskPlan/SubTaskSpec/SubTaskResult`、`QueueEvent.SUB_TASK_*`、`AgentQueueManager.forward`、`FunctionCallAgent`/`ReACTAgent`（Task 3 条件入口）、提示词模板（Task 1）
- Produces: `OrchestratorAgent`（在 `internal/core/agent/agents/__init__.py` 导出）。图 = plan → (execute → summarize | direct_answer)。事件流：`SUB_TASK_PLAN → SUB_TASK_START×N →（子事件桥接，带 sub_task_id/sub_task_title）→ SUB_TASK_END×N → AGENT_END`（或 direct_answer 直接 AGENT_MESSAGE → AGENT_END）
- 本任务 execute **不做断点**（Task 8 加入）；停止监控已实现（主 stop → 子 stop 标志）

- [ ] **Step 1: 写失败测试**

创建 `test/internal/core/agent/test_orchestrator_agent.py`：

```python
import json
import threading
import time
import uuid

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage
from pydantic import ConfigDict

from internal.core.agent.agents import OrchestratorAgent
from internal.core.agent.entities.agent_entity import AgentConfig, SubTaskPlan, SubTaskSpec
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.entity.conversation_entity import InvokeFrom


class FakeOrchestratorLLM(BaseLanguageModel):
    """假 LLM：with_structured_output 返回固定计划；stream 产出固定文本"""
    model_config = ConfigDict(extra="allow")

    def __init__(self, *, subtasks=None, features=None, **kwargs):
        super().__init__(**kwargs)
        self._subtasks = subtasks
        self.features = features or [ModelFeature.TOOL_CALL]

    def with_structured_output(self, schema, **kwargs):
        class FakePlanner:
            def invoke(self, messages):
                return SubTaskPlan(subtasks=self._subtasks or [])
        return FakePlanner()

    def stream(self, messages):
        yield AIMessageChunk(content="好的", tool_calls=[])

    def get_num_tokens_safe(self, messages):
        return 10

    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


class StubQueueManager:
    """进程内收集事件，替代依赖 Redis 的真实管理器"""

    def __init__(self, user_id=None, invoke_from=None):
        self.events = []
        self._done = threading.Event()

    def publish(self, task_id, thought):
        self.events.append(thought)
        if thought.event in (QueueEvent.AGENT_END, QueueEvent.ERROR, QueueEvent.STOP, QueueEvent.TIMEOUT):
            self._done.set()

    def publish_error(self, task_id, error):
        self.publish(task_id, AgentThought(
            id=uuid.uuid4(), task_id=task_id,
            event=QueueEvent.ERROR, observation=str(error),
        ))

    def forward(self, task_id, thought):
        self.events.append(thought)

    def stop_listen(self, task_id):
        self._done.set()

    def listen(self, task_id):
        deadline = time.time() + 15
        while time.time() < deadline:
            if self._done.is_set():
                yield from self.events
                return
            time.sleep(0.01)
        raise AssertionError("编排器图 15s 内未完成推理")

    def _is_stopped(self, task_id):
        return False


def _run_agent(monkeypatch, llm, input_extra=None):
    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    agent = OrchestratorAgent(
        name="orch",
        llm=llm,
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP,
            preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 2, "resume_mode": "auto"},
        ),
    )
    base = {"messages": [HumanMessage(content="写一篇市场调研报告")], "history": []}
    if input_extra:
        base.update(input_extra)
    return list(agent.stream(base))


def test_orchestrator_decomposes_and_runs_subtasks(monkeypatch):
    specs = [
        SubTaskSpec(order=1, title="市场调研", role_prompt="你是调研员，负责收集市场数据", expect_output="调研结论"),
        SubTaskSpec(order=2, title="报告撰写", role_prompt="你是撰稿人，负责写报告", expect_output="报告正文"),
    ]
    events = _run_agent(monkeypatch, FakeOrchestratorLLM(subtasks=specs))
    kinds = [e.event for e in events]
    assert QueueEvent.SUB_TASK_PLAN in kinds
    assert kinds.count(QueueEvent.SUB_TASK_START) == 2
    assert kinds.count(QueueEvent.SUB_TASK_END) == 2
    assert kinds.count(QueueEvent.AGENT_END) == 1
    # 子任务事件带归属
    sub_events = [e for e in events if e.event == QueueEvent.AGENT_MESSAGE and e.sub_task_id]
    assert sub_events, "子 Agent 消息事件应桥接并带 sub_task_id"
    assert sub_events[0].sub_task_title in ("市场调研", "报告撰写")


def test_orchestrator_without_subtasks_degrades_to_direct_answer(monkeypatch):
    events = _run_agent(monkeypatch, FakeOrchestratorLLM(subtasks=[]))
    kinds = [e.event for e in events]
    assert QueueEvent.SUB_TASK_PLAN not in kinds
    assert QueueEvent.SUB_TASK_START not in kinds
    assert kinds.count(QueueEvent.AGENT_END) == 1
    assert any(e.event == QueueEvent.AGENT_MESSAGE for e in events)


def test_orchestrator_summarizes_sub_results(monkeypatch):
    specs = [SubTaskSpec(order=1, title="调研", role_prompt="调研", expect_output="结论")]
    events = _run_agent(monkeypatch, FakeOrchestratorLLM(subtasks=specs))
    # summarize 阶段产出 AGENT_MESSAGE（不带 sub_task_id）
    final_messages = [e for e in events if e.event == QueueEvent.AGENT_MESSAGE and not e.sub_task_id]
    assert final_messages, "汇总阶段应产出主消息"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/core/agent/test_orchestrator_agent.py -v`
Expected: FAIL（ImportError: cannot import name 'OrchestratorAgent'）

- [ ] **Step 3: 实现**

创建 `internal/core/agent/agents/orchestrator_agent.py`：

```python
#!/usr/bin/env python
"""编排器智能体：任务分解 → 并行子Agent执行 → 汇总

图结构：plan → (execute → summarize | direct_answer) → END
子 Agent 事件通过 AgentQueueManager.forward 桥接进主队列（带 sub_task_id/sub_task_title）。
断点保存/恢复由 Task 8 在 _run_subtask 中加入。
"""
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, messages_to_dict
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.agents.base_agent import BaseAgent
from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.core.agent.agents.react_agent import ReACTAgent
from internal.core.agent.entities.agent_entity import (
    ORCHESTRATOR_PLAN_SYSTEM_PROMPT_TEMPLATE,
    ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE,
    AgentConfig,
    AgentState,
    SubTaskPlan,
    SubTaskResult,
    SubTaskSpec,
)
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import ModelFeature

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    """编排器智能体"""

    def _build_agent(self) -> CompiledStateGraph:
        graph = StateGraph(AgentState)
        graph.add_node("plan", self._plan_node)
        graph.add_node("direct_answer", self._direct_answer_node)
        graph.add_node("execute", self._execute_node)
        graph.add_node("summarize", self._summarize_node)

        graph.set_entry_point("plan")
        graph.add_conditional_edges("plan", self._plan_condition)
        graph.add_edge("execute", "summarize")
        graph.add_edge("summarize", END)
        graph.add_edge("direct_answer", END)
        return graph.compile()

    @classmethod
    def _plan_condition(cls, state: AgentState) -> Literal["execute", "direct_answer"]:
        return "execute" if state["sub_tasks"] else "direct_answer"

    def _plan_node(self, state: AgentState) -> AgentState:
        """规划节点：LLM 结构化输出子任务清单"""
        cfg = self.agent_config.orchestrator_config or {}
        max_sub_tasks = cfg.get("max_sub_tasks", 5)
        system_prompt = ORCHESTRATOR_PLAN_SYSTEM_PROMPT_TEMPLATE.format(max_sub_tasks=max_sub_tasks)
        plan_llm = self.llm.with_structured_output(SubTaskPlan)
        plan = plan_llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=state["query"]),
        ])
        specs = plan.subtasks if plan and plan.subtasks else []
        specs = specs[:max_sub_tasks]
        # 派发子任务id
        for spec in specs:
            spec.task_id = spec.task_id or uuid.uuid4()

        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(), task_id=state["task_id"],
            event=QueueEvent.SUB_TASK_PLAN,
            thought=json.dumps([s.model_dump(exclude={"task_id"}) for s in specs], ensure_ascii=False),
            message=messages_to_dict(state["messages"]),
        ))
        return {"sub_tasks": specs}

    def _direct_answer_node(self, state: AgentState) -> AgentState:
        """无子任务时直接回答（退化为普通 Agent）"""
        stream_id = uuid.uuid4()
        gathered = None
        for chunk in self.llm.stream([
            SystemMessage(content=ORCHESTRATOR_PLAN_SYSTEM_PROMPT_TEMPLATE.format(max_sub_tasks=5)),
            HumanMessage(content=state["query"]),
        ]):
            if gathered is None:
                gathered = chunk
            else:
                gathered += chunk
            if chunk.content:
                self.agent_queue_manager.publish(state["task_id"], AgentThought(
                    id=stream_id, task_id=state["task_id"],
                    event=QueueEvent.AGENT_MESSAGE,
                    thought=chunk.content, message=messages_to_dict(state["messages"]),
                    answer=chunk.content,
                ))
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(), task_id=state["task_id"], event=QueueEvent.AGENT_END,
        ))
        return {"messages": [gathered or AIMessage(content="")]}

    def _execute_node(self, state: AgentState) -> AgentState:
        """并行执行子任务：每个子任务一个工作线程，事件桥接进主队列"""
        specs = state["sub_tasks"]
        cfg = self.agent_config.orchestrator_config or {}
        max_parallel = cfg.get("max_parallel", 3)
        results: dict[int, SubTaskResult] = {}
        running_ids: set = set()
        ids_lock = threading.Lock()

        # 停止监控：主任务被停止时，给所有运行中子任务设置停止标志
        def monitor_stop():
            while True:
                if self.agent_queue_manager._is_stopped(state["task_id"]):
                    with ids_lock:
                        for tid in list(running_ids):
                            AgentQueueManager.set_stop_flag(
                                tid, self.agent_config.invoke_from, self.agent_config.user_id,
                            )
                    return
                time.sleep(0.5)

        monitor = threading.Thread(target=monitor_stop, daemon=True)
        monitor.start()

        try:
            with ThreadPoolExecutor(max_workers=max_parallel) as pool:
                futures = {
                    pool.submit(self._run_subtask, state, spec, running_ids, ids_lock): spec
                    for spec in specs
                }
                for fut in as_completed(futures):
                    spec = futures[fut]
                    try:
                        results[spec.order] = fut.result()
                    except Exception as e:
                        logger.exception("子任务执行失败 order=%s", spec.order)
                        results[spec.order] = SubTaskResult(
                            order=spec.order, title=spec.title, status="error", error=str(e),
                        )
        finally:
            monitor.join(timeout=5)

        return {"sub_results": [results[o] for o in sorted(results)]}

    def _run_subtask(self, state: AgentState, spec: SubTaskSpec, running_ids: set, ids_lock: threading.Lock) -> SubTaskResult:
        """单个子任务：动态创建子 Agent，流式执行并桥接事件"""
        sub_task_id = spec.task_id or uuid.uuid4()
        with ids_lock:
            running_ids.add(sub_task_id)
        started = time.perf_counter()
        try:
            self._publish_sub_task_event(state, QueueEvent.SUB_TASK_START, spec, thought=spec.role_prompt[:200], sub_task_id=sub_task_id)

            sub_agent = self._build_sub_agent(spec)
            input_data = {
                "messages": [self.llm.convert_to_human_message(state["query"], None)],
                "history": [],
                "iteration_count": 0,
                "resume": False,
            }
            answer_parts = []
            for thought in sub_agent.stream(input_data):
                if thought.event in (QueueEvent.PING, QueueEvent.AGENT_END, QueueEvent.STOP, QueueEvent.TIMEOUT, QueueEvent.ERROR):
                    continue
                bridged = thought.model_copy(update={"sub_task_id": sub_task_id, "sub_task_title": spec.title})
                self.agent_queue_manager.forward(state["task_id"], bridged)
                if thought.event == QueueEvent.AGENT_MESSAGE:
                    answer_parts.append(thought.answer)
        except Exception as e:
            logger.exception("子任务异常 order=%s", spec.order)
            self._publish_sub_task_event(state, QueueEvent.SUB_TASK_END, spec, observation=f"error: {e}", latency=time.perf_counter() - started, sub_task_id=sub_task_id)
            return SubTaskResult(order=spec.order, title=spec.title, status="error", error=str(e), latency=time.perf_counter() - started)
        finally:
            with ids_lock:
                running_ids.discard(sub_task_id)

        answer = "".join(answer_parts)
        self._publish_sub_task_event(state, QueueEvent.SUB_TASK_END, spec, observation=answer[:500], latency=time.perf_counter() - started, sub_task_id=sub_task_id)
        return SubTaskResult(order=spec.order, title=spec.title, status="normal", answer=answer, latency=time.perf_counter() - started)

    def _build_sub_agent(self, spec: SubTaskSpec):
        """动态创建子 Agent（支持 tool_call 用 FunctionCallAgent，否则 ReACTAgent）"""
        cls = FunctionCallAgent if ModelFeature.TOOL_CALL in self.llm.features else ReACTAgent
        return cls(
            name=f"sub-{spec.order}",
            llm=self.llm,
            agent_config=AgentConfig(
                user_id=self.agent_config.user_id,
                invoke_from=self.agent_config.invoke_from,
                preset_prompt=spec.role_prompt,
                tools=self.agent_config.tools,
                review_config=self.agent_config.review_config,
            ),
        )

    def _publish_sub_task_event(self, state: AgentState, event: QueueEvent, spec: SubTaskSpec, *, thought: str = "", observation: str = "", latency: float = 0.0, sub_task_id: uuid.UUID) -> None:
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(), task_id=state["task_id"], event=event,
            thought=thought, observation=observation, latency=latency,
            sub_task_id=sub_task_id, sub_task_title=spec.title,
            message=messages_to_dict(state["messages"]),
        ))

    def _summarize_node(self, state: AgentState) -> AgentState:
        """汇总节点：综合子任务结果生成最终答案"""
        lines = []
        for r in state["sub_results"]:
            body = r.answer if r.status == "normal" else f"（{r.status}）{r.error or '无结果'}"
            lines.append(f"【子任务{r.order}】{r.title}：\n{body}")
        prompt = ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE.format(
            query=state["query"], sub_results_text="\n".join(lines),
        )
        stream_id = uuid.uuid4()
        gathered = None
        for chunk in self.llm.stream([SystemMessage(content=prompt)]):
            if gathered is None:
                gathered = chunk
            else:
                gathered += chunk
            if chunk.content:
                self.agent_queue_manager.publish(state["task_id"], AgentThought(
                    id=stream_id, task_id=state["task_id"],
                    event=QueueEvent.AGENT_MESSAGE,
                    thought=chunk.content, message=messages_to_dict(state["messages"]),
                    answer=chunk.content,
                ))
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(), task_id=state["task_id"], event=QueueEvent.AGENT_END,
        ))
        return {"messages": [gathered or AIMessage(content="")]}
```

`internal/core/agent/agents/__init__.py`：

```python
from .orchestrator_agent import OrchestratorAgent
```
并加入 `__all__`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/core/agent/test_orchestrator_agent.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/agents/orchestrator_agent.py internal/core/agent/agents/__init__.py test/internal/core/agent/test_orchestrator_agent.py
git commit -m "feat(agent): OrchestratorAgent 规划/并行子Agent执行/汇总"
```

---

### Task 8: 断点保存与恢复集成（resume_mode auto/manual）

**Files:**
- Modify: `internal/core/agent/agents/orchestrator_agent.py`
- Test: `test/internal/core/agent/test_orchestrator_resume.py`

**Interfaces:**
- Consumes: `SubTaskService`（Task 5）、`AgentState.conversation_id / query / resume_trigger`、`AgentState.resume`（Task 3 条件入口）
- Produces: execute 对每个子任务：断点查询 → 恢复续跑 / 复用 complete 缓存 / 全新执行；运行中周期落盘；异常终止保存；完成时 mark_complete。`SubTaskResult.resumed` 标记恢复。
- `SubTaskService` 通过 `from app.http.module import injector` 懒加载（与 `agent_queue_manager` 取 Redis 同模式），避免 core→service 循环导入。

- [ ] **Step 1: 写失败测试**

创建 `test/internal/core/agent/test_orchestrator_resume.py`（复用 Task 7 的 `FakeOrchestratorLLM` / `StubQueueManager`，可复制到本文件）：

```python
import uuid

import pytest
from langchain_core.messages import HumanMessage

from internal.core.agent.agents import OrchestratorAgent
from internal.core.agent.entities.agent_entity import AgentConfig, SubTaskSpec
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.agent.entities.queue_entity import QueueEvent as QE
from internal.entity.conversation_entity import InvokeFrom
from internal.model import SubTaskCheckpoint
from internal.service.sub_task_service import SubTaskService

# （FakeOrchestratorLLM / StubQueueManager 与 test_orchestrator_agent.py 相同，这里省略重复定义——见该文件）


def test_resume_auto_continues_from_checkpoint(app, db, monkeypatch):
    """auto 模式：断点存在且 query 匹配 → 子任务恢复续跑（resume=True 输入）"""
    from test.internal.core.agent.test_orchestrator_agent import FakeOrchestratorLLM, StubQueueManager
    from langchain_core.messages import AIMessageChunk
    from pydantic import ConfigDict
    from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature

    captured = {}

    class RecordingLLM(FakeOrchestratorLLM):
        def stream(self, messages):
            captured["last_input"] = messages
            yield from super().stream(messages)

    class RecordingQueue(StubQueueManager):
        def __init__(self, user_id=None, invoke_from=None):
            super().__init__(user_id=user_id, invoke_from=invoke_from)
            self.sub_inputs = []

    # 预置断点：position 1 已中断
    service = SubTaskService(db=db)
    conv_id = uuid.uuid4()
    spec = SubTaskSpec(order=1, title="调研", role_prompt="调研员", expect_output="结论")
    service.save_checkpoint(
        app_id=uuid.uuid4(), conversation_id=conv_id, message_id=uuid.uuid4(),
        position=1, query="写报告", spec=spec, status="stop",
        messages=[{"type": "human", "data": {"content": "x"}}], iteration_count=2,
        partial_answer="部分内容",
    )

    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", RecordingQueue)
    # 注入真实 SubTaskService（断点查询走 DB）；orchestrator_agent 内是局部 from app.http.module import injector
    monkeypatch.setattr(
        "app.http.module.injector",
        type("FakeInjector", (), {"get": lambda self, cls, *a, **k: service if cls is SubTaskService else None})(),
    )

    agent = OrchestratorAgent(
        name="orch",
        llm=RecordingLLM(subtasks=[spec]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"max_sub_tasks": 5, "max_parallel": 1, "resume_mode": "auto"},
        ),
    )
    events = list(agent.stream({
        "messages": [HumanMessage(content="写报告")],
        "history": [],
        "conversation_id": conv_id,
        "query": "写报告",
        "resume_trigger": False,
    }))
    # 恢复执行：事件中应出现子任务消息事件
    sub_msgs = [e for e in events if e.event == QE.AGENT_MESSAGE and e.sub_task_id]
    assert sub_msgs, "断点恢复后子任务应继续产出事件"
    # 完成后断点应标记 complete
    ck = service.get_checkpoint(conv_id, 1)
    assert ck.status == "complete"


def test_resume_manual_ignores_checkpoint_without_trigger(app, db, monkeypatch):
    """manual 模式：resume_trigger=False → 不查断点，全新执行（断点仍为 stop）"""
    from test.internal.core.agent.test_orchestrator_agent import FakeOrchestratorLLM, StubQueueManager

    service = SubTaskService(db=db)
    conv_id = uuid.uuid4()
    spec = SubTaskSpec(order=1, title="调研", role_prompt="调研员", expect_output="结论")
    service.save_checkpoint(
        app_id=uuid.uuid4(), conversation_id=conv_id, message_id=uuid.uuid4(),
        position=1, query="写报告", spec=spec, status="stop",
        messages=[], iteration_count=2, partial_answer="部分内容",
    )
    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", StubQueueManager)
    monkeypatch.setattr(
        "app.http.module.injector",
        type("FakeInjector", (), {"get": lambda self, cls, *a, **k: service if cls is SubTaskService else None})(),
    )
    agent = OrchestratorAgent(
        name="orch", llm=FakeOrchestratorLLM(subtasks=[spec]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"resume_mode": "manual"},
        ),
    )
    events = list(agent.stream({
        "messages": [HumanMessage(content="写报告")], "history": [],
        "conversation_id": conv_id, "query": "写报告", "resume_trigger": False,
    }))
    ck = service.get_checkpoint(conv_id, 1)
    assert ck.status == "complete"  # 全新执行并覆盖断点


def test_resume_reuses_completed_cache(app, db, monkeypatch):
    """complete 断点 → 子任务跳过执行，直接复用缓存答案"""
    from test.internal.core.agent.test_orchestrator_agent import FakeOrchestratorLLM, StubQueueManager

    service = SubTaskService(db=db)
    conv_id = uuid.uuid4()
    spec = SubTaskSpec(order=1, title="调研", role_prompt="调研员", expect_output="结论")
    service.save_checkpoint(
        app_id=uuid.uuid4(), conversation_id=conv_id, message_id=uuid.uuid4(),
        position=1, query="写报告", spec=spec, status="stop",
        messages=[], iteration_count=1, partial_answer="",
    )
    service.mark_complete(conversation_id=conv_id, position=1, answer="缓存答案", total_token_count=1, total_price=0.0)

    seen_sub_start = []

    class CountingQueue(StubQueueManager):
        def __init__(self, user_id=None, invoke_from=None):
            super().__init__(user_id=user_id, invoke_from=invoke_from)

        def publish(self, task_id, thought):
            if thought.event == QE.SUB_TASK_START:
                seen_sub_start.append(thought)
            super().publish(task_id, thought)

    monkeypatch.setattr("internal.core.agent.agents.base_agent.AgentQueueManager", CountingQueue)
    monkeypatch.setattr(
        "app.http.module.injector",
        type("FakeInjector", (), {"get": lambda self, cls, *a, **k: service if cls is SubTaskService else None})(),
    )
    agent = OrchestratorAgent(
        name="orch", llm=FakeOrchestratorLLM(subtasks=[spec]),
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.WEB_APP, preset_prompt="", tools=[],
            orchestrator_config={"resume_mode": "auto"},
        ),
    )
    list(agent.stream({
        "messages": [HumanMessage(content="写报告")], "history": [],
        "conversation_id": conv_id, "query": "写报告", "resume_trigger": False,
    }))
    assert seen_sub_start == [], "complete 缓存子任务不应重新执行（不发布 SUB_TASK_START）"
```

注意：`test_resume_auto_continues_from_checkpoint` 中断点恢复以 `resume=True` 调子 Agent；FakeOrchestratorLLM 的 stream 不关心消息内容，测试只断言事件与断点状态变化。若 `injector` 打桩影响 AgentQueueManager 内建获取（本测试已把 base_agent 的 AgentQueueManager 换成 Stub），无冲突。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/core/agent/test_orchestrator_resume.py -v`
Expected: FAIL（Task 7 的 `_run_subtask` 尚无断点逻辑：auto 恢复测试中断点不会变 complete、manual 测试中断点仍 stop）

- [ ] **Step 3: 实现**

`internal/core/agent/agents/orchestrator_agent.py` 修改 `_execute_node` 与 `_run_subtask`：

`_execute_node` 传入恢复参数并加超时：

```python
    def _execute_node(self, state: AgentState) -> AgentState:
        """并行执行子任务：断点恢复 / 缓存复用 / 全新执行，事件桥接进主队列"""
        specs = state["sub_tasks"]
        cfg = self.agent_config.orchestrator_config or {}
        max_parallel = cfg.get("max_parallel", 3)
        resume_mode = cfg.get("resume_mode", "auto")
        sub_task_timeout = cfg.get("sub_task_timeout", 300)
        results: dict[int, SubTaskResult] = {}
        running_ids: set = set()
        ids_lock = threading.Lock()

        def monitor_stop():
            while True:
                if self.agent_queue_manager._is_stopped(state["task_id"]):
                    with ids_lock:
                        for tid in list(running_ids):
                            AgentQueueManager.set_stop_flag(
                                tid, self.agent_config.invoke_from, self.agent_config.user_id,
                            )
                    return
                time.sleep(0.5)

        monitor = threading.Thread(target=monitor_stop, daemon=True)
        monitor.start()

        try:
            with ThreadPoolExecutor(max_workers=max_parallel) as pool:
                futures = {
                    pool.submit(self._run_subtask, state, spec, running_ids, ids_lock, resume_mode, sub_task_timeout): spec
                    for spec in specs
                }
                for fut in as_completed(futures):
                    spec = futures[fut]
                    try:
                        results[spec.order] = fut.result()
                    except Exception as e:
                        logger.exception("子任务执行失败 order=%s", spec.order)
                        results[spec.order] = SubTaskResult(
                            order=spec.order, title=spec.title, status="error", error=str(e),
                        )
        finally:
            monitor.join(timeout=5)

        return {"sub_results": [results[o] for o in sorted(results)]}
```

`_run_subtask` 重写（含断点）：

```python
    def _run_subtask(
            self,
            state: AgentState,
            spec: SubTaskSpec,
            running_ids: set,
            ids_lock: threading.Lock,
            resume_mode: str,
            sub_task_timeout: int,
    ) -> SubTaskResult:
        """单个子任务：断点查询 → 恢复续跑 / 复用缓存 / 全新执行；桥接事件；周期落盘"""
        from app.http.module import injector
        from internal.service.sub_task_service import SubTaskService

        sub_task_service = injector.get(SubTaskService)
        sub_task_id = spec.task_id or uuid.uuid4()
        app_id = state.get("app_id") or self.agent_config.user_id
        message_id = state.get("message_id") or state.get("conversation_id")
        with ids_lock:
            running_ids.add(sub_task_id)
        started = time.perf_counter()
        should_resume = False
        reuse_answer = None

        # 1、断点查询（auto 模式或显式恢复触发）
        allow_resume = resume_mode == "auto" or state.get("resume_trigger")
        if allow_resume and state.get("conversation_id"):
            checkpoint = sub_task_service.get_checkpoint(state["conversation_id"], spec.order)
            if checkpoint and checkpoint.query == state["query"]:
                if checkpoint.status == "complete":
                    reuse_answer = checkpoint.partial_answer
                elif checkpoint.status in ("running", "stop", "timeout", "error"):
                    should_resume = True

        # 2、已完成缓存直接复用
        if reuse_answer is not None:
            return SubTaskResult(
                order=spec.order, title=spec.title, status="normal",
                answer=reuse_answer, latency=0.0, resumed=False,
            )

        # 恢复提示：SUB_TASK_START 附注"已从断点恢复"
        start_thought = spec.role_prompt[:200]
        if should_resume:
            start_thought = f"（已从断点恢复，继续执行）{start_thought}"

        try:
            self._publish_sub_task_event(state, QueueEvent.SUB_TASK_START, spec, thought=start_thought, sub_task_id=sub_task_id)

            sub_agent = self._build_sub_agent(spec)
            if should_resume:
                checkpoint = sub_task_service.get_checkpoint(state["conversation_id"], spec.order)
                messages = [self._message_dict_to_langchain(m) for m in (checkpoint.messages or [])]
                input_data = {
                    "messages": messages,
                    "history": [],
                    "iteration_count": checkpoint.iteration_count,
                    "resume": True,
                }
                answer_parts = [checkpoint.partial_answer or ""]
            else:
                input_data = {
                    "messages": [self.llm.convert_to_human_message(state["query"], None)],
                    "history": [],
                    "iteration_count": 0,
                    "resume": False,
                }
                answer_parts = []

            event_count = 0
            last_save_at = time.time()
            timed_out = False
            for thought in sub_agent.stream(input_data):
                if thought.event in (QueueEvent.PING, QueueEvent.AGENT_END, QueueEvent.STOP, QueueEvent.TIMEOUT, QueueEvent.ERROR):
                    continue
                bridged = thought.model_copy(update={"sub_task_id": sub_task_id, "sub_task_title": spec.title})
                self.agent_queue_manager.forward(state["task_id"], bridged)
                if thought.event == QueueEvent.AGENT_MESSAGE:
                    answer_parts.append(thought.answer)
                event_count += 1
                # 周期落盘：每10个桥接事件且距上次≥10秒
                if event_count % 10 == 0 and (time.time() - last_save_at) >= 10 and state.get("conversation_id"):
                    sub_task_service.save_checkpoint(
                        app_id=app_id, conversation_id=state["conversation_id"],
                        message_id=message_id, position=spec.order,
                        query=state["query"], spec=spec, status="running",
                        messages=messages_to_dict(input_data["messages"]),
                        iteration_count=input_data.get("iteration_count", 0),
                        partial_answer="".join(answer_parts),
                    )
                    last_save_at = time.time()
                # 子任务超时：标记 timeout 并终止该子任务（其余子任务不受影响）
                if sub_task_timeout and (time.perf_counter() - started) > sub_task_timeout:
                    timed_out = True
                    break
        except Exception as e:
            logger.exception("子任务异常 order=%s", spec.order)
            if state.get("conversation_id"):
                try:
                    sub_task_service.save_checkpoint(
                        app_id=app_id, conversation_id=state["conversation_id"],
                        message_id=message_id, position=spec.order,
                        query=state["query"], spec=spec, status="error",
                        messages=messages_to_dict(input_data.get("messages", [])),
                        iteration_count=input_data.get("iteration_count", 0),
                        partial_answer="".join(answer_parts),
                    )
                except Exception:
                    logger.exception("保存错误断点失败")
            self._publish_sub_task_event(state, QueueEvent.SUB_TASK_END, spec, observation=f"error: {e}", latency=time.perf_counter() - started, sub_task_id=sub_task_id)
            return SubTaskResult(order=spec.order, title=spec.title, status="error", error=str(e), latency=time.perf_counter() - started, resumed=should_resume)
        finally:
            with ids_lock:
                running_ids.discard(sub_task_id)

        answer = "".join(answer_parts)

        # 超时分支：保存 timeout 断点
        if timed_out:
            if state.get("conversation_id"):
                try:
                    sub_task_service.save_checkpoint(
                        app_id=app_id, conversation_id=state["conversation_id"],
                        message_id=message_id, position=spec.order,
                        query=state["query"], spec=spec, status="timeout",
                        messages=messages_to_dict(input_data["messages"]),
                        iteration_count=input_data.get("iteration_count", 0),
                        partial_answer=answer,
                    )
                except Exception:
                    logger.exception("保存超时断点失败")
            self._publish_sub_task_event(state, QueueEvent.SUB_TASK_END, spec, observation=f"timeout: {answer[:300]}", latency=time.perf_counter() - started, sub_task_id=sub_task_id)
            return SubTaskResult(order=spec.order, title=spec.title, status="timeout", answer=answer, latency=time.perf_counter() - started, resumed=should_resume)

        # 3、完成：缓存最终答案
        if state.get("conversation_id"):
            try:
                sub_task_service.save_checkpoint(
                    app_id=app_id, conversation_id=state["conversation_id"],
                    message_id=message_id, position=spec.order,
                    query=state["query"], spec=spec, status="complete",
                    messages=messages_to_dict(input_data["messages"]),
                    iteration_count=input_data.get("iteration_count", 0),
                    partial_answer=answer,
                )
            except Exception:
                logger.exception("保存完成断点失败")
        self._publish_sub_task_event(state, QueueEvent.SUB_TASK_END, spec, observation=answer[:500], latency=time.perf_counter() - started, sub_task_id=sub_task_id)
        return SubTaskResult(order=spec.order, title=spec.title, status="normal", answer=answer, latency=time.perf_counter() - started, resumed=should_resume)

    @staticmethod
    def _message_dict_to_langchain(m: dict):
        """将 messages_to_dict 输出还原为 LangChain 消息"""
        from langchain_core.messages import message_to_dict
        from langchain_core.load import loads
        return loads(json.dumps(m))
```

注：`messages_to_dict` 输出可直接用 `langchain_core.load.loads(json.dumps(...))` 还原为 BaseMessage；若加载报错，退化为 `HumanMessage`（实现时在 `_message_dict_to_langchain` 内 try/except 兜底）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/core/agent/test_orchestrator_resume.py -v`
Expected: PASS（3 passed）
回归：`python -m pytest test/internal/core/agent/ -v`

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/agents/orchestrator_agent.py test/internal/core/agent/test_orchestrator_resume.py
git commit -m "feat(agent): 子任务断点保存/恢复（auto/manual）+ 完成缓存复用"
```

---

### Task 9: ChatRunner 接入编排器

**Files:**
- Modify: `internal/service/chat_runner.py:70-150, 207-217`
- Modify: `internal/entity/app_entity.py`（若 Task 4 未做，此处补 `orchestrator_config` 默认块）
- Test: `test/internal/service/test_chat_runner_orchestrator.py`

**Interfaces:**
- Consumes: `OrchestratorAgent`（Task 7/8）、`AgentConfig.orchestrator_config`、请求 `resume` 字段（Task 10 定义，此处先接受 kwargs）
- Produces: `ChatRunner.run()` 在 `app.app_type == "orchestrator"` 且 `orchestrator_config.enable` 时使用 `OrchestratorAgent`；输入注入 `conversation_id` / `query` / `resume_trigger`；SSE 序列化透传 `sub_task_id` / `sub_task_title`

- [ ] **Step 1: 写失败测试**

创建 `test/internal/service/test_chat_runner_orchestrator.py`：

```python
import json
from unittest.mock import MagicMock
from uuid import uuid4

from app.http.module import injector
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import ModelFeature
from internal.entity.conversation_entity import InvokeFrom
from internal.service import ChatRunner


class FakeLLM:
    features = (ModelFeature.TOOL_CALL,)
    context_window = None
    max_tokens = 8192

    def convert_to_human_message(self, query, image_urls=None):
        from langchain_core.messages import HumanMessage
        return HumanMessage(content=query)


class CapturingOrchestrator:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    def stream(self, input, **kwargs):
        captured["input"] = input
        yield AgentThought(
            id=uuid4(), task_id=uuid4(), event=QueueEvent.SUB_TASK_PLAN,
            thought='[]', message=[],
        )
        yield AgentThought(
            id=uuid4(), task_id=uuid4(), event=QueueEvent.AGENT_MESSAGE,
            thought="汇总", message=[], answer="汇总",
            sub_task_id=uuid4(), sub_task_title="子任务",
        )
        yield AgentThought(id=uuid4(), task_id=uuid4(), event=QueueEvent.AGENT_END)


captured = {}

MOCK_CONFIG = {
    "model_config": {"provider": "deepseek", "model": "deepseek-v4-flash"},
    "dialog_round": 5, "tools": [], "datasets": [], "workflows": [], "skills": [],
    "preset_prompt": "", "long_term_memory": {"enable": False}, "review_config": {},
    "orchestrator_config": {"enable": True, "resume_mode": "auto"},
}


def test_chat_runner_selects_orchestrator_and_injects_input(app, monkeypatch):
    runner = injector.get(ChatRunner)
    account = MagicMock(id=uuid4())
    conversation = MagicMock(id=uuid4(), summary="")
    message = MagicMock(id=uuid4(), query="写报告", image_urls=[])

    monkeypatch.setattr(runner.language_model_service, "load_language_model", lambda cfg: FakeLLM())
    monkeypatch.setattr(runner.app_config_service, "get_langchain_tools_by_tools_config", lambda cfg: [])
    monkeypatch.setattr(runner, "_build_history", lambda llm, conv, r: [])
    monkeypatch.setattr(runner.conversation_service, "compact_if_needed", lambda *a, **k: False)
    monkeypatch.setattr(runner.episodic_memory_service, "search_episodes", lambda *a, **k: [])
    monkeypatch.setattr(runner.conversation_service, "save_agent_thoughts", lambda **kwargs: None)
    monkeypatch.setattr("internal.service.chat_runner.OrchestratorAgent", CapturingOrchestrator)

    with app.app_context():
        events = list(runner.run(
            app=MagicMock(id=uuid4(), app_type="orchestrator"),
            app_config=dict(MOCK_CONFIG),
            conversation=conversation, message=message, account=account,
            invoke_from=InvokeFrom.DEBUGGER,
        ))

    assert captured["input"]["conversation_id"] == conversation.id
    assert captured["input"]["query"] == "写报告"
    assert captured["input"]["resume_trigger"] is False
    sse = "\n".join(events)
    assert '"sub_task_id"' in sse
    assert '"sub_task_title"' in sse
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_chat_runner_orchestrator.py -v`
Expected: FAIL（chat_runner 未选择 OrchestratorAgent，未注入字段，SSE 无 sub_task 字段）

- [ ] **Step 3: 实现**

`internal/service/chat_runner.py`：

1) 顶部导入：

```python
from internal.core.agent.agents import FunctionCallAgent, OrchestratorAgent, ReACTAgent
```

2) `run()` 中 Agent 选择（原第 122 行附近）改为：

```python
        # 4、根据应用类型与 LLM 能力决定 Agent 类型
        orchestrator_cfg = app_config.get("orchestrator_config") or {}
        if getattr(app, "app_type", "agent") == "orchestrator" and orchestrator_cfg.get("enable"):
            agent_class = OrchestratorAgent
        elif ModelFeature.TOOL_CALL in llm.features:
            agent_class = FunctionCallAgent
        else:
            agent_class = ReACTAgent
        agent = agent_class(
            name="debug-agent",
            llm=llm,
            agent_config=AgentConfig(
                user_id=account.id,
                invoke_from=invoke_from,
                preset_prompt=app_config["preset_prompt"],
                enable_long_term_memory=app_config["long_term_memory"]["enable"],
                tools=tools,
                review_config=app_config["review_config"],
                orchestrator_config=orchestrator_cfg,
            ),
        )
```

3) `_stream_and_persist` 的 stream 输入（原第 177-184 行）追加五个键：

```python
            for agent_thought in agent.stream({
                "messages": [llm.convert_to_human_message(message.query, message.image_urls)],
                "history": history,
                "long_term_memory": conversation.summary if conversation.summary else "",
                "user_profile": user_profile,
                "episodic_memory": episodic_memory,
                "procedural_instructions": procedural_instructions,
                "conversation_id": conversation.id,
                "app_id": app.id,
                "message_id": message.id,
                "query": message.query,
                "resume_trigger": bool(getattr(message, "resume_trigger", False)),
            }):
```

4) 两处 SSE 序列化的 `model_dump(include={...})` 列表追加 `"sub_task_id", "sub_task_title"`（第 208-211 行与第 227-230 行）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_chat_runner_orchestrator.py -v`
Expected: PASS
回归：`python -m pytest test/internal/service/test_chat_runner.py -v`

- [ ] **Step 5: 提交**

```bash
git add internal/service/chat_runner.py test/internal/service/test_chat_runner_orchestrator.py
git commit -m "feat(service): ChatRunner 接入 OrchestratorAgent 并透传子任务字段"
```

---

### Task 10: 应用链路（app_type / resume 字段 / can_resume / 删除清理）

**Files:**
- Modify: `internal/schema/app_schema.py`（`CreateAppReq`、`DebugChatReq`、`GetDebugConversationMessagesWithPageResp`）
- Modify: `internal/schema/web_app_schema.py`（`WebAppChatReq`）
- Modify: `internal/service/app_service.py`（`create_app` / AI 创建 / 拷贝复制透传 `app_type`）
- Modify: `internal/task/app_task.py`（`auto_create_app` 接收 `app_type`）
- Modify: `internal/service/conversation_service.py`（`delete_conversation` 清理断点）
- Modify: `internal/service/app_config_service.py`（如创建默认配置处需带 `orchestrator_config`，跟随 `DEFAULT_APP_CONFIG` 自动生效，无需改动——验证即可）
- Test: `test/internal/schema/test_orchestrator_app_schema.py`、`test/internal/service/test_conversation_delete_checkpoints.py`

**Interfaces:**
- Consumes: `SubTaskService`（Task 5）、`App.app_type`（Task 4）
- Produces:
  - `CreateAppReq.app_type`（StringField 可选，默认 `"agent"`）
  - `DebugChatReq.resume: BooleanField`、`WebAppChatReq.resume: BooleanField`
  - 消息响应 `can_resume: bool` + agent_thoughts 项含 `sub_task_id/sub_task_title`
  - `auto_create_app(name, description, account_id, app_type="agent")`
  - `delete_conversation` 内调用 `sub_task_service.clear_checkpoints(conversation_id)`

- [ ] **Step 1: 写失败测试**

创建 `test/internal/schema/test_orchestrator_app_schema.py`：

```python
from internal.schema.app_schema import CreateAppReq, DebugChatReq
from internal.schema.web_app_schema import WebAppChatReq


class TestOrchestratorAppSchema:
    def test_create_app_req_has_app_type(self):
        req = CreateAppReq()
        assert req.app_type.data == "agent"

    def test_debug_chat_req_has_resume(self):
        req = DebugChatReq()
        assert req.resume.data is False

    def test_web_app_chat_req_has_resume(self):
        req = WebAppChatReq()
        assert req.resume.data is False
```

创建 `test/internal/service/test_conversation_delete_checkpoints.py`：

```python
import uuid

from internal.core.agent.entities.agent_entity import SubTaskSpec
from internal.model import Conversation
from internal.service import ConversationService, SubTaskService
from internal.entity.conversation_entity import InvokeFrom


def test_delete_conversation_clears_checkpoints(app, db, monkeypatch):
    account_id = uuid.uuid4()
    app_id = uuid.uuid4()
    conv_service = ConversationService(db=db)
    conversation = conv_service.create(
        Conversation, app_id=app_id, name="测试", invoke_from=InvokeFrom.DEBUGGER,
        created_by=account_id, updated_by=account_id,
    )
    sub_service = SubTaskService(db=db)
    sub_service.save_checkpoint(
        app_id=app_id, conversation_id=conversation.id, message_id=uuid.uuid4(),
        position=1, query="q", spec=SubTaskSpec(order=1, title="t", role_prompt="r", expect_output="e"),
        status="stop", messages=[], iteration_count=0, partial_answer="",
    )
    assert sub_service.get_checkpoint(conversation.id, 1) is not None

    conv_service.delete_conversation(conversation.id, account=type("A", (), {"id": account_id})())
    assert sub_service.get_checkpoint(conversation.id, 1) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/schema/test_orchestrator_app_schema.py test/internal/service/test_conversation_delete_checkpoints.py -v`
Expected: FAIL（字段不存在 / 删除未清理断点）

- [ ] **Step 3: 实现**

`internal/schema/app_schema.py`：

```python
class CreateAppReq(FlaskForm):
    """创建Agent应用请求结构体"""
    name = StringField("name", validators=[...])
    icon = StringField("icon", validators=[...])
    description = StringField("description", validators=[...])
    app_type = StringField("app_type", default="agent", validators=[Optional()])
```

`DebugChatReq` 追加：

```python
    resume = BooleanField("resume", default=False)
```

`GetDebugConversationMessagesWithPageResp`：

- 新增字段：`can_resume = fields.Boolean(dump_default=False)`
- `process_data` 中：

```python
            "can_resume": getattr(data, "can_resume", False),
```

- agent_thoughts 项追加：

```python
                "sub_task_id": str(agent_thought.sub_task_id) if agent_thought.sub_task_id else None,
                "sub_task_title": agent_thought.sub_task_title,
```

`internal/schema/web_app_schema.py` `WebAppChatReq` 追加：

```python
    resume = BooleanField("resume", default=False)
```

`internal/service/app_service.py`：`create_app`（约 177 行）与 AI 创建（约 109 行）创建 `App(...)` 时透传 `app_type=req.app_type`（AI 创建默认 `"orchestrator"` 与否由调用方决定，默认 `"agent"`）；拷贝复制（约 229 行）`new_app` 复制 `app_type=self.app_type`。

`internal/task/app_task.py` `auto_create_app`：

```python
@celery.task
def auto_create_app(name, description, account_id, app_type="agent"):
    ...
    # 内部调用 app_service 创建时透传 app_type
```

`internal/service/conversation_service.py` `delete_conversation`（约 440 行）在删除会话处追加：

```python
        # 清理子任务断点
        try:
            from app.http.module import injector
            from .sub_task_service import SubTaskService
            injector.get(SubTaskService).clear_checkpoints(conversation_id)
        except Exception:
            logger.exception("清理子任务断点失败 conversation_id=%s", conversation_id)
```

`can_resume` 标记：在返回消息列表的服务中 enrich（调试会话 `internal/service/app_service.py` 约 574 行 `get_conversation_messages_with_page`；Web 应用会话 `internal/service/web_app_service.py` 对应方法），分页完成后追加：

```python
        from app.http.module import injector
        from .sub_task_service import SubTaskService
        sub_task_service = injector.get(SubTaskService)
        for m in messages:
            m.can_resume = sub_task_service.has_resumable_checkpoints(conversation.id, m.query)
```

（`Message` 模型无 `can_resume` 列，动态属性即可；schema 用 `getattr(data, "can_resume", False)` 读取。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/schema/test_orchestrator_app_schema.py test/internal/service/test_conversation_delete_checkpoints.py -v`
Expected: PASS
回归：`python -m pytest test/internal/schema/ test/internal/service/test_conversation_service.py -v`

- [ ] **Step 5: 提交**

```bash
git add internal/schema/app_schema.py internal/schema/web_app_schema.py internal/service/app_service.py internal/task/app_task.py internal/service/conversation_service.py test/internal/schema/ test/internal/service/test_conversation_delete_checkpoints.py
git commit -m "feat(app): 编排型应用类型透传+resume请求字段+can_resume响应+删除清理断点"
```

---

### Task 11: 前端（计划卡片 / 子任务分组 / 继续执行按钮 / 配置表单）

**Files:**
- Modify: `ai-code-llmops-web/src/config/index.ts`
- Modify: `ai-code-llmops-web/src/views/space/apps/components/AgentThought.vue`
- Modify: `ai-code-llmops-web/src/views/web-apps/IndexView.vue`
- Modify: `ai-code-llmops-web/src/views/space/apps/components/PreviewDebugChat.vue`
- Modify: `ai-code-llmops-web/src/views/pages/HomeView.vue`
- Modify: `ai-code-llmops-web/src/models/app.ts`、`web-app.ts`、`conversation.ts`（agent_thoughts 项与消息模型补 `sub_task_id/sub_task_title/can_resume/resume` 可选字段）
- Modify: `ai-code-llmops-web/src/views/space/apps/` 下的应用创建/配置组件（实现阶段按实际文件定位，新增"应用类型"选择与编排配置表单）

**Interfaces:**
- Consumes: 后端事件字符串 `sub_task_plan / sub_task_start / sub_task_end`；消息响应 `can_resume`；聊天请求 `resume`
- Produces: 前端展示"任务分解计划"卡片、按 `sub_task_id` 分组折叠步骤、"继续执行"按钮（can_resume 时重发原 query + `resume=true`）、应用配置页编排表单

- [ ] **Step 1: 配置常量**

`src/config/index.ts` `QueueEvent` 追加：

```ts
  subTaskPlan: 'sub_task_plan',
  subTaskStart: 'sub_task_start',
  subTaskEnd: 'sub_task_end',
```

- [ ] **Step 2: AgentThought.vue 渲染**

- `sub_task_plan`：在步骤列表顶部渲染可折叠"任务分解计划"卡片（`agent_thought.thought` 为 JSON 数组，parse 后列出 `order.title`）
- `sub_task_start/end`：新增图标分支与文案（"子任务开始"/"子任务完成"），end 显示 `latency`；start 的 `thought` 含"已从断点恢复"字样时原样显示
- 分组：`filteredThoughts` 后按 `sub_task_id` 分组——无 `sub_task_id` 的步骤保持原样；有 `sub_task_id` 的步骤折叠到子任务标题分组头下（同 `sub_task_id` 合并展示）

- [ ] **Step 3: 消息气泡"继续执行"按钮**

三个聊天视图（`IndexView.vue / PreviewDebugChat.vue / HomeView.vue`）的消息操作区：

```vue
<button v-if="message.can_resume && !isStreaming" @click="resumeMessage(message)">
  继续执行
</button>
```

`resumeMessage` 复用发送逻辑，携带原 `query` 与 `resume: true`：

```ts
async function resumeMessage(message) {
  await sendMessage(message.query, { resume: true })
}
```

发送接口的请求体需包含 `resume`（`DebugChatReq` / `WebAppChatReq` 已支持）。

- [ ] **Step 4: 应用创建/配置页**

在应用创建表单加"应用类型"选择（agent/orchestrator）；编排类型时显示编排配置表单：启用开关、`max_sub_tasks`、`max_parallel`、`sub_task_timeout`、`resume_mode`（auto/manual 下拉）。保存进 `orchestrator_config`。

- [ ] **Step 5: 验证**

Run: `cd ai-code-llmops-web && npm run build`
Expected: 构建通过、无 TS 错误。
再按 spec 第 7 节用 Playwright（webapp-testing）或手动验证：编排型应用对话 → 计划卡片出现 → 子任务步骤分组显示 → 停止后消息出现"继续执行"按钮 → 点击后从断点续跑。

- [ ] **Step 6: 提交**

```bash
git add ai-code-llmops-web/src/
git commit -m "feat(web): 编排型应用前端（计划卡片/子任务分组/继续执行/配置表单）"
```

---

### Task 12: 端到端验证与分支提交

**Files:**
- 无新文件；验证 + 收尾

**Interfaces:**
- 全部上游任务产物

- [ ] **Step 1: 后端全量回归**

Run: `python -m pytest test/ -v`
Expected: 全部通过（新增编排器相关测试 + 既有测试无回归）

- [ ] **Step 2: 迁移验证**

Run: `flask db upgrade head && flask db downgrade -1 && flask db upgrade head`
Expected: 成功且无报错（开发库/临时库均可）

- [ ] **Step 3: 端到端冒烟（真实模型可选）**

若环境有可用的 LLM API Key，用编排型应用发一个可分解任务（如"写一篇XX市场调研报告"），确认 SSE 顺序：`SUB_TASK_PLAN → SUB_TASK_START×N → 子事件（带 sub_task_id）→ SUB_TASK_END×N → AGENT_END`；中途停止一次后重发，确认断点续跑/缓存复用。无 Key 则以 Task 7/8 的桩测试为准。

- [ ] **Step 4: 检查分支与提交**

Run: `git status --short && git log --oneline -15`
Expected: 全部改动已提交到 `release_20260828`，工作区干净（未跟踪的杂项文件如 PDF/图片除外）

- [ ] **Step 5: 总结交付**

输出：功能清单、改动文件清单、已知限制（spec 第 8 节二期范围）、运行/验证方式。
