# Agent 记忆系统分层改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前"滑动窗口 + 整段连续摘要"的单一记忆模型，升级为主流分层记忆架构：短期记忆（滑动窗口 + 滚动摘要互斥 + 惰性压缩）、语义记忆（用户画像卡片，双时间机制 + LLM 写侧管道 + 冲突检测）、情景记忆（经历向量召回 + RRF 融合排序）、程序记忆（规则/人设工具化 + 反馈反思改写），并修复代码重复、摘要模型硬编码、空标签、多模态 token 估算等 6 条既有设计问题。

**Architecture:** 四个内存层次按职责分离——短期记忆由 `TokenBufferMemory` 演进（窗口内原文 + 窗口外滚动摘要互斥，上下文快满时惰性压缩并打归档标记）；语义记忆新建 `UserMemoryFact` 模型（`valid_from/valid_to` 有效区间 + `tx_created_at/tx_invalidated_at` 事务时间双时间机制，旧事实作废不删除、支持时间点回溯），由 `UserMemoryService` 负责 LLM 特征抽取（写侧管道）、冲突检测与双时间写入，并在对话前注入 Agent 系统提示词的 `<用户画像>` 块；情景记忆新建 `EpisodicMemory` 模型 + Weaviate 集合（按 `user_id` 隔离命名空间），对话后异步写入经历、对话前向量+BM25 双路召回 → RRF 融合 + 新近度/重要性加权排序后注入 `<情景记忆>` 块；程序记忆新建 `ProceduralMemory` 模型，并通过 `search_memory/write_memory/update_memory/forget_memory` 工具化暴露给 Agent 主动读写，反馈（like/dislike）触发反思改写；`ChatRunner` 抽取两处重复的 Agent 对话执行逻辑并统一组装各层记忆。

**Tech Stack:** Python 3.12 / Flask / SQLAlchemy 2.0 / flask-migrate / langchain-core / langgraph / injector / pytest（真实 Postgres + 事务回滚测试）

**Spec:** 本计划依据 2026-08-24 会话中确认的设计（"Agent记忆怎样分层"讨论 + 双时间机制补充）。前置分析见同会话：`internal/memory/token_buffer_memory.py`、`internal/service/app_service.py:533`、`internal/service/web_app_service.py:87`、`internal/core/agent/entities/agent_entity.py`、`internal/core/agent/agents/function_call_agent.py`。

## Global Constraints

- Python 3.12；依赖仅允许使用 `requirements.txt` 中已有的包，不新增依赖
- 数据库迁移必须使用 flask-migrate（`internal/migrations/` 已配置），新模型需生成迁移文件
- 测试遵循仓库现有模式：`test/conftest.py` 的 `db` fixture（真实 DB + 事务回滚）、`injector.get(Service)` 取真实服务、`monkeypatch` 替换 LLM/依赖；不引入 mock 数据库
- 所有既有 HTTP 接口的响应结构向后兼容：只允许新增字段，不允许改名或删字段
- `AgentConfig` / `AgentState` / 既有 SSE 事件格式保持兼容，`invoke_from` 语义不变
- 会话隔离沿用现有 `created_by` 账号维度；新的用户卡片记忆按 `(app_id, user_id)` 命名空间隔离
- Windows 环境下迁移命令使用 `set FLASK_APP=app.http.app && flask db ...`（PowerShell 用 `$env:FLASK_APP="app.http.app"; flask db ...`）
- 每个 Task 结束时运行 `pytest test/ -x`（或该任务指定用例）确认无回归后提交

---

## 范围说明（Scope）

本计划覆盖：短期记忆升级（Phase 2）、语义记忆用户卡片（Phase 3）、情景记忆向量召回（Phase 5）、程序记忆工具化（Phase 6）、基础设施重构（Phase 1）、治理与审计（Phase 4）、前端归档展示（Phase 2 内）、全量验证（Phase 7）。情景记忆检索复用项目既有 Weaviate + `EmbeddingsService` + `rrf_fusion`（`internal/core/retrievers/rrf.py`），按 `user_id` 命名空间隔离；程序记忆以 `search_memory/write_memory/update_memory/forget_memory` 工具化暴露给 Agent，并支持反馈反思改写。记忆评测（召回命中率/注入增益基线）不在本计划内，作为后续计划。

---

## Phase 1：基础设施重构

### Task 1: 抽取 ChatRunner 统一对话执行器

**Files:**
- Create: `internal/service/chat_runner.py`
- Modify: `internal/service/app_service.py:533-697`（`debug_chat` 改为调用 ChatRunner）
- Modify: `internal/service/web_app_service.py:87-254`（`web_app_chat` 改为调用 ChatRunner）
- Test: `test/internal/service/test_chat_runner.py`

**Interfaces:**
- Consumes: `BaseService`、`TokenBufferMemory`、`FunctionCallAgent`/`ReACTAgent`、`AgentConfig`、`AgentThought`/`QueueEvent`、`InvokeFrom`、`ModelFeature`、`RetrievalSource`
- Produces:
  - `ChatRunner(db, retrieval_service, app_config_service, conversation_service, language_model_service)`（injector dataclass）
  - `ChatRunner.run(*, app: App, app_config: dict, conversation: Conversation, message: Message, account: Account, invoke_from: InvokeFrom, user_profile: str = "") -> Generator[str, None, None]`：产出 SSE 事件字符串（`event: ...\ndata: ...\n\n`）
  - `ChatRunner._build_history(llm, conversation, dialog_round) -> list[AnyMessage]`：窗口内历史消息（未归档）
  - `ChatRunner._stream_and_persist(*, agent, llm, app, app_config, conversation, message, account, invoke_from, history, user_profile) -> Generator[str, None, None]`：内部流式推理 + 异常兜底 + 落库

- [ ] **Step 1: 写失败测试**

Create `test/internal/service/test_chat_runner.py`:

```python
#!/usr/bin/env python
"""ChatRunner 统一对话执行器测试：SSE 产出、异常兜底、落库调用"""
import json
from unittest.mock import MagicMock
from uuid import uuid4

from app.http.module import injector
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import ModelFeature
from internal.entity.conversation_entity import InvokeFrom
from internal.service import ChatRunner


class FakeLLM:
    """支持 tool_call 的假 LLM"""
    features = (ModelFeature.TOOL_CALL,)
    context_window = None
    max_tokens = 8192

    def convert_to_human_message(self, query, image_urls=None):
        from langchain_core.messages import HumanMessage
        return HumanMessage(content=query)


class FakeAgent:
    """流式产出一个 AGENT_MESSAGE 后结束的假 Agent"""
    def __init__(self, *args, **kwargs):
        pass

    def stream(self, *args, **kwargs):
        yield AgentThought(
            id=uuid4(), task_id=uuid4(),
            event=QueueEvent.AGENT_MESSAGE,
            thought="你好", message=[], answer="你好", latency=0.1,
        )


MOCK_CONFIG = {
    "model_config": {"provider": "deepseek", "model": "deepseek-v4-flash"},
    "dialog_round": 5,
    "tools": [],
    "datasets": [],
    "workflows": [],
    "skills": [],
    "preset_prompt": "",
    "long_term_memory": {"enable": False},
    "review_config": {},
}


class TestChatRunner:
    def test_run_streams_sse_and_persists(self, app, monkeypatch):
        runner = injector.get(ChatRunner)
        account = MagicMock(id=uuid4())
        app_id = uuid4()
        conversation = MagicMock(id=uuid4(), summary="")
        message = MagicMock(id=uuid4(), query="你好", image_urls=[])

        monkeypatch.setattr(runner.language_model_service, "load_language_model", lambda cfg: FakeLLM())
        monkeypatch.setattr(runner.app_config_service, "get_langchain_tools_by_tools_config", lambda cfg: [])
        monkeypatch.setattr("internal.service.chat_runner.FunctionCallAgent", FakeAgent)
        # 短期记忆窗口：conversation 为 MagicMock 时跳过真实 DB 查询
        monkeypatch.setattr(runner, "_build_history", lambda llm, conversation, dialog_round: [])

        saved = {}
        monkeypatch.setattr(
            runner.conversation_service, "save_agent_thoughts",
            lambda **kwargs: saved.update(kwargs),
        )

        with app.app_context():
            events = list(runner.run(
                app=MagicMock(id=app_id),
                app_config=dict(MOCK_CONFIG),
                conversation=conversation,
                message=message,
                account=account,
                invoke_from=InvokeFrom.DEBUGGER,
            ))

        assert any("event: agent_message" in e for e in events), "应产出 agent_message 事件"
        assert saved.get("invoke_from") == InvokeFrom.DEBUGGER
        assert saved.get("conversation_id") == conversation.id
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_chat_runner.py::TestChatRunner::test_run_streams_sse_and_persists -v`
Expected: FAIL with `ImportError: cannot import name 'ChatRunner'`

- [ ] **Step 3: 实现 ChatRunner**

Create `internal/service/chat_runner.py`:

```python
#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : chat_runner.py
"""
import json
import logging
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from flask import current_app
from injector import inject

from internal.core.agent.agents import FunctionCallAgent, ReACTAgent
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.entity.conversation_entity import InvokeFrom
from internal.entity.dataset_entity import RetrievalSource
from internal.memory.token_buffer_memory import TokenBufferMemory
from internal.model import Account, App, Conversation, Message
from package.sqlalchemy import SQLAlchemy

from .base_service import BaseService
from .app_config_service import AppConfigService
from .conversation_service import ConversationService
from .language_model_service import LanguageModelService
from .retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


@inject
@dataclass
class ChatRunner(BaseService):
    """统一 Agent 对话执行器：从 debug_chat / web_app_chat 抽取的公共推理链路"""
    db: SQLAlchemy
    retrieval_service: RetrievalService
    app_config_service: AppConfigService
    conversation_service: ConversationService
    language_model_service: LanguageModelService

    def run(
            self,
            *,
            app: App,
            app_config: dict[str, Any],
            conversation: Conversation,
            message: Message,
            account: Account,
            invoke_from: InvokeFrom,
            user_profile: str = "",
    ) -> Generator[str, None, None]:
        """根据配置构建 Agent 并流式推理，产出 SSE 事件字符串"""
        # 1、加载大语言模型
        llm = self.language_model_service.load_language_model(app_config.get("model_config", {}))

        # 2、短期记忆（滑动窗口，窗口外内容由滚动摘要承担）
        history = self._build_history(llm, conversation, app_config["dialog_round"])

        # 3、构建工具列表：插件/知识库/工作流/技能
        tools = self.app_config_service.get_langchain_tools_by_tools_config(app_config["tools"])
        if app_config["datasets"]:
            dataset_tool = self.retrieval_service.create_langchain_tool_from_search(
                flask_app=current_app._get_current_object(),
                dataset_ids=[d["id"] for d in app_config["datasets"]],
                account_id=account.id,
                retrieval_score=RetrievalSource.APP,
                **app_config["retrieval_config"],
            )
            tools.append(dataset_tool)
        if app_config["workflows"]:
            tools.extend(self.app_config_service.get_langchain_tools_by_workflow_ids(
                [w["id"] for w in app_config["workflows"]]
            ))
        if app_config["skills"]:
            tools.extend(self.app_config_service.get_langchain_tools_by_skill_ids(
                [s["id"] for s in app_config["skills"]]
            ))

        # 4、根据 LLM 是否支持 tool_call 决定 Agent 类型
        agent_class = FunctionCallAgent if ModelFeature.TOOL_CALL in llm.features else ReACTAgent
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
            ),
        )

        # 5、流式推理 + 事件序列化 + 异常兜底 + 落库
        yield from self._stream_and_persist(
            agent=agent,
            llm=llm,
            app=app,
            app_config=app_config,
            conversation=conversation,
            message=message,
            account=account,
            invoke_from=invoke_from,
            history=history,
            user_profile=user_profile,
        )

    def _build_history(self, llm: BaseLanguageModel, conversation: Conversation, dialog_round: int) -> list:
        """构建短期记忆历史消息（窗口内原文，未归档消息）"""
        token_buffer_memory = TokenBufferMemory(db=self.db, conversation=conversation, model_instance=llm)
        return token_buffer_memory.get_history_prompt_messages(message_limit=dialog_round)

    def _stream_and_persist(
            self,
            *,
            agent,
            llm: BaseLanguageModel,
            app: App,
            app_config: dict[str, Any],
            conversation: Conversation,
            message: Message,
            account: Account,
            invoke_from: InvokeFrom,
            history: list,
            user_profile: str,
    ) -> Generator[str, None, None]:
        """流式推理，将 AgentThought 序列化为 SSE；异常兜底；finally 落库"""
        agent_thoughts = {}
        error_event = None
        try:
            for agent_thought in agent.stream({
                "messages": [llm.convert_to_human_message(message.query, message.image_urls)],
                "history": history,
                "long_term_memory": conversation.summary if conversation.summary else "",
                "user_profile": user_profile,
            }):
                event_id = str(agent_thought.id)
                if agent_thought.event != QueueEvent.PING:
                    if agent_thought.event == QueueEvent.AGENT_MESSAGE:
                        if event_id not in agent_thoughts:
                            agent_thoughts[event_id] = agent_thought
                        else:
                            agent_thoughts[event_id] = agent_thoughts[event_id].model_copy(update={
                                "thought": agent_thoughts[event_id].thought + agent_thought.thought,
                                "message": agent_thought.message,
                                "message_token_count": agent_thought.message_token_count,
                                "message_unit_price": agent_thought.message_unit_price,
                                "message_price_unit": agent_thought.message_price_unit,
                                "answer_token_count": agent_thought.answer_token_count,
                                "answer_unit_price": agent_thought.answer_unit_price,
                                "answer_price_unit": agent_thought.answer_price_unit,
                                "total_token_count": agent_thought.total_token_count,
                                "total_price": agent_thought.total_price,
                                "answer": agent_thoughts[event_id].answer + agent_thought.answer,
                                "latency": agent_thought.latency,
                            })
                    else:
                        agent_thoughts[event_id] = agent_thought
                data = {
                    **agent_thought.model_dump(include={
                        "event", "thought", "observation", "tool", "tool_input", "answer", "latency",
                        "total_token_count", "total_price",
                    }),
                    "id": event_id,
                    "conversation_id": str(conversation.id),
                    "message_id": str(message.id),
                    "task_id": str(agent_thought.task_id),
                }
                yield f"event: {agent_thought.event.value}\ndata: {json.dumps(data)}\n\n"
        except Exception as e:
            logger.exception(f"Agent推理过程发生异常，app_id={app.id}, conversation_id={conversation.id}")
            error_event = AgentThought(
                id=uuid4(),
                task_id=uuid4(),
                event=QueueEvent.ERROR,
                observation=f"推理过程发生异常：{e}",
            )
            data = {
                **error_event.model_dump(include={
                    "event", "thought", "observation", "tool", "tool_input", "answer", "latency",
                    "total_token_count", "total_price",
                }),
                "id": str(error_event.id),
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "task_id": str(error_event.task_id),
            }
            yield f"event: {QueueEvent.ERROR.value}\ndata: {json.dumps(data)}\n\n"
        finally:
            all_thoughts = [t for t in agent_thoughts.values()]
            if error_event:
                all_thoughts.append(error_event)
            if all_thoughts:
                try:
                    self.conversation_service.save_agent_thoughts(
                        account_id=account.id,
                        app_id=app.id,
                        app_config=app_config,
                        conversation_id=conversation.id,
                        message_id=message.id,
                        agent_thoughts=all_thoughts,
                        invoke_from=invoke_from,
                    )
                except Exception:
                    logger.exception(f"保存会话推理过程失败，message_id={message.id}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_chat_runner.py::TestChatRunner::test_run_streams_sse_and_persists -v`
Expected: PASS

- [ ] **Step 5: 改造 app_service.debug_chat 与 web_app_service.web_app_chat**

Modify `internal/service/app_service.py`：
- 在 `AppService` dataclass 字段中注入 `chat_runner: ChatRunner`（import `from .chat_runner import ChatRunner`）
- `debug_chat` 方法体替换为：

```python
def debug_chat(self, app_id: UUID, req: DebugChatReq, account: Account, flask_app=None) -> Generator:
    """根据传递的应用id+提问query向特定的应用发起会话调试"""
    app = self.get_app(app_id, account)
    draft_app_config = self.get_draft_app_config(app_id, account)
    # 1、获取当前账号在该应用下的调试会话信息（按账号隔离，避免多用户串话）
    debug_conversation = self.get_or_create_debug_conversation(app, account)

    # 2、新建消息
    message = self.create(
        Message,
        app_id=app_id,
        conversation_id=debug_conversation.id,
        invoke_from=InvokeFrom.DEBUGGER,
        created_by=account.id,
        updated_by=account.id,
        query=req.data.get("query"),
        image_urls=req.data.get("image_urls"),
        status=MessageStatus.NORMAL,
    )

    # 3、委托统一对话执行器
    yield from self.chat_runner.run(
        app=app,
        app_config=draft_app_config,
        conversation=debug_conversation,
        message=message,
        account=account,
        invoke_from=InvokeFrom.DEBUGGER,
    )
```

Modify `internal/service/web_app_service.py`：
- 在 `WebAppService` dataclass 字段中注入 `chat_runner: ChatRunner`
- `web_app_chat` 中，保留"校验/创建会话 → 取发布配置 → 创建消息"逻辑，删除从 `llm = self.language_model_service.load_language_model(...)` 到 `finally` 的整段推理代码，替换为：

```python
        # 4、委托统一对话执行器（消息/会话已在上面创建）
        yield from self.chat_runner.run(
            app=app,
            app_config=app_config,
            conversation=conversation,
            message=message,
            account=account,
            invoke_from=InvokeFrom.WEB_APP,
        )
```

清理 `web_app_service.py` 中不再使用的 import（`AgentQueueManager`、`FunctionCallAgent`、`ReACTAgent`、`AgentConfig`、`AgentThought`、`QueueEvent`、`ModelFeature`、`TokenBufferMemory`、`json`、`uuid4` 等，按 lint 结果删）。

- [ ] **Step 6: 运行既有回归测试**

Run: `pytest test/internal/service/test_chat_error_handling.py -v`
Expected: 全部 PASS（`debug_chat`/`web_app_chat` 的异常兜底行为保持不变）

- [ ] **Step 7: 提交**

```bash
git add internal/service/chat_runner.py internal/service/app_service.py internal/service/web_app_service.py test/internal/service/test_chat_runner.py
git commit -m "refactor: 抽取 ChatRunner 统一 debug_chat/web_app_chat 推理链路"
```

---

### Task 2: 摘要/命名模型改走 LanguageModelService

**Files:**
- Modify: `internal/service/conversation_service.py:51-135`（`summary`、`generate_conversation_name`、`generate_suggested_questions`）
- Test: `test/internal/service/test_conversation_service.py`

**Interfaces:**
- Consumes: `LanguageModelService.load_default_language_model()`（返回 `BaseLanguageModel`）
- Produces: 改为实例方法的 `ConversationService.summary(human_message, ai_message, old_summary="") -> str`、`generate_conversation_name(query) -> str`、`generate_suggested_questions(histories) -> list[str]`

- [ ] **Step 1: 写失败测试**

Create `test/internal/service/test_conversation_service.py`:

