# 编排器任务分配与汇总确认（confirm_plan / confirm_result）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让编排器（OrchestratorAgent）主 Agent 在任务分配后（确认点 1，必现）和汇总后（确认点 2，LLM 自主）提供 ask_user 确认交互，子任务执行期间不弹框。

**Architecture:** 在 OrchestratorAgent 图里插入两个新节点：`confirm_plan`（plan 之后，发布携带结构化子任务方案的 ask_user，用户勾选保留/重新规划，超时按全量执行）和 `confirm_result`（summarize 之后，LLM 判断汇总有无歧义，有则弹"确认完成/重新生成"）。复用现有 ask_user 事件、Redis 等待（`wait_for_choice`）、前端确认框；协议扩展 `AgentThought.sub_task_options` + 提交 payload 的 `action/keep_orders/custom` 字段。

**Tech Stack:** Python 3.12 / LangGraph / Redis / Vue 3 + TypeScript / vitest / pytest

**Spec:** `Obsidian/Obsidian/编排器任务分配与汇总确认设计.md`

## Global Constraints

- 确认点 1：有子任务时必现；无子任务（direct_answer）不弹框
- 确认点 1 交互：子任务勾选列表**默认全不选** + 自定义原因输入 + `确认执行`/`重新规划`按钮；`重新规划`**必须填原因**（前端禁用无原因的重新规划）
- 确认点 1 超时（300s）：按推荐选择 = **全量子任务执行**
- 重新规划：`plan_feedback` 传给 plan 重拆，**最多 2 轮**（`plan_attempts >= 2` 不再重拆）
- 确认点 2：LLM 结构化输出 `ConfirmVerdict{need_confirm, reason}`；无歧义直接 END；有歧义弹"确认完成/重新生成"
- 确认点 2 超时：按"确认完成"处理
- 子任务执行期间（execute）不弹框
- 协议：`AgentThought` 新增 `sub_task_options: list[dict]`；提交 payload 扩展 `{action, keep_orders, custom, skip, event_id}`（plan 模式）与 `{choice, custom, skip, event_id}`（option 模式，含确认点 2）
- `wait_for_choice` 保持向后兼容（旧 payload 无 action 时按 choice 处理）；新增 `wait_for_plan_choice` 返回 `(action, keep_orders, custom, skipped)`
- 不新增数据库表/列；`sub_task_options` 随 `AgentThought` 序列化，历史回显依赖现有 `message_agent_thought.tool_input`/`message` 落库
- 前端 `AskUserOptions.vue` 扩展 `mode` prop（`option` 默认 / `plan` 新增），三端 SSE 存入 `sub_task_options`

---

### Task 1: 协议扩展（sub_task_options 字段 + ConfirmVerdict + 常量）

**Files:**
- Modify: `internal/core/agent/entities/queue_entity.py`
- Modify: `internal/core/agent/entities/agent_entity.py`
- Test: `test/internal/core/agent/test_ask_user_entity.py`（追加）

**Interfaces:**
- Consumes: `AgentThought`、`QueueEvent`（已存在）
- Produces: `AgentThought.sub_task_options: list[dict] = Field(default_factory=list)`；`ConfirmVerdict(BaseModel){need_confirm: bool=False, reason: str=""}`；`ORCHESTRATOR_CONFIRM_PROMPT_TEMPLATE: str`（常量，见 spec）

- [ ] **Step 1: 写失败测试**（追加到 `test_ask_user_entity.py`）

```python
from internal.core.agent.entities.agent_entity import ConfirmVerdict


def test_agent_thought_sub_task_options():
    thought = AgentThought(
        id="00000000-0000-0000-0000-000000000001",
        task_id="00000000-0000-0000-0000-000000000002",
        event=QueueEvent.ASK_USER,
        sub_task_options=[{"order": 1, "title": "检索资料", "role_prompt": "你是检索专家"}],
    )
    assert thought.sub_task_options == [{"order": 1, "title": "检索资料", "role_prompt": "你是检索专家"}]


def test_confirm_verdict_model():
    v = ConfirmVerdict()
    assert v.need_confirm is False
    assert v.reason == ""
    v2 = ConfirmVerdict(need_confirm=True, reason="存在歧义")
    assert v2.need_confirm is True
    assert v2.reason == "存在歧义"
```

- [ ] **Step 2: 运行确认失败**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_ask_user_entity.py -v`
Expected: FAIL（`sub_task_options` 字段缺失 / `ConfirmVerdict` 不存在）

- [ ] **Step 3: 最小实现**

`internal/core/agent/entities/queue_entity.py`：`AgentThought` 的 ask_user 字段组后加：

```python
    # 交互式选项选择（ask_user 事件专用）
    question: str = ""  # 向用户展示的问题
    options: list[str] = Field(default_factory=list)  # 可选项列表
    allow_custom: bool = True  # 是否允许用户自定义输入
    choice: str = ""  # 用户最终选择（落库回显用）
    # 编排器任务分配确认（confirm_plan 事件专用）：子任务方案 [{order, title, role_prompt, expect_output, required_tools}]
    sub_task_options: list[dict] = Field(default_factory=list)
```

`internal/core/agent/entities/agent_entity.py` 末尾加：

```python
class ConfirmVerdict(BaseModel):
    """汇总歧义判断：LLM 结构化输出"""
    need_confirm: bool = False  # 汇总结果是否需要用户确认
    reason: str = ""            # 需要确认的原因（need_confirm=True 时展示给用户）


