# Agent 交互式选项选择（ask_user）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Agent 在推理中遇到多选项决策时暂停，通过 SSE 向用户展示选项卡片，用户选择（或跳过/超时）后在同一 SSE 流内继续推理。

**Architecture:** 在 FunctionCallAgent 的 `_tools_node` 注入 ask_user 特殊分支：LLM 调用 ask_user 工具时不真执行，发布 `QueueEvent.ASK_USER` 事件到 SSE，Agent 线程用 Redis `BLPOP` 阻塞等待；前端经新接口 `POST .../chat/choice` 提交选择写入 Redis，线程唤醒后把选择包装成 ToolMessage 返回 LLM 继续。SSE 流全程保持打开，实现同轮续跑。复用现有 `AgentQueueManager` 的 belong 校验防越权，复用 `message_agent_thought` 表承载事件（question/options 落 `tool_input`，choice 落 `observation`）。

**Tech Stack:** Python 3.12 / Flask / LangGraph / Redis / Vue 3 + TypeScript / vitest / pytest

**Spec:** `Obsidian/Obsidian/Agent交互式选项选择设计.md`

## Global Constraints

- ask_user 仅在 `ModelFeature.TOOL_CALL in llm.features` 且走 FunctionCallAgent 分支时注入；ReACTAgent 不注入，行为与现状完全一致
- OrchestratorAgent 主 Agent 的 plan 节点不触发 ask_user；子任务（FunctionCallAgent）触发，事件用子任务 task_id 桥接
- ask_user 占位工具定义 langchain `StructuredTool`（name=`ask_user`），其 `_run` 永不真正执行（`_tools_node` 拦截）
- 等待超时 300 秒，超时按"跳过"处理；超时常量 `ASK_USER_WAIT_TIMEOUT` 定义于 `queue_entity.py` 或 `agent_entity.py`（取一，全计划统一用 `agent_entity.py`）
- 提交幂等：同一 task_id 重复提交取第一次；归属校验复用 `AgentQueueManager.generate_task_belong_cache_key` + belong 值比对
- 不新增数据库表、不加列：question/options/allow_custom 落 `tool_input`（JSONB），choice 落 `observation`（Text）
- 三个入口共用同一后端逻辑，路由贴合现有 stop 风格（task_id 走路径）：
  - `POST /apps/<uuid:app_id>/conversations/tasks/<uuid:task_id>/choice`
  - `POST /web_apps/<string:token>/chat/<uuid:task_id>/choice`
  - `POST /assistant_agent/chat/<uuid:task_id>/choice`
- 前端三端复用 `AskUserOptions.vue`：`PreviewDebugChat.vue`、`IndexView.vue`、`HomeView.vue`；`QueueEvent` 集中定义于 `src/config/index.ts`

---

### Task 1: 事件协议扩展（QueueEvent + AgentThought 字段）

**Files:**
- Modify: `internal/core/agent/entities/queue_entity.py`
- Test: `test/internal/core/agent/test_ask_user_entity.py`（新建）

**Interfaces:**
- Produces: `QueueEvent.ASK_USER`（值 `"ask_user"`）；`AgentThought` 新增字段 `question: str = ""`、`options: list[str] = Field(default_factory=list)`、`allow_custom: bool = True`、`choice: str = ""`

- [ ] **Step 1: 写失败测试**

```python
# test/internal/core/agent/test_ask_user_entity.py
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent


def test_ask_user_event_value():
    assert QueueEvent.ASK_USER == "ask_user"


def test_agent_thought_ask_user_fields():
    thought = AgentThought(
        id="00000000-0000-0000-0000-000000000001",
        task_id="00000000-0000-0000-0000-000000000002",
        event=QueueEvent.ASK_USER,
        question="选择哪种授权模型？",
        options=["RBAC", "ABAC", "混合"],
        allow_custom=True,
        choice="混合",
    )
    assert thought.question == "选择哪种授权模型？"
    assert thought.options == ["RBAC", "ABAC", "混合"]
    assert thought.allow_custom is True
    assert thought.choice == "混合"
    assert thought.event == "ask_user"
```

- [ ] **Step 2: 运行确认失败**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_ask_user_entity.py -v`
Expected: FAIL（`QueueEvent.ASK_USER` 不存在 / AgentThought 字段缺失）

- [ ] **Step 3: 最小实现**

`internal/core/agent/entities/queue_entity.py`：
- `QueueEvent` 枚举加一行：`ASK_USER = "ask_user"  # 向用户提问，等待选择`
- `AgentThought` 在 `trace` 字段后加：

```python
    # 交互式选项选择（ask_user 事件专用）
    question: str = ""  # 向用户展示的问题
    options: list[str] = Field(default_factory=list)  # 可选项列表
    allow_custom: bool = True  # 是否允许用户自定义输入
    choice: str = ""  # 用户最终选择（落库回显用）
```