```python
#!/usr/bin/env python
"""ConversationService 摘要/命名模型走 LanguageModelService 的测试"""
from unittest.mock import MagicMock
from uuid import uuid4

from app.http.module import injector
from internal.service import ConversationService


class FakeSummaryLLM:
    """记录输入并返回固定文本的假 LLM（可被 RunnableSequence 包装）"""
    temperature = 1.0

    def __init__(self, reply="摘要结果"):
        self.reply = reply
        self.invoked_inputs = []

    def __call__(self, inputs):
        """Runnable 协议：被 coerce_to_runnable 包装为 RunnableLambda 后由链调用"""
        self.invoked_inputs.append(inputs)
        return self.reply


class TestConversationServiceSummary:
    def test_summary_uses_language_model_service(self, app, monkeypatch):
        service = injector.get(ConversationService)
        fake_llm = FakeSummaryLLM("新摘要")

        monkeypatch.setattr(
            service.language_model_service, "load_default_language_model",
            lambda: fake_llm,
        )

        with app.app_context():
            result = service.summary("你好", "你好，有什么可以帮你？", "旧摘要")

        assert result == "新摘要"
        assert fake_llm.temperature == 0.5, "摘要模型温度应被设置为 0.5"
        assert fake_llm.invoked_inputs[0]["summary"] == "旧摘要"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_conversation_service.py::TestConversationServiceSummary -v`
Expected: FAIL（`summary` 是 classmethod，`service.language_model_service` 不存在）

- [ ] **Step 3: 实现**

Modify `internal/service/conversation_service.py`：
- dataclass 字段增加 `language_model_service: LanguageModelService`（import 同包 `from .language_model_service import LanguageModelService`）
- `summary` 由 `@classmethod` 改为实例方法：

```python
    def summary(self, human_message: str, ai_message: str, old_summary: str = "") -> str:
        """根据传递的人类信息、AI消息还有原始的摘要信息总结生成一段新的摘要"""
        # 1、创建prompt
        prompt = ChatPromptTemplate.from_template(SUMMARIZER_TEMPLATE)

        # 2、构建大语言模型实例（走模型管理器，避免硬编码模型与API Key），将温度调低降低幻觉
        llm = self.language_model_service.load_default_language_model()
        llm.temperature = 0.5

        # 3、构建链应用
        summary_chain = prompt | llm | StrOutputParser()

        # 4、调用链并获取新摘要信息
        new_summary = summary_chain.invoke({
            "summary": old_summary,
            "new_lines": f"Human:{human_message}\nAI：{ai_message}",
        })
        return new_summary
```

- `generate_conversation_name` 改为实例方法，`llm = ChatDeepSeek(model="deepseek-v4-flash", temperature=0)` 替换为 `llm = self.language_model_service.load_default_language_model(); llm.temperature = 0`（保留 `with_structured_output` 用法）
- `generate_suggested_questions` 改为实例方法，同样替换 LLM 来源
- 删除 `from langchain_deepseek import ChatDeepSeek` 与 `from langchain_openai import ChatOpenAI`（若不再使用）
- 更新 `_generate_summary_and_update` / `_generate_conversation_name_and_update` 中的调用方式（`self.summary(...)` / `self.generate_conversation_name(...)`，现已是实例方法无需改动调用处）

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_conversation_service.py -v`
Expected: PASS

- [ ] **Step 5: 回归 + 提交**

Run: `pytest test/internal/service/test_chat_error_handling.py test/internal/service/test_conversation_service.py -v`
Expected: 全部 PASS

```bash
git add internal/service/conversation_service.py test/internal/service/test_conversation_service.py
git commit -m "fix: 摘要/命名模型改走 LanguageModelService，移除硬编码模型"
```

---

### Task 3: System Prompt 条件渲染（去除空标签）

**Files:**
- Modify: `internal/core/agent/entities/agent_entity.py:18-112`（两个模板 + 新增构建函数）
- Modify: `internal/core/agent/agents/function_call_agent.py:106-112`（`_long_term_memory_recall_node`）
- Modify: `internal/core/agent/agents/react_agent.py:42-84`（`_long_term_memory_recall_node`）
- Test: `test/internal/core/agent/test_system_prompt.py`

**Interfaces:**
- Produces: `build_system_prompt(template: str, *, preset_prompt: str, long_term_memory: str = "", user_profile: str = "", tool_description: str = "") -> str`：模板中 `<长期记忆>`、`<用户画像>` 块为空时整块省略
- Consumes: 由两个 Agent 的 `_long_term_memory_recall_node` 调用

- [ ] **Step 1: 写失败测试**

Create `test/internal/core/agent/test_system_prompt.py`:

```python
#!/usr/bin/env python
"""System Prompt 条件渲染测试：无长期记忆/用户画像时不产生空标签"""
from internal.core.agent.entities.agent_entity import (
    AGENT_SYSTEM_PROMPT_TEMPLATE,
    REACT_AGENT_SYSTEM_PROMPT_TEMPLATE,
    build_system_prompt,
)


class TestBuildSystemPrompt:
    def test_empty_memory_omits_blocks(self):
        prompt = build_system_prompt(
            AGENT_SYSTEM_PROMPT_TEMPLATE,
            preset_prompt="你是客服助手",
        )
        assert "长期记忆" not in prompt
        assert "用户画像" not in prompt

    def test_filled_blocks_rendered(self):
        prompt = build_system_prompt(
            AGENT_SYSTEM_PROMPT_TEMPLATE,
            preset_prompt="你是客服助手",
            long_term_memory="用户喜欢简洁回复",
            user_profile="用户常驻北京",
        )
        assert "用户喜欢简洁回复" in prompt
        assert "用户常驻北京" in prompt

    def test_react_template_tool_description_rendered(self):
        prompt = build_system_prompt(
            REACT_AGENT_SYSTEM_PROMPT_TEMPLATE,
            preset_prompt="",
            tool_description="gaode_weather - 查询天气",
        )
        assert "gaode_weather" in prompt
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/core/agent/test_system_prompt.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_system_prompt'`

- [ ] **Step 3: 实现**

Modify `internal/core/agent/entities/agent_entity.py`：
- 两个模板中的 `<长期记忆>\n{long_term_memory}\n</长期记忆>` 替换为 `{long_term_memory_block}`；在模板末尾（或 `<预设提示>` 之后）追加 `{user_profile_block}` 占位
- 新增构建函数：

```python
def build_system_prompt(
        template: str,
        *,
        preset_prompt: str,
        long_term_memory: str = "",
        user_profile: str = "",
        tool_description: str = "",
) -> str:
    """构建系统提示词：<长期记忆>/<用户画像> 为空时整块省略，避免空标签浪费 token"""
    long_term_memory_block = (
        f"\n<长期记忆>\n{long_term_memory}\n</长期记忆>\n"
        if long_term_memory else ""
    )
    user_profile_block = (
        f"\n<用户画像>\n{user_profile}\n</用户画像>\n"
        if user_profile else ""
    )
    return template.format(
        preset_prompt=preset_prompt,
        long_term_memory_block=long_term_memory_block,
        user_profile_block=user_profile_block,
        tool_description=tool_description,
    )
```

Modify `internal/core/agent/agents/function_call_agent.py` `_long_term_memory_recall_node` 中的构建处（原 `SystemMessage(AGENT_SYSTEM_PROMPT_TEMPLATE.format(...))`）替换为：

```python
        preset_messages = [
            SystemMessage(build_system_prompt(
                AGENT_SYSTEM_PROMPT_TEMPLATE,
                preset_prompt=self.agent_config.preset_prompt,
                long_term_memory=long_term_memory,
                user_profile=state.get("user_profile", ""),
            ))
        ]
```

（import 增加 `build_system_prompt`）

Modify `internal/core/agent/agents/react_agent.py` `_long_term_memory_recall_node` 中的构建处（原 `REACT_AGENT_SYSTEM_PROMPT_TEMPLATE.format(...)`）替换为：

```python
            SystemMessage(build_system_prompt(
                REACT_AGENT_SYSTEM_PROMPT_TEMPLATE,
                preset_prompt=self.agent_config.preset_prompt,
                long_term_memory=long_term_memory,
                user_profile=state.get("user_profile", ""),
                tool_description=tools_render,
            ))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/core/agent/test_system_prompt.py -v`
Expected: PASS

- [ ] **Step 5: 回归 + 提交**

Run: `pytest test/internal/service/test_chat_runner.py test/internal/service/test_chat_error_handling.py -v`
Expected: 全部 PASS

```bash
git add internal/core/agent/entities/agent_entity.py internal/core/agent/agents/function_call_agent.py internal/core/agent/agents/react_agent.py test/internal/core/agent/test_system_prompt.py
git commit -m "fix: System Prompt 条件渲染，长期记忆/用户画像为空时省略整块"
```

---

### Task 4: 多模态 token 估算（图片固定 token）

**Files:**
- Modify: `internal/core/language_model/entities/model_entity.py:100-124`（`get_num_tokens_safe`）
- Modify: `internal/core/language_model/providers/deepseek/chat.py:33-52`（`get_num_tokens_safe`，子类覆盖，同步修）
- Test: `test/internal/core/language_model/test_token_estimate.py`

**Interfaces:**
- Consumes: 无（纯内部工具）
- Produces: `BaseLanguageModel.IMAGE_TOKEN_ESTIMATE = 1100`（类常量）；`get_num_tokens_safe(messages)` 对 `content` 中的 `image_url` 块按每张 1100 token 计入

- [ ] **Step 1: 写失败测试**

Create `test/internal/core/language_model/test_token_estimate.py`:

```python
#!/usr/bin/env python
"""多模态 token 估算：图片按固定 token 计入"""
from langchain_core.messages import HumanMessage

from internal.core.language_model.entities.model_entity import BaseLanguageModel


class SimpleLLM(BaseLanguageModel):
    """无 tiktoken 的最小 LLM，get_num_tokens 抛错走 utf-8 兜底"""

    def get_num_tokens(self, text: str) -> int:
        raise NotImplementedError("no vocab")

    # langchain BaseLanguageModel 抽象方法：测试不实际调用，仅满足实例化
    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


class TestMultimodalTokenEstimate:
    def test_image_blocks_count_fixed_tokens(self):
        llm = SimpleLLM(context_window=32768)
        msg = HumanMessage(content=[
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
            {"type": "image_url", "image_url": {"url": "https://example.com/b.png"}},
            {"type": "text", "text": "这是什么？"},
        ])
        # utf-8 文本估算 + 2 * IMAGE_TOKEN_ESTIMATE
        text_tokens = len("这是什么？".encode("utf-8"))
        assert llm.get_num_tokens_safe([msg]) == text_tokens + 2 * llm.IMAGE_TOKEN_ESTIMATE

    def test_plain_text_message_unchanged(self):
        llm = SimpleLLM(context_window=32768)
        msg = HumanMessage(content="你好")
        assert llm.get_num_tokens_safe([msg]) == len("你好".encode("utf-8"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/core/language_model/test_token_estimate.py -v`
Expected: FAIL（当前实现只统计文本，图片不计入）

- [ ] **Step 3: 实现**

Modify `internal/core/language_model/entities/model_entity.py`：

```python
    # 图片 token 估算常量：OpenAI 近似单张图 token 开销
    IMAGE_TOKEN_ESTIMATE = 1100

    @staticmethod
    def _count_image_blocks(messages: list[Any]) -> int:
        """统计消息列表中 image_url 内容块数量"""
        count = 0
        for m in messages:
            content = getattr(m, "content", None)
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "image_url":
                        count += 1
        return count
```

`get_num_tokens_safe` 改造：在文本估算结果上累加图片 token：

```python
    def get_num_tokens_safe(self, messages: list[Any]) -> int | None:
        """安全统计token数，兼容无tiktoken词表的本地模型/提供商。

        优先使用底层模型自带的token计数，失败时回退为UTF-8字节长度估算；
        多模态消息中的图片按固定 token 估算（IMAGE_TOKEN_ESTIMATE）。
        """
        try:
            # 1、提取文本内容（兼容字符串列表 / 消息字典列表 / LangChain消息对象列表）
            if all(isinstance(m, str) for m in messages):
                text = "\n".join(messages)
            else:
                text = "\n".join(
                    getattr(m, "content", m.get("content", "")) if isinstance(m, dict) else getattr(m, "content", "")
                    for m in messages
                )

            # 2、优先使用模型自带的token计数
            try:
                token_count = self.get_num_tokens(text)
            except (NotImplementedError, KeyError, ValueError, TypeError, AttributeError):
                token_count = len(text.encode("utf-8"))

            # 3、叠加图片固定 token
            return token_count + self._count_image_blocks(messages) * self.IMAGE_TOKEN_ESTIMATE
        except (TypeError, ValueError):
            return 0
```

Modify `internal/core/language_model/providers/deepseek/chat.py` `get_num_tokens_safe`，在返回前同样叠加图片 token（调用 `self._count_image_blocks(messages)`）。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/core/language_model/test_token_estimate.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/core/language_model/entities/model_entity.py internal/core/language_model/providers/deepseek/chat.py test/internal/core/language_model/test_token_estimate.py
git commit -m "fix: 多模态消息图片按固定 token 估算，上下文预算更准确"
```

---

## Phase 2：短期记忆升级（滑动窗口 + 滚动摘要互斥 + 惰性压缩）

### Task 5: Message 归档标记 + 窗口互斥

**Files:**
- Modify: `internal/model/conversation.py:64-116`（`Message` 增加 `is_archived` 列）
- Modify: `internal/memory/token_buffer_memory.py:56-67`（查询过滤 `is_archived=False`）
- Test: `test/internal/memory/test_token_buffer_memory.py`
- Migration: `internal/migrations/versions/xxxx_add_message_is_archived.py`（flask db migrate 生成）

**Interfaces:**
- Consumes: `Message` 模型
- Produces: `Message.is_archived: Mapped[bool]`（默认 False）；`TokenBufferMemory.get_history_prompt_messages` 只返回未归档消息（窗口内原文）

- [ ] **Step 1: 生成迁移并写失败测试**

Run（Windows PowerShell，工作目录为项目根）:
```powershell
$env:FLASK_APP="app.http.app"; flask db migrate -m "add message is_archived"
$env:FLASK_APP="app.http.app"; flask db upgrade
```
Expected: 迁移文件生成且 `message` 表新增 `is_archived` 列（boolean, default false）

Create `test/internal/memory/test_token_buffer_memory.py`:

```python
#!/usr/bin/env python
"""TokenBufferMemory 窗口互斥测试：归档消息不进入短期记忆窗口"""
from unittest.mock import MagicMock
from uuid import uuid4

from app.http.module import injector
from internal.core.language_model.entities.model_entity import BaseLanguageModel
from internal.entity.conversation_entity import MessageStatus
from internal.memory.token_buffer_memory import TokenBufferMemory
from internal.model import Conversation, Message


class WindowLLM(BaseLanguageModel):
    def get_num_tokens(self, text: str) -> int:
        return len(text.encode("utf-8"))

    # langchain BaseLanguageModel 抽象方法：测试不实际调用
    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


class TestTokenBufferMemoryWindow:
    def test_archived_messages_excluded(self, app, db):
        llm = WindowLLM(context_window=32768)
        user_id = uuid4()
        app_id = uuid4()

        conv = Conversation(
            app_id=app_id, created_by=user_id, updated_by=user_id,
            name="测试会话", invoke_from="debugger",
        )
        db.session.add(conv)
        db.session.flush()

        # 3 轮消息：第 1 轮归档，第 2、3 轮未归档
        for i, archived in enumerate([True, False, False]):
            msg = Message(
                app_id=app_id, conversation_id=conv.id,
                created_by=user_id, updated_by=user_id,
                invoke_from="debugger",
                query=f"问题{i}", answer=f"答案{i}",
                status=MessageStatus.NORMAL, is_archived=archived,
            )
            db.session.add(msg)
            db.session.flush()

        memory = TokenBufferMemory(db=db, conversation=conv, model_instance=llm)
        history = memory.get_history_prompt_messages(message_limit=10)

        texts = [m.content for m in history]
        assert "问题0" not in texts, "归档消息不应进入窗口"
        assert "问题1" in texts and "问题2" in texts
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/memory/test_token_buffer_memory.py -v`
Expected: FAIL（`Message` 无 `is_archived` 字段或窗口未过滤归档）

- [ ] **Step 3: 实现**

Modify `internal/model/conversation.py` `Message` 增加字段（放在 `status` 附近）：

```python
    # 是否已归档（压缩出短期记忆窗口，仅保留在滚动摘要与历史查询中）
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
```

Modify `internal/memory/token_buffer_memory.py` 查询条件（`get_history_prompt_messages`）：

```python
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == self.conversation.id,
                Message.answer != "",
                Message.is_deleted.is_(False),
                Message.is_archived.is_(False),  # 窗口内只含未归档消息
                Message.status.in_([MessageStatus.NORMAL, MessageStatus.STOP]),
            )
            .order_by(Message.created_at.desc())
            .limit(message_limit)
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/memory/test_token_buffer_memory.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/model/conversation.py internal/memory/token_buffer_memory.py internal/migrations/versions/ test/internal/memory/test_token_buffer_memory.py
git commit -m "feat: Message 归档标记，短期记忆窗口只含未归档原文"
```

---

### Task 6: 惰性压缩（窗口快满 → 最旧轮次归档并入滚动摘要）

**Files:**
- Modify: `internal/service/conversation_service.py`（新增压缩方法）
- Modify: `internal/service/chat_runner.py:run`（取历史前触发压缩）
- Test: `test/internal/service/test_conversation_compact.py`

**Interfaces:**
- Consumes: `Conversation`、`Message`、`TokenBufferMemory._derive_max_token_limit` 同款预算公式；`ConversationService.summary`（Task 2 已改为实例方法）
- Produces: `ConversationService.compact_if_needed(conversation_id: UUID, llm, *, budget_ratio: float = 0.6) -> bool`：当窗口 token 超过 `预算 * budget_ratio` 时，把最旧的若干轮标记 `is_archived=True` 并滚动更新 `conversation.summary`，返回是否发生压缩

- [ ] **Step 1: 写失败测试**

Create `test/internal/service/test_conversation_compact.py`:

```python
#!/usr/bin/env python
"""惰性压缩测试：窗口 token 超预算阈值时归档最旧消息并更新滚动摘要"""
from unittest.mock import MagicMock
from uuid import uuid4

from app.http.module import injector
from internal.core.language_model.entities.model_entity import BaseLanguageModel
from internal.entity.conversation_entity import MessageStatus
from internal.model import Conversation, Message
from internal.service import ConversationService


class BudgetLLM(BaseLanguageModel):
    """token 计数可编程的假 LLM：每条消息计 per_message token"""
    def __init__(self, *args, per_message=100, **kwargs):
        super().__init__(*args, **kwargs)
        self.per_message = per_message

    def get_num_tokens_safe(self, messages):
        return len(messages) * self.per_message

    # langchain BaseLanguageModel 抽象方法：测试不实际调用
    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