ORCHESTRATOR_CONFIRM_PROMPT_TEMPLATE = (
    "你是任务结果审核助手。下面给出了用户的问题和基于子任务执行结果的最终汇总答案。\n"
    "请判断这个汇总答案是否完整、明确、无歧义，是否足以让用户直接采用：\n"
    "1. 答案完整且无歧义，用户可以直接采纳 → need_confirm=false\n"
    "2. 答案存在不确定性、缺少关键信息、涉及多个可选方向需要用户决策 → need_confirm=true，并在 reason 中简述需要用户确认的点\n"
    "只输出 JSON：{{'need_confirm': bool, 'reason': str}}"
)
```

- [ ] **Step 4: 运行确认通过**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_ask_user_entity.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/entities/queue_entity.py internal/core/agent/entities/agent_entity.py test/internal/core/agent/test_ask_user_entity.py
git commit -m "feat(agent): AgentThought 新增 sub_task_options 字段，编排器汇总确认新增 ConfirmVerdict 与提示词常量"
```

---

### Task 2: 队列层新增 wait_for_plan_choice + submit_choice 扩展

**Files:**
- Modify: `internal/core/agent/agents/agent_queue_manager.py`
- Test: `test/internal/core/agent/test_queue_manager_choice.py`（追加）

**Interfaces:**
- Consumes: `generate_choice_queue_key`（已存在）、`wait_for_choice`（已存在，保持不动）
- Produces:
  - `AgentQueueManager.submit_choice(task_id, choice=None, skip=False, event_id=None, action: str | None = None, keep_orders: list[int] | None = None, custom: str | None = None) -> bool` — payload 增加 action/keep_orders/custom（缺省保持旧结构）
  - `AgentQueueManager.wait_for_plan_choice(task_id, timeout=300, event_id=None) -> tuple[str, list[int], str, bool]` — 返回 `(action, keep_orders, custom, skipped)`；超时/异常 → `("confirm", [], "", True)`

- [ ] **Step 1: 写失败测试**（追加到 `test_queue_manager_choice.py`）

```python
def test_submit_choice_with_plan_payload(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.exists.return_value = False
    ok = AgentQueueManager.submit_choice(
        uuid.uuid4(), action="confirm", keep_orders=[1, 3], custom="", event_id="e1",
    )
    assert ok is True
    payload = json.loads(fake_redis.rpush.call_args.args[1])
    assert payload["action"] == "confirm"
    assert payload["keep_orders"] == [1, 3]
    assert payload["custom"] == ""
    assert payload["event_id"] == "e1"


def test_wait_for_plan_choice_confirm(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = ("key", json.dumps(
        {"action": "confirm", "keep_orders": [1, 3], "custom": "", "skip": False, "event_id": "e1"},
    ).encode())
    action, keep, custom, skipped = AgentQueueManager.wait_for_plan_choice(uuid.uuid4(), event_id="e1")
    assert action == "confirm"
    assert keep == [1, 3]
    assert custom == ""
    assert skipped is False


def test_wait_for_plan_choice_replan(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = ("key", json.dumps(
        {"action": "replan", "keep_orders": [], "custom": "改用ABAC", "skip": False, "event_id": "e1"},
    ).encode())
    action, keep, custom, skipped = AgentQueueManager.wait_for_plan_choice(uuid.uuid4(), event_id="e1")
    assert action == "replan"
    assert keep == []
    assert custom == "改用ABAC"
    assert skipped is False


def test_wait_for_plan_choice_timeout(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = None
    action, keep, custom, skipped = AgentQueueManager.wait_for_plan_choice(uuid.uuid4(), timeout=1)
    assert skipped is True
    assert action == "confirm"  # 超时按确认处理，调用方据此全量执行
```

- [ ] **Step 2: 运行确认失败**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_queue_manager_choice.py -v`
Expected: FAIL（`submit_choice` 无新参数 / `wait_for_plan_choice` 不存在）

- [ ] **Step 3: 最小实现**

`internal/core/agent/agents/agent_queue_manager.py`：

1. `submit_choice` 签名扩展（payload 构造改为）：

```python
    @classmethod
    def submit_choice(cls, task_id: UUID, choice: str | None = None, skip: bool = False, event_id: str | None = None,
                      action: str | None = None, keep_orders: list[int] | None = None, custom: str | None = None) -> bool:
        """提交用户选择到 Redis 队列；同一 task_id 已有未消费选择时忽略（幂等）"""
        from app.http.module import injector
        redis_client = injector.get(Redis)
        key = cls.generate_choice_queue_key(task_id)
        if redis_client.exists(key) and redis_client.llen(key) > 0:
            return False
        payload = {
            "choice": choice,
            "skip": skip,
            "event_id": str(event_id) if event_id else "",
        }
        if action is not None:
            payload["action"] = action
        if keep_orders is not None:
            payload["keep_orders"] = keep_orders
        if custom is not None:
            payload["custom"] = custom
        redis_client.rpush(key, json.dumps(payload, ensure_ascii=False))
        redis_client.expire(key, 1800)
        return True