- [ ] **Step 4: 运行确认通过**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_ask_user_entity.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/entities/queue_entity.py test/internal/core/agent/test_ask_user_entity.py
git commit -m "feat(agent): 新增 ask_user 事件与 AgentThought 交互字段"
```

---

### Task 2: 队列管理器选择等待机制（submit_choice / wait_for_choice）

**Files:**
- Modify: `internal/core/agent/agents/agent_queue_manager.py`
- Test: `test/internal/core/agent/test_queue_manager_choice.py`（新建）

**Interfaces:**
- Consumes: `AgentThought`、`QueueEvent`（Task 1）
- Produces:
  - `AgentQueueManager.submit_choice(task_id: UUID, choice: str | None = None, skip: bool = False) -> bool`（**classmethod**，内部 `from app.http.module import injector; redis_client = injector.get(Redis)`）— 写选择到 Redis 队列，重复提交（key 存在且有元素）返回 False
  - `AgentQueueManager.wait_for_choice(task_id: UUID, timeout: int = 300) -> tuple[str | None, bool]`（**classmethod**，同 injector 模式）— BLPOP 等待，返回 `(choice, skipped)`；超时/异常返回 `(None, True)`
  - `AgentQueueManager.generate_choice_queue_key(task_id: UUID) -> str`（classmethod）— `f"gen_task:choice:{task_id}"`

- [ ] **Step 1: 写失败测试**

```python
# test/internal/core/agent/test_queue_manager_choice.py
import json
import uuid
from unittest.mock import MagicMock

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager


def _fake_redis(monkeypatch) -> MagicMock:
    fake_redis = MagicMock()
    fake_injector = MagicMock()
    fake_injector.get.return_value = fake_redis
    monkeypatch.setattr("app.http.module.injector", fake_injector)
    return fake_redis