class TestCompactIfNeeded:
    def _setup_conversation(self, db, rounds=5):
        user_id = uuid4()
        app_id = uuid4()
        conv = Conversation(
            app_id=app_id, created_by=user_id, updated_by=user_id,
            name="测试会话", invoke_from="debugger", summary="",
        )
        db.session.add(conv)
        db.session.flush()
        for i in range(rounds):
            db.session.add(Message(
                app_id=app_id, conversation_id=conv.id,
                created_by=user_id, updated_by=user_id,
                invoke_from="debugger",
                query=f"问题{i}", answer=f"答案{i}",
                status=MessageStatus.NORMAL, is_archived=False,
            ))
            db.session.flush()
        return conv

    def test_compacts_when_over_budget(self, app, db, monkeypatch):
        service = injector.get(ConversationService)
        conv = self._setup_conversation(db, rounds=5)

        # 窗口 5 轮 = 10 条消息 = 1000 token；预算推导 monkeypatch 为 600，阈值 600*0.6=360 → 触发压缩
        monkeypatch.setattr(
            "internal.memory.token_buffer_memory.TokenBufferMemory._derive_max_token_limit",
            lambda self: 600,
        )

        llm = BudgetLLM(context_window=32768, per_message=100)
        fake_summary = MagicMock(return_value="压缩后的摘要")
        monkeypatch.setattr(service, "_summarize", fake_summary)

        with app.app_context():
            compressed = service.compact_if_needed(conv.id, llm)

        assert compressed is True, "窗口 1000 token > 预算600*0.6=360，应触发压缩"
        assert fake_summary.called, "应调用摘要生成"
        archived = db.session.query(Message).filter(
            Message.conversation_id == conv.id, Message.is_archived.is_(True)
        ).count()
        assert archived >= 1, "应有消息被归档"
        db.session.refresh(conv)
        assert conv.summary == "压缩后的摘要"

    def test_no_compact_within_budget(self, app, db, monkeypatch):
        service = injector.get(ConversationService)
        conv = self._setup_conversation(db, rounds=1)

        monkeypatch.setattr(
            "internal.memory.token_buffer_memory.TokenBufferMemory._derive_max_token_limit",
            lambda self: 600,
        )
        llm = BudgetLLM(context_window=32768, per_message=100)
        fake_summary = MagicMock(return_value="x")
        monkeypatch.setattr(service, "_summarize", fake_summary)

        with app.app_context():
            compressed = service.compact_if_needed(conv.id, llm)

        assert compressed is False, "1 轮 2 条消息 200 token < 360，不应压缩"
        assert not fake_summary.called
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_conversation_compact.py -v`
Expected: FAIL with `AttributeError: ConversationService has no attribute 'compact_if_needed'`

- [ ] **Step 3: 实现**

Modify `internal/service/conversation_service.py` 新增方法：

```python
    def compact_if_needed(
            self,
            conversation_id: UUID,
            llm,
            *,
            budget_ratio: float = 0.6,
    ) -> bool:
        """窗口 token 超过预算阈值时，把最旧轮次归档并入滚动摘要（惰性压缩）。

        预算 = 模型上下文窗口推导出的历史预算（复用 TokenBufferMemory._derive_max_token_limit）。
        返回是否发生了压缩。
        """
        # 1、读取窗口内（未归档）消息，按时间升序（最旧在前）
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.answer != "",
                Message.is_deleted.is_(False),
                Message.is_archived.is_(False),
                Message.status.in_([MessageStatus.NORMAL, MessageStatus.STOP]),
            )
            .order_by(Message.created_at.asc())
        )
        window_messages = self.db.session.execute(stmt).scalars().all()
        if not window_messages:
            return False

        # 2、估算窗口 token（每轮 = Human + AI 两条消息）
        prompt_messages = []
        for message in window_messages:
            prompt_messages.extend([
                llm.convert_to_human_message(message.query, message.image_urls),
                AIMessage(content=message.answer),
            ])
        window_tokens = llm.get_num_tokens_safe(prompt_messages) or 0

        # 3、推导预算（复用 TokenBufferMemory 的预算公式，保证可测试）
        memory = TokenBufferMemory(
            db=self.db,
            conversation=self.get(Conversation, conversation_id),
            model_instance=llm,
        )
        budget = memory._derive_max_token_limit()
        if window_tokens <= budget * budget_ratio:
            return False

        # 4、从最旧开始逐轮归档，直到窗口 token 降到阈值内
        conversation = self.get(Conversation, conversation_id)
        archived_lines = []
        remaining_tokens = window_tokens
        for message in window_messages:
            if remaining_tokens <= budget * budget_ratio:
                break
            msg_tokens = (
                llm.get_num_tokens_safe([
                    llm.convert_to_human_message(message.query, message.image_urls),
                    AIMessage(content=message.answer),
                ]) or 0
            )
            self.update(message, is_archived=True)
            archived_lines.append(f"Human:{message.query}\nAI：{message.answer}")
            remaining_tokens -= msg_tokens

        # 5、将归档轮次滚动进摘要
        if archived_lines:
            new_lines = "\n".join(archived_lines)
            new_summary = self._summarize(conversation.summary, new_lines)
            self.update(conversation, summary=new_summary)
        return True

    def _summarize(self, old_summary: str, new_lines: str) -> str:
        """调用摘要模型生成滚动摘要（old_summary + 新归档内容 -> 新摘要）"""
        from internal.entity.conversation_entity import SUMMARIZER_TEMPLATE
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_template(SUMMARIZER_TEMPLATE)
        llm = self.language_model_service.load_default_language_model()
        llm.temperature = 0.5
        chain = prompt | llm | StrOutputParser()
        return chain.invoke({"summary": old_summary, "new_lines": new_lines})
```

（`AIMessage` 需 `from langchain_core.messages import AIMessage`；`TokenBufferMemory` 需 `from internal.memory.token_buffer_memory import TokenBufferMemory`）

Modify `internal/service/chat_runner.py:run`，在 `_build_history` 之前触发压缩：

```python
        # 2、短期记忆：窗口快满时先惰性压缩（归档最旧轮次并入滚动摘要）
        self.conversation_service.compact_if_needed(conversation.id, llm)
        history = self._build_history(llm, conversation, app_config["dialog_round"])
```

注意：`run` 的生成器在首次迭代前不会执行 `compact_if_needed`，因此真实调用 `debug_chat`/`web_app_chat` 时行为正确；单元测试中若 conversation 是 MagicMock，需 monkeypatch `runner.conversation_service.compact_if_needed` 为 no-op（见 Task 1 测试）。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_conversation_compact.py -v`
Expected: PASS

- [ ] **Step 5: 同步更新 Task 1 测试 + 回归**

Task 6 让 `ChatRunner.run` 首行调用 `compact_if_needed`，Task 1 测试中的 `conversation` 是 MagicMock（`conversation.id` 无法查库），因此更新 `test/internal/service/test_chat_runner.py`，在每个测试开头 monkeypatch 压缩为 no-op：

```python
        monkeypatch.setattr(
            runner.conversation_service, "compact_if_needed",
            lambda *a, **k: False,
        )
```

Run: `pytest test/internal/service/test_chat_runner.py test/internal/service/test_conversation_compact.py -v`
Expected: 全部 PASS

```bash
git add internal/service/conversation_service.py internal/service/chat_runner.py test/internal/service/test_conversation_compact.py
git commit -m "feat: 短期记忆惰性压缩，窗口超预算时归档最旧轮次并入滚动摘要"
```

---

### Task 7: 消息接口返回归档标记 + 前端归档展示（历史查询入口）

**Files:**
- Modify: `internal/schema/app_schema.py:186-222`（`GetDebugConversationMessagesWithPageResp` 增加 `is_archived`）
- Modify: `internal/schema/conversation_schema.py`（`GetConversationMessagesWithPageResp` 增加 `is_archived`）
- Modify: `ai-code-llmops-web/src/models/conversation.ts`（类型加字段）
- Modify: `ai-code-llmops-web/src/views/space/apps/components/AiMessage.vue`（归档占位）
- Modify: `ai-code-llmops-web/src/views/web-apps/IndexView.vue`（归档占位）
- Test: `test/internal/handler/test_app_handler.py`（扩展）

**Interfaces:**
- Consumes: `Message.is_archived`（Task 5）
- Produces: 消息列表响应新增 `is_archived: bool` 字段；前端对 `is_archived=true` 的消息渲染"已归档"占位卡片，点击"查看历史"展示原文（数据来自同一分页接口）

- [ ] **Step 1: 写失败测试**

Create `test/internal/schema/test_message_resp_schema.py`（schema 级单元测试，避免依赖真实 app 记录）：

```python
#!/usr/bin/env python
"""消息列表响应 schema 归档标记测试"""
from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

from internal.schema.app_schema import GetDebugConversationMessagesWithPageResp
from internal.schema.conversation_schema import GetConversationMessagesWithPageResp


def _mock_message(is_archived: bool):
    msg = MagicMock(
        id=uuid4(), conversation_id=uuid4(), query="q", image_urls=[],
        answer="a", total_token_count=0, latency=0.0, feedback="",
        agent_thoughts=[], created_at=datetime.now(),
        is_archived=is_archived,
    )
    return msg


class TestMessageRespSchema:
    def test_debug_resp_includes_is_archived(self):
        resp = GetDebugConversationMessagesWithPageResp()
        data = resp.dump(_mock_message(is_archived=True))
        assert data["is_archived"] is True
        data = resp.dump(_mock_message(is_archived=False))
        assert data["is_archived"] is False

    def test_conversation_resp_includes_is_archived(self):
        resp = GetConversationMessagesWithPageResp()
        data = resp.dump(_mock_message(is_archived=True))
        assert data["is_archived"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/schema/test_message_resp_schema.py -v`
Expected: FAIL（`process_data` 未输出 `is_archived` 键，断言 `data["is_archived"]` 抛 KeyError）

- [ ] **Step 3: 实现**

Modify `internal/schema/app_schema.py` `GetDebugConversationMessagesWithPageResp` 增加字段：

```python
    is_archived = fields.Boolean(dump_default=False)
```

并在 `@pre_dump.process_data` 返回 dict 中补充键（放在 `created_at` 之前）：

```python
            "is_archived": data.is_archived,
```

Modify `internal/schema/conversation_schema.py` `GetConversationMessagesWithPageResp` 同样处理（加字段 + pre_dump 键）。

Modify `ai-code-llmops-web/src/models/conversation.ts`：`GetConversationMessagesWithPageResponse` 类型中 `created_at: number` 之前增加 `is_archived: boolean`（行 30 前）。Modify `ai-code-llmops-web/src/models/app.ts`：`GetDebugConversationMessagesWithPageResponse` 类型同样在 `created_at: number`（行 174）前增加 `is_archived: boolean`。

Modify `ai-code-llmops-web/src/views/space/apps/components/AiMessage.vue`：
- props 增加（紧跟现有 `feedback` prop 之后）：

```typescript
  is_archived: { type: Boolean, default: false },
  query: { type: String, default: '' },
```

- script 增加展开状态（`copiedCodeIndex` 附近）：

```typescript
// 归档消息历史展开状态
const showArchivedHistory = ref(false)
```

- 模板中，在 `<div class="flex flex-col items-start gap-2 flex-1">` 内部、应用名称 `<div class="text-gray-700 font-bold">` 之前，插入归档分支（`is_archived` 为真时不渲染 `agent-thought` 与 markdown 回答，仅显示占位与历史入口；`showArchivedHistory` 为真时展示 query/answer 原文）：

```html
      <!-- 归档消息：默认不展示原文，提供历史查询入口 -->
      <div v-if="props.is_archived" class="w-full">
        <div class="text-xs text-gray-400 mb-1">该轮对话已归档（压缩出短期记忆窗口）</div>
        <a-button size="mini" @click="showArchivedHistory = !showArchivedHistory">
          {{ showArchivedHistory ? '收起历史' : '查看历史' }}
        </a-button>
        <div v-if="showArchivedHistory" class="mt-2 w-full bg-gray-50 border border-gray-200 rounded-lg p-3">
          <div class="text-sm text-gray-800">{{ props.query }}</div>
          <div class="text-sm text-gray-800 mt-2">{{ props.answer }}</div>
        </div>
      </div>
      <template v-else>
        <!-- 原有 agent-thought 与回答渲染内容保持不变 -->
      </template>
```

（`a-button` 来自项目已用的 Arco Design。注意：`v-if`/`v-else` 分支需包裹原 `agent-thought` 与回答区域，将原有内容整体移入 `<template v-else>`。）

Modify `ai-code-llmops-web/src/views/space/apps/components/PreviewDebugChat.vue` 消息列表渲染（第 388-415 行）：对归档消息，整轮（human-message + ai-message）替换为归档占位，避免把已归档原文直接渲染在对话流中：

```html
            <div class="flex flex-col gap-2 pb-4">
              <template v-if="item.is_archived">
                <div class="flex flex-col gap-1 text-xs text-gray-400">
                  <span>该轮对话已归档，不再参与模型上下文</span>
                  <a-button size="mini" @click="openArchivedMessage(item)">查看历史原文</a-button>
                </div>
              </template>
              <template v-else>
                <!-- 原有 human-message + ai-message 渲染保持不变 -->
              </template>
            </div>
```

（`openArchivedMessage(item)` 在 script 中定义：`window.open` 或弹出抽屉跳转到历史查询——本项目历史查询即现有的消息分页列表，点击后滚动定位即可；若沿用 AiMessage 内联展开方式，则此处保持渲染 `<ai-message :is_archived="item.is_archived" :query="item.query" ...>` 并透传。）

Modify `ai-code-llmops-web/src/views/web-apps/IndexView.vue`（第 460-470 行本地 `messages.value.unshift` 的新消息对象、第 1021-1022 行消息渲染）同样处理：新消息对象增加 `is_archived: false`；渲染处对归档消息显示占位/透传 `is_archived` 与 `query`。Modify `ai-code-llmops-web/src/views/space/apps/components/PreviewDebugChat.vue` 第 125-135 行本地 `messages.value.unshift` 的新消息对象同样增加 `is_archived: false` 字段。

- [ ] **Step 4: 运行后端测试确认通过**

Run: `pytest test/internal/schema/test_message_resp_schema.py -v`
Expected: PASS

- [ ] **Step 5: 前端构建验证 + 提交**

Run（工作目录 `ai-code-llmops-web`）: `npm run build`
Expected: 构建成功

```bash
git add internal/schema/app_schema.py internal/schema/conversation_schema.py ai-code-llmops-web/src/models/conversation.ts ai-code-llmops-web/src/views/space/apps/components/AiMessage.vue ai-code-llmops-web/src/views/web-apps/IndexView.vue test/internal/schema/test_message_resp_schema.py
git commit -m "feat: 消息接口返回归档标记，前端归档消息显示历史查询入口"
```

---

## Phase 3：语义记忆用户卡片（双时间机制）

### Task 8: UserMemoryFact 模型（双时间机制）

**Files:**
- Create: `internal/model/user_memory.py`
- Modify: `internal/model/__init__.py:10-19`（注册导出）
- Migration: flask db migrate 生成 `add user_memory_fact` 迁移
- Test: `test/internal/model/test_user_memory.py`

**Interfaces:**
- Consumes: `db`、`PG_UUID`、`JSONB`
- Produces: `UserMemoryFact` 模型，字段：`id, app_id, user_id, fact_key, fact_value(JSONB), source, trust_score, confidence, is_implicit, valid_from, valid_to(Nullable), tx_created_at, tx_invalidated_at(Nullable), created_at, updated_at, is_deleted`
- 约束：唯一当前有效事实由服务层保证（查询过滤 `valid_to IS NULL AND tx_invalidated_at IS NULL AND is_deleted=False`），不建部分唯一索引（保持迁移简单）

- [ ] **Step 1: 生成迁移**

Run（Windows PowerShell，工作目录为项目根）:
```powershell
$env:FLASK_APP="app.http.app"; flask db migrate -m "add user_memory_fact"
$env:FLASK_APP="app.http.app"; flask db upgrade
```
Expected: 迁移生成并应用成功

- [ ] **Step 2: 写失败测试**

Create `test/internal/model/test_user_memory.py`:

```python
#!/usr/bin/env python
"""UserMemoryFact 双时间机制模型测试"""
from datetime import datetime, timedelta
from uuid import uuid4

from internal.model import UserMemoryFact


class TestUserMemoryFact:
    def test_create_fact_with_dual_time(self, app, db):
        fact = UserMemoryFact(
            app_id=uuid4(), user_id=uuid4(),
            fact_key="location", fact_value={"city": "北京"},
            source="llm_inferred", trust_score=0.8, confidence=0.9,
            is_implicit=True,
            valid_from=datetime.now(),
            valid_to=None,
            tx_created_at=datetime.now(),
            tx_invalidated_at=None,
        )
        db.session.add(fact)
        db.session.flush()

        db.session.refresh(fact)
        assert fact.valid_to is None, "当前有效事实 valid_to 应为 NULL"
        assert fact.tx_invalidated_at is None, "未作废事实 tx_invalidated_at 应为 NULL"
        assert fact.fact_value == {"city": "北京"}

    def test_invalidated_fact_keeps_history(self, app, db):
        now = datetime.now()
        fact = UserMemoryFact(
            app_id=uuid4(), user_id=uuid4(),
            fact_key="location", fact_value={"city": "深圳"},
            source="user_explicit", trust_score=1.0, confidence=1.0,
            is_implicit=False,
            valid_from=now - timedelta(days=30),
            valid_to=now,
            tx_created_at=now - timedelta(days=30),
            tx_invalidated_at=now,
        )
        db.session.add(fact)
        db.session.flush()
        db.session.refresh(fact)
        assert fact.valid_to is not None, "失效事实保留历史记录"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest test/internal/model/test_user_memory.py -v`
Expected: FAIL with `ImportError: cannot import name 'UserMemoryFact'`

- [ ] **Step 4: 实现**

Create `internal/model/user_memory.py`：

```python
#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : user_memory.py
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, PrimaryKeyConstraint, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from internal.extension.database_extension import db


class UserMemoryFact(db.Model):
    """用户事实记忆（语义记忆）—— 用户画像卡片，双时间机制。

    有效区间（valid_from/valid_to）：事实在现实世界何时为真；
    事务时间（tx_created_at/tx_invalidated_at）：系统何时写入/作废。
    旧事实失效不删除，保留历史以支持时间点回溯与审计。
    """
    __tablename__ = "user_memory_fact"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_user_memory_fact_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"))
    app_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)  # 应用命名空间
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)  # 按用户隔离
    fact_key: Mapped[str] = mapped_column(String(255), nullable=False)  # 事实键：location/occupation/preference:xxx
    fact_value: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # 结构化值
    source: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''::character varying"))  # user_explicit/llm_inferred/tool/system
    trust_score: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"))  # 信任加权 0~1
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"))  # LLM 提取置信度 0~1
    is_implicit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))  # 是否隐式推断

    # 有效区间（现实世界）
    valid_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # NULL = 当前有效

    # 事务时间（系统写入/作废）
    tx_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    tx_invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # NULL = 未作废

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
```

Modify `internal/model/__init__.py`：`from .user_memory import UserMemoryFact` 追加到导出。

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest test/internal/model/test_user_memory.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add internal/model/user_memory.py internal/model/__init__.py internal/migrations/versions/ test/internal/model/test_user_memory.py
git commit -m "feat: UserMemoryFact 双时间机制模型（有效区间+事务时间）"
```

---

### Task 9: 写侧管道——LLM 特征抽取

**Files:**
- Create: `internal/service/user_memory_service.py`
- Test: `test/internal/service/test_user_memory_service.py`

**Interfaces:**
- Consumes: `BaseService`、`LanguageModelService`、`UserMemoryFact`；`USER_FACT_EXTRACTOR_TEMPLATE`（本文件内定义）
- Produces:
  - `ExtractedFact` dataclass：`fact_key: str, fact_value: dict, confidence: float, is_implicit: bool, evidence: str`
  - `UserMemoryService(db, language_model_service)`
  - `UserMemoryService.extract_user_facts(query: str, answer: str, current_profile: str) -> list[ExtractedFact]`：LLM 抽取本轮对话中的用户特征；输出 JSON `{"facts": [...]}`，解析失败返回空列表
  - `UserMemoryService._parse_facts(raw: str) -> list[ExtractedFact]`：容错解析（剥离 ```json 围栏、取第一个 JSON 对象、异常返回 []）
  - `UserMemoryService._render_current_facts(facts: list[UserMemoryFact]) -> str`：把当前有效事实渲染成画像文本