```

2. 新增 `wait_for_plan_choice`（放在 `wait_for_choice` 之后）：

```python
    @classmethod
    def wait_for_plan_choice(cls, task_id: UUID, timeout: int = 300, event_id: str | None = None) -> tuple[str, list[int], str, bool]:
        """等待任务分配确认：返回 (action, keep_orders, custom, skipped)。

        - action: "confirm" / "replan"（缺省按 confirm 兼容旧载荷）
        - keep_orders: 用户勾选保留的子任务 order 列表
        - custom: 用户填的原因/补充要求
        - skipped: 超时/异常 → True（调用方按推荐选择=全量子任务执行）
        """
        from app.http.module import injector
        redis_client = injector.get(Redis)
        key = cls.generate_choice_queue_key(task_id)
        deadline = time.time() + timeout
        while True:
            remaining = max(0, int(deadline - time.time()))
            if remaining <= 0:
                return "confirm", [], "", True
            try:
                item = redis_client.blpop(key, timeout=min(remaining, 1))
            except Exception:  # noqa: BLE001 - Redis 异常统一按跳过处理
                return "confirm", [], "", True
            if not item:
                continue
            try:
                payload = json.loads(item[1])
            except (TypeError, ValueError):
                continue
            if event_id is not None and payload.get("event_id") != event_id:
                continue  # 残留载荷，丢弃继续等
            return (
                payload.get("action") or "confirm",
                payload.get("keep_orders") or [],
                payload.get("custom") or "",
                bool(payload.get("skip", False)),
            )
```

- [ ] **Step 4: 运行确认通过**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_queue_manager_choice.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/agents/agent_queue_manager.py test/internal/core/agent/test_queue_manager_choice.py
git commit -m "feat(agent): 队列层新增 wait_for_plan_choice，submit_choice 支持 action/keep_orders/custom"
```

---

### Task 3: wait_for_choice 返回 custom（三元组改造，全调用方同步）

**Files:**
- Modify: `internal/core/agent/agents/agent_queue_manager.py`
- Modify: `internal/core/agent/agents/function_call_agent.py`（`_handle_ask_user` 解包）
- Test: `test/internal/core/agent/test_queue_manager_choice.py`（既有 wait_for_choice 测试更新为三元组）

**Interfaces:**
- Consumes: `wait_for_choice`（Task 2 保持二元组，本任务改三元组）
- Produces: `AgentQueueManager.wait_for_choice(task_id, timeout=300, event_id=None) -> tuple[str | None, bool, str]` — 返回 `(choice, skipped, custom)`；custom 缺省 `""`
- 同步更新 `function_call_agent._handle_ask_user` 的解包（`choice, skipped = ...` → `choice, skipped, _ = ...`）

- [ ] **Step 1: 更新既有测试为三元组**

`test/internal/core/agent/test_queue_manager_choice.py` 中 `wait_for_choice` 相关断言改为：

```python
def test_wait_for_choice_returns_choice(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = ("key", json.dumps({"choice": "ABAC", "skip": False}).encode())
    choice, skipped, custom = AgentQueueManager.wait_for_choice(uuid.uuid4(), timeout=300)
    assert choice == "ABAC"
    assert skipped is False
    assert custom == ""


def test_wait_for_choice_custom(monkeypatch):
    fake_redis = _fake_redis(monkeypatch)
    fake_redis.blpop.return_value = ("key", json.dumps(
        {"choice": "重新生成", "skip": False, "custom": "重点看方案B", "event_id": "e1"},
    ).encode())
    choice, skipped, custom = AgentQueueManager.wait_for_choice(uuid.uuid4(), event_id="e1")
    assert choice == "重新生成"
    assert custom == "重点看方案B"
    assert skipped is False
```

（保留既有 `test_wait_for_choice_timeout_returns_skip`，断言改为三元组解包 `choice, skipped, custom = ...` 后 `assert choice is None; assert skipped is True`）

- [ ] **Step 2: 运行确认失败**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_queue_manager_choice.py -v`
Expected: FAIL（wait_for_choice 仍返回二元组，三元组解包 ValueError）

- [ ] **Step 3: 最小实现**

`internal/core/agent/agents/agent_queue_manager.py` 的 `wait_for_choice`：

```python
    @classmethod
    def wait_for_choice(cls, task_id: UUID, timeout: int = 300, event_id: str | None = None) -> tuple[str | None, bool, str]:
        """阻塞等待用户选择：返回 (choice, skipped, custom)；超时/异常按跳过处理。"""
        from app.http.module import injector
        redis_client = injector.get(Redis)
        key = cls.generate_choice_queue_key(task_id)
        deadline = time.time() + timeout
        while True:
            remaining = max(0, int(deadline - time.time()))
            if remaining <= 0:
                return None, True, ""
            try:
                item = redis_client.blpop(key, timeout=min(remaining, 1))
            except Exception:  # noqa: BLE001
                return None, True, ""
            if not item:
                continue
            try:
                payload = json.loads(item[1])
            except (TypeError, ValueError):
                continue
            if event_id is not None and payload.get("event_id") != event_id:
                continue
            return payload.get("choice"), bool(payload.get("skip", False)), payload.get("custom") or ""
```

`internal/core/agent/agents/function_call_agent.py` 的 `_handle_ask_user`：

```python
        choice, skipped, _custom = AgentQueueManager.wait_for_choice(
            state["task_id"], timeout=ASK_USER_WAIT_TIMEOUT, event_id=str(ask_event_id),
        )