def test_submit_choice_writes_json_to_redis(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.exists.return_value = False
    task_id = uuid.uuid4()
    ok = AgentQueueManager.submit_choice(task_id, choice="RBAC")
    assert ok is True
    key = AgentQueueManager.generate_choice_queue_key(task_id)
    fake_redis.rpush.assert_called_once()
    payload = json.loads(fake_redis.rpush.call_args.args[1])
    assert payload == {"choice": "RBAC", "skip": False}


def test_submit_choice_duplicate_ignored(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.exists.return_value = True
    fake_redis.llen.return_value = 1
    ok = AgentQueueManager.submit_choice(uuid.uuid4(), choice="RBAC")
    assert ok is False
    fake_redis.rpush.assert_not_called()


def test_wait_for_choice_returns_choice(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = ("key", json.dumps({"choice": "ABAC", "skip": False}).encode())
    choice, skipped = AgentQueueManager.wait_for_choice(uuid.uuid4(), timeout=300)
    assert choice == "ABAC"
    assert skipped is False


def test_wait_for_choice_timeout_returns_skip(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = None
    choice, skipped = AgentQueueManager.wait_for_choice(uuid.uuid4(), timeout=300)
    assert choice is None
    assert skipped is True
```

- [ ] **Step 2: 运行确认失败**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_queue_manager_choice.py -v`
Expected: FAIL（`submit_choice` / `wait_for_choice` 不存在）

- [ ] **Step 3: 最小实现**

`internal/core/agent/agents/agent_queue_manager.py`，类内加（文件头已 `import json`）：

```python
    @classmethod
    def generate_choice_queue_key(cls, task_id: UUID) -> str:
        """生成用户选择队列 key"""
        return f"gen_task:choice:{task_id!s}"

    @classmethod
    def submit_choice(cls, task_id: UUID, choice: str | None = None, skip: bool = False) -> bool:
        """提交用户选择到 Redis 队列；同一 task_id 已有未消费选择时忽略（幂等）"""
        from app.http.module import injector
        redis_client = injector.get(Redis)
        key = cls.generate_choice_queue_key(task_id)
        if redis_client.exists(key) and redis_client.llen(key) > 0:
            return False
        payload = json.dumps({"choice": choice, "skip": skip}, ensure_ascii=False)
        redis_client.rpush(key, payload)
        redis_client.expire(key, 1800)
        return True

    @classmethod
    def wait_for_choice(cls, task_id: UUID, timeout: int = 300) -> tuple[str | None, bool]:
        """阻塞等待用户选择：返回 (choice, skipped)；超时/异常按跳过处理"""
        from app.http.module import injector
        redis_client = injector.get(Redis)
        key = cls.generate_choice_queue_key(task_id)
        try:
            item = redis_client.blpop(key, timeout=timeout)
        except Exception:
            return None, True
        if not item:
            return None, True
        try:
            payload = json.loads(item[1])
        except (TypeError, ValueError):
            return None, True
        return payload.get("choice"), bool(payload.get("skip", False))
```

- [ ] **Step 4: 运行确认通过**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_queue_manager_choice.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/agents/agent_queue_manager.py test/internal/core/agent/test_queue_manager_choice.py
git commit -m "feat(agent): AgentQueueManager 支持用户选择提交与等待（Redis BLPOP）"
```

---

### Task 3: ask_user 占位工具定义（agent_entity.py）

**Files:**
- Modify: `internal/core/agent/entities/agent_entity.py`
- Test: `test/internal/core/agent/test_ask_user_entity.py`（追加用例）

**Interfaces:**
- Produces: 常量 `ASK_USER_TOOL_NAME = "ask_user"`；`ASK_USER_WAIT_TIMEOUT = 300`；工厂函数 `create_ask_user_tool() -> StructuredTool`（name=ask_user，description 中文说明，args_schema 含 question: str / options: list[str] / allow_custom: bool，func 为占位返回空字符串）

- [ ] **Step 1: 写失败测试**（追加到 `test_ask_user_entity.py`）

```python
from internal.core.agent.entities.agent_entity import (
    ASK_USER_TOOL_NAME,
    ASK_USER_WAIT_TIMEOUT,
    create_ask_user_tool,
)


def test_ask_user_tool_definition():
    tool = create_ask_user_tool()
    assert tool.name == ASK_USER_TOOL_NAME == "ask_user"
    assert ASK_USER_WAIT_TIMEOUT == 300
    schema = tool.args_schema.schema()
    assert "question" in schema["properties"]
    assert "options" in schema["properties"]
    assert "allow_custom" in schema["properties"]
```

- [ ] **Step 2: 运行确认失败**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_ask_user_entity.py -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 最小实现**

`internal/core/agent/entities/agent_entity.py` 末尾加（若文件头 `from langchain_core.tools import BaseTool` 已存在，改为 `from langchain_core.tools import BaseTool, StructuredTool`）：

```python
ASK_USER_TOOL_NAME = "ask_user"
ASK_USER_WAIT_TIMEOUT = 300


class AskUserArgs(BaseModel):
    """ask_user 工具参数：向用户提问并等待选择"""
    question: str = Field(description="向用户展示的问题")
    options: list[str] = Field(default_factory=list, description="可选项列表，供用户单选")
    allow_custom: bool = Field(default=True, description="是否允许用户输入自定义选项")


def create_ask_user_tool() -> StructuredTool:
    """ask_user 占位工具：仅用于让 LLM 在 bind_tools 时知道可调用。

    其 func 不会被真正执行——FunctionCallAgent._tools_node 会对
    ASK_USER_TOOL_NAME 走特殊分支（发布事件 + 阻塞等待用户选择）。
    """
    return StructuredTool.from_function(
        name=ASK_USER_TOOL_NAME,
        func=lambda **kwargs: "",
        description=(
            "当任务存在多个可行方案或需要用户决策时调用：向用户展示问题与选项，"
            "等待用户选择后再继续。例如设计权限方案时可让用户选择 RBAC/ABAC/混合。"
        ),
        args_schema=AskUserArgs,
    )
```

（确保 `StructuredTool` 已从 langchain 导入；`BaseModel`/`Field` 已导入）

- [ ] **Step 4: 运行确认通过**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_ask_user_entity.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/entities/agent_entity.py test/internal/core/agent/test_ask_user_entity.py
git commit -m "feat(agent): 定义 ask_user 占位工具与等待超时常量"
```

---

### Task 4: FunctionCallAgent._tools_node 的 ask_user 分支

**Files:**
- Modify: `internal/core/agent/agents/function_call_agent.py`
- Test: `test/internal/core/agent/test_ask_user_agent_branch.py`（新建）

**Interfaces:**
- Consumes: `QueueEvent.ASK_USER`（Task 1）、`AgentQueueManager.wait_for_choice`（Task 2）、`ASK_USER_TOOL_NAME`/`ASK_USER_WAIT_TIMEOUT`（Task 3）
- Produces: `FunctionCallAgent._handle_ask_user(state, tool_call) -> str` — 发布 ASK_USER 事件（带 question/options/allow_custom、`tool="ask_user"`、`tool_input=args`），`wait_for_choice(task_id, ASK_USER_WAIT_TIMEOUT)`，跳过时返回 `"用户跳过了选择，请基于已有信息自行决策并继续。"`，否则返回 `f"用户选择了：{choice}"`

- [ ] **Step 1: 写失败测试**

```python
# test/internal/core/agent/test_ask_user_agent_branch.py
import uuid
from unittest.mock import MagicMock

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.core.agent.entities.agent_entity import AgentConfig, ASK_USER_TOOL_NAME
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.conversation_entity import InvokeFrom


def _make_agent(monkeypatch, wait_result=("RBAC", False)):
    monkeypatch.setattr(
        AgentQueueManager, "wait_for_choice", MagicMock(return_value=wait_result),
    )
    llm = MagicMock()
    agent = FunctionCallAgent(
        llm=llm,
        agent_config=AgentConfig(
            user_id=uuid.uuid4(),
            invoke_from=InvokeFrom.DEBUGGER,
            preset_prompt="",
            enable_long_term_memory=False,
            tools=[],
            review_config={"enable": False, "keywords": [], "inputs_config": {"enable": False}, "outputs_config": {"enable": False}},
            orchestrator_config={},
        ),
    )
    return agent


def test_handle_ask_user_publishes_event_and_returns_choice(monkeypatch):
    agent = _make_agent(monkeypatch)
    task_id = uuid.uuid4()
    state = {"task_id": task_id, "messages": []}
    tool_call = {
        "name": ASK_USER_TOOL_NAME,
        "args": {"question": "选择哪种授权模型？", "options": ["RBAC", "ABAC"], "allow_custom": True},
        "id": "call_1",
    }
    result = agent._handle_ask_user(state, tool_call)
    assert result == "用户选择了：RBAC"
    published = agent.agent_queue_manager.publish.call_args.args[1]
    assert published.event == QueueEvent.ASK_USER
    assert published.question == "选择哪种授权模型？"
    assert published.options == ["RBAC", "ABAC"]
    assert published.allow_custom is True
    assert published.tool == ASK_USER_TOOL_NAME


def test_handle_ask_user_skip(monkeypatch):
    agent = _make_agent(monkeypatch, wait_result=(None, True))
    result = agent._handle_ask_user({"task_id": uuid.uuid4(), "messages": []}, {"name": ASK_USER_TOOL_NAME, "args": {"question": "q"}, "id": "c1"})
    assert "跳过" in result
```

- [ ] **Step 2: 运行确认失败**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_ask_user_agent_branch.py -v`
Expected: FAIL（`_handle_ask_user` 不存在）

- [ ] **Step 3: 最小实现**

`internal/core/agent/agents/function_call_agent.py`：

1. 导入区加：

```python
from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.entities.agent_entity import (
    AGENT_SYSTEM_PROMPT_TEMPLATE,
    ASK_USER_TOOL_NAME,
    ASK_USER_WAIT_TIMEOUT,
    DATASET_RETRIEVAL_TOOL_NAME,
    MAX_ITERATION_RESPONSE,
    AgentState,
    build_system_prompt,
)
```

2. `_tools_node` 的循环内，把 `tool = tools_by_name[tool_call["name"]]; tool_result = tool.invoke(...)` 替换为：

```python
            try:
                if tool_call["name"] == ASK_USER_TOOL_NAME:
                    # 交互式选项：不执行工具，发布 ask_user 事件并阻塞等待用户选择
                    tool_result = self._handle_ask_user(state, tool_call)
                else:
                    tool = tools_by_name[tool_call["name"]]
                    tool_result = tool.invoke(tool_call["args"])
                # 读取知识库检索工具的 Agentic 重检轨迹（未开启 agentic 时为空列表）
                if tool_call["name"] == DATASET_RETRIEVAL_TOOL_NAME:
                    trace = list(getattr(tool, "agentic_trace", None) or [])
            except Exception as e:
                tool_result = f"工具执行出错：{e!s}"
```

3. 类内新增方法（`wait_for_choice` 为 classmethod，直接调用）：

```python
    def _handle_ask_user(self, state: AgentState, tool_call: dict) -> str:
        """ask_user 特殊分支：发布 ASK_USER 事件 → 阻塞等待用户选择 → 返回选择文本。

        返回字符串作为 ToolMessage 内容给 LLM，继续推理（同轮续跑）。
        """
        args = tool_call.get("args") or {}
        question = str(args.get("question", ""))
        options = [str(o) for o in (args.get("options") or [])]
        allow_custom = bool(args.get("allow_custom", True))

        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(),
            task_id=state["task_id"],
            event=QueueEvent.ASK_USER,
            question=question,
            options=options,
            allow_custom=allow_custom,
            tool=ASK_USER_TOOL_NAME,
            tool_input=args,
            message=messages_to_dict(state["messages"]),
            latency=0,
        ))

        choice, skipped = AgentQueueManager.wait_for_choice(
            state["task_id"], timeout=ASK_USER_WAIT_TIMEOUT,
        )
        if skipped or not choice:
            return "用户跳过了选择，请基于已有信息自行决策并继续。"
        return f"用户选择了：{choice}"
```

- [ ] **Step 4: 运行确认通过**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_ask_user_agent_branch.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/agents/function_call_agent.py test/internal/core/agent/test_ask_user_agent_branch.py
git commit -m "feat(agent): FunctionCallAgent 支持 ask_user 交互分支（发布事件+阻塞等待）"
```

---

### Task 5: ChatRunner 注入 ask_user + SSE 序列化 + 落库适配

**Files:**
- Modify: `internal/service/chat_runner.py`
- Modify: `internal/service/conversation_service.py`（`save_agent_thoughts`）
- Test: `test/internal/service/test_ask_user_chat_runner.py`（新建）

**Interfaces:**
- Consumes: `create_ask_user_tool`、`ASK_USER_TOOL_NAME`（Task 3）、`QueueEvent.ASK_USER`（Task 1）、`ModelFeature`（已存在）
- Produces: `ChatRunner.run` 在 FunctionCallAgent 分支注入 ask_user 工具；`_stream_and_persist` 的 `model_dump(include=...)` 加 `question/options/allow_custom/choice`；`save_agent_thoughts` 的保存事件列表加 `QueueEvent.ASK_USER`，并把 `question/options/allow_custom` 写入 `tool_input`（已由 `_handle_ask_user` 保证）、`choice` 写入 `observation`

- [ ] **Step 1: 写失败测试**

```python
# test/internal/service/test_ask_user_chat_runner.py
import uuid

from internal.core.agent.entities.agent_entity import ASK_USER_TOOL_NAME, create_ask_user_tool
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.entity.conversation_entity import InvokeFrom
from internal.service.conversation_service import ConversationService


def test_ask_user_tool_injected_when_tool_call():
    """ask_user 工具定义可被注入：name 正确、schema 完整（纯函数级验证）"""
    tool = create_ask_user_tool()
    assert tool.name == ASK_USER_TOOL_NAME
    props = tool.args_schema.schema()["properties"]
    assert {"question", "options", "allow_custom"} <= set(props)


def test_ask_user_event_in_save_list():
    """save_agent_thoughts 的保存事件列表必须包含 ASK_USER（读取源确认）"""
    import inspect
    from internal.service import conversation_service as cs
    src = inspect.getsource(cs.ConversationService.save_agent_thoughts)
    assert "QueueEvent.ASK_USER" in src
```

- [ ] **Step 2: 运行确认失败**

Run: `venv\Scripts\python -m pytest test/internal/service/test_ask_user_chat_runner.py -v`
Expected: FAIL（第二个用例断言 src 不含 `QueueEvent.ASK_USER`）

- [ ] **Step 3: 最小实现**

`internal/service/chat_runner.py`：

1. 导入加 `from internal.core.agent.entities.agent_entity import AgentConfig, create_ask_user_tool`（若 AgentConfig 已导入则只加 create_ask_user_tool）与 `from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature`（ModelFeature 若已导入则跳过）
2. `run()` 中工具注入逻辑：把注入点放在 agent_class 判断处，**只要 `ModelFeature.TOOL_CALL` 就注入**（编排器场景的 OrchestratorAgent 子任务复用 `self.agent_config.tools`，同样需要 ask_user）：

```python
        if orchestrator_cfg.get("enable"):
            agent_class = OrchestratorAgent
        elif ModelFeature.TOOL_CALL in llm.features:
            agent_class = FunctionCallAgent
        else:
            agent_class = ReACTAgent

        # 注入 ask_user 交互工具：仅工具调用型模型（FunctionCallAgent 及编排器子任务）
        # ReACTAgent（非 TOOL_CALL）不注入，行为与现状完全一致
        if ModelFeature.TOOL_CALL in llm.features:
            tools.append(create_ask_user_tool())
```

3. `_stream_and_persist` 的 `model_dump(include={...})` 元组加 `"question", "options", "allow_custom", "choice"`：

```python
                    **agent_thought.model_dump(include={
                        "event", "thought", "observation", "tool", "tool_input", "answer", "latency",
                        "total_token_count", "total_price", "sub_task_id", "sub_task_title", "trace",
                        "question", "options", "allow_custom", "choice",
                    }),
```

（ERROR 兜底事件的 include 无需加——错误事件无这些字段，加了也只是空值，为一致性可加）

`internal/service/conversation_service.py` 的 `save_agent_thoughts`：

1. 保存事件列表加 `QueueEvent.ASK_USER`：

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
                QueueEvent.ASK_USER,
            ]:
```

2. `self.create(MessageAgentThought, ...)` 里 `observation=agent_thought.observation` 改为 `observation=agent_thought.choice or agent_thought.observation`（choice 优先，落库可回显），`tool_input=agent_thought.tool_input` 保持（`_handle_ask_user` 已把 args 写入 tool_input）

- [ ] **Step 4: 运行确认通过**

Run: `venv\Scripts\python -m pytest test/internal/service/test_ask_user_chat_runner.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/service/chat_runner.py internal/service/conversation_service.py test/internal/service/test_ask_user_chat_runner.py
git commit -m "feat(chat): ChatRunner 注入 ask_user 工具、SSE 透传交互字段、推理过程落库支持 ASK_USER"
```

---

### Task 6: 选择提交接口（schema + service + handler + router ×3 入口）

**Files:**
- Create: `internal/service/choice_service.py`
- Create: `internal/schema/choice_schema.py`
- Modify: `internal/handler/app_handler.py`、`internal/handler/web_app_handler.py`、`internal/handler/assistant_agent_handler.py`
- Modify: `internal/router/router.py`
- Test: `test/internal/service/test_choice_service.py`（新建）

**Interfaces:**
- Consumes: `AgentQueueManager.submit_choice`、`AgentQueueManager.generate_task_belong_cache_key`（classmethod）、`set_stop_flag` 的 belong 校验模式、注入的 `Redis`
- Produces:
  - `ChoiceReq(FlaskForm)`：`choice`（StringField, default=""）、`skip`（BooleanField, default=False）；校验二选一（choice 非空 或 skip 为 True）。task_id 走 URL 路径，不在 body
  - `ChoiceService.submit(task_id: UUID, choice: str, skip: bool, account: Account, invoke_from: InvokeFrom) -> None` — belong 校验 → `AgentQueueManager.submit_choice(...)`；归属不符抛 `ForbiddenException("该任务不存在或不属于当前用户")`
  - 路由（均 POST，task_id 走路径，贴合现有 stop 路由风格）：
    - `POST /apps/<uuid:app_id>/conversations/tasks/<uuid:task_id>/choice` → `app_handler.debug_chat_choice(app_id, task_id)`
    - `POST /web_apps/<string:token>/chat/<uuid:task_id>/choice` → `web_app_handler.web_app_chat_choice(token, task_id)`
    - `POST /assistant_agent/chat/<uuid:task_id>/choice` → `assistant_agent_handler.assistant_agent_chat_choice(task_id)`
  - 三个 handler 各注入 `ChoiceService` 字段（`@inject @dataclass` 模式，与 `AppHandler` 现有字段一致）

- [ ] **Step 1: 写失败测试**

```python
# test/internal/service/test_choice_service.py
import uuid
from unittest.mock import MagicMock

import pytest

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.entity.conversation_entity import InvokeFrom
from internal.exception import ForbiddenException
from internal.service.choice_service import ChoiceService


def _make_service(monkeypatch, belong_value) -> tuple[ChoiceService, MagicMock]:
    fake_redis = MagicMock()
    fake_redis.get.return_value = belong_value
    svc = ChoiceService(redis_client=fake_redis)
    monkeypatch.setattr(AgentQueueManager, "submit_choice", MagicMock(return_value=True))
    return svc, fake_redis


def test_submit_writes_choice(monkeypatch):
    account_id = uuid.uuid4()
    belong_value = f"account-{account_id}".encode()
    svc, fake_redis = _make_service(monkeypatch, belong_value)
    svc.submit(uuid.uuid4(), "RBAC", False, MagicMock(id=account_id), InvokeFrom.DEBUGGER)
    AgentQueueManager.submit_choice.assert_called_once()
    call = AgentQueueManager.submit_choice.call_args
    assert call.kwargs["choice"] == "RBAC"
    assert call.kwargs["skip"] is False


def test_submit_forbidden_when_task_missing(monkeypatch):
    svc, _ = _make_service(monkeypatch, None)  # belong key 不存在
    with pytest.raises(ForbiddenException):
        svc.submit(uuid.uuid4(), "RBAC", False, MagicMock(id=uuid.uuid4()), InvokeFrom.DEBUGGER)


def test_submit_forbidden_when_not_owner(monkeypatch):
    svc, _ = _make_service(monkeypatch, b"account-other-user-id")
    with pytest.raises(ForbiddenException):
        svc.submit(uuid.uuid4(), "RBAC", False, MagicMock(id=uuid.uuid4()), InvokeFrom.DEBUGGER)
```

- [ ] **Step 2: 运行确认失败**

Run: `venv\Scripts\python -m pytest test/internal/service/test_choice_service.py -v`
Expected: FAIL（ImportError / ChoiceService 不存在）

- [ ] **Step 3: 最小实现**

`internal/schema/choice_schema.py`：

```python
#!/usr/bin/env python
"""用户选择提交请求结构（task_id 走 URL 路径，不在 body）"""
from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField

from internal.exception import ValidateException


class ChoiceReq(FlaskForm):
    """用户选择提交请求：choice 与 skip 至少提供一个"""
    choice = StringField("choice", default="")
    skip = BooleanField("skip", default=False)

    def validate_choice(self, field) -> None:
        if not field.data and not self.skip.data:
            raise ValidateException("choice 与 skip 至少提供一个")
```

`internal/service/choice_service.py`：

```python
#!/usr/bin/env python
"""用户选择提交服务：校验任务归属 → 写入 Redis 选择队列（ask_user 交互）"""
import logging
from dataclasses import dataclass
from uuid import UUID

from injector import inject
from redis import Redis

from internal.core.agent.agents import AgentQueueManager
from internal.entity.conversation_entity import InvokeFrom
from internal.exception import ForbiddenException
from internal.model import Account

logger = logging.getLogger(__name__)


@inject
@dataclass
class ChoiceService:
    redis_client: Redis

    def submit(self, task_id: UUID, choice: str, skip: bool, account: Account, invoke_from: InvokeFrom) -> None:
        """校验 task_id 归属后提交用户选择"""
        key = AgentQueueManager.generate_task_belong_cache_key(task_id)
        belong = self.redis_client.get(key)
        if not belong:
            raise ForbiddenException("该任务不存在或已过期")
        user_prefix = "account" if invoke_from in [
            InvokeFrom.WEB_APP, InvokeFrom.DEBUGGER, InvokeFrom.ASSISTANT_AGENT,
        ] else "end-user"
        expected = f"{user_prefix}-{account.id!s}"
        if belong.decode("utf-8") != expected:
            raise ForbiddenException("该任务不存在或不属于当前用户")
        ok = AgentQueueManager.submit_choice(task_id, choice=choice, skip=skip)
        if not ok:
            logger.warning("重复提交用户选择被忽略 task_id=%s", task_id)
```

`internal/handler/app_handler.py`：`AppHandler` 加字段 `choice_service: ChoiceService`（import 对应加），加方法：

```python
    @login_required
    def debug_chat_choice(self, app_id: UUID, task_id: UUID):
        """根据传递的应用id+任务id提交调试对话的用户选择"""
        req = ChoiceReq()
        if not req.validate():
            return validation_error_json(req.errors)
        self.choice_service.submit(task_id, req.choice.data, req.skip.data, current_user, InvokeFrom.DEBUGGER)
        return success_message_json("已提交选择")
```

`internal/handler/web_app_handler.py`：加字段 `choice_service: ChoiceService`，加方法 `web_app_chat_choice(self, token: str, task_id: UUID)`（先 `self.web_app_service.get_web_app(token)` 校验 WebApp 存在，其余同上，`InvokeFrom.WEB_APP`）。

`internal/handler/assistant_agent_handler.py`：加字段 `choice_service: ChoiceService`，加方法 `assistant_agent_chat_choice(self, task_id: UUID)`（同上，`InvokeFrom.ASSISTANT_AGENT`）。

`internal/router/router.py` 三个路由（参考现有 stop 路由的 rule/methods）：

```python
        bp.add_url_rule(
            "/apps/<uuid:app_id>/conversations/tasks/<uuid:task_id>/choice",
            view_func=self.app_handler.debug_chat_choice,
            methods=["POST"],
        )
```
```python
        bp.add_url_rule(
            "/web_apps/<string:token>/chat/<uuid:task_id>/choice",
            view_func=self.web_app_handler.web_app_chat_choice,
            methods=["POST"],
        )
```
```python
        bp.add_url_rule(
            "/assistant_agent/chat/<uuid:task_id>/choice",
            view_func=self.assistant_agent_handler.assistant_agent_chat_choice,
            methods=["POST"],
        )
```

- [ ] **Step 4: 运行确认通过**

Run: `venv\Scripts\python -m pytest test/internal/service/test_choice_service.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/schema/choice_schema.py internal/service/choice_service.py internal/handler/app_handler.py internal/handler/web_app_handler.py internal/handler/assistant_agent_handler.py internal/router/router.py test/internal/service/test_choice_service.py
git commit -m "feat(chat): 三个入口新增用户选择提交接口（ask_user 交互）"
```

---

### Task 7: 前端 AskUserOptions 组件 + 三端接入

**Files:**
- Create: `ai-code-llmops-web/src/components/AskUserOptions.vue`
- Create: `ai-code-llmops-web/src/components/__tests__/AskUserOptions.spec.ts`
- Modify: `ai-code-llmops-web/src/config/index.ts`（QueueEvent 加 `askUser: 'ask_user'`）
- Modify: `ai-code-llmops-web/src/views/space/apps/components/PreviewDebugChat.vue`
- Modify: `ai-code-llmops-web/src/views/web-apps/IndexView.vue`
- Modify: `ai-code-llmops-web/src/views/pages/HomeView.vue`

**Interfaces:**
- Consumes: 后端 `ask_user` SSE 事件（字段 event/question/options/allow_custom/task_id/id/choice）、`POST .../choice` 接口（task_id 在 URL 路径，body 为 `{ choice }` 或 `{ skip: true }`）
- Produces: `<AskUserOptions :question :options :allow-custom :task-id :event-id :choice @submitted>`；三端 SSE 处理加 `ask_user` 分支（push 进 `currentMessage.agent_thoughts`）；消息渲染区在 AI 内容下渲染组件

- [ ] **Step 1: 写失败测试**（vitest + @vue/test-utils，参考 `ai-code-llmops-web` 现有测试配置）

```ts
// ai-code-llmops-web/src/components/__tests__/AskUserOptions.spec.ts
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AskUserOptions from '../AskUserOptions.vue'

describe('AskUserOptions', () => {
  it('渲染问题与选项', () => {
    const wrapper = mount(AskUserOptions, {
      props: {
        question: '选择授权模型？',
        options: ['RBAC', 'ABAC'],
        allowCustom: true,
        taskId: 't1',
        eventId: 'e1',
        choice: '',
      },
    })
    expect(wrapper.text()).toContain('选择授权模型？')
    expect(wrapper.text()).toContain('RBAC')
    expect(wrapper.text()).toContain('ABAC')
  })

  it('提交选择后进入已提交状态并 emit submitted', async () => {
    const wrapper = mount(AskUserOptions, {
      props: { question: 'q', options: ['A'], allowCustom: false, taskId: 't1', eventId: 'e1', choice: '' },
    })
    await wrapper.findAll('button')[0].trigger('click')
    expect(wrapper.emitted('submitted')).toBeTruthy()
    expect(wrapper.emitted('submitted')![0]).toEqual([{ taskId: 't1', choice: 'A', skip: false }])
  })

  it('choice 非空时回显已选', () => {
    const wrapper = mount(AskUserOptions, {
      props: { question: 'q', options: ['A'], allowCustom: false, taskId: 't1', eventId: 'e1', choice: 'A' },
    })
    expect(wrapper.text()).toContain('已选：A')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd ai-code-llmops-web && npx vitest run src/components/__tests__/AskUserOptions.spec.ts`
Expected: FAIL（组件不存在）

- [ ] **Step 3: 实现组件**

`ai-code-llmops-web/src/components/AskUserOptions.vue`（Vue 3 `<script setup lang="ts">`，样式用项目 tailwind 类）：

- Props：`question: string`、`options: string[]`、`allowCustom: boolean`、`taskId: string`、`eventId: string`、`choice: string`
- 状态：`selected`（当前高亮项）、`customText`（自定义输入）、`submitted`（是否已提交）、`submitting`
- Emits：`submitted: (payload: { taskId: string; choice: string; skip: boolean }) => void`
- 逻辑：
  - `isHistory = computed(() => !!props.choice)` → 回显模式：显示"已选：{choice}"，全部按钮禁用
  - 提交：`choice = selected || customText`；`emit('submitted', { taskId, choice, skip: false })`；`submitted = true`
  - 跳过：`emit('submitted', { taskId, choice: '', skip: true })`；`submitted = true`
  - `submitted` 后按钮禁用，文案"已提交，继续处理中…"
- 模板结构：问题文本 → 选项按钮列表（`v-for`，选中态高亮）→ 自定义输入框（`v-if="allowCustom"`）→ 底部"提交"与"跳过"按钮

- [ ] **Step 4: 三端接入**

每个页面（`PreviewDebugChat.vue` / `IndexView.vue` / `HomeView.vue`）：

1. `src/config/index.ts` 的 `QueueEvent` 对象加 `askUser: 'ask_user'`（三端共用同一常量，无需各页改动枚举）
2. SSE 事件处理分支（参照现有 `agentMessage`/`agentThought` 分支的 push 模式）：

```ts
        if (event === QueueEvent.askUser) {
          const exists = agent_thoughts.findIndex((item) => item?.id === event_id)
          const payload = {
            id: event_id,
            event: QueueEvent.askUser,
            question: data?.question ?? '',
            options: data?.options ?? [],
            allow_custom: data?.allow_custom ?? true,
            choice: data?.choice ?? '',
            task_id: data?.task_id,
          }
          if (exists === -1) agent_thoughts.push(payload)
          else agent_thoughts[exists] = payload
        }
```

3. 消息渲染区（AI 消息内容下方）加：

```html
<AskUserOptions
  v-if="askUserThought"
  :question="askUserThought.question"
  :options="askUserThought.options"
  :allow-custom="askUserThought.allow_custom"
  :task-id="askUserThought.task_id"
  :event-id="askUserThought.id"
  :choice="askUserThought.choice || ''"
  @submitted="onChoiceSubmitted"
/>
```

`askUserThought` 为该消息 `agent_thoughts` 中最后一个 `event === QueueEvent.askUser` 的 thought（computed）。

4. `onChoiceSubmitted(payload)`：调对应入口的 choice 接口（task_id 拼进 URL 路径，body 只带 `{ choice, skip }`），失败 toast；成功后本地把该 thought 的 `choice` 置为提交值（或交给 SSE 后续事件）。三个入口的 URL：
   - 调试：`/apps/${appId}/conversations/tasks/${payload.taskId}/choice`
   - WebApp：`/web_apps/${token}/chat/${payload.taskId}/choice`
   - 助手：`/assistant_agent/chat/${payload.taskId}/choice`

- [ ] **Step 5: 运行确认通过**

Run: `cd ai-code-llmops-web && npx vitest run src/components/__tests__/AskUserOptions.spec.ts`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add ai-code-llmops-web/src/components/AskUserOptions.vue ai-code-llmops-web/src/components/__tests__/AskUserOptions.spec.ts ai-code-llmops-web/src/views/space/apps/components/PreviewDebugChat.vue ai-code-llmops-web/src/views/web-apps/IndexView.vue ai-code-llmops-web/src/views/pages/HomeView.vue
git commit -m "feat(web): 新增 AskUserOptions 组件并接入调试/WebApp/助手三端"
```

---

### Task 8: 联调验证与文档收尾

**Files:**
- Test: `test/internal/core/agent/test_ask_user_agent_branch.py`（追加超时用例）、`test/internal/core/agent/test_queue_manager_choice.py`（追加 skip 用例）
- Modify: `Obsidian/Obsidian/Agent交互式选项选择设计.md`（状态改为 implementing→done 可选）、工作日志

**Interfaces:**
- 无新接口；验证 Task 1-7 端到端行为

- [ ] **Step 1: 追加超时/跳过用例**

```python
# test_ask_user_agent_branch.py 追加
def test_handle_ask_user_timeout_treated_as_skip(monkeypatch):
    agent = _make_agent(monkeypatch, wait_result=(None, True))
    result = agent._handle_ask_user({"task_id": uuid.uuid4(), "messages": []}, {"name": ASK_USER_TOOL_NAME, "args": {"question": "q"}, "id": "c2"})
    assert "跳过" in result


def test_wait_for_choice_skip_payload(monkeypatch):
    from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
    from test.internal.core.agent.test_queue_manager_choice import _fake_redis
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = ("key", b'{"choice": "", "skip": true}')
    choice, skipped = AgentQueueManager.wait_for_choice(uuid.uuid4(), timeout=300)
    assert choice == ""
    assert skipped is True
```

- [ ] **Step 2: 运行全量 agent 相关测试**

Run: `venv\Scripts\python -m pytest test/internal/core/agent test/internal/service/test_choice_service.py test/internal/service/test_ask_user_chat_runner.py -v`
Expected: 全部 PASS

- [ ] **Step 3: 前端全量单测**

Run: `cd ai-code-llmops-web && npx vitest run`
Expected: 全部 PASS（含既有用例不回归）

- [ ] **Step 4: 后端静态检查**

Run: `venv\Scripts\python -m ruff check internal test`（项目用 ruff，见 `.ruff_cache`）
Expected: 无新增 error

- [ ] **Step 5: 提交**

```bash
git add test/internal/core/agent/test_ask_user_agent_branch.py test/internal/core/agent/test_queue_manager_choice.py
git commit -m "test(agent): ask_user 超时按跳过处理、skip 载荷用例"
```

- [ ] **Step 6: 更新 Obsidian 文档状态并记录工作日志**

`Obsidian/Obsidian/Agent交互式选项选择设计.md` frontmatter `status: designing` → `status: done`（若联调验证通过）；`Obsidian/Obsidian/工作日志/2026-08-27.md` 追加当日实现记录。提交：

```bash
git add Obsidian
git commit -m "docs: ask_user 交互功能实现完成，更新设计状态与工作日志"
```