- [ ] **Step 1: 写失败测试**

Create `test/internal/service/test_user_memory_service.py`:

```python
#!/usr/bin/env python
"""UserMemoryService 写侧管道测试：LLM 抽取用户特征（隐式更新判断）"""
from unittest.mock import MagicMock
from uuid import uuid4

from app.http.module import injector
from internal.service import UserMemoryService


class FakeExtractLLM:
    temperature = 0.0

    def __init__(self, reply):
        self.reply = reply

    def __call__(self, inputs):
        """Runnable 协议：被 coerce_to_runnable 包装后由链调用"""
        return self.reply


class TestExtractUserFacts:
    def test_extract_location_from_implicit_signals(self, app, monkeypatch):
        service = injector.get(UserMemoryService)
        raw = (
            '```json\n{"facts": [{"fact_key": "location", '
            '"fact_value": {"city": "北京"}, "confidence": 0.85, '
            '"is_implicit": true, "evidence": "用户询问北京天气并规划行程"}]}\n```'
        )
        monkeypatch.setattr(
            service.language_model_service, "load_default_language_model",
            lambda: FakeExtractLLM(raw),
        )

        with app.app_context():
            facts = service.extract_user_facts(
                "北京今天天气怎么样？帮我规划一下行程",
                "根据北京天气为您推荐了行程",
                "",
            )

        assert len(facts) == 1
        assert facts[0].fact_key == "location"
        assert facts[0].fact_value == {"city": "北京"}
        assert facts[0].is_implicit is True
        assert facts[0].confidence == 0.85

    def test_parse_garbage_returns_empty(self, app):
        service = injector.get(UserMemoryService)
        assert service._parse_facts("不是 JSON") == []
        assert service._parse_facts("") == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_user_memory_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'UserMemoryService'`

- [ ] **Step 3: 实现**

Create `internal/service/user_memory_service.py`：

```python
#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : user_memory_service.py
"""
import json
import logging
import re
from dataclasses import dataclass, field
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from injector import inject
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from internal.model import UserMemoryFact
from package.sqlalchemy import SQLAlchemy

from .base_service import BaseService
from .language_model_service import LanguageModelService

logger = logging.getLogger(__name__)

# 用户特征抽取提示词：只抽取关于用户的稳定事实；识别隐式变化；拒绝指令性/无关内容（防投毒）
USER_FACT_EXTRACTOR_TEMPLATE = """你是一个用户画像抽取器。请根据用户与助手的对话，判断是否有值得记录的"用户自身"的稳定事实变化。

可以抽取的事实类型（fact_key）示例：
- location：用户常住地/当前所在城市（如用户询问某城市天气、规划该城市行程，可隐式推断）
- occupation：职业
- preference:<主题>：偏好（如 preference:reply_style = 简洁）
- identity：身份信息

规则：
1. 只抽取关于"用户本人"的事实，不抽取助手行为、对话寒暄、一次性查询本身；
2. 允许隐式推断：用户没有明说，但行为强烈暗示（如连续询问北京天气+规划北京行程 → 推断用户在北京/要去北京），此时 is_implicit=true 并给出 evidence；
3. confidence 表示推断置信度（0~1），明说的给 0.9 以上，隐式推断按证据强度给；
4. 严禁记录指令性内容（"以后都要XX"这种是要求，不是事实）、猜测的敏感信息、与用户无关的内容；
5. 如果没有值得记录的事实，输出空列表。

当前用户画像：
{current_profile}

本轮对话：
Human: {query}
AI: {answer}

输出严格 JSON，不要输出其他内容：
{{"facts": [{{"fact_key": "...", "fact_value": {{...}}, "confidence": 0.x, "is_implicit": true/false, "evidence": "..."}}]}}"""


@dataclass
class ExtractedFact:
    """LLM 抽取出的用户事实"""
    fact_key: str
    fact_value: dict
    confidence: float
    is_implicit: bool
    evidence: str = ""


@inject
@dataclass
class UserMemoryService(BaseService):
    """用户事实记忆（语义记忆）服务：LLM 写侧管道 + 双时间写入 + 检索"""
    db: SQLAlchemy
    language_model_service: LanguageModelService

    def extract_user_facts(self, query: str, answer: str, current_profile: str) -> list[ExtractedFact]:
        """根据本轮对话抽取用户特征事实（写侧管道入口）"""
        try:
            prompt = ChatPromptTemplate.from_template(USER_FACT_EXTRACTOR_TEMPLATE)
            llm = self.language_model_service.load_default_language_model()
            llm.temperature = 0
            chain = prompt | llm | StrOutputParser()
            raw = chain.invoke({
                "query": query,
                "answer": answer,
                "current_profile": current_profile,
            })
            return self._parse_facts(raw)
        except Exception:
            logger.exception("用户特征抽取失败")
            return []

    def _parse_facts(self, raw: str) -> list[ExtractedFact]:
        """容错解析 LLM 输出：剥离 ```json 围栏，取第一个 JSON 对象"""
        if not raw:
            return []
        text = raw.strip()
        # 1、剥离代码围栏
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        # 2、提取第一个 { ... } 块
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return []
        facts = []
        for item in data.get("facts", []):
            try:
                facts.append(ExtractedFact(
                    fact_key=str(item["fact_key"]),
                    fact_value=dict(item.get("fact_value", {})),
                    confidence=float(item.get("confidence", 0.5)),
                    is_implicit=bool(item.get("is_implicit", False)),
                    evidence=str(item.get("evidence", "")),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return facts

    def _render_current_facts(self, facts: list[UserMemoryFact]) -> str:
        """将当前有效事实渲染成画像文本，供 System Prompt 注入"""
        if not facts:
            return ""
        lines = []
        for fact in facts:
            value = json.dumps(fact.fact_value, ensure_ascii=False)
            lines.append(f"{fact.fact_key}: {value}（来源:{fact.source}，置信度:{fact.confidence:.2f}）")
        return "\n".join(lines)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_user_memory_service.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/service/user_memory_service.py test/internal/service/test_user_memory_service.py
git commit -m "feat: UserMemoryService LLM 写侧管道，抽取用户特征（含隐式推断）"
```

---

### Task 10: 冲突检测 + 双时间写入（upsert）

**Files:**
- Modify: `internal/service/user_memory_service.py`
- Test: `test/internal/service/test_user_memory_service.py`（扩展）

**Interfaces:**
- Consumes: `UserMemoryFact`、`ExtractedFact`
- Produces:
  - `UserMemoryService.get_current_fact(app_id: UUID, user_id: UUID, fact_key: str) -> UserMemoryFact | None`
  - `UserMemoryService.write_fact(app_id: UUID, user_id: UUID, fact: ExtractedFact) -> UserMemoryFact | None`：冲突检测 + 双时间写入；返回写入/更新的记录，冲突被拒绝时返回 None
  - `UserMemoryService.upsert_facts(app_id: UUID, user_id: UUID, facts: list[ExtractedFact]) -> list[UserMemoryFact]`：批量调用 write_fact
  - 冲突规则：同键存在当前有效事实时——
    1. 值相同 → 原地更新 confidence/source/evidence（不产生新记录）
    2. 值不同且新事实为显式（is_implicit=False）→ 新胜出：旧事实 `valid_to=now, tx_invalidated_at=now`，新事实 `valid_from=now, tx_created_at=now` 插入
    3. 值不同且新事实为隐式 → 比较置信度：`new.confidence > old.confidence` 才按规则 2 替换；否则拒绝并记录日志（保留旧事实）

- [ ] **Step 1: 写失败测试**

扩展 `test/internal/service/test_user_memory_service.py`：

```python
from datetime import datetime, timedelta
from internal.model import UserMemoryFact
from internal.service.user_memory_service import ExtractedFact


class TestWriteFactConflict:
    def _add_fact(self, db, app_id, user_id, *, fact_key="location", value, confidence, implicit, source, valid_to=None, tx_invalidated=None, valid_from=None):
        now = datetime.now()
        fact = UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key=fact_key,
            fact_value=value, source=source, trust_score=0.5,
            confidence=confidence, is_implicit=implicit,
            valid_from=valid_from or (now - timedelta(days=30)),
            valid_to=valid_to,
            tx_created_at=now - timedelta(days=30),
            tx_invalidated_at=tx_invalidated,
        )
        db.session.add(fact)
        db.session.flush()
        return fact

    def test_explicit_new_wins_over_old(self, app, db):
        service = injector.get(UserMemoryService)
        app_id, user_id = uuid4(), uuid4()
        old = self._add_fact(db, app_id, user_id, value={"city": "深圳"},
                             confidence=1.0, implicit=False, source="user_explicit")

        with app.app_context():
            result = service.write_fact(app_id, user_id, ExtractedFact(
                fact_key="location", fact_value={"city": "北京"},
                confidence=1.0, is_implicit=False, evidence="用户明说搬去北京",
            ))

        assert result is not None and result.id != old.id, "显式新事实应插入新记录"
        db.session.refresh(old)
        assert old.valid_to is not None, "旧事实应作废（保留历史）"
        assert old.tx_invalidated_at is not None, "旧事实应记录事务作废时间"
        current = service.get_current_fact(app_id, user_id, "location")
        assert current.fact_value == {"city": "北京"}

    def test_implicit_low_confidence_rejected(self, app, db):
        service = injector.get(UserMemoryService)
        app_id, user_id = uuid4(), uuid4()
        old = self._add_fact(db, app_id, user_id, value={"city": "深圳"},
                             confidence=1.0, implicit=False, source="user_explicit")

        with app.app_context():
            result = service.write_fact(app_id, user_id, ExtractedFact(
                fact_key="location", fact_value={"city": "北京"},
                confidence=0.6, is_implicit=True, evidence="询问北京天气",
            ))

        assert result is None, "低置信度隐式推断不应覆盖显式旧事实"
        db.session.refresh(old)
        assert old.valid_to is None, "旧事实应保持不变"
        current = service.get_current_fact(app_id, user_id, "location")
        assert current.fact_value == {"city": "深圳"}

    def test_implicit_high_confidence_wins(self, app, db):
        service = injector.get(UserMemoryService)
        app_id, user_id = uuid4(), uuid4()
        old = self._add_fact(db, app_id, user_id, value={"city": "深圳"},
                             confidence=0.7, implicit=True, source="llm_inferred")

        with app.app_context():
            result = service.write_fact(app_id, user_id, ExtractedFact(
                fact_key="location", fact_value={"city": "北京"},
                confidence=0.9, is_implicit=True, evidence="连续询问北京天气并规划北京行程",
            ))

        assert result is not None, "高置信度隐式推断可覆盖低置信度旧推断"
        current = service.get_current_fact(app_id, user_id, "location")
        assert current.fact_value == {"city": "北京"}

    def test_same_value_merges_in_place(self, app, db):
        service = injector.get(UserMemoryService)
        app_id, user_id = uuid4(), uuid4()
        old = self._add_fact(db, app_id, user_id, value={"city": "北京"},
                             confidence=0.8, implicit=True, source="llm_inferred")

        with app.app_context():
            result = service.write_fact(app_id, user_id, ExtractedFact(
                fact_key="location", fact_value={"city": "北京"},
                confidence=0.95, is_implicit=True, evidence="用户再次确认在北京",
            ))

        assert result is not None and result.id == old.id, "值相同应原地更新"
        db.session.refresh(old)
        assert old.confidence == 0.95
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_user_memory_service.py::TestWriteFactConflict -v`
Expected: FAIL with `AttributeError: UserMemoryService has no attribute 'write_fact'`

- [ ] **Step 3: 实现**

Modify `internal/service/user_memory_service.py`，追加：

```python
    def get_current_fact(self, app_id: UUID, user_id: UUID, fact_key: str) -> UserMemoryFact | None:
        """查询当前有效事实（有效区间 + 事务时间均未闭合）"""
        from sqlalchemy import select
        stmt = (
            select(UserMemoryFact)
            .where(
                UserMemoryFact.app_id == app_id,
                UserMemoryFact.user_id == user_id,
                UserMemoryFact.fact_key == fact_key,
                UserMemoryFact.valid_to.is_(None),
                UserMemoryFact.tx_invalidated_at.is_(None),
                UserMemoryFact.is_deleted.is_(False),
            )
            .order_by(UserMemoryFact.tx_created_at.desc())
            .limit(1)
        )
        return self.db.session.execute(stmt).scalar_one_or_none()

    def write_fact(self, app_id: UUID, user_id: UUID, fact: ExtractedFact) -> UserMemoryFact | None:
        """冲突检测 + 双时间写入。

        规则：
        1. 无当前有效事实 → 直接写入；
        2. 值相同 → 原地合并（提升置信度）；
        3. 值不同：显式新事实胜出；隐式新事实需置信度高于旧事实才胜出；
           胜出时旧事实作废（valid_to/tx_invalidated_at=now）并保留历史。
        """
        now = datetime.now()
        old = self.get_current_fact(app_id, user_id, fact.fact_key)

        if old is None:
            return self.create(
                UserMemoryFact,
                app_id=app_id, user_id=user_id,
                fact_key=fact.fact_key, fact_value=fact.fact_value,
                source="user_explicit" if not fact.is_implicit else "llm_inferred",
                trust_score=0.9 if not fact.is_implicit else 0.5,
                confidence=fact.confidence, is_implicit=fact.is_implicit,
                valid_from=now, valid_to=None,
                tx_created_at=now, tx_invalidated_at=None,
            )

        # 值相同：原地合并
        if old.fact_value == fact.fact_value:
            self.update(
                old,
                confidence=max(old.confidence, fact.confidence),
                fact_value=fact.fact_value,
            )
            return old

        # 值不同：判断是否允许覆盖
        new_explicit = not fact.is_implicit
        old_explicit = not old.is_implicit
        allowed = (
            new_explicit
            or (old_explicit and fact.confidence >= 0.85)   # 隐式新事实覆盖显式旧事实需高置信度
            or (not old_explicit and fact.confidence > old.confidence)  # 隐式 vs 隐式按置信度
        )
        if not allowed:
            logger.info(
                "用户事实冲突被拒绝：key=%s old=%s new=%s（隐式推断置信度不足）",
                fact.fact_key, old.fact_value, fact.fact_value,
            )
            return None

        # 胜出：旧事实作废保留历史，新事实生效
        self.update(old, valid_to=now, tx_invalidated_at=now)
        return self.create(
            UserMemoryFact,
            app_id=app_id, user_id=user_id,
            fact_key=fact.fact_key, fact_value=fact.fact_value,
            source="user_explicit" if new_explicit else "llm_inferred",
            trust_score=0.9 if new_explicit else 0.5,
            confidence=fact.confidence, is_implicit=fact.is_implicit,
            valid_from=now, valid_to=None,
            tx_created_at=now, tx_invalidated_at=None,
        )

    def upsert_facts(self, app_id: UUID, user_id: UUID, facts: list[ExtractedFact]) -> list[UserMemoryFact]:
        """批量写入抽取结果，返回成功写入/更新的记录"""
        results = []
        for fact in facts:
            record = self.write_fact(app_id, user_id, fact)
            if record is not None:
                results.append(record)
        return results
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_user_memory_service.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add internal/service/user_memory_service.py test/internal/service/test_user_memory_service.py
git commit -m "feat: 用户事实冲突检测与双时间写入（显式优先、隐式按置信度）"
```

---

### Task 11: 记忆检索服务（当前有效 + 时间点回溯）

**Files:**
- Modify: `internal/service/user_memory_service.py`
- Test: `test/internal/service/test_user_memory_service.py`（扩展）

**Interfaces:**
- Produces:
  - `UserMemoryService.get_current_facts(app_id: UUID, user_id: UUID, *, min_trust: float = 0.0) -> list[UserMemoryFact]`
  - `UserMemoryService.get_facts_at(app_id: UUID, user_id: UUID, at: datetime) -> list[UserMemoryFact]`：时间点回溯（现实视角：`valid_from <= at < valid_to`）
  - `UserMemoryService.get_facts_history(app_id: UUID, user_id: UUID) -> list[UserMemoryFact]`：含作废记录（审计）

- [ ] **Step 1: 写失败测试**

扩展 `test/internal/service/test_user_memory_service.py`：

```python
class TestRetrieveFacts:
    def test_current_facts_exclude_invalidated(self, app, db):
        service = injector.get(UserMemoryService)
        app_id, user_id = uuid4(), uuid4()
        now = datetime.now()
        # 当前有效
        db.session.add(UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key="location",
            fact_value={"city": "北京"}, source="user_explicit",
            trust_score=1.0, confidence=1.0, is_implicit=False,
            valid_from=now, valid_to=None,
            tx_created_at=now, tx_invalidated_at=None,
        ))
        # 已作废历史
        db.session.add(UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key="location",
            fact_value={"city": "深圳"}, source="user_explicit",
            trust_score=1.0, confidence=1.0, is_implicit=False,
            valid_from=now - timedelta(days=30), valid_to=now,
            tx_created_at=now - timedelta(days=30), tx_invalidated_at=now,
        ))
        db.session.flush()

        with app.app_context():
            current = service.get_current_facts(app_id, user_id)
            history = service.get_facts_history(app_id, user_id)
            past = service.get_facts_at(app_id, user_id, now - timedelta(days=10))

        assert len(current) == 1 and current[0].fact_value == {"city": "北京"}
        assert len(history) == 2, "历史应含作废记录（审计）"
        assert len(past) == 1 and past[0].fact_value == {"city": "深圳"}, "时间点回溯应命中旧有效事实"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_user_memory_service.py::TestRetrieveFacts -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: 实现**

Modify `internal/service/user_memory_service.py`，追加：

```python
    def get_current_facts(self, app_id: UUID, user_id: UUID, *, min_trust: float = 0.0) -> list[UserMemoryFact]:
        """默认检索：只取当前有效事实（valid_to IS NULL 且 tx_invalidated_at IS NULL）"""
        from sqlalchemy import select
        stmt = (
            select(UserMemoryFact)
            .where(
                UserMemoryFact.app_id == app_id,
                UserMemoryFact.user_id == user_id,
                UserMemoryFact.valid_to.is_(None),
                UserMemoryFact.tx_invalidated_at.is_(None),
                UserMemoryFact.is_deleted.is_(False),
                UserMemoryFact.trust_score >= min_trust,
            )
            .order_by(UserMemoryFact.updated_at.desc())
        )
        return self.db.session.execute(stmt).scalars().all()

    def get_facts_at(self, app_id: UUID, user_id: UUID, at: datetime) -> list[UserMemoryFact]:
        """时间点回溯（现实视角）：查询 at 时刻有效的事实（含后来作废的历史）"""
        from sqlalchemy import select
        stmt = (
            select(UserMemoryFact)
            .where(
                UserMemoryFact.app_id == app_id,
                UserMemoryFact.user_id == user_id,
                UserMemoryFact.valid_from <= at,
                (UserMemoryFact.valid_to.is_(None)) | (UserMemoryFact.valid_to > at),
                UserMemoryFact.is_deleted.is_(False),
            )
            .order_by(UserMemoryFact.valid_from.desc())
        )
        return self.db.session.execute(stmt).scalars().all()

    def get_facts_history(self, app_id: UUID, user_id: UUID) -> list[UserMemoryFact]:
        """获取全部记录（含作废历史，用于审计）"""
        from sqlalchemy import select
        stmt = (
            select(UserMemoryFact)
            .where(
                UserMemoryFact.app_id == app_id,
                UserMemoryFact.user_id == user_id,
                UserMemoryFact.is_deleted.is_(False),
            )
            .order_by(UserMemoryFact.tx_created_at.desc())
        )
        return self.db.session.execute(stmt).scalars().all()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_user_memory_service.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add internal/service/user_memory_service.py test/internal/service/test_user_memory_service.py
git commit -m "feat: 用户事实检索——当前有效/时间点回溯/历史审计"
```

---

### Task 12: 画像注入 Agent（对话上下文）

**Files:**
- Modify: `internal/service/chat_runner.py`（`run` 接收 `user_profile`，传入 `_stream_and_persist` 的 stream 输入）
- Modify: `internal/service/app_service.py`（`debug_chat` 注入用户画像）
- Modify: `internal/service/web_app_service.py`（`web_app_chat` 注入用户画像）
- Test: `test/internal/service/test_chat_runner.py`（扩展）

**Interfaces:**
- Consumes: `UserMemoryService.get_current_facts` + `_render_current_facts`（Task 9/11）
- Produces: `ChatRunner.run` 的 `user_profile: str` 参数已存在于 Task 1 签名；Agent stream 输入新增 `"user_profile"` 键（Task 3 已让 Agent 消费 `state["user_profile"]`）

- [ ] **Step 1: 写失败测试**

扩展 `test/internal/service/test_chat_runner.py`：

```python
class TestChatRunnerProfile:
    def test_run_passes_user_profile_to_agent(self, app, monkeypatch):
        runner = injector.get(ChatRunner)
        account = MagicMock(id=uuid4())
        conversation = MagicMock(id=uuid4(), summary="")
        message = MagicMock(id=uuid4(), query="你好", image_urls=[])

        monkeypatch.setattr(runner.language_model_service, "load_language_model", lambda cfg: FakeLLM())
        monkeypatch.setattr(runner.app_config_service, "get_langchain_tools_by_tools_config", lambda cfg: [])
        monkeypatch.setattr(runner, "_build_history", lambda llm, conv, r: [])
        monkeypatch.setattr(runner.conversation_service, "compact_if_needed", lambda *a, **k: False)

        captured = {}
        class CapturingAgent(FakeAgent):
            def stream(self, *args, **kwargs):
                captured["input"] = args[0] if args else kwargs.get("input")
                yield from super().stream(*args, **kwargs)

        monkeypatch.setattr("internal.service.chat_runner.FunctionCallAgent", CapturingAgent)

        with app.app_context():
            list(runner.run(
                app=MagicMock(id=uuid4()),
                app_config=dict(MOCK_CONFIG),
                conversation=conversation,
                message=message,
                account=account,
                invoke_from=InvokeFrom.WEB_APP,
                user_profile="location: {\"city\": \"北京\"}",
            ))

        assert captured["input"]["user_profile"] == "location: {\"city\": \"北京\"}"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_chat_runner.py::TestChatRunnerProfile -v`
Expected: FAIL（`user_profile` 未传入 stream input）

- [ ] **Step 3: 实现**

Modify `internal/service/chat_runner.py`：`_stream_and_persist` 的 `agent.stream({...})` 输入已含 `"user_profile": user_profile`（Task 1 Step 3 已写入）；确认 `run` 的 `user_profile` 参数贯穿到 `_stream_and_persist`（Task 1 已实现）。若未贯穿则补上。

Modify `internal/service/app_service.py` `debug_chat`，注入用户画像（在 `yield from` 前）：

```python
        # 3、加载用户画像（语义记忆：当前有效事实 -> 画像文本）
        user_profile = self.user_memory_service._render_current_facts(
            self.user_memory_service.get_current_facts(app_id, account.id, min_trust=0.3)
        )

        # 4、委托统一对话执行器
        yield from self.chat_runner.run(
            app=app,
            app_config=draft_app_config,
            conversation=debug_conversation,
            message=message,
            account=account,
            invoke_from=InvokeFrom.DEBUGGER,
            user_profile=user_profile,
        )
```

（`AppService` dataclass 注入 `user_memory_service: UserMemoryService`；import `from .user_memory_service import UserMemoryService`）

Modify `internal/service/web_app_service.py` `web_app_chat`，在 `yield from` 前注入用户画像（WebAppService dataclass 同样注入 `user_memory_service: UserMemoryService`）：

```python
        # 4、加载用户画像（语义记忆：当前有效事实 -> 画像文本）
        user_profile = self.user_memory_service._render_current_facts(
            self.user_memory_service.get_current_facts(app.id, account.id, min_trust=0.3)
        )

        # 5、委托统一对话执行器
        yield from self.chat_runner.run(
            app=app,
            app_config=app_config,
            conversation=conversation,
            message=message,
            account=account,
            invoke_from=InvokeFrom.WEB_APP,
            user_profile=user_profile,
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_chat_runner.py test/internal/service/test_chat_error_handling.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add internal/service/chat_runner.py internal/service/app_service.py internal/service/web_app_service.py test/internal/service/test_chat_runner.py
git commit -m "feat: 用户画像注入 Agent 系统提示词（语义记忆进入上下文）"
```

---

### Task 13: 对话完成后异步触发写侧管道

**Files:**
- Modify: `internal/service/chat_runner.py`（`_stream_and_persist` finally 落库后触发抽取）
- Modify: `internal/service/conversation_service.py`（`save_agent_thoughts` 内已有异步线程模式可参考）
- Test: `test/internal/service/test_chat_runner.py`（扩展）

**Interfaces:**
- Consumes: `UserMemoryService.extract_user_facts` + `upsert_facts`
- Produces: `ChatRunner._trigger_memory_extraction(*, flask_app, app_config, account, conversation, message)`：当 `app_config["long_term_memory"]["enable"]` 为 True 时，子线程执行"抽取 → upsert"（防投毒：抽取 prompt 已拒绝指令性内容，写入走 Task 10 冲突检测）

- [ ] **Step 1: 写失败测试**

扩展 `test/internal/service/test_chat_runner.py`：

```python
class SyncThread:
    """测试替身：start() 时同步执行 target，避免子线程竞态"""
    def __init__(self, target=None, kwargs=None):
        self._target = target
        self._kwargs = kwargs or {}

    def start(self):
        self._target(**self._kwargs)


class TestChatRunnerMemoryExtraction:
    def test_extraction_triggered_after_stream(self, app, monkeypatch):
        runner = injector.get(ChatRunner)
        account = MagicMock(id=uuid4())
        conversation = MagicMock(id=uuid4(), summary="")
        message = MagicMock(id=uuid4(), query="北京天气怎么样", image_urls=[])

        monkeypatch.setattr(runner.language_model_service, "load_language_model", lambda cfg: FakeLLM())
        monkeypatch.setattr(runner.app_config_service, "get_langchain_tools_by_tools_config", lambda cfg: [])
        monkeypatch.setattr(runner, "_build_history", lambda llm, conv, r: [])
        monkeypatch.setattr("internal.service.chat_runner.FunctionCallAgent", FakeAgent)
        monkeypatch.setattr(runner.conversation_service, "save_agent_thoughts", lambda **kw: None)
        monkeypatch.setattr(runner.conversation_service, "compact_if_needed", lambda *a, **k: False)
        # 同步执行子线程任务（chat_runner 内使用 from threading import Thread，monkeypatch 模块内名字）
        monkeypatch.setattr("internal.service.chat_runner.Thread", SyncThread)

        triggered = {}
        monkeypatch.setattr(
            runner, "_trigger_memory_extraction",
            lambda **kwargs: triggered.update(kwargs),
        )

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

        assert triggered.get("app_config", {}).get("long_term_memory", {}).get("enable") is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_chat_runner.py::TestChatRunnerMemoryExtraction -v`
Expected: FAIL with `AttributeError: ChatRunner has no attribute '_trigger_memory_extraction'`

- [ ] **Step 3: 实现**

Modify `internal/service/chat_runner.py`：
- dataclass 注入 `user_memory_service: UserMemoryService`
- `_stream_and_persist` 的 `finally` 中，落库完成后追加：

```python
        finally:
            all_thoughts = [t for t in agent_thoughts.values()]
            if error_event:
                all_thoughts.append(error_event)
            if all_thoughts:
                try:
                    self.conversation_service.save_agent_thoughts(
                        account_id=account.id,
                        app_id=app.id,
                        app_config=app_config,
                        conversation_id=conversation.id,
                        message_id=message.id,
                        agent_thoughts=all_thoughts,
                        invoke_from=invoke_from,
                    )
                except Exception:
                    logger.exception(f"保存会话推理过程失败，message_id={message.id}")

            # 12、长期记忆开启时，异步触发用户特征抽取与写入（写侧管道）
            if app_config.get("long_term_memory", {}).get("enable"):
                flask_app = current_app._get_current_object()
                Thread(
                    target=self._trigger_memory_extraction,
                    kwargs={
                        "flask_app": flask_app,
                        "app_config": app_config,
                        "account": account,
                        "conversation": conversation,
                        "message": message,
                    },
                ).start()
```

- 新增方法：

```python
    def _trigger_memory_extraction(
            self,
            *,
            flask_app,
            app_config: dict[str, Any],
            account: Account,
            conversation: Conversation,
            message: Message,
    ) -> None:
        """写侧管道：从本轮对话抽取用户特征并写入语义记忆（子线程）"""
        with flask_app.app_context():
            try:
                current_facts = self.user_memory_service.get_current_facts(
                    conversation.app_id, account.id
                )
                current_profile = self.user_memory_service._render_current_facts(current_facts)
                extracted = self.user_memory_service.extract_user_facts(
                    message.query, message.answer, current_profile,
                )
                if extracted:
                    self.user_memory_service.upsert_facts(
                        conversation.app_id, account.id, extracted,
                    )
            except Exception:
                logger.exception("用户特征抽取写入失败，conversation_id=%s", conversation.id)
```

（`Thread` 从 `threading` import）

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_chat_runner.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 回归 + 提交**

Run: `pytest test/internal/service/test_chat_runner.py test/internal/service/test_chat_error_handling.py -v`
Expected: 全部 PASS

```bash
git add internal/service/chat_runner.py test/internal/service/test_chat_runner.py
git commit -m "feat: 长期记忆开启时对话完成后异步抽取用户特征写入语义记忆"
```

---

## Phase 4：治理与审计

### Task 14: TTL 过期清理 + 信任过滤

**Files:**
- Modify: `internal/service/user_memory_service.py`
- Test: `test/internal/service/test_user_memory_service.py`（扩展）

**Interfaces:**
- Produces: `UserMemoryService.expire_overdue_facts(app_id: UUID | None = None, user_id: UUID | None = None) -> int`：把超过 `valid_to`（或全局 TTL）的事实作废（`tx_invalidated_at=now`），返回作废条数；`get_current_facts` 已支持 `min_trust` 过滤（Task 11）

- [ ] **Step 1: 写失败测试**

扩展 `test/internal/service/test_user_memory_service.py`：

```python
class TestTtlExpiry:
    def test_expire_overdue_facts(self, app, db):
        service = injector.get(UserMemoryService)
        app_id, user_id = uuid4(), uuid4()
        now = datetime.now()
        # 已过 valid_to 的事实
        db.session.add(UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key="promo",
            fact_value={"expired": True}, source="system",
            trust_score=1.0, confidence=1.0, is_implicit=False,
            valid_from=now - timedelta(days=10), valid_to=now - timedelta(days=1),
            tx_created_at=now - timedelta(days=10), tx_invalidated_at=None,
        ))
        # 当前有效
        db.session.add(UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key="location",
            fact_value={"city": "北京"}, source="user_explicit",
            trust_score=1.0, confidence=1.0, is_implicit=False,
            valid_from=now, valid_to=None,
            tx_created_at=now, tx_invalidated_at=None,
        ))
        db.session.flush()

        with app.app_context():
            count = service.expire_overdue_facts(app_id, user_id)

        assert count == 1
        with app.app_context():
            current = service.get_current_facts(app_id, user_id)
        assert len(current) == 1, "过期事实作废后不再进入当前有效集合"

    def test_min_trust_filter(self, app, db):
        service = injector.get(UserMemoryService)
        app_id, user_id = uuid4(), uuid4()
        now = datetime.now()
        db.session.add(UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key="location",
            fact_value={"city": "北京"}, source="llm_inferred",
            trust_score=0.2, confidence=0.9, is_implicit=True,
            valid_from=now, valid_to=None,
            tx_created_at=now, tx_invalidated_at=None,
        ))
        db.session.flush()

        with app.app_context():
            all_facts = service.get_current_facts(app_id, user_id)
            trusted = service.get_current_facts(app_id, user_id, min_trust=0.5)

        assert len(all_facts) == 1
        assert len(trusted) == 0, "低信任事实应按 min_trust 过滤"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_user_memory_service.py::TestTtlExpiry -v`
Expected: FAIL with `AttributeError: expire_overdue_facts`

- [ ] **Step 3: 实现**

Modify `internal/service/user_memory_service.py`，追加：

```python
    def expire_overdue_facts(self, app_id: UUID | None = None, user_id: UUID | None = None) -> int:
        """TTL 过期清理：将 valid_to 已过的事实作废（tx_invalidated_at=now），返回作废条数"""
        from sqlalchemy import select
        now = datetime.now()
        stmt = select(UserMemoryFact).where(
            UserMemoryFact.valid_to.is_not(None),
            UserMemoryFact.valid_to < now,
            UserMemoryFact.tx_invalidated_at.is_(None),
            UserMemoryFact.is_deleted.is_(False),
        )
        if app_id is not None:
            stmt = stmt.where(UserMemoryFact.app_id == app_id)
        if user_id is not None:
            stmt = stmt.where(UserMemoryFact.user_id == user_id)
        overdue = self.db.session.execute(stmt).scalars().all()
        for fact in overdue:
            self.update(fact, tx_invalidated_at=now)
        return len(overdue)