```

- [ ] **Step 4: 运行确认通过**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_queue_manager_choice.py test/internal/core/agent/test_ask_user_agent_branch.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/agents/agent_queue_manager.py internal/core/agent/agents/function_call_agent.py test/internal/core/agent/test_queue_manager_choice.py
git commit -m "refactor(agent): wait_for_choice 返回 (choice, skipped, custom) 三元组，支持确认点2原因回传"
```

---

### Task 5: 编排器 confirm_plan 节点（任务分配确认）

**Files:**
- Modify: `internal/core/agent/agents/orchestrator_agent.py`
- Test: `test/internal/core/agent/test_orchestrator_confirm_plan.py`（新建）

**Interfaces:**
- Consumes: `AgentThought.sub_task_options`（Task 1）、`wait_for_plan_choice`（Task 2）、`ASK_USER_TOOL_NAME`/`ASK_USER_WAIT_TIMEOUT`（已存在）、`QueueEvent.ASK_USER`（已存在）
- Produces: `OrchestratorAgent._confirm_plan_node(state) -> AgentState` — 有子任务时发布 ASK_USER（question/options/sub_task_options），`wait_for_plan_choice`；超时→全量子任务；replan→`{"plan_feedback": custom, "sub_tasks": []}`；confirm→按 keep_orders 过滤（空 keep_orders 且确认→全选）

- [ ] **Step 1: 写失败测试**

```python
# test/internal/core/agent/test_orchestrator_confirm_plan.py
import uuid
from unittest.mock import MagicMock

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.agents.orchestrator_agent import OrchestratorAgent
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.conversation_entity import InvokeFrom


def _make_agent(monkeypatch, wait_result=("confirm", [1, 3], "", False)):
    monkeypatch.setattr(
        AgentQueueManager, "wait_for_plan_choice", MagicMock(return_value=wait_result),
    )
    agent = OrchestratorAgent(
        name="test-orch",
        llm=MagicMock(),
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
    # 实例 publish 替换为 mock（断言发布内容用）；AgentQueueManager 依赖 injector 拿 Redis，
    # 但 __init__ 惰性构造不连库（与既有 ask_user 测试同款处理）
    monkeypatch.setattr(agent.agent_queue_manager, "publish", MagicMock())
    return agent


def _specs():
    from internal.core.agent.entities.agent_entity import SubTaskSpec
    return [
        SubTaskSpec(order=1, title="检索资料", role_prompt="你是检索专家"),
        SubTaskSpec(order=2, title="撰写报告", role_prompt="你是报告专家"),
        SubTaskSpec(order=3, title="复核", role_prompt="你是复核专家"),
    ]


def test_confirm_plan_publishes_ask_user_with_sub_task_options(monkeypatch):
    agent = _make_agent(monkeypatch)
    task_id = uuid.uuid4()
    state = {"task_id": task_id, "sub_tasks": _specs(), "messages": []}
    result = agent._confirm_plan_node(state)
    published = agent.agent_queue_manager.publish.call_args.args[1]
    assert published.event == QueueEvent.ASK_USER
    assert published.sub_task_options == [
        {"order": 1, "title": "检索资料", "role_prompt": "你是检索专家"},
        {"order": 2, "title": "撰写报告", "role_prompt": "你是报告专家"},
        {"order": 3, "title": "复核", "role_prompt": "你是复核专家"},
    ]
    assert [o for o in published.options] == ["检索资料", "撰写报告", "复核"]
    # confirm [1,3] → 保留 order 1,3
    assert [s.order for s in result["sub_tasks"]] == [1, 3]


def test_confirm_plan_no_subtasks_skips(monkeypatch):
    agent = _make_agent(monkeypatch)
    result = agent._confirm_plan_node({"task_id": uuid.uuid4(), "sub_tasks": [], "messages": []})
    agent.agent_queue_manager.publish.assert_not_called()
    assert result["sub_tasks"] == []


def test_confirm_plan_replan(monkeypatch):
    agent = _make_agent(monkeypatch, wait_result=("replan", [], "第二个子任务改用ABAC", False))
    result = agent._confirm_plan_node({"task_id": uuid.uuid4(), "sub_tasks": _specs(), "messages": []})
    assert result["plan_feedback"] == "第二个子任务改用ABAC"
    assert result["sub_tasks"] == []


def test_confirm_plan_timeout_keeps_all(monkeypatch):
    agent = _make_agent(monkeypatch, wait_result=("confirm", [], "", True))
    result = agent._confirm_plan_node({"task_id": uuid.uuid4(), "sub_tasks": _specs(), "messages": []})
    assert [s.order for s in result["sub_tasks"]] == [1, 2, 3]
```

- [ ] **Step 2: 运行确认失败**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_orchestrator_confirm_plan.py -v`
Expected: FAIL（`_confirm_plan_node` 不存在）

- [ ] **Step 3: 最小实现**

`internal/core/agent/agents/orchestrator_agent.py`：导入区加 `ASK_USER_TOOL_NAME`、`ASK_USER_WAIT_TIMEOUT`（`agent_entity` 导入块）；类内新增：

```python
    def _confirm_plan_node(self, state: AgentState) -> AgentState:
        """任务分配确认：发布 ask_user 展示子任务方案，等待用户确认/重新规划"""
        specs = state["sub_tasks"]
        if not specs:
            return {"sub_tasks": specs}  # 无子任务（direct_answer 场景）不弹框

        ask_event_id = uuid.uuid4()
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=ask_event_id, task_id=state["task_id"],
            event=QueueEvent.ASK_USER,
            question="请确认任务分配方案：勾选需要执行的子任务",
            options=[s.title for s in specs],
            sub_task_options=[s.model_dump(exclude={"task_id"}) for s in specs],
            allow_custom=True,
            tool=ASK_USER_TOOL_NAME,
            tool_input={"question": "请确认任务分配方案", "options": [s.title for s in specs]},
            message=messages_to_dict(state["messages"]),
            latency=0,
        ))

        action, keep_orders, custom, skipped = AgentQueueManager.wait_for_plan_choice(
            state["task_id"], timeout=ASK_USER_WAIT_TIMEOUT, event_id=str(ask_event_id),
        )
        if skipped:
            # 超时：按推荐选择 = 全量子任务执行（任务不卡死）
            return {"sub_tasks": specs}
        if action == "replan" or custom:
            # 重新规划：自定义原因存进 state，回 plan 重拆
            return {"plan_feedback": custom, "sub_tasks": []}
        # 确认：按 keep_orders 过滤（空 keep_orders 但确认 → 全选）
        keep = set(keep_orders) if keep_orders else {s.order for s in specs}
        filtered = [s for s in specs if s.order in keep]
        return {"sub_tasks": filtered}
```

- [ ] **Step 4: 运行确认通过**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_orchestrator_confirm_plan.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/agents/orchestrator_agent.py test/internal/core/agent/test_orchestrator_confirm_plan.py
git commit -m "feat(agent): 编排器新增 confirm_plan 节点——任务分配后弹 ask_user 确认，支持勾选保留/重新规划/超时全量"
```

---

### Task 6: plan 节点融合 plan_feedback + confirm_result 节点（汇总确认）

**Files:**
- Modify: `internal/core/agent/agents/orchestrator_agent.py`
- Test: `test/internal/core/agent/test_orchestrator_confirm_result.py`（新建）

**Interfaces:**
- Consumes: `ConfirmVerdict`/`ORCHESTRATOR_CONFIRM_PROMPT_TEMPLATE`（Task 1）、`wait_for_choice` 三元组（Task 3）、`QueueEvent.ASK_USER`（已存在）
- Produces:
  - `_plan_node` 改造：`plan_feedback` 拼进 prompt；`plan_attempts >= 2` 时不再重拆（直接用现有 sub_tasks）
  - `_confirm_result_node(state) -> AgentState` — LLM 判断 need_confirm；无歧义→`{}`；有歧义→发布 ask_user（确认完成/重新生成），`wait_for_choice` 三元组拿 custom，完成/超时→`{}`，重新生成→`{"plan_feedback": custom, "sub_tasks": [], "plan_attempts": 0, "regenerate": True}`
  - `_replan_condition(state) -> Literal["plan", "execute"]`、`_confirm_done_condition(state) -> Literal["plan", "__end__"]`（classmethod）

- [ ] **Step 1: 写失败测试**

```python
# test/internal/core/agent/test_orchestrator_confirm_result.py
import uuid
from unittest.mock import MagicMock

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.agents.orchestrator_agent import OrchestratorAgent
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.conversation_entity import InvokeFrom


def _make_agent(monkeypatch, verdict=None, wait_result=("确认完成", False, "")):
    monkeypatch.setattr(
        AgentQueueManager, "wait_for_choice", MagicMock(return_value=wait_result),
    )
    llm = MagicMock()
    class FakeVerdict:
        need_confirm = verdict.need_confirm if verdict else False
        reason = verdict.reason if verdict else ""
    class FakePlanner:
        def invoke(self, messages):
            return FakeVerdict()
    llm.with_structured_output.return_value = FakePlanner()
    agent = OrchestratorAgent(
        name="test-orch",
        llm=llm,
        agent_config=AgentConfig(
            user_id=uuid.uuid4(), invoke_from=InvokeFrom.DEBUGGER,
            preset_prompt="", enable_long_term_memory=False, tools=[],
            review_config={"enable": False, "keywords": [], "inputs_config": {"enable": False}, "outputs_config": {"enable": False}},
            orchestrator_config={},
        ),
    )
    monkeypatch.setattr(agent.agent_queue_manager, "publish", MagicMock())
    return agent


def test_confirm_result_no_ambiguity_no_ask(monkeypatch):
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=False, reason=""))
    result = agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    agent.agent_queue_manager.publish.assert_not_called()
    assert result == {}


def test_confirm_result_ambiguity_publishes_ask(monkeypatch):
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=True, reason="方向未定"))
    agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    published = agent.agent_queue_manager.publish.call_args.args[1]
    assert published.event == QueueEvent.ASK_USER
    assert published.options == ["确认完成", "重新生成"]
    assert "方向未定" in published.question


def test_confirm_result_confirm_done(monkeypatch):
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=True, reason="x"),
                        wait_result=("确认完成", False, ""))
    result = agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    assert result == {}


def test_confirm_result_regenerate(monkeypatch):
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=True, reason="x"),
                        wait_result=("重新生成", False, "重点看方案B"))
    result = agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    assert result["regenerate"] is True
    assert result["plan_feedback"] == "重点看方案B"
    assert result["plan_attempts"] == 0


def test_confirm_result_timeout_done(monkeypatch):
    agent = _make_agent(monkeypatch, verdict=MagicMock(need_confirm=True, reason="x"),
                        wait_result=(None, True, ""))
    result = agent._confirm_result_node({"task_id": uuid.uuid4(), "query": "q", "final_answer": "a"})
    assert result == {}
```