```

Modify `ChatRunner._trigger_memory_extraction` 开头调用 `expire_overdue_facts(conversation.app_id, account.id)`（惰性过期，避免依赖定时任务）。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_user_memory_service.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add internal/service/user_memory_service.py test/internal/service/test_user_memory_service.py
git commit -m "feat: 用户事实 TTL 过期清理与信任过滤"
```

---

### Task 15: 用户卡片调试/审计 API

**Files:**
- Create: `internal/schema/user_memory_schema.py`
- Modify: `internal/handler/app_handler.py`（新增两个方法）
- Modify: `internal/router/router.py`（注册路由）
- Test: `test/internal/handler/test_app_handler.py`（扩展）

**Interfaces:**
- Consumes: `UserMemoryService.get_current_facts` / `get_facts_history` / `get_facts_at`
- Produces:
  - `GET /apps/<uuid:app_id>/memory/facts` → `{"facts": [{fact_key, fact_value, source, trust_score, confidence, is_implicit, valid_from, valid_to, tx_created_at, tx_invalidated_at}]}`
  - `GET /apps/<uuid:app_id>/memory/facts/history?at=<timestamp>` → 同结构（at 缺省返回全部历史）

- [ ] **Step 1: 写失败测试**

扩展 `test/internal/handler/test_app_handler.py`：

```python
    def test_memory_facts_endpoint(self, client):
        """用户卡片调试接口返回 facts 数组"""
        resp = client.get("/apps/00000000-0000-0000-0000-000000000000/memory/facts")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "facts" in body.get("data", {})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/handler/test_app_handler.py::TestAppHandler::test_memory_facts_endpoint -v`
Expected: FAIL（404 或路由不存在）

- [ ] **Step 3: 实现**

Create `internal/schema/user_memory_schema.py`：

```python
#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : user_memory_schema.py
"""
from marshmallow import Schema, fields, pre_dump

from internal.model import UserMemoryFact


class UserMemoryFactResp(Schema):
    """用户事实记忆响应结构"""
    fact_key = fields.String(dump_default="")
    fact_value = fields.Dict(dump_default={})
    source = fields.String(dump_default="")
    trust_score = fields.Float(dump_default=0.0)
    confidence = fields.Float(dump_default=0.0)
    is_implicit = fields.Boolean(dump_default=False)
    valid_from = fields.DateTime(dump_default=None)
    valid_to = fields.DateTime(dump_default=None)
    tx_created_at = fields.DateTime(dump_default=None)
    tx_invalidated_at = fields.DateTime(dump_default=None)

    @pre_dump
    def process_data(self, data: UserMemoryFact, **kwargs):
        return {
            "fact_key": data.fact_key,
            "fact_value": data.fact_value,
            "source": data.source,
            "trust_score": data.trust_score,
            "confidence": data.confidence,
            "is_implicit": data.is_implicit,
            "valid_from": data.valid_from,
            "valid_to": data.valid_to,
            "tx_created_at": data.tx_created_at,
            "tx_invalidated_at": data.tx_invalidated_at,
        }
```

Modify `internal/handler/app_handler.py`：
- dataclass 字段注入 `user_memory_service: UserMemoryService`（import `from internal.service import UserMemoryService`）
- 新增两个方法：

```python
    @login_required
    def get_user_memory_facts(self, app_id: UUID):
        """根据传递的应用id获取当前用户在当前应用下的有效事实（用户卡片）"""
        facts = self.user_memory_service.get_current_facts(app_id, current_user.id, min_trust=0.0)
        resp = UserMemoryFactResp(many=True)
        return success_json({"facts": resp.dump(facts)})

    @login_required
    def get_user_memory_facts_history(self, app_id: UUID):
        """根据传递的应用id获取当前用户在当前应用下的事实历史（审计）"""
        facts = self.user_memory_service.get_facts_history(app_id, current_user.id)
        resp = UserMemoryFactResp(many=True)
        return success_json({"facts": resp.dump(facts)})
```

（`AppHandler` 已 import `current_user`、`login_required`；新增 `from internal.schema.user_memory_schema import UserMemoryFactResp`）

Modify `internal/router/router.py`（`AppHandler` 区域追加）：

```python
        bp.add_url_rule(
            "/apps/<uuid:app_id>/memory/facts",
            view_func=self.app_handler.get_user_memory_facts,
        )
        bp.add_url_rule(
            "/apps/<uuid:app_id>/memory/facts/history",
            view_func=self.app_handler.get_user_memory_facts_history,
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/handler/test_app_handler.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add internal/schema/user_memory_schema.py internal/handler/app_handler.py internal/router/router.py test/internal/handler/test_app_handler.py
git commit -m "feat: 用户卡片调试/审计 API（当前有效 + 历史）"
```

---

## Phase 5：情景记忆（经历向量召回 + RRF 融合）

### Task 16: EpisodicMemory 模型 + Weaviate 集合管理

**Files:**
- Create: `internal/model/episodic_memory.py`
- Modify: `internal/model/__init__.py`（注册导出）
- Modify: `internal/service/vector_database_service.py`（增加情景记忆集合常量与集合访问器）
- Test: `test/internal/model/test_episodic_memory.py`
- Migration: flask db migrate 生成 `add episodic_memory`