- [ ] **Step 2: 运行确认失败**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_orchestrator_confirm_result.py -v`
Expected: FAIL（`_confirm_result_node` 不存在）

- [ ] **Step 3: 最小实现**

`internal/core/agent/agents/orchestrator_agent.py`：

0. 导入区加（`agent_entity` 导入块补两项）：

```python
from internal.core.agent.entities.agent_entity import (
    ORCHESTRATOR_DIRECT_ANSWER_SYSTEM_PROMPT_TEMPLATE,
    ORCHESTRATOR_PLAN_SYSTEM_PROMPT_TEMPLATE,
    ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE,
    ORCHESTRATOR_CONFIRM_PROMPT_TEMPLATE,
    AgentConfig,
    AgentState,
    ConfirmVerdict,
    SubTaskPlan,
    SubTaskResult,
    SubTaskSpec,
    build_system_prompt,
)
```

（同时确认 `ASK_USER_TOOL_NAME` / `ASK_USER_WAIT_TIMEOUT` 已在导入——Task 5 已加，若无则一并补）

1. `_plan_node` 改造（在 `HumanMessage(content=state["query"])` 处）：

```python
        feedback = state.get("plan_feedback", "")
        if feedback:
            human_content = f"{state['query']}\n\n用户补充要求：{feedback}"
        else:
            human_content = state["query"]
        ...
                plan = plan_llm.invoke([
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=human_content),
                ])
```

2. 类内新增 `_confirm_result_node`：

```python
    def _confirm_result_node(self, state: AgentState) -> AgentState:
        """汇总确认：LLM 判断汇总答案是否有歧义，有则弹框"""
        verdict = self.llm.with_structured_output(ConfirmVerdict).invoke([
            SystemMessage(content=ORCHESTRATOR_CONFIRM_PROMPT_TEMPLATE),
            HumanMessage(content=state["query"]),
            SystemMessage(content=state["final_answer"]),
        ])
        if not verdict.need_confirm:
            return {}  # 无歧义，直接 END

        ask_event_id = uuid.uuid4()
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=ask_event_id, task_id=state["task_id"],
            event=QueueEvent.ASK_USER,
            question=f"汇总结果存在以下需要确认的点：{verdict.reason}\n请选择：",
            options=["确认完成", "重新生成"],
            allow_custom=True,
            tool=ASK_USER_TOOL_NAME,
            tool_input={"question": verdict.reason, "options": ["确认完成", "重新生成"]},
            message=messages_to_dict(state["messages"]),
            latency=0,
        ))
        choice, skipped, custom = AgentQueueManager.wait_for_choice(
            state["task_id"], timeout=ASK_USER_WAIT_TIMEOUT, event_id=str(ask_event_id),
        )
        if skipped or choice == "确认完成":
            return {}  # 完成（超时也按完成）
        # 重新生成：custom 为用户填的原因（可能为空），回 plan 重拆
        return {"plan_feedback": custom or "", "sub_tasks": [], "plan_attempts": 0, "regenerate": True}
```

3. 条件边（classmethod，图注册用）：

```python
    @classmethod
    def _replan_condition(cls, state: AgentState) -> Literal["plan", "execute"]:
        """确认点 1：重新规划（plan_feedback 非空且重拆未超轮）回 plan，否则 execute"""
        if state.get("plan_feedback") and (state.get("plan_attempts") or 0) < 2:
            return "plan"
        return "execute"

    @classmethod
    def _confirm_done_condition(cls, state: AgentState) -> Literal["plan", "__end__"]:
        """确认点 2：重新生成（regenerate 标记）回 plan，否则结束"""
        return "plan" if state.get("regenerate") else END
```

6. `_build_agent` 图结构更新：

```python
        graph = StateGraph(AgentState)
        graph.add_node("plan", self._plan_node)
        graph.add_node("confirm_plan", self._confirm_plan_node)
        graph.add_node("direct_answer", self._direct_answer_node)
        graph.add_node("execute", self._execute_node)
        graph.add_node("summarize", self._summarize_node)
        graph.add_node("confirm_result", self._confirm_result_node)

        graph.set_entry_point("plan")
        graph.add_conditional_edges("plan", self._plan_condition)
        graph.add_edge("confirm_plan", "execute")
        graph.add_conditional_edges("confirm_plan", self._replan_condition)
        graph.add_edge("execute", "summarize")
        graph.add_edge("summarize", "confirm_result")
        graph.add_conditional_edges("confirm_result", self._confirm_done_condition)
        graph.add_edge("direct_answer", END)
        return graph.compile()