**Interfaces:**
- Consumes: `db`、`PG_UUID`、`JSONB`
- Produces:
  - `EpisodicMemory` 模型：`id, app_id, user_id, content, importance(Float 0~1), source, trust_score, expires_at(Nullable), embedding_id(String, Weaviate object id), created_at, updated_at, is_deleted`
  - `EPISODIC_MEMORY_COLLECTION = "EpisodicMemory"`（常量，放 `vector_database_service.py`）
  - `VectorDatabaseService.episodic_memory_collection` 属性：返回 Weaviate `EpisodicMemory` 集合对象（按需惰性创建）
- 隔离规则：按 `(app_id, user_id)` 命名空间隔离（与语义记忆一致），Weaviate 对象属性带 `app_id/user_id` 用于检索过滤

- [ ] **Step 1: 生成迁移并写失败测试**

Run（Windows PowerShell，工作目录为项目根）:
```powershell
$env:FLASK_APP="app.http.app"; flask db migrate -m "add episodic_memory"
$env:FLASK_APP="app.http.app"; flask db upgrade
```
Expected: 迁移生成并应用成功

Create `test/internal/model/test_episodic_memory.py`:

```python
#!/usr/bin/env python
"""EpisodicMemory 情景记忆模型测试"""
from datetime import datetime
from uuid import uuid4

from internal.model import EpisodicMemory


class TestEpisodicMemory:
    def test_create_episode(self, app, db):
        episode = EpisodicMemory(
            app_id=uuid4(), user_id=uuid4(),
            content="用户询问北京天气，Agent 推荐了周末行程并调用地图工具规划路线",
            importance=0.8, source="llm_inferred", trust_score=0.5,
            expires_at=None,
        )
        db.session.add(episode)
        db.session.flush()
        db.session.refresh(episode)
        assert episode.importance == 0.8
        assert episode.is_deleted is False
        assert episode.embedding_id == "", "未入库向量时 embedding_id 为空串"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/model/test_episodic_memory.py -v`
Expected: FAIL with `ImportError: cannot import name 'EpisodicMemory'`

- [ ] **Step 3: 实现**

Create `internal/model/episodic_memory.py`：

```python
#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : episodic_memory.py
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, PrimaryKeyConstraint, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from internal.extension.database_extension import db


class EpisodicMemory(db.Model):
    """情景记忆 —— 一次完整经历的记录（事件/情景/思路），配合向量检索召回。

    按 (app_id, user_id) 命名空间隔离，防止多用户记忆混乱。
    """
    __tablename__ = "episodic_memory"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_episodic_memory_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"))
    app_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))  # 经历内容
    importance: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"))  # 重要性 0~1（写入时 LLM 打分）
    source: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''::character varying"))  # llm_inferred/user_explicit/tool/system
    trust_score: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # TTL
    embedding_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''::character varying"))  # Weaviate 对象 id
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
```

Modify `internal/model/__init__.py`：`from .episodic_memory import EpisodicMemory` 追加导出。

Modify `internal/service/vector_database_service.py`：增加常量与访问器：

```python
# 情景记忆向量集合名（与 Dataset 集合分离，按 user_id 过滤隔离）
EPISODIC_MEMORY_COLLECTION = "EpisodicMemory"

    @property
    def episodic_memory_collection(self) -> Collection:
        """获取（必要时创建）情景记忆 Weaviate 集合"""
        client = self.weaviate.client
        if EPISODIC_MEMORY_COLLECTION not in client.collections.list_all():
            client.collections.create(
                name=EPISODIC_MEMORY_COLLECTION,
                vectorizer="none",  # 由 EmbeddingsService 提供向量，禁用 Weaviate 内置向量化
                properties=[
                    {"name": "app_id", "dataType": ["text"]},
                    {"name": "user_id", "dataType": ["text"]},
                    {"name": "content", "dataType": ["text"]},
                    {"name": "importance", "dataType": ["number"]},
                    {"name": "created_at", "dataType": ["number"]},
                ],
            )
        return client.collections.get(EPISODIC_MEMORY_COLLECTION)
```

（`Collection` 已 import；`client.collections.create` 为 weaviate v4 客户端 API，项目 `requirements.txt` 中 weaviate-client 已支持。）

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/model/test_episodic_memory.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/model/episodic_memory.py internal/model/__init__.py internal/service/vector_database_service.py internal/migrations/versions/ test/internal/model/test_episodic_memory.py
git commit -m "feat: EpisodicMemory 情景记忆模型与 Weaviate 集合管理"
```

---

### Task 17: 情景记忆写侧管道（LLM 抽取经历 + 向量入库）

**Files:**
- Create: `internal/service/episodic_memory_service.py`
- Modify: `internal/service/chat_runner.py`（对话完成后异步触发抽取）
- Test: `test/internal/service/test_episodic_memory_service.py`

**Interfaces:**
- Consumes: `BaseService`、`LanguageModelService`、`EmbeddingsService`、`VectorDatabaseService`、`EpisodicMemory`
- Produces:
  - `EPISODE_EXTRACTOR_TEMPLATE`（本文件内定义）
  - `EpisodicMemoryService(db, language_model_service, embeddings_service, vector_database_service)`
  - `EpisodicMemoryService.extract_episodes(query: str, answer: str, existing_memories_text: str) -> list[dict]`：LLM 从本轮对话抽取"值得记住的经历"，输出 `[{"content": "...", "importance": 0.x, "evidence": "..."}]`
  - `EpisodicMemoryService.write_episode(*, app_id, user_id, content, importance, source="llm_inferred") -> EpisodicMemory`：Postgres 落库 + embedding 入库 Weaviate（写 `embedding_id`）
  - `EpisodicMemoryService.upsert_episodes(app_id, user_id, episodes: list[dict]) -> list[EpisodicMemory]`
  - `ChatRunner._trigger_episodic_extraction(*, flask_app, app_config, account, conversation, message)`：长期记忆开启时子线程执行"抽取 → 写入"

- [ ] **Step 1: 写失败测试**

Create `test/internal/service/test_episodic_memory_service.py`:

```python
#!/usr/bin/env python
"""EpisodicMemoryService 写侧管道测试：LLM 抽取经历 + 向量入库"""
from unittest.mock import MagicMock
from uuid import uuid4

from app.http.module import injector
from internal.service import EpisodicMemoryService


class FakeEpisodeLLM:
    temperature = 0.0

    def __init__(self, reply):
        self.reply = reply

    def __call__(self, inputs):
        return self.reply


class FakeEmbeddings:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class TestEpisodicWrite:
    def test_extract_episodes_parses(self, app, monkeypatch):
        service = injector.get(EpisodicMemoryService)
        raw = (
            '```json\n{"episodes": [{"content": "用户询问北京天气，Agent 推荐了周末行程", '
            '"importance": 0.8, "evidence": "用户连续询问北京相关话题"}]}\n```'
        )
        monkeypatch.setattr(
            service.language_model_service, "load_default_language_model",
            lambda: FakeEpisodeLLM(raw),
        )

        with app.app_context():
            episodes = service.extract_episodes("北京天气怎么样", "为您推荐了行程", "")

        assert len(episodes) == 1
        assert episodes[0]["content"].startswith("用户询问北京天气")
        assert episodes[0]["importance"] == 0.8

    def test_write_episode_persists_and_embeds(self, app, db, monkeypatch):
        service = injector.get(EpisodicMemoryService)
        # 替换向量相关依赖：embeddings 与 weaviate 集合
        fake_collection = MagicMock()
        fake_collection.data.insert.return_value = "obj-id-123"
        monkeypatch.setattr(
            service.vector_database_service, "episodic_memory_collection",
            fake_collection,
        )
        monkeypatch.setattr(service.embeddings_service, "embeddings", FakeEmbeddings())

        with app.app_context():
            episode = service.write_episode(
                app_id=uuid4(), user_id=uuid4(),
                content="用户询问北京天气，Agent 推荐了行程",
                importance=0.8,
            )

        assert episode.embedding_id == "obj-id-123"
        assert episode.importance == 0.8
        fake_collection.data.insert.assert_called_once()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_episodic_memory_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'EpisodicMemoryService'`

- [ ] **Step 3: 实现**

Create `internal/service/episodic_memory_service.py`：

```python
#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : episodic_memory_service.py
"""
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from injector import inject
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from internal.model import EpisodicMemory
from package.sqlalchemy import SQLAlchemy

from .base_service import BaseService
from .embeddings_service import EmbeddingsService
from .language_model_service import LanguageModelService
from .vector_database_service import VectorDatabaseService

logger = logging.getLogger(__name__)

# 情景记忆抽取提示词：只记录"完整的、可能有用的经历"，不记录寒暄/一次性查询
EPISODE_EXTRACTOR_TEMPLATE = """你是一个情景记忆抽取器。请判断用户与助手的对话中，是否有值得长期记住的"完整经历"。

值得记录的经历示例：
- 用户正在推进的一个长期任务及其进展（如"正在准备搬家到北京，已完成房源搜索"）
- 一次成功/失败的交互过程及其思路（如"用户偏好用表格对比方案，Agent 提供了三方案对比"）
- 反复出现的行为模式（如"用户每次提问都要求先给结论"）

不值得记录的内容：
- 一次性的闲聊、问候、简单问答；
- 助手自己的行为总结（除非用户明确认可）；
- 指令性内容（"以后都要XX"这类要求不构成经历，属于程序记忆范畴）。

规则：
1. importance 表示该经历对后续对话的价值（0~1），需要长期任务跟踪/行为模式给 0.8 以上；
2. 只输出真正有复用价值的经历，宁缺毋滥，没有则输出空列表；
3. 严禁记录猜测的敏感信息与用户隐私细节。

已有情景记忆：
{existing_memories}

本轮对话：
Human: {query}
AI: {answer}

输出严格 JSON，不要输出其他内容：
{{"episodes": [{{"content": "...", "importance": 0.x, "evidence": "..."}}]}}"""


@inject
@dataclass
class EpisodicMemoryService(BaseService):
    """情景记忆服务：写侧管道（抽取+向量入库）与检索"""
    db: SQLAlchemy
    language_model_service: LanguageModelService
    embeddings_service: EmbeddingsService
    vector_database_service: VectorDatabaseService

    def extract_episodes(self, query: str, answer: str, existing_memories_text: str) -> list[dict]:
        """根据本轮对话抽取值得记住的经历（写侧管道入口）"""
        try:
            prompt = ChatPromptTemplate.from_template(EPISODE_EXTRACTOR_TEMPLATE)
            llm = self.language_model_service.load_default_language_model()
            llm.temperature = 0
            chain = prompt | llm | StrOutputParser()
            raw = chain.invoke({
                "query": query,
                "answer": answer,
                "existing_memories": existing_memories_text,
            })
            return self._parse_episodes(raw)
        except Exception:
            logger.exception("情景记忆抽取失败")
            return []

    def _parse_episodes(self, raw: str) -> list[dict]:
        """容错解析 LLM 输出：剥离 ```json 围栏，取第一个 JSON 对象"""
        if not raw:
            return []
        text = raw.strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return []
        episodes = []
        for item in data.get("episodes", []):
            try:
                episodes.append({
                    "content": str(item["content"]),
                    "importance": float(item.get("importance", 0.5)),
                    "evidence": str(item.get("evidence", "")),
                })
            except (KeyError, TypeError, ValueError):
                continue
        return episodes

    def write_episode(
            self,
            *,
            app_id: UUID,
            user_id: UUID,
            content: str,
            importance: float,
            source: str = "llm_inferred",
    ) -> EpisodicMemory:
        """写入一条情景记忆：Postgres 落库 + embedding 入库 Weaviate"""
        # 1、向量入库（按 user_id 命名空间隔离）
        embedding = self.embeddings_service.embeddings.embed_query(content)
        collection = self.vector_database_service.episodic_memory_collection
        obj_id = collection.data.insert(
            properties={
                "app_id": str(app_id),
                "user_id": str(user_id),
                "content": content,
                "importance": importance,
                "created_at": datetime.now().timestamp(),
            },
            vector=embedding,
        )

        # 2、Postgres 落库（关联 embedding_id 便于审计/删除）
        return self.create(
            EpisodicMemory,
            app_id=app_id, user_id=user_id,
            content=content, importance=importance,
            source=source, trust_score=0.5,
            expires_at=None, embedding_id=str(obj_id),
        )

    def upsert_episodes(self, app_id: UUID, user_id: UUID, episodes: list[dict]) -> list[EpisodicMemory]:
        """批量写入抽取结果"""
        results = []
        for episode in episodes:
            record = self.write_episode(
                app_id=app_id, user_id=user_id,
                content=episode["content"],
                importance=episode["importance"],
            )
            results.append(record)
        return results
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_episodic_memory_service.py -v`
Expected: 全部 PASS

- [ ] **Step 5: ChatRunner 接入异步写侧管道**

Modify `internal/service/chat_runner.py`：
- dataclass 注入 `episodic_memory_service: EpisodicMemoryService`
- `_stream_and_persist` 的 finally 中，在语义抽取触发之后追加情景抽取：

```python
            # 13、长期记忆开启时，异步触发情景记忆抽取与写入
            if app_config.get("long_term_memory", {}).get("enable"):
                Thread(
                    target=self._trigger_episodic_extraction,
                    kwargs={
                        "flask_app": current_app._get_current_object(),
                        "app_config": app_config,
                        "account": account,
                        "conversation": conversation,
                        "message": message,
                    },
                ).start()
```

- 新增方法：

```python
    def _trigger_episodic_extraction(
            self,
            *,
            flask_app,
            app_config: dict[str, Any],
            account: Account,
            conversation: Conversation,
            message: Message,
    ) -> None:
        """情景记忆写侧管道：从本轮对话抽取经历并向量入库（子线程）"""
        with flask_app.app_context():
            try:
                # 已有记忆参考文本（Task 18 实现 get_recent_text 后替换为真实调用）
                existing = ""
                episodes = self.episodic_memory_service.extract_episodes(
                    message.query, message.answer, existing,
                )
                if episodes:
                    self.episodic_memory_service.upsert_episodes(
                        conversation.app_id, account.id, episodes,
                    )
            except Exception:
                logger.exception("情景记忆抽取写入失败，conversation_id=%s", conversation.id)
```

（`get_recent_text` 在 Task 18 实现；Task 18 完成后，把上面 `existing = ""` 替换为 `existing = self.episodic_memory_service.get_recent_text(conversation.app_id, account.id)`。）

- [ ] **Step 6: 回归 + 提交**

Task 17 让 `ChatRunner` 在长期记忆开启时额外触发 `_trigger_episodic_extraction`，既有 `test_chat_runner.py` 中 `TestChatRunnerMemoryExtraction`（Task 13）的配置 `long_term_memory.enable=True` 会真实执行 episodic 抽取（连接 embedding 模型）。同步更新该测试，追加 monkeypatch：

```python
        monkeypatch.setattr(runner, "_trigger_episodic_extraction", lambda **kwargs: None)
```

同时 `TestChatRunnerProfile`（Task 12）与 `TestChatRunnerEpisodicMemory`（Task 19）中 `MOCK_CONFIG` 的 `long_term_memory.enable=False`，不受影响。

Run: `pytest test/internal/service/test_episodic_memory_service.py test/internal/service/test_chat_runner.py -v`
Expected: 全部 PASS

```bash
git add internal/service/episodic_memory_service.py internal/service/chat_runner.py test/internal/service/test_episodic_memory_service.py
git commit -m "feat: 情景记忆写侧管道（LLM 抽取经历 + 向量入库）"
```

---

### Task 18: 情景记忆检索（向量+BM25 → RRF → 新近度/重要性加权）

**Files:**
- Modify: `internal/service/episodic_memory_service.py`
- Test: `test/internal/service/test_episodic_memory_service.py`（扩展）

**Interfaces:**
- Consumes: `rrf_fusion`（`internal/core/retrievers/rrf.py`）、Weaviate `Filter`/`MetadataQuery`
- Produces:
  - `EpisodicMemoryService._recall_vector(app_id, user_id, query, k) -> list[tuple[str, float]]`：返回 `[(memory_id, similarity), ...]`
  - `EpisodicMemoryService._recall_bm25(app_id, user_id, query, k) -> list[tuple[str, float]]`
  - `EpisodicMemoryService._recency_weight(created_at, decay=0.05) -> float`：`exp(-decay * age_days)`
  - `EpisodicMemoryService.search_episodes(app_id, user_id, query, *, top_k=5, fusion_k=20) -> list[EpisodicMemory]`：双路召回 → `rrf_fusion` → 最终分 = RRF 分 + 新近度权重 + 重要性权重 → top-k
  - `EpisodicMemoryService.get_recent_text(app_id, user_id, limit=5) -> str`：最近经历文本（供写侧管道去重参考）

- [ ] **Step 1: 写失败测试**

扩展 `test/internal/service/test_episodic_memory_service.py`：

```python
class TestEpisodicSearch:
    def test_recency_weight_decays(self):
        service = injector.get(EpisodicMemoryService)
        from datetime import datetime, timedelta
        now = datetime.now()
        assert service._recency_weight(now) == 1.0
        old = service._recency_weight(now - timedelta(days=30))
        assert 0 < old < 1.0, "30 天前经历的新近度权重应小于 1"

    def test_search_fuses_and_ranks(self, app, db, monkeypatch):
        service = injector.get(EpisodicMemoryService)
        app_id, user_id = uuid4(), uuid4()

        # 向量依赖替换为假实现（避免真实连接模型/weaviate）
        fake_collection = MagicMock()
        fake_collection.data.insert.return_value = "obj-id-abc"
        monkeypatch.setattr(
            service.vector_database_service, "episodic_memory_collection",
            fake_collection,
        )
        monkeypatch.setattr(service.embeddings_service, "embeddings", FakeEmbeddings())

        # 写入两条经历（写侧管道复用 Task 17 测试的 FakeEmbeddings）
        episodes = []
        for content, importance in [
            ("用户正在准备搬家到北京，已完成房源搜索", 0.9),
            ("用户偏好用表格对比方案", 0.6),
        ]:
            ep = service.write_episode(
                app_id=app_id, user_id=user_id,
                content=content, importance=importance,
            )
            episodes.append(ep)

        # 双路召回：monkeypatch 返回固定排名（向量路命中第二条，BM25 路命中第一条）
        def fake_vector(app_id, user_id, query, k):
            return [(str(episodes[1].id), 0.8)]

        def fake_bm25(app_id, user_id, query, k):
            return [(str(episodes[0].id), 1.2)]

        monkeypatch.setattr(service, "_recall_vector", fake_vector)
        monkeypatch.setattr(service, "_recall_bm25", fake_bm25)

        with app.app_context():
            results = service.search_episodes(app_id, user_id, "北京搬家")

        assert len(results) >= 1
        assert all(isinstance(r, type(episodes[0])) for r in results)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_episodic_memory_service.py::TestEpisodicSearch -v`
Expected: FAIL with `AttributeError: EpisodicMemoryService has no attribute '_recency_weight'`

- [ ] **Step 3: 实现**

Modify `internal/service/episodic_memory_service.py`，追加：

```python
    def _recency_weight(self, created_at: datetime, decay: float = 0.05) -> float:
        """新近度权重：exp(-decay * age_days)，距今越近权重越高"""
        import math
        age_days = max((datetime.now() - created_at).total_seconds() / 86400.0, 0.0)
        return math.exp(-decay * age_days)

    def _recall_vector(self, app_id: UUID, user_id: UUID, query: str, k: int) -> list[tuple[str, float]]:
        """向量召回：near_vector + Filter(user_id)，返回 [(memory_id, similarity)]"""
        from weaviate.classes.query import Filter, MetadataQuery

        query_vector = self.embeddings_service.embeddings.embed_query(query)
        collection = self.vector_database_service.episodic_memory_collection
        filters = Filter.all_of([
            Filter.by_property("app_id").equal(str(app_id)),
            Filter.by_property("user_id").equal(str(user_id)),
        ])
        response = collection.query.near_vector(
            near_vector=query_vector,
            limit=k,
            filters=filters,
            return_metadata=MetadataQuery(distance=True),
        )
        results = []
        for obj in response.objects:
            distance = obj.metadata.distance or 1.0
            similarity = max(1.0 - distance, 0.0)
            results.append((obj.uuid, similarity))
        return results

    def _recall_bm25(self, app_id: UUID, user_id: UUID, query: str, k: int) -> list[tuple[str, float]]:
        """BM25 召回：Weaviate bm25 + Filter(user_id)，返回 [(memory_id, score)]"""
        from weaviate.classes.query import Filter, MetadataQuery

        collection = self.vector_database_service.episodic_memory_collection
        filters = Filter.all_of([
            Filter.by_property("app_id").equal(str(app_id)),
            Filter.by_property("user_id").equal(str(user_id)),
        ])
        response = collection.query.bm25(
            query=query,
            query_properties=["content"],
            limit=k,
            filters=filters,
            return_metadata=MetadataQuery(score=True),
        )
        results = []
        for obj in response.objects:
            score = getattr(obj.metadata, "score", 0) or 0
            results.append((obj.uuid, float(score)))
        return results

    def search_episodes(
            self,
            app_id: UUID,
            user_id: UUID,
            query: str,
            *,
            top_k: int = 5,
            fusion_k: int = 20,
    ) -> list[EpisodicMemory]:
        """情景记忆检索：向量 + BM25 双路召回 → RRF 融合 → 新近度/重要性加权 → top-k

        检索隔离：所有召回均带 (app_id, user_id) 过滤，防止多用户记忆混乱。
        """
        from internal.core.retrievers.rrf import rrf_fusion

        # 1、双路召回
        vector_hits = self._recall_vector(app_id, user_id, query, fusion_k)
        bm25_hits = self._recall_bm25(app_id, user_id, query, fusion_k)

        # 2、RRF 融合（key = memory_id）
        fused = rrf_fusion(
            [vector_hits, bm25_hits],
            key_func=lambda pair: pair[0],
        )  # [(memory_id, rrf_score)]

        if not fused:
            return []

        # 3、按 memory_id 批量加载记录并加权排序
        memory_ids = [memory_id for memory_id, _ in fused[:fusion_k]]
        from sqlalchemy import select
        stmt = (
            select(EpisodicMemory)
            .where(
                EpisodicMemory.id.in_(memory_ids),
                EpisodicMemory.is_deleted.is_(False),
            )
        )
        records = {record.id: record for record in self.db.session.execute(stmt).scalars().all()}

        ranked = []
        for memory_id, rrf_score in fused:
            record = records.get(memory_id)
            if record is None:
                continue
            final_score = (
                rrf_score
                + 0.3 * self._recency_weight(record.created_at)
                + 0.4 * record.importance
            )
            ranked.append((record, final_score))

        ranked.sort(key=lambda pair: pair[1], reverse=True)
        return [record for record, _ in ranked[:top_k]]

    def get_recent_text(self, app_id: UUID, user_id: UUID, limit: int = 5) -> str:
        """获取最近的情景记忆文本（供写侧管道参考，避免重复记录）"""
        from sqlalchemy import select, desc
        stmt = (
            select(EpisodicMemory)
            .where(
                EpisodicMemory.app_id == app_id,
                EpisodicMemory.user_id == user_id,
                EpisodicMemory.is_deleted.is_(False),
            )
            .order_by(desc(EpisodicMemory.created_at))
            .limit(limit)
        )
        records = self.db.session.execute(stmt).scalars().all()
        return "\n".join(f"- {r.content}" for r in records)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_episodic_memory_service.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 回归 + 提交**

Run: `pytest test/internal/service/test_episodic_memory_service.py test/internal/service/test_chat_runner.py -v`
Expected: 全部 PASS

```bash
git add internal/service/episodic_memory_service.py test/internal/service/test_episodic_memory_service.py
git commit -m "feat: 情景记忆检索——向量+BM25 双路召回、RRF 融合、新近度/重要性加权"
```

---

### Task 19: 情景记忆注入 Agent（对话前召回 → `<情景记忆>` 块）

**Files:**
- Modify: `internal/service/chat_runner.py`（`run` 召回并传入）
- Modify: `internal/core/agent/entities/agent_entity.py`（模板 + `build_system_prompt` 增加 `episodic_memory` 参数）
- Modify: `internal/core/agent/agents/function_call_agent.py`（`_long_term_memory_recall_node` 消费 `state["episodic_memory"]`）
- Modify: `internal/core/agent/agents/react_agent.py`（同上）
- Test: `test/internal/service/test_chat_runner.py`（扩展）+ `test/internal/core/agent/test_system_prompt.py`（扩展）

**Interfaces:**
- Consumes: `EpisodicMemoryService.search_episodes`（Task 18）
- Produces: `build_system_prompt(..., episodic_memory: str = "")` 渲染 `<情景记忆>` 块（空则省略）；`ChatRunner.run` 新增参数 `episodic_memory: str = ""`，`_stream_and_persist` 的 stream 输入新增 `"episodic_memory"` 键

- [ ] **Step 1: 写失败测试**

扩展 `test/internal/core/agent/test_system_prompt.py`：

```python
    def test_episodic_memory_block_rendered_when_present(self):
        prompt = build_system_prompt(
            AGENT_SYSTEM_PROMPT_TEMPLATE,
            preset_prompt="你是客服助手",
            episodic_memory="用户正在准备搬家到北京，已完成房源搜索",
        )
        assert "用户正在准备搬家到北京" in prompt

    def test_episodic_memory_block_omitted_when_empty(self):
        prompt = build_system_prompt(
            AGENT_SYSTEM_PROMPT_TEMPLATE,
            preset_prompt="你是客服助手",
        )
        assert "情景记忆" not in prompt
```

扩展 `test/internal/service/test_chat_runner.py`：

```python
class TestChatRunnerEpisodicMemory:
    def test_run_passes_episodic_memory_to_agent(self, app, monkeypatch):
        runner = injector.get(ChatRunner)
        account = MagicMock(id=uuid4())
        conversation = MagicMock(id=uuid4(), summary="")
        message = MagicMock(id=uuid4(), query="你好", image_urls=[])

        monkeypatch.setattr(runner.language_model_service, "load_language_model", lambda cfg: FakeLLM())
        monkeypatch.setattr(runner.app_config_service, "get_langchain_tools_by_tools_config", lambda cfg: [])
        monkeypatch.setattr(runner, "_build_history", lambda llm, conv, r: [])
        monkeypatch.setattr(runner.conversation_service, "compact_if_needed", lambda *a, **k: False)

        captured = {}
        class CapturingAgent(FakeAgent):
            def stream(self, *args, **kwargs):
                captured["input"] = args[0] if args else kwargs.get("input")
                yield from super().stream(*args, **kwargs)

        monkeypatch.setattr("internal.service.chat_runner.FunctionCallAgent", CapturingAgent)
        monkeypatch.setattr(
            runner.episodic_memory_service, "search_episodes",
            lambda app_id, user_id, query, **kw: [
                MagicMock(content="用户正在准备搬家到北京"),
            ],
        )

        with app.app_context():
            list(runner.run(
                app=MagicMock(id=uuid4()),
                app_config=dict(MOCK_CONFIG),
                conversation=conversation,
                message=message,
                account=account,
                invoke_from=InvokeFrom.WEB_APP,
            ))

        assert "用户正在准备搬家到北京" in captured["input"].get("episodic_memory", "")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/core/agent/test_system_prompt.py test/internal/service/test_chat_runner.py::TestChatRunnerEpisodicMemory -v`
Expected: FAIL（模板无 `episodic_memory` 参数 / stream 输入无该键）

- [ ] **Step 3: 实现**

Modify `internal/core/agent/entities/agent_entity.py`：
- 两个模板末尾追加 `{episodic_memory_block}` 占位
- `build_system_prompt` 增加参数与渲染：

```python
def build_system_prompt(
        template: str,
        *,
        preset_prompt: str,
        long_term_memory: str = "",
        user_profile: str = "",
        episodic_memory: str = "",
        tool_description: str = "",
) -> str:
    """构建系统提示词：<长期记忆>/<用户画像>/<情景记忆> 为空时整块省略"""
    long_term_memory_block = (
        f"\n<长期记忆>\n{long_term_memory}\n</长期记忆>\n"
        if long_term_memory else ""
    )
    user_profile_block = (
        f"\n<用户画像>\n{user_profile}\n</用户画像>\n"
        if user_profile else ""
    )
    episodic_memory_block = (
        f"\n<情景记忆>\n{episodic_memory}\n</情景记忆>\n"
        if episodic_memory else ""
    )
    return template.format(
        preset_prompt=preset_prompt,
        long_term_memory_block=long_term_memory_block,
        user_profile_block=user_profile_block,
        episodic_memory_block=episodic_memory_block,
        tool_description=tool_description,
    )
```

Modify `function_call_agent.py` / `react_agent.py` 的 `_long_term_memory_recall_node`：`build_system_prompt(...)` 调用增加 `episodic_memory=state.get("episodic_memory", "")`。

Modify `internal/service/chat_runner.py`：
- `run` 签名增加 `episodic_memory: str = ""`；`_stream_and_persist` 签名增加 `episodic_memory: str = ""` 参数，`run` 在调用处透传
- `run` 内部（`_build_history` 之后）召回情景记忆：

```python
        # 2.1、情景记忆：对话前按当前提问召回 top-k 经历
        if not episodic_memory:
            try:
                episodes = self.episodic_memory_service.search_episodes(
                    conversation.app_id, account.id, message.query,
                    top_k=3,
                )
                episodic_memory = "\n".join(f"- {e.content}" for e in episodes)
            except Exception:
                logger.exception("情景记忆召回失败")
```

- `_stream_and_persist` 的 stream 输入增加 `"episodic_memory": episodic_memory`

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/core/agent/test_system_prompt.py test/internal/service/test_chat_runner.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 回归 + 提交**

Run: `pytest test/internal/service/ test/internal/core/agent/ -v`
Expected: 全部 PASS

```bash
git add internal/core/agent/entities/agent_entity.py internal/core/agent/agents/function_call_agent.py internal/core/agent/agents/react_agent.py internal/service/chat_runner.py test/internal/core/agent/test_system_prompt.py test/internal/service/test_chat_runner.py
git commit -m "feat: 情景记忆对话前召回并注入 Agent 系统提示词"
```

---

## Phase 6：程序记忆（规则/人设工具化 + 反馈反思改写）

### Task 20: ProceduralMemory 模型 + 记忆工具集

**Files:**
- Create: `internal/model/procedural_memory.py`
- Modify: `internal/model/__init__.py`
- Create: `internal/core/tools/memory_tools.py`
- Test: `test/internal/model/test_procedural_memory.py`、`test/internal/core/tools/test_memory_tools.py`
- Migration: flask db migrate 生成 `add procedural_memory`

**Interfaces:**
- Consumes: `UserMemoryService`（语义）、`EpisodicMemoryService`（情景）、`db`
- Produces:
  - `ProceduralMemory` 模型：`id, app_id, user_id, content, source, trust_score, version, created_at, updated_at, is_deleted`
  - `MemoryTools(db, user_memory_service, episodic_memory_service)`（injector dataclass）
  - `MemoryTools.get_tools(*, flask_app, app_id, user_id) -> list[BaseTool]`：返回 `search_memory` / `write_memory` / `update_memory` / `forget_memory` 四个工具
  - `ProceduralMemoryService`（含在 `memory_tools.py` 内或独立文件——本计划放独立 `internal/service/procedural_memory_service.py`）：`get_instructions(app_id, user_id) -> str`、`upsert_instruction(app_id, user_id, content, source)`、`soft_delete(app_id, user_id, memory_id)`

- [ ] **Step 1: 生成迁移并写失败测试**

Run（Windows PowerShell，工作目录为项目根）:
```powershell
$env:FLASK_APP="app.http.app"; flask db migrate -m "add procedural_memory"
$env:FLASK_APP="app.http.app"; flask db upgrade
```
Expected: 迁移生成并应用成功

Create `test/internal/model/test_procedural_memory.py`:

```python
#!/usr/bin/env python
"""ProceduralMemory 程序记忆模型测试"""
from uuid import uuid4

from internal.model import ProceduralMemory


class TestProceduralMemory:
    def test_create_instruction(self, app, db):
        record = ProceduralMemory(
            app_id=uuid4(), user_id=uuid4(),
            content="回答用户时先给结论再给细节",
            source="reflection", trust_score=0.6, version=1,
        )
        db.session.add(record)
        db.session.flush()
        db.session.refresh(record)
        assert record.version == 1
        assert record.is_deleted is False
```

Create `test/internal/core/tools/test_memory_tools.py`:

```python
#!/usr/bin/env python
"""记忆工具集测试：search/write/update/forget_memory"""
from unittest.mock import MagicMock
from uuid import uuid4

from app.http.module import injector
from internal.core.tools.memory_tools import MemoryTools


class TestMemoryTools:
    def test_get_tools_returns_four_tools(self):
        tools_service = injector.get(MemoryTools)
        tools = tools_service.get_tools(
            flask_app=MagicMock(),
            app_id=uuid4(),
            user_id=uuid4(),
        )
        names = {tool.name for tool in tools}
        assert names == {"search_memory", "write_memory", "update_memory", "forget_memory"}

    def test_write_tool_persists_procedural(self, app, db):
        tools_service = injector.get(MemoryTools)
        app_id, user_id = uuid4(), uuid4()
        tools = tools_service.get_tools(flask_app=MagicMock(), app_id=app_id, user_id=user_id)
        write_tool = next(t for t in tools if t.name == "write_memory")

        with app.app_context():
            result = write_tool.invoke({
                "content": "用户要求回答时先给结论",
                "memory_type": "procedural",
            })

        assert "成功" in result
        from internal.model import ProceduralMemory
        records = db.session.query(ProceduralMemory).filter(
            ProceduralMemory.app_id == app_id,
            ProceduralMemory.user_id == user_id,
        ).all()
        assert len(records) == 1
        assert records[0].content == "用户要求回答时先给结论"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/model/test_procedural_memory.py test/internal/core/tools/test_memory_tools.py -v`
Expected: FAIL with `ImportError: cannot import name 'ProceduralMemory'`

- [ ] **Step 3: 实现**

Create `internal/model/procedural_memory.py`：

```python
#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : procedural_memory.py
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, Integer, PrimaryKeyConstraint, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from internal.extension.database_extension import db


class ProceduralMemory(db.Model):
    """程序记忆 —— Agent 做事的规则和人设，靠反馈与反思不断改写。

    按 (app_id, user_id) 隔离；version 乐观锁，每次改写 +1，保留历史由外部审计。
    """
    __tablename__ = "procedural_memory"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_procedural_memory_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"))
    app_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))  # 行为规则/人设指令
    source: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''::character varying"))  # reflection/feedback/user_explicit/system
    trust_score: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))  # 改写版本号
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
```

Modify `internal/model/__init__.py`：导出 `ProceduralMemory`。

Create `internal/service/procedural_memory_service.py`：

```python
#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : procedural_memory_service.py
"""
import logging
from dataclasses import dataclass
from uuid import UUID

from injector import inject
from sqlalchemy import select

from internal.model import ProceduralMemory
from package.sqlalchemy import SQLAlchemy

from .base_service import BaseService

logger = logging.getLogger(__name__)


@inject
@dataclass
class ProceduralMemoryService(BaseService):
    """程序记忆服务：Agent 行为规则/人设的读取与改写"""
    db: SQLAlchemy

    def get_instructions(self, app_id: UUID, user_id: UUID) -> str:
        """获取当前有效的程序记忆（行为规则），渲染成文本供注入"""
        stmt = (
            select(ProceduralMemory)
            .where(
                ProceduralMemory.app_id == app_id,
                ProceduralMemory.user_id == user_id,
                ProceduralMemory.is_deleted.is_(False),
            )
            .order_by(ProceduralMemory.version.desc())
        )
        records = self.db.session.execute(stmt).scalars().all()
        return "\n".join(f"- {r.content}" for r in records)

    def upsert_instruction(self, app_id: UUID, user_id: UUID, content: str, source: str) -> ProceduralMemory:
        """写入/改写一条程序记忆（幂等：相同内容合并，不同内容新写一条并版本+1 由审计保留）"""
        stmt = (
            select(ProceduralMemory)
            .where(
                ProceduralMemory.app_id == app_id,
                ProceduralMemory.user_id == user_id,
                ProceduralMemory.content == content,
                ProceduralMemory.is_deleted.is_(False),
            )
        )
        existing = self.db.session.execute(stmt).scalar_one_or_none()
        if existing:
            return existing
        # 计算当前最大版本
        stmt = (
            select(ProceduralMemory)
            .where(
                ProceduralMemory.app_id == app_id,
                ProceduralMemory.user_id == user_id,
                ProceduralMemory.is_deleted.is_(False),
            )
            .order_by(ProceduralMemory.version.desc())
            .limit(1)
        )
        latest = self.db.session.execute(stmt).scalar_one_or_none()
        version = (latest.version + 1) if latest else 1
        return self.create(
            ProceduralMemory,
            app_id=app_id, user_id=user_id,
            content=content, source=source,
            trust_score=0.6, version=version,
        )

    def soft_delete(self, app_id: UUID, user_id: UUID, memory_id: UUID) -> None:
        """删除一条程序记忆"""
        stmt = (
            select(ProceduralMemory)
            .where(
                ProceduralMemory.id == memory_id,
                ProceduralMemory.app_id == app_id,
                ProceduralMemory.user_id == user_id,
                ProceduralMemory.is_deleted.is_(False),
            )
        )
        record = self.db.session.execute(stmt).scalar_one_or_none()
        if record:
            self.update(record, is_deleted=True)
```

Create `internal/core/tools/memory_tools.py`：

```python
#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : memory_tools.py

记忆工具集：把记忆的读写检索暴露给 Agent（MemGPT/LangMem 模式）。
- search_memory：检索情景记忆（向量召回）
- write_memory：写入情景经历（episodic）或行为规则（procedural）
- update_memory：改写程序记忆（规则/人设）
- forget_memory：删除记忆
"""
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from flask import Flask
from injector import inject
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from internal.service.episodic_memory_service import EpisodicMemoryService
from internal.service.procedural_memory_service import ProceduralMemoryService
from internal.service.user_memory_service import UserMemoryService
from package.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


class SearchMemoryInput(BaseModel):
    query: str = Field(description="检索 query，与当前对话主题相关")
    memory_type: str = Field(default="episodic", description="记忆类型：episodic(经历) / procedural(规则)")


class WriteMemoryInput(BaseModel):
    content: str = Field(description="要写入的记忆内容")
    memory_type: str = Field(default="episodic", description="记忆类型：episodic(经历) / procedural(规则)")


class UpdateMemoryInput(BaseModel):
    memory_id: str = Field(description="要改写的程序记忆 id")
    content: str = Field(description="改写后的规则内容")


class ForgetMemoryInput(BaseModel):
    memory_id: str = Field(description="要删除的记忆 id")
    memory_type: str = Field(default="procedural", description="记忆类型：episodic / procedural")