```

- [ ] **Step 4: 运行确认通过**

Run: `venv\Scripts\python -m pytest test/internal/core/agent/test_orchestrator_confirm_result.py test/internal/core/agent/test_queue_manager_choice.py -v`
Expected: PASS（含既有 wait_for_choice 测试更新后通过）

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/agents/orchestrator_agent.py internal/core/agent/agents/agent_queue_manager.py test/internal/core/agent/test_orchestrator_confirm_result.py test/internal/core/agent/test_queue_manager_choice.py
git commit -m "feat(agent): 编排器新增 confirm_result 节点与图结构——plan 融合 feedback、汇总歧义弹确认、重生成回 plan"
```

---

### Task 7: ChatRunner SSE 透传 sub_task_options + 落库适配

**Files:**
- Modify: `internal/service/chat_runner.py`（`_stream_and_persist` include 元组）
- Modify: `internal/service/assistant_agent_service.py`（同 include 元组，若走编排则一致）
- Test: `test/internal/service/test_ask_user_chat_runner.py`（追加）

**Interfaces:**
- Consumes: `AgentThought.sub_task_options`（Task 1）
- Produces: SSE data 含 `sub_task_options`；`save_agent_thoughts` 事件列表已含 ASK_USER（无需改），`sub_task_options` 落库走 `tool_input`（confirm_plan 发布时 tool_input 已含 question/options；sub_task_options 序列化进 thought/message 由现有逻辑处理）

- [ ] **Step 1: 写失败测试**（追加到 `test_ask_user_chat_runner.py`）

```python
def test_ask_user_sub_task_options_in_sse_include():
    """chat_runner 的 model_dump include 必须包含 sub_task_options（读取源确认）"""
    import inspect
    from internal.service import chat_runner as cr
    src = inspect.getsource(cr.ChatRunner._stream_and_persist)
    assert '"sub_task_options"' in src
```

- [ ] **Step 2: 运行确认失败**

Run: `venv\Scripts\python -m pytest test/internal/service/test_ask_user_chat_runner.py -v`
Expected: FAIL（src 不含 sub_task_options）

- [ ] **Step 3: 最小实现**

`internal/service/chat_runner.py` 的 `_stream_and_persist` 两处 `model_dump(include={...})` 元组加 `"sub_task_options"`：

```python
                    **agent_thought.model_dump(include={
                        "event", "thought", "observation", "tool", "tool_input", "answer", "latency",
                        "total_token_count", "total_price", "sub_task_id", "sub_task_title", "trace",
                        "question", "options", "allow_custom", "choice", "sub_task_options",
                    }),
```

`internal/service/assistant_agent_service.py` 的 `model_dump(include={...})` 元组同样加 `"sub_task_options"`。

- [ ] **Step 4: 运行确认通过**

Run: `venv\Scripts\python -m pytest test/internal/service/test_ask_user_chat_runner.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/service/chat_runner.py internal/service/assistant_agent_service.py test/internal/service/test_ask_user_chat_runner.py
git commit -m "feat(chat): SSE 透传 sub_task_options（编排器任务分配确认）"
```

---

### Task 8: 前端 AskUserOptions plan 模式 + 三端接入

**Files:**
- Modify: `ai-code-llmops-web/src/components/AskUserOptions.vue`（web 仓库）
- Modify: `ai-code-llmops-web/src/views/space/apps/components/PreviewDebugChat.vue`
- Modify: `ai-code-llmops-web/src/views/web-apps/IndexView.vue`
- Modify: `ai-code-llmops-web/src/views/pages/HomeView.vue`
- Test: `ai-code-llmops-web/src/components/__tests__/AskUserOptions.spec.ts`（追加 plan 模式用例）

**Interfaces:**
- Consumes: 后端 ask_user SSE 事件（新增 `sub_task_options: {order, title, role_prompt, expect_output}[]`）、choice 接口（新增 action/keep_orders/custom 字段）
- Produces: `<AskUserOptions :mode="'option'|'plan'" :sub-task-options :requires-reason ...>`；plan 模式 emit `{taskId, action:'confirm'|'replan', keepOrders:number[], custom:string, skip:boolean, eventId}`

- [ ] **Step 1: 写失败测试**（追加到 `AskUserOptions.spec.ts`）

```ts
describe('AskUserOptions plan 模式', () => {
  it('渲染子任务勾选列表，默认全不选', () => {
    const wrapper = mount(AskUserOptions, {
      props: {
        mode: 'plan',
        question: '请确认任务分配方案',
        subTaskOptions: [
          { order: 1, title: '检索资料' },
          { order: 2, title: '撰写报告' },
        ],
        requiresReason: true,
        taskId: 't1',
        eventId: 'e1',
        choice: '',
      },
    })
    expect(wrapper.text()).toContain('检索资料')
    expect(wrapper.text()).toContain('撰写报告')
    expect(wrapper.findAll('input[type="checkbox"]').length).toBe(2)
    expect(wrapper.findAll('input[type="checkbox"]:checked').length).toBe(0)
  })

  it('确认执行 emit keepOrders', async () => {
    const wrapper = mount(AskUserOptions, {
      props: { mode: 'plan', question: 'q', subTaskOptions: [{ order: 1, title: 'A' }, { order: 2, title: 'B' }], requiresReason: false, taskId: 't1', eventId: 'e1', choice: '' },
    })
    await wrapper.findAll('input[type="checkbox"]')[0].setValue(true)
    await wrapper.findAll('button')[0].trigger('click') // 确认执行
    const emitted = wrapper.emitted('submitted')![0][0] as any
    expect(emitted).toMatchObject({ taskId: 't1', action: 'confirm', keepOrders: [1], custom: '', skip: false, eventId: 'e1' })
  })

  it('重新规划无原因时按钮禁用', async () => {
    const wrapper = mount(AskUserOptions, {
      props: { mode: 'plan', question: 'q', subTaskOptions: [{ order: 1, title: 'A' }], requiresReason: true, taskId: 't1', eventId: 'e1', choice: '' },
    })
    const replanBtn = wrapper.findAll('button')[1]
    expect(replanBtn.attributes('disabled')).toBeDefined()
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd ai-code-llmops-web && npx vitest run src/components/__tests__/AskUserOptions.spec.ts`
Expected: FAIL（mode/subTaskOptions prop 不存在）

- [ ] **Step 3: 实现 plan 模式**

`AskUserOptions.vue`：

- Props 加：`mode?: 'option' | 'plan'`（默认 'option'）、`subTaskOptions?: { order: number; title: string; role_prompt?: string; expect_output?: string }[]`、`requiresReason?: boolean`（默认 false）
- 状态加：`checkedOrders: ref<number[]>([])`（默认空 = 全不选）
- `disabled` 计算不变；`replanDisabled = computed(() => requiresReason && !customText.trim())`
- 方法：
  - `toggleOrder(order)`：勾选/取消
  - `handlePlanSubmit(action)`：action 为 'confirm' 时 emit `{taskId, action, keepOrders: checkedOrders, custom: customText.trim(), skip: false, eventId}`；'replan' 时若 replanDisabled 不执行，emit `{taskId, action:'replan', keepOrders: [], custom: customText.trim(), skip: false, eventId}`
  - 提交后 `submitted=true`
- 模板：`mode==='plan'` 时渲染勾选列表（`v-for="opt in subTaskOptions"` + checkbox）+ 自定义输入 + 两个按钮（确认执行 / 重新规划）；否则现有 option 模式
- 回显（choice 非空）：plan 模式显示"已确认执行/已重新规划 + 保留项"，按钮禁用

- [ ] **Step 4: 三端接入**

每个页面（`PreviewDebugChat.vue` / `IndexView.vue` / `HomeView.vue`）：

1. SSE askUser 分支 payload 加 `sub_task_options: data?.sub_task_options ?? []`
2. 渲染 `<AskUserOptions>` 加：
```html
<AskUserOptions
  v-if="askUserThought(item)"
  :mode="askUserThought(item)?.sub_task_options?.length ? 'plan' : 'option'"
  :sub-task-options="askUserThought(item)?.sub_task_options ?? []"
  :requires-reason="true"
  ... 现有 props ...
/>
```
3. `onChoiceSubmitted` 扩展：payload 类型加 `action?/keepOrders?/custom?`；POST body 按模式组装（plan：`{action, keep_orders, custom, skip, event_id}`；option：`{choice, custom, skip, event_id}`）

- [ ] **Step 5: 运行确认通过**

Run: `cd ai-code-llmops-web && npx vitest run src/components/__tests__/AskUserOptions.spec.ts`
Expected: PASS

- [ ] **Step 6: 提交**（web 仓库）

```bash
git add src/components/AskUserOptions.vue src/components/__tests__/AskUserOptions.spec.ts src/views/space/apps/components/PreviewDebugChat.vue src/views/web-apps/IndexView.vue src/views/pages/HomeView.vue
git commit -m "feat(web): AskUserOptions 支持 plan 模式（子任务勾选+原因），三端接入编排器任务分配确认"
```

---

### Task 9: 联调验证与文档收尾

**Files:**
- Modify: `Obsidian/Obsidian/编排器任务分配与汇总确认设计.md`（status → done）
- Modify: `Obsidian/Obsidian/工作日志/2026-08-28.md`（追加记录）
- Test: 全量 agent/service 测试 + 前端 vitest + ruff

**Interfaces:**
- 无新接口；验证 Task 1-8 端到端

- [ ] **Step 1: 全量后端测试**

Run: `venv\Scripts\python -m pytest test/internal/core/agent test/internal/service -q`
Expected: 全部 PASS（含新增 confirm_plan/confirm_result 用例，既有用例不回归）

- [ ] **Step 2: ruff 检查**

Run: `ruff check internal test`（venv 无 ruff 用全局 ruff.exe）
Expected: 本次新增代码零告警（既有告警只报告不改）

- [ ] **Step 3: 前端测试 + 类型检查**

Run: `cd ai-code-llmops-web && npx vitest run && npx vue-tsc --build`
Expected: 全部 PASS + exit 0

- [ ] **Step 4: 联调验证（手动/可选 Playwright）**

1. 编排应用提问 → 确认点 1 弹框 → 勾选部分子任务 → 确认 → 子任务执行 → 汇总 → 无歧义直接完成
2. 构造歧义场景 → 确认点 2 弹框 → 确认完成 / 重新生成
3. 超时场景（临时调小 ASK_USER_WAIT_TIMEOUT 验证）→ 全量子任务执行

- [ ] **Step 5: 提交（含文档）**

```bash
git add Obsidian
git commit -m "docs: 编排器任务分配与汇总确认实现完成，更新设计状态与工作日志"
```