@inject
@dataclass
class MemoryTools:
    """记忆工具集构建器"""
    db: SQLAlchemy
    user_memory_service: UserMemoryService
    episodic_memory_service: EpisodicMemoryService
    procedural_memory_service: ProceduralMemoryService

    def get_tools(
            self,
            *,
            flask_app: Flask,
            app_id: UUID,
            user_id: UUID,
    ) -> list[BaseTool]:
        """构建四个记忆工具，闭包绑定 app_id/user_id 实现命名空间隔离"""

        @tool("search_memory", args_schema=SearchMemoryInput)
        def search_memory(query: str, memory_type: str = "episodic") -> str:
            """检索记忆：episodic 返回情景经历（向量召回），procedural 返回行为规则"""
            with flask_app.app_context():
                if memory_type == "procedural":
                    return self.procedural_memory_service.get_instructions(app_id, user_id)
                episodes = self.episodic_memory_service.search_episodes(
                    app_id, user_id, query, top_k=5,
                )
                if not episodes:
                    return "没有检索到相关的情景记忆"
                return "\n".join(f"- {e.content}" for e in episodes)

        @tool("write_memory", args_schema=WriteMemoryInput)
        def write_memory(content: str, memory_type: str = "episodic") -> str:
            """写入记忆：episodic 写入情景经历，procedural 写入/改写行为规则"""
            with flask_app.app_context():
                if memory_type == "procedural":
                    self.procedural_memory_service.upsert_instruction(
                        app_id, user_id, content, source="agent_tool",
                    )
                    return "行为规则已写入"
                self.episodic_memory_service.write_episode(
                    app_id=app_id, user_id=user_id,
                    content=content, importance=0.6, source="agent_tool",
                )
                return "情景记忆已写入"

        @tool("update_memory", args_schema=UpdateMemoryInput)
        def update_memory(memory_id: str, content: str) -> str:
            """改写程序记忆（行为规则/人设），新内容生效并版本+1"""
            with flask_app.app_context():
                self.procedural_memory_service.upsert_instruction(
                    app_id, user_id, content, source="agent_update",
                )
                # 旧规则软删除，避免同一规则多版本共存
                try:
                    self.procedural_memory_service.soft_delete(
                        app_id, user_id, UUID(memory_id),
                    )
                except Exception:
                    logger.warning("update_memory 旧规则删除失败：%s", memory_id)
                return "行为规则已更新"

        @tool("forget_memory", args_schema=ForgetMemoryInput)
        def forget_memory(memory_id: str, memory_type: str = "procedural") -> str:
            """删除记忆（软删除，保留审计）"""
            with flask_app.app_context():
                if memory_type == "procedural":
                    self.procedural_memory_service.soft_delete(
                        app_id, user_id, UUID(memory_id),
                    )
                    return "程序记忆已删除"
                # episodic：软删除 + 删除 Weaviate 向量（Task 18 后可扩展）
                from internal.model import EpisodicMemory
                record = self.db.session.get(EpisodicMemory, UUID(memory_id))
                if record and record.app_id == app_id and record.user_id == user_id:
                    self.db.session.delete(record)
                    self.db.session.commit()
                return "情景记忆已删除"

        return [search_memory, write_memory, update_memory, forget_memory]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/model/test_procedural_memory.py test/internal/core/tools/test_memory_tools.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add internal/model/procedural_memory.py internal/model/__init__.py internal/service/procedural_memory_service.py internal/core/tools/memory_tools.py internal/migrations/versions/ test/internal/model/test_procedural_memory.py test/internal/core/tools/test_memory_tools.py
git commit -m "feat: ProceduralMemory 模型与记忆工具集（search/write/update/forget_memory）"
```

---

### Task 21: 记忆工具注入 Agent + 程序记忆注入 System Prompt

**Files:**
- Modify: `internal/service/chat_runner.py`（注入记忆工具 + 程序记忆文本）
- Modify: `internal/core/agent/entities/agent_entity.py`（`build_system_prompt` 增加 `procedural_instructions` 参数）
- Modify: `internal/core/agent/agents/function_call_agent.py` / `react_agent.py`（消费 `state["procedural_instructions"]`）
- Test: `test/internal/service/test_chat_runner.py`（扩展）

**Interfaces:**
- Consumes: `MemoryTools.get_tools`（Task 20）、`ProceduralMemoryService.get_instructions`
- Produces: `ChatRunner.run` 在长期记忆开启时把 `MemoryTools.get_tools(...)` 追加到 `tools`；`build_system_prompt(..., procedural_instructions: str = "")` 渲染 `<行为规则>` 块；stream 输入新增 `"procedural_instructions"` 键

- [ ] **Step 1: 写失败测试**

扩展 `test/internal/service/test_chat_runner.py`：

```python
class TestChatRunnerProceduralMemory:
    def test_tools_injected_when_long_term_memory_enabled(self, app, monkeypatch):
        runner = injector.get(ChatRunner)
        account = MagicMock(id=uuid4())
        conversation = MagicMock(id=uuid4(), summary="")
        message = MagicMock(id=uuid4(), query="你好", image_urls=[])

        monkeypatch.setattr(runner.language_model_service, "load_language_model", lambda cfg: FakeLLM())
        monkeypatch.setattr(runner.app_config_service, "get_langchain_tools_by_tools_config", lambda cfg: [])
        monkeypatch.setattr(runner, "_build_history", lambda llm, conv, r: [])
        monkeypatch.setattr(runner.conversation_service, "compact_if_needed", lambda *a, **k: False)
        # 记忆服务：episodic 召回与抽取均为 no-op，避免真实连接 embedding/weaviate
        monkeypatch.setattr(
            runner.episodic_memory_service, "search_episodes",
            lambda app_id, user_id, query, **kw: [],
        )
        monkeypatch.setattr(runner, "_trigger_episodic_extraction", lambda **kwargs: None)
        monkeypatch.setattr(runner, "_trigger_memory_extraction", lambda **kwargs: None)

        captured = {}
        class CapturingAgent(FakeAgent):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                captured["agent_config"] = kwargs.get("agent_config")

            def stream(self, *args, **kwargs):
                captured["input"] = args[0] if args else kwargs.get("input")
                yield from super().stream(*args, **kwargs)

        monkeypatch.setattr("internal.service.chat_runner.FunctionCallAgent", CapturingAgent)
        monkeypatch.setattr(
            runner.procedural_memory_service, "get_instructions",
            lambda app_id, user_id: "回答用户时先给结论再给细节",
        )

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

        # 记忆工具已注入（MemoryTools.get_tools 返回 4 个工具）
        injected_names = {t.name for t in captured["agent_config"].tools}
        assert {"search_memory", "write_memory", "update_memory", "forget_memory"} <= injected_names
        # 程序记忆注入 system prompt
        assert "先给结论再给细节" in captured["input"].get("procedural_instructions", "")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_chat_runner.py::TestChatRunnerProceduralMemory -v`
Expected: FAIL（工具未注入 / 输入缺 `procedural_instructions`）

- [ ] **Step 3: 实现**

Modify `internal/core/agent/entities/agent_entity.py`：
- 两个模板末尾追加 `{procedural_instructions_block}` 占位
- `build_system_prompt` 基于 Task 19 的完整函数（含 `episodic_memory` 参数）增加 `procedural_instructions` 参数——替换为以下完整版本：

```python
def build_system_prompt(
        template: str,
        *,
        preset_prompt: str,
        long_term_memory: str = "",
        user_profile: str = "",
        episodic_memory: str = "",
        procedural_instructions: str = "",
        tool_description: str = "",
) -> str:
    """构建系统提示词：<长期记忆>/<用户画像>/<情景记忆>/<行为规则> 为空时整块省略"""
    long_term_memory_block = (
        f"\n<长期记忆>\n{long_term_memory}\n</长期记忆>\n"
        if long_term_memory else ""
    )
    user_profile_block = (
        f"\n<用户画像>\n{user_profile}\n</用户画像>\n"
        if user_profile else ""
    )
    episodic_memory_block = (
        f"\n<情景记忆>\n{episodic_memory}\n</情景记忆>\n"
        if episodic_memory else ""
    )
    procedural_instructions_block = (
        f"\n<行为规则>\n{procedural_instructions}\n</行为规则>\n"
        if procedural_instructions else ""
    )
    return template.format(
        preset_prompt=preset_prompt,
        long_term_memory_block=long_term_memory_block,
        user_profile_block=user_profile_block,
        episodic_memory_block=episodic_memory_block,
        procedural_instructions_block=procedural_instructions_block,
        tool_description=tool_description,
    )
```

（该版本替换 Task 19 中定义的 `build_system_prompt` 完整函数体，两个 Agent 的 `_long_term_memory_recall_node` 调用同步改为传 `procedural_instructions=state.get("procedural_instructions", "")`。）

Modify `internal/service/chat_runner.py`：
- dataclass 注入 `memory_tools: MemoryTools` 与 `procedural_memory_service: ProceduralMemoryService`
- `run` 中工具构建处（`skills` 之后）追加：

```python
        # 3.1、长期记忆开启时注入记忆工具（Agent 主动读写记忆）
        enable_memory = app_config.get("long_term_memory", {}).get("enable")
        if enable_memory:
            tools.extend(self.memory_tools.get_tools(
                flask_app=current_app._get_current_object(),
                app_id=conversation.app_id,
                user_id=account.id,
            ))
        # 3.2、程序记忆（行为规则/人设）渲染文本
        procedural_instructions = (
            self.procedural_memory_service.get_instructions(conversation.app_id, account.id)
            if enable_memory else ""
        )
```

- `run` 签名增加 `procedural_instructions: str = ""`；`_stream_and_persist` 签名增加 `procedural_instructions: str = ""` 参数，`run` 在调用处透传；`_stream_and_persist` 的 stream 输入增加 `"procedural_instructions": procedural_instructions`。

注意：`run` 调用 `_stream_and_persist` 时需同时透传 `episodic_memory`（Task 19）与 `procedural_instructions`（本任务）两个参数，二者均为默认空串。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_chat_runner.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 回归 + 提交**

Run: `pytest test/internal/service/ test/internal/core/agent/ -v`
Expected: 全部 PASS

```bash
git add internal/core/agent/entities/agent_entity.py internal/core/agent/agents/function_call_agent.py internal/core/agent/agents/react_agent.py internal/service/chat_runner.py test/internal/service/test_chat_runner.py
git commit -m "feat: 记忆工具注入 Agent + 程序记忆渲染进系统提示词"
```

---

### Task 22: 反馈反思改写（like/dislike 触发程序记忆更新）

**Files:**
- Modify: `internal/service/conversation_service.py`（`update_message_feedback` 触发反思线程）
- Create: `internal/service/reflection_service.py`
- Test: `test/internal/service/test_reflection_service.py`

**Interfaces:**
- Consumes: `ProceduralMemoryService.upsert_instruction`、`LanguageModelService`、`Message.feedback`（like/dislike）
- Produces:
  - `REFLECTION_TEMPLATE`（本文件内定义）
  - `ReflectionService(db, language_model_service, procedural_memory_service)`
  - `ReflectionService.reflect_on_feedback(*, flask_app, app_id, user_id, query, answer, feedback) -> None`：dislike 时 LLM 反思该轮对话，产出可改写的行为规则并 `upsert_instruction`
  - `ConversationService.update_message_feedback` 在 feedback 为 `dislike` 时启动子线程调用反思

- [ ] **Step 1: 写失败测试**

Create `test/internal/service/test_reflection_service.py`:

```python
#!/usr/bin/env python
"""反馈反思改写测试：dislike 触发程序记忆更新"""
from unittest.mock import MagicMock
from uuid import uuid4

from app.http.module import injector
from internal.model import ProceduralMemory
from internal.service import ReflectionService


class FakeReflectLLM:
    temperature = 0.0

    def __init__(self, reply):
        self.reply = reply

    def __call__(self, inputs):
        return self.reply


class TestReflection:
    def test_dislike_reflection_writes_instruction(self, app, db, monkeypatch):
        service = injector.get(ReflectionService)
        app_id, user_id = uuid4(), uuid4()

        raw = (
            '```json\n{"instruction": "回答用户时应先给结论，再展开细节，'
            '避免冗长铺垫"}\n```'
        )
        monkeypatch.setattr(
            service.language_model_service, "load_default_language_model",
            lambda: FakeReflectLLM(raw),
        )

        with app.app_context():
            service.reflect_on_feedback(
                flask_app=MagicMock(),
                app_id=app_id, user_id=user_id,
                query="请帮我分析这份报告",
                answer="（一段很长的铺垫后给出结论）",
                feedback="dislike",
            )

        records = db.session.query(ProceduralMemory).filter(
            ProceduralMemory.app_id == app_id,
            ProceduralMemory.user_id == user_id,
        ).all()
        assert len(records) == 1
        assert "先给结论" in records[0].content

    def test_like_does_not_reflect(self, app, db, monkeypatch):
        service = injector.get(ReflectionService)
        app_id, user_id = uuid4(), uuid4()
        fake_llm = FakeReflectLLM("{}")
        monkeypatch.setattr(
            service.language_model_service, "load_default_language_model",
            lambda: fake_llm,
        )

        with app.app_context():
            service.reflect_on_feedback(
                flask_app=MagicMock(),
                app_id=app_id, user_id=user_id,
                query="谢谢", answer="不客气", feedback="like",
            )

        records = db.session.query(ProceduralMemory).filter(
            ProceduralMemory.app_id == app_id,
            ProceduralMemory.user_id == user_id,
        ).all()
        assert len(records) == 0, "like 不应触发规则改写"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest test/internal/service/test_reflection_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'ReflectionService'`

- [ ] **Step 3: 实现**

Create `internal/service/reflection_service.py`：

```python
#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : reflection_service.py
"""
import json
import logging
import re
from dataclasses import dataclass
from uuid import UUID

from injector import inject
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from package.sqlalchemy import SQLAlchemy

from .base_service import BaseService
from .language_model_service import LanguageModelService
from .procedural_memory_service import ProceduralMemoryService

logger = logging.getLogger(__name__)

# 反思提示词：从负面反馈中提炼可改写的行为规则
REFLECTION_TEMPLATE = """你是一个 Agent 行为反思器。用户对以下回答点了"不喜欢"，请分析回答失败的原因，并产出一条可执行的改进规则（行为指令），供 Agent 下次遵循。

规则：
1. 只输出对 Agent 行为有指导意义的指令（如"先给结论再展开""回答控制在 3 条以内"）；
2. 指令要具体、可执行，不要泛泛而谈；
3. 如果无法提炼（如用户单纯情绪化），输出空对象；
4. 严禁把用户隐私/情绪写入规则。

用户问题：{query}
Agent 回答：{answer}
反馈：dislike

输出严格 JSON，不要输出其他内容：
{{"instruction": "..."}}"""


@inject
@dataclass
class ReflectionService(BaseService):
    """反馈反思服务：根据 dislike 反馈提炼并改写程序记忆"""
    db: SQLAlchemy
    language_model_service: LanguageModelService
    procedural_memory_service: ProceduralMemoryService

    def reflect_on_feedback(
            self,
            *,
            flask_app,
            app_id: UUID,
            user_id: UUID,
            query: str,
            answer: str,
            feedback: str,
    ) -> None:
        """根据反馈触发反思：dislike 时提炼行为规则写入程序记忆"""
        if feedback != "dislike":
            return
        with flask_app.app_context():
            try:
                prompt = ChatPromptTemplate.from_template(REFLECTION_TEMPLATE)
                llm = self.language_model_service.load_default_language_model()
                llm.temperature = 0
                chain = prompt | llm | StrOutputParser()
                raw = chain.invoke({"query": query, "answer": answer})

                instruction = self._parse_instruction(raw)
                if not instruction:
                    return
                self.procedural_memory_service.upsert_instruction(
                    app_id, user_id, instruction, source="feedback_reflection",
                )
            except Exception:
                logger.exception("反馈反思失败，app_id=%s, user_id=%s", app_id, user_id)

    def _parse_instruction(self, raw: str) -> str:
        """容错解析反思输出"""
        if not raw:
            return ""
        text = raw.strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return ""
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return ""
        return str(data.get("instruction", "")).strip()
```

Modify `internal/service/conversation_service.py` `update_message_feedback`（第 392-416 行）：在 `self.update(message, feedback=feedback)` 之后追加反馈反思触发：

```python
        # 4、更新消息反馈
        self.update(message, feedback=feedback)

        # 5、feedback 为 dislike 时，异步触发行为反思（程序记忆改写）
        if feedback == "dislike" and message.answer:
            flask_app = current_app._get_current_object()
            Thread(
                target=self._trigger_reflection,
                kwargs={
                    "flask_app": flask_app,
                    "app_id": message.app_id,
                    "user_id": message.created_by,
                    "query": message.query,
                    "answer": message.answer,
                },
            ).start()

        return message

    def _trigger_reflection(
            self,
            *,
            flask_app,
            app_id: UUID,
            user_id: UUID,
            query: str,
            answer: str,
    ) -> None:
        """子线程执行反馈反思（写程序记忆）"""
        with flask_app.app_context():
            self.reflection_service.reflect_on_feedback(
                flask_app=flask_app,
                app_id=app_id, user_id=user_id,
                query=query, answer=answer, feedback="dislike",
            )
```

（`ConversationService` dataclass 注入 `reflection_service: ReflectionService`，import `from .reflection_service import ReflectionService`；`Thread` 从 `threading` import。ReflectionService 不依赖 ConversationService，无循环依赖。）

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest test/internal/service/test_reflection_service.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 回归 + 提交**

Run: `pytest test/internal/service/ -v`
Expected: 全部 PASS

```bash
git add internal/service/reflection_service.py internal/service/conversation_service.py test/internal/service/test_reflection_service.py
git commit -m "feat: dislike 反馈触发反思，提炼并改写程序记忆"
```

---

## Phase 7：全量验证

### Task 23: 端到端回归验证

**Files:**
- Modify: 无（仅验证）
- Test: 全部测试

- [ ] **Step 1: 运行全量测试**

Run: `pytest test/ -v`
Expected: 全部 PASS（含既有用例，无回归）

- [ ] **Step 2: 启动服务冒烟验证**

Run（工作目录项目根）:
```powershell
$env:FLASK_APP="app.http.app"; flask run
```
Expected: 服务启动成功；`GET /ping` 返回 `{"pong": "success"}`；`GET /apps/<任意app_id>/memory/facts` 返回 200；`GET /apps/<任意app_id>/memory/facts/history` 返回 200

- [ ] **Step 3: 前端构建验证**

Run（工作目录 `ai-code-llmops-web`）: `npm run build`
Expected: 构建成功

- [ ] **Step 4: 提交（如有遗留改动）**

```bash
git add -A
git commit -m "chore: memory system v1 全量验证"
```

---

## 后续计划（不在本计划内）

1. **记忆管理 UI**：用户可见/可删的记忆卡片面板（语义/情景/程序三类）+ 投毒举报通道
2. **记忆评测**：召回命中率、注入增益、token 成本基线（情景记忆 RRF 权重调参依赖该评测）
3. **记忆工具审计**：Agent 每次 search/write/update/forget_memory 的审计日志与可视化
4. **反思循环升级**：定时/触发式反思（不只依赖 dislike 反馈），对比目标与行为持续改写程序记忆
5. **情景记忆去重合并**：检索到高度相似经历时合并，控制向量集合膨胀
