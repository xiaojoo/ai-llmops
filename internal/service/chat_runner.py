#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : chat_runner.py
"""
import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from internal.config.settings import get_settings
from internal.core.agent.agents import (
    AgentQueueManager,
    FunctionCallAgent,
    GuardedOrchestratorAgent,
    OrchestratorAgent,
    ReACTAgent,
)
from internal.core.agent.entities.agent_entity import AgentConfig, create_ask_user_tool
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.agent.checkpoint import get_checkpoint_store
from internal.core.agent.run_context import RunContext
from internal.core.telemetry import current_trace_id, current_traceparent
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.entity.conversation_entity import InvokeFrom
from internal.entity.dataset_entity import RetrievalSource
from internal.exception import ForbiddenException, ValidateException
from internal.memory.token_buffer_memory import TokenBufferMemory
from internal.model import Account, AgentRun, App, Conversation, Message

from .base_service import BaseService
from .app_config_service import AppConfigService
from .event_replay import run_event_log
from .conversation_service import ConversationService
from .language_model_service import LanguageModelService

# 后台记忆写任务句柄集合——fire-and-forget 的 create_task 需持有引用防 GC；
# 记忆写侧（LLM 抽取可耗时 60s+）绝不能阻塞 SSE 流结束。
_BG_MEMORY_TASKS: set[asyncio.Task] = set()
# 断开接管任务的句柄集合，同理防 GC。
_BG_TAKEOVER_TASKS: set[asyncio.Task] = set()

# 会让队列收尾的那批事件（与 AgentQueueManager.publish 里 put(None) 的判定保持一致）。
# 接管者据此决定何时停：读到这些就说明 run 已经跑完了。
_TERMINAL_QUEUE_EVENTS = frozenset({
    QueueEvent.AGENT_END, QueueEvent.STOP, QueueEvent.ERROR, QueueEvent.TIMEOUT,
})
from .memory_provider import MemoryProvider, MemoryProviderResolver
from .retrieval_service import RetrievalService

logger = logging.getLogger(__name__)

# 编排引擎取值清单（报错文案与配置提示用）。加新引擎要同时加进 _orchestrator_engines。
ORCHESTRATOR_ENGINE_NAMES = ("subtask", "guarded")


def _orchestrator_engines() -> dict[str, type]:
    """引擎名 → 类。

    故意在函数体内构造而不是模块级字典：模块级会在 import 时就把类固化，
    monkeypatch chat_runner.OrchestratorAgent 的测试（以及运行期换实现的场景）会静默失效。
    """
    return {
        "subtask": OrchestratorAgent,         # 默认：自判断拆分 + 依赖 DAG 调度 + 失败自动重规划
        "guarded": GuardedOrchestratorAgent,  # 同上，外加 token/花费/墙钟/子任务数预算熔断
    }


def _resolve_orchestrator_class(orchestrator_cfg: dict[str, Any]) -> type:
    """选编排引擎：应用配置 engine 优先，其次系统设置的全局默认 ORCHESTRATOR_ENGINE。

    取值不认识时回落 subtask 并记 warning：配错不该让整轮对话失败，但也不能静默——
    否则用户以为开着预算护栏，实际跑的是不限流的默认引擎。
    """
    engines = _orchestrator_engines()
    engine = str(
        orchestrator_cfg.get("engine") or os.getenv("ORCHESTRATOR_ENGINE") or "subtask"
    ).strip().lower()
    cls = engines.get(engine)
    if cls is None:
        logger.warning(
            "未知编排引擎 %r，回落 subtask（可选值：%s）",
            engine, " / ".join(ORCHESTRATOR_ENGINE_NAMES),
        )
        cls = engines["subtask"]
    return cls


# 与 agent_queue_manager._QUIET_STREAM_EVENTS 语义一致：sse-write 定位日志忽略高频流式事件。
# AGENT_MESSAGE 例外：每个 stream_id 只记"首帧"（first_of_id），一答一行，用于观察
# ask_user 之后模型是否仍有内容写出。
_QUIET_SSE_EVENTS = frozenset({
    QueueEvent.PING,
    QueueEvent.AGENT_MESSAGE,
    QueueEvent.AGENT_THOUGHT,
})


def _app_has_filesystem_tool(app_config: dict[str, Any]) -> bool:
    """判断应用是否在配置中绑定了 filesystem 工具包。

    Agent 模式的工作区工具（文件系统 + shell 命令）仅在应用显式绑定
    filesystem 工具包后才注入——能力来源必须由应用配置授权。
    """
    from internal.core.tools.workspace_tools import bound_filesystem_tool_names

    return bool(bound_filesystem_tool_names(app_config))


def _hint_sse(hint: str, conversation: Conversation, message: Message) -> str:
    """构造一条提示消息 + 结束事件（SSE 字符串），用于应用未绑定工具等前置提示。"""
    from package.response import sse_format

    task_id = uuid4()
    cid = str(conversation.id)
    mid = str(message.id)
    msg_data = {
        "event": QueueEvent.AGENT_MESSAGE.value,
        "thought": hint,
        "answer": hint,
        "observation": "",
        "tool": "",
        "tool_input": {},
        "id": str(uuid4()),
        "conversation_id": cid,
        "message_id": mid,
        "task_id": str(task_id),
    }
    end_data = {
        "event": QueueEvent.AGENT_END.value,
        "id": str(uuid4()),
        "conversation_id": cid,
        "message_id": mid,
        "task_id": str(task_id),
    }
    return sse_format(QueueEvent.AGENT_MESSAGE.value, msg_data, 1) + \
        sse_format(QueueEvent.AGENT_END.value, end_data, 2)


async def _aiter_sync(gen):
    """同步生成器 → 异步迭代器桥接（每个元素经线程池 next()，事件循环不阻塞）。

    agent.stream 仍为同步生成器（agent 在子线程中运行，内部已起图线程 + Redis 队列监听，
    逐事件阻塞等待）；把阻塞的 next() 放到线程池，async 侧按原顺序收到元素。StopIteration
    用哨兵跨线程传递（StopIteration 穿越 await/线程池边界会被 Python 转成 RuntimeError）。

    客户端断开（StreamingResponse 被取消 → async generator aclose → GeneratorExit
    在 await 点抛出）时，finally 关闭底层同步生成器——agent 内部 listen() 的
    queue.get(timeout=1) 阻塞循环会因 GeneratorExit 在 1s 内退出，避免线程池 worker 与
    图线程悬挂至监听超时（600s）。
    """
    _SENTINEL = object()

    def _next():
        try:
            return next(gen)
        except StopIteration:
            return _SENTINEL

    try:
        while True:
            item = await run_in_threadpool(_next)
            if item is _SENTINEL:
                break
            yield item
    finally:
        # 客户端断开/提前退出：关闭底层同步生成器，中断其内部阻塞监听（图线程可退出）
        try:
            gen.close()
        except Exception:
            pass


def agent_thought_to_sse_frame(
        agent_thought: AgentThought,
        conversation_id: str,
        message_id: str,
        run_id: UUID | None,
        seq: int,
) -> str:
    """把 AgentThought 序列化为 SSE 帧；真实流与续传端点共用，保证两端序列化完全一致。

    与 _stream_and_persist 的帧结构（data 字段并集、id/事件/序号）保持一致。
    """
    from package.response import sse_format

    data = {
        **agent_thought.model_dump(include={
            "event", "thought", "observation", "tool", "tool_input", "answer", "latency",
            "total_token_count", "total_price", "sub_task_id", "sub_task_title", "trace",
            "question", "options", "allow_custom", "choice", "sub_task_options",
            "model_name", "llm_output", "tool_calls", "tool_call_id", "trace_id",
        }),
        "id": str(agent_thought.id),
        "conversation_id": conversation_id,
        "message_id": message_id,
        "task_id": str(agent_thought.task_id),
        "run_id": str(run_id) if run_id is not None else str(agent_thought.task_id),
    }
    return sse_format(agent_thought.event.value, data, seq)


def merge_agent_thought(store: dict[str, AgentThought], agent_thought: AgentThought) -> bool:
    """按事件 id 把一条流式事件归并成"待落库形态"，返回该 id 是否首次出现。

    同一 id 的 AGENT_MESSAGE 是增量 chunk，要累加 thought/answer 再带上最后一条的统计；
    其余事件按 id 覆盖；PING 不入库。真实流（_stream_and_persist）与断流续传落库共用这一份，
    两处各写一遍会让库里的推理过程与 SSE 帧形态漂移。
    """
    event_id = str(agent_thought.id)
    first_of_id = event_id not in store
    if agent_thought.event == QueueEvent.PING:
        return first_of_id
    prev = store.get(event_id)
    if agent_thought.event == QueueEvent.AGENT_MESSAGE and prev is not None:
        store[event_id] = prev.model_copy(update={
            "thought": prev.thought + agent_thought.thought,
            "message": agent_thought.message,
            "message_token_count": agent_thought.message_token_count,
            "message_unit_price": agent_thought.message_unit_price,
            "message_price_unit": agent_thought.message_price_unit,
            "answer_token_count": agent_thought.answer_token_count,
            "answer_unit_price": agent_thought.answer_unit_price,
            "answer_price_unit": agent_thought.answer_price_unit,
            "total_token_count": agent_thought.total_token_count,
            "total_price": agent_thought.total_price,
            "answer": prev.answer + agent_thought.answer,
            "latency": agent_thought.latency,
            "llm_output": agent_thought.llm_output or prev.llm_output,
            "model_name": agent_thought.model_name or prev.model_name,
            "reasoning_content": agent_thought.reasoning_content or prev.reasoning_content,
        })
    else:
        store[event_id] = agent_thought
    return first_of_id


@dataclass
class ChatRunner(BaseService):
    """统一 Agent 对话执行器：从 debug_chat / web_app_chat 抽取的公共推理链路

    `run()` 为 async generator，产出 SSE 事件字符串。
    """
    db: AsyncSession
    retrieval_service: RetrievalService
    app_config_service: AppConfigService
    conversation_service: ConversationService
    language_model_service: LanguageModelService
    memory_provider_resolver: MemoryProviderResolver

    async def run(
            self,
            *,
            app: App,
            app_config: dict[str, Any],
            conversation: Conversation,
            message: Message,
            account: Account,
            invoke_from: InvokeFrom,
            user_profile: str = "",
            episodic_memory: str = "",
            procedural_instructions: str = "",
            mode: str = "auto",
            project_root: str = "",
            local_tool_runtime: bool = False,
    ) -> AsyncGenerator[str, None]:
        """根据配置构建 Agent 并流式推理，产出 SSE 事件字符串（async generator）

        mode=agent 且 project_root 为存在的目录时，额外注入绑定该工作区的
        filesystem + shell 工具（Agent 可独立完成代码编写/测试）。
        """
        # 1、加载大语言模型（custom_api 按账号懒合并需 account_id，否则用户自选模型无法加载）
        llm = await self.language_model_service.load_language_model(
            app_config.get("model_config", {}), account_id=account.id
        )

        # 2、短期记忆：窗口快满时先惰性压缩（归档最旧轮次并入滚动摘要）
        await self.conversation_service.compact_if_needed(conversation.id, llm)
        # 会话级短期记忆覆盖：conversation.dialog_round 非空时优先，否则用应用配置
        effective_dialog_round = (
            conversation.dialog_round
            if conversation.dialog_round is not None
            else app_config["dialog_round"]
        )
        history = await self._build_history(llm, conversation, effective_dialog_round)

        # 2.0、解析记忆系统 Provider（应用覆盖 > 系统默认 > builtin）
        memory_provider = await self.memory_provider_resolver.resolve(app_config)
        # 长期记忆总开关：enable=false 时读写都不生效（记忆功能整体关闭）
        enable_memory = app_config.get("long_term_memory", {}).get("enable")

        # 2.1、情景记忆：长期记忆开启时，对话前按当前提问召回 top-k 经历
        read_ctx = None
        if enable_memory and not episodic_memory:
            try:
                read_ctx = await memory_provider.get_read_context(
                    app_config, conversation.app_id, account.id, message.query,
                )
                episodic_memory = read_ctx.episodic_memory
            except Exception:
                logger.exception("情景记忆召回失败")

        # 3、构建工具列表：插件/知识库/工作流/技能（按 account 二次校验归属）
        tools = await self.app_config_service.get_langchain_tools_by_tools_config(
            app_config["tools"], account_id=account.id
        )
        if app_config["datasets"]:
            dataset_tool = await self.retrieval_service.create_langchain_tool_from_search(
                dataset_ids=[d["id"] for d in app_config["datasets"]],
                account_id=account.id,
                retrieval_score=RetrievalSource.APP,
                **app_config["retrieval_config"],
            )
            tools.append(dataset_tool)
        if app_config["workflows"]:
            tools.extend(await self.app_config_service.get_langchain_tools_by_workflow_ids(
                [w["id"] for w in app_config["workflows"]], account_id=account.id
            ))
        if app_config["skills"]:
            tools.extend(await self.app_config_service.get_langchain_tools_by_skill_ids(
                [s["id"] for s in app_config["skills"]], account_id=account.id
            ))

        # 3.1、长期记忆开启时注入记忆工具（Agent 主动读写记忆）
        if enable_memory:
            tools.extend(await memory_provider.get_memory_tools(
                app_config, conversation.app_id, account.id,
            ))
        # 3.2、程序记忆（行为规则/人设）渲染文本
        if enable_memory:
            if read_ctx is None:
                try:
                    read_ctx = await memory_provider.get_read_context(
                        app_config, conversation.app_id, account.id, message.query,
                    )
                except Exception:
                    logger.exception("程序记忆读取失败")
            procedural_instructions = read_ctx.procedural_instructions if read_ctx else ""

        # 3.3、Agent 模式(智能体)：注入绑定请求工作区的 filesystem + shell 工具，
        # 使 Agent 能独立完成代码编写/测试；Chat 模式或无工作区则保持纯聊天。
        # 仅当应用在配置中绑定了 filesystem 工具包时才注入——未绑定则提示用户，
        # 避免 Agent 拿到能力却操作不了（能力来源必须由应用显式授权）。
        #
        # local_tool_runtime=True 时：这类文件/命令工具不服务器执行，改为注入"本地工具桩"
        # （全部文件类工具：fs_list/fs_stat/fs_read/fs_write/fs_edit/fs_mkdir/fs_copy/
        #   fs_move/fs_delete/fs_search），由插件进程对用户真实本地工作区执行。桩工具与服务器
        # 工具同名会冲突，故先剔除服务器端文件/命令工具，再注入本地桩。
        from internal.core.tools.workspace_tools import (
            bound_filesystem_tool_names,
            build_local_tool_stubs,
            build_workspace_tools,
            should_strip_server_tool,
        )

        if mode == "agent" and local_tool_runtime:
            # 本地工具运行时：文件能力（尤其写入）随应用绑定授权，绝不写死。
            # 先从应用配置取实际绑定的 filesystem 工具名集合，按"读/写"绑定决定注入哪些桩。
            bound_fs = bound_filesystem_tool_names(app_config)
            if not bound_fs:
                hint = (
                    "当前应用未绑定文件系统工具包（filesystem），Agent 模式无法操作"
                    "工作区文件。请先在应用配置的『扩展插件』中添加 filesystem 工具包"
                    "（可读/写工作区文件），再使用 Agent 模式。"
                )
                logger.info("Agent 模式跳过本地文件工具注入：应用未绑定 filesystem 工具 (app=%s)", app.id)
                yield _hint_sse(hint, conversation, message)
                return
            # 剔除服务器端 fs_*/shell_run 工具，仅注入应用实际绑定的本地文件工具桩
            tools = [t for t in tools if not should_strip_server_tool(getattr(t, "name", ""))]
            local_stubs = build_local_tool_stubs(bound_fs)
            logger.info(
                "Agent 模式注入本地工具桩: %d 个 (local_tool_runtime, 绑定=%s)",
                len(local_stubs), sorted(bound_fs),
            )
            tools.extend(local_stubs)
        elif mode == "agent" and project_root:
            if not _app_has_filesystem_tool(app_config):
                hint = (
                    "当前应用未绑定文件系统工具包（filesystem），Agent 模式无法操作"
                    "工作区文件或执行命令。请先在应用配置中添加 filesystem 工具包，"
                    "再使用 Agent 模式。"
                )
                logger.info("Agent 模式跳过工作区工具注入：应用未绑定 filesystem 工具 (app=%s)", app.id)
                yield _hint_sse(hint, conversation, message)
                return
            workspace_tools = build_workspace_tools(project_root)
            if workspace_tools:
                logger.info(
                    "Agent 模式注入工作区工具: %d 个 (workspace=%s)",
                    len(workspace_tools), project_root,
                )
                tools.extend(workspace_tools)

        # 4、根据应用配置与 LLM 能力决定 Agent 类型
        orchestrator_cfg = app_config.get("orchestrator_config") or {}
        # 任务编排开启即用自判断编排器（不再按 app_type 写死）：编排引擎的 plan 节点
        # 让 LLM 自行判断——复杂任务拆分子任务执行，简单任务返回空子任务走 direct_answer 直接回答。
        # 用哪个引擎由 engine / 系统设置 ORCHESTRATOR_ENGINE 决定（默认 subtask = 原 OrchestratorAgent，
        # 未配置时行为与改动前完全一致）。
        if orchestrator_cfg.get("enable"):
            agent_class = _resolve_orchestrator_class(orchestrator_cfg)
        elif ModelFeature.TOOL_CALL in llm.features:
            agent_class = FunctionCallAgent
        else:
            agent_class = ReACTAgent

        # 4.1、Chat 模式（纯聊天，无工作区工具）能力边界约束：
        # 当前请求未注入文件系统/命令执行工具，LLM 必须诚实告知"无法执行"，
        # 不得编造"已运行/已创建/已安装"等结果，并引导用户切换 Agent 模式。
        preset_prompt = app_config["preset_prompt"] or ""
        if mode != "agent":
            preset_prompt = (
                f"{preset_prompt}\n\n"
                "【当前模式约束】你正处于 Chat 模式（纯聊天），没有文件系统与命令执行能力，"
                "无法读写文件、创建/修改文件、安装依赖或执行任何命令。"
                "如果用户要求执行命令、运行脚本、创建/修改文件、安装软件包等操作，"
                "你必须明确说明：当前 Chat 模式无法执行这些操作，请切换到 Agent 模式后再尝试；"
                "绝对不要编造'已运行/已启动/已创建/已安装/执行成功'等结果。"
            ).strip()

        # 注入 ask_user 交互工具：仅工具调用型模型（FunctionCallAgent 及编排器子任务）
        # ReACTAgent（非 TOOL_CALL）不注入，行为与现状完全一致
        if ModelFeature.TOOL_CALL in llm.features:
            tools.append(create_ask_user_tool())

        # 去重：同名工具（如 fs_* 同时来自应用配置与工作区注入）会导致
        # API "Tool names must be unique" 400。这里按工具名保留最后一个，
        # 使注入的"绑定选定工作区"工具覆盖应用配置里的静态/默认工作区工具。
        seen: set[str] = set()
        deduped: list = []
        for tool in reversed(tools):
            name = getattr(tool, "name", "")
            if not name or name in seen:
                continue
            seen.add(name)
            deduped.append(tool)
        deduped.reverse()
        tools = deduped

        run_id = uuid4()
        checkpoint_store = get_checkpoint_store()
        checkpoint_thread_id = await self._resolve_checkpoint_thread_id(message, conversation, account)
        if checkpoint_store is not None and getattr(message, "resume_trigger", False) is not True:
            checkpoint_store.delete_thread(checkpoint_thread_id)
        run_context = RunContext(
            run_id=run_id,
            task_id=run_id,
            thread_id=checkpoint_thread_id,
            trace_id=current_trace_id(),
            traceparent=current_traceparent(),
        )

        agent = agent_class(
            name="debug-agent",
            llm=llm,
            agent_config=AgentConfig(
                user_id=account.id,
                invoke_from=invoke_from,
                max_iteration_count=app_config.get("max_iteration_count", 30),
                preset_prompt=preset_prompt,
                enable_long_term_memory=app_config["long_term_memory"]["enable"],
                tools=tools,
                review_config=app_config["review_config"],
                orchestrator_config=orchestrator_cfg,
                local_tool_runtime=local_tool_runtime,
            ),
            checkpointer=checkpoint_store.saver if checkpoint_store is not None else None,
            run_context=run_context,
        )

        # 5、流式推理 + 事件序列化 + 异常兜底 + 落库
        # 进入 Agent 循环前先提交请求会话的读事务——LLM 调用与 ask_user 等待可能长达
        # 数分钟，期间读事务空闲会触发 idle_in_transaction_session_timeout（60s）被 PG 终止，
        # 后续 save_agent_thoughts commit 抛 "connection is closed"。
        # expire_on_commit=False 下 message/conversation 对象仍可用。
        await self.db.commit()
        # 顶层 run_id = 本次会话推理的唯一标识（编排器下即"父任务"task_id）。
        # 用于：插件"主动停止"按钮 — 停止该 run_id 会经编排器 monitor_stop 级联中止所有子任务；
        # 与工具结果回传用的 task_id（可能是子任务 id）区分开。
        # run 实体落库：run_id / message / conversation / account 关系 + version（防丢、审计、
        # message.status 投影的权威来源）。失败仅记日志，绝不阻断对话主链路。
        await self._record_run_start(
            run_id=run_id,
            app=app,
            conversation=conversation,
            message=message,
            account=account,
            invoke_from=invoke_from,
            agent_type=type(agent).__name__,
        )
        async for event in self._stream_and_persist(
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
            episodic_memory=episodic_memory,
            procedural_instructions=procedural_instructions,
            memory_provider=memory_provider,
            run_id=run_id,
        ):
            yield event

    async def _resolve_checkpoint_thread_id(
        self,
        message: Message,
        conversation: Conversation,
        account: Account,
    ) -> str:
        resume_message_id = getattr(message, "resume_message_id", None)
        if getattr(message, "resume_trigger", False) is not True:
            return str(message.id)
        if not resume_message_id:
            raise ValidateException("断点续跑必须提供 resume_message_id")
        original = await self.db.get(Message, resume_message_id)
        if (
            original is None
            or original.conversation_id != conversation.id
            or original.created_by != account.id
        ):
            raise ForbiddenException("断点消息不存在或不属于当前会话/用户")
        return str(original.id)

    async def _record_run_start(
            self,
            *,
            run_id: UUID,
            app: App,
            conversation: Conversation,
            message: Message,
            account: Account,
            invoke_from: InvokeFrom,
            agent_type: str,
    ) -> None:
        """写入 run 行（running）。任何失败仅记日志——run 是增强记录，不阻断对话。"""
        try:
            from internal.service.run_service import RunService
            from internal.entity.conversation_entity import RunStatus

            await RunService(db=self.db).start_run(
                run_id=run_id,
                message_id=message.id,
                conversation_id=conversation.id,
                app_id=app.id,
                account_id=account.id,
                invoke_from=invoke_from,
                agent_type=agent_type,
                resume_trigger=getattr(message, "resume_trigger", False) is True,
            )
        except Exception:
            logger.exception("记录 run 开始失败 run_id=%s（不影响对话）", run_id)

    async def _record_run_finish(
            self,
            *,
            run_id: UUID,
            terminal_status: str,
            error: str = "",
            total_token_count: int = 0,
            total_price: float = 0.0,
            latency: float = 0.0,
    ) -> None:
        """run 终结落库 + message.status 投影（终态由调用方判定）。失败仅记日志。"""
        try:
            from internal.service.run_service import RunService
            from internal.entity.conversation_entity import RunStatus

            await RunService(db=self.db).finish_run(
                run_id,
                status=RunStatus(terminal_status),
                error=error,
                total_token_count=total_token_count,
                total_price=total_price,
                latency=latency,
            )
        except Exception:
            logger.exception("记录 run 终结失败 run_id=%s（不影响对话）", run_id)

    async def persist_resumed_run(
            self,
            *,
            run: AgentRun,
            thoughts: list[AgentThought],
            account: Account,
    ) -> None:
        """断流续传的收尾落库：把"断开前已发出 + 断开后新产生"的事件写库并终结 run。

        为什么必须由续传侧做：客户端断开时原流拿到 GeneratorExit，其 finally 里的 await
        在解绕过程中不会完成——真机实测重连把 29340 字送到了客户端，而 message_agent_thought
        仍是 0 行、message.answer 为空、run 永远停在 running。续传请求自己的 DB 会话在
        整段流期间是活的，所以由它补上这一次落库。

        thoughts 为空时直接返回：二次重连时缓冲已被上一次续传清空、队列也已耗尽，
        而 save_agent_thoughts 是纯 INSERT，再跑一次会长出重复的推理过程行。
        """
        if not thoughts:
            return
        if not run_event_log.claim_persist(str(run.id)):
            logger.info("[sse-resume] 落库已被接管者认领，跳过 run=%s", run.id)
            return
        app = await self.db.get(App, run.app_id)
        if app is None:
            logger.warning("续传落库跳过：应用不存在 run=%s app=%s", run.id, run.app_id)
            return
        try:
            app_config = await self.app_config_service.get_app_config(app)
        except Exception:
            logger.exception("续传落库跳过：读取应用配置失败 run=%s", run.id)
            return
        try:
            await self.conversation_service.save_agent_thoughts(
                account_id=account.id,
                app_id=run.app_id,
                app_config=app_config,
                conversation_id=run.conversation_id,
                message_id=run.message_id,
                agent_thoughts=thoughts,
                invoke_from=InvokeFrom(run.invoke_from),
            )
        except Exception:
            logger.exception("续传落库失败 run=%s message=%s", run.id, run.message_id)
            return

        terminal, err = self._derive_run_terminal(thoughts)
        await self._record_run_finish(
            run_id=run.id,
            terminal_status=terminal,
            error=err,
            total_token_count=sum(t.total_token_count or 0 for t in thoughts),
            total_price=sum(t.total_price or 0 for t in thoughts),
            latency=sum(t.latency or 0 for t in thoughts),
        )
        logger.info(
            "[sse-resume] 落库完成 run=%s 事件=%d 终态=%s",
            run.id, len(thoughts), terminal,
        )

    def _start_takeover(
            self,
            *,
            run_id: UUID | None,
            store: dict,
            seq: int,
            app: App,
            app_config: dict[str, Any],
            conversation: Conversation,
            message: Message,
            account: Account,
            invoke_from: InvokeFrom,
    ) -> None:
        """客户端断开后派一个脱离本请求的接管者去读完队列、落库、终结 run。

        必须用 create_task 而不是 await：调用点正处在 async generator 的 GeneratorExit
        解绕中，那里 await 任何东西都不会再被恢复——断开路径的 finally 落不了库就是这个原因。
        """
        if run_id is None:
            return
        try:
            task = asyncio.create_task(self._take_over_run(
                run_id=run_id, store=store, seq=seq, app=app, app_config=app_config,
                conversation=conversation, message=message, account=account,
                invoke_from=invoke_from,
            ))
        except RuntimeError:
            # 不在事件循环里（同步上下文调用）：放弃接管，行为退回改动前而不是把请求打崩
            logger.warning("无法启动断开接管：当前无运行中的事件循环 run=%s", run_id)
            return
        _BG_TAKEOVER_TASKS.add(task)
        task.add_done_callback(_BG_TAKEOVER_TASKS.discard)

    async def _take_over_run(
            self,
            *,
            run_id: UUID,
            store: dict,
            seq: int,
            app: App,
            app_config: dict[str, Any],
            conversation: Conversation,
            message: Message,
            account: Account,
            invoke_from: InvokeFrom,
    ) -> None:
        """接管循环：独占队列继续读，逐条写入事件日志，见到终态事件就收尾。

        为什么这里能独占队列：原读者（SSE 生成器）已经因断开而退出，同一时刻只有一个
        读者才不会出现"两个消费者各抢一半事件"。重连的客户端因此改成只读事件日志，不再碰队列。
        """
        run_id_s = str(run_id)
        manager = AgentQueueManager(user_id=account.id, invoke_from=invoke_from, model_name="")
        seen = seq
        logger.info(
            "[sse-takeover] 接管开始 run=%s 已发到 seq=%d 已收集事件=%d",
            run_id, seq, len(store),
        )
        try:
            async for at in _aiter_sync(manager.listen(run_id)):
                if at is None:
                    break
                seen += 1
                merge_agent_thought(store, at)
                frame = agent_thought_to_sse_frame(
                    at, str(conversation.id), str(message.id), run_id, seen,
                )
                run_event_log.record(run_id_s, seen, frame, at)
                if at.event in _TERMINAL_QUEUE_EVENTS:
                    break
        except Exception:
            logger.exception("[sse-takeover] 读队列异常 run=%s", run_id)
        finally:
            await self._persist_detached(
                run_id=run_id, thoughts=list(store.values()), app=app, app_config=app_config,
                conversation=conversation, message=message, account=account,
                invoke_from=invoke_from,
            )
            run_event_log.clear(run_id_s)
            logger.info("[sse-takeover] 接管结束 run=%s 累计事件=%d", run_id, len(store))

    async def _persist_detached(
            self,
            *,
            run_id: UUID,
            thoughts: list[AgentThought],
            app: App,
            app_config: dict[str, Any],
            conversation: Conversation,
            message: Message,
            account: Account,
            invoke_from: InvokeFrom,
    ) -> None:
        """接管者落库：必须自带会话——请求的 AsyncSession 已随响应结束而关闭。

        worker_run 起独立事件循环 + 独立 engine（与编排器子任务线程同源）；直接
        await self.conversation_service 会撞上 "connection is closed"。
        """
        if not thoughts:
            return
        if not run_event_log.claim_persist(str(run_id)):
            logger.info("[sse-takeover] 落库已被重连端点认领，跳过 run=%s", run_id)
            return
        from package.database import build_engine, worker_run

        from internal.container import create_conversation_service
        from internal.entity.conversation_entity import RunStatus
        from internal.service.run_service import RunService

        terminal, err = self._derive_run_terminal(thoughts)
        total_tokens = sum(t.total_token_count or 0 for t in thoughts)
        total_price = sum(t.total_price or 0 for t in thoughts)
        latency = sum(t.latency or 0 for t in thoughts)

        def _work(session: AsyncSession):
            async def _run():
                await create_conversation_service(session).save_agent_thoughts(
                    account_id=account.id, app_id=app.id, app_config=app_config,
                    conversation_id=conversation.id, message_id=message.id,
                    agent_thoughts=thoughts, invoke_from=invoke_from,
                )
                await RunService(db=session).finish_run(
                    run_id, status=RunStatus(terminal), error=err,
                    total_token_count=total_tokens, total_price=total_price, latency=latency,
                )
            return _run()

        try:
            await asyncio.to_thread(lambda: worker_run(_work, engine_factory=build_engine))
            logger.info(
                "[sse-takeover] 落库完成 run=%s 事件=%d 终态=%s", run_id, len(thoughts), terminal,
            )
        except Exception:
            logger.exception("[sse-takeover] 落库失败 run=%s message=%s", run_id, message.id)

    @staticmethod
    def _derive_run_terminal(all_thoughts: list) -> tuple[str, str]:
        """从终态事件推导 run 终态。

        判定优先级：ERROR（图异常）> TIMEOUT（超时）> STOP（用户停止）> 默认 succeeded。
        """
        from internal.entity.conversation_entity import RunStatus

        for t in all_thoughts:
            if t.event == QueueEvent.ERROR:
                return RunStatus.FAILED.value, (t.observation or "推理过程发生异常")
        for t in all_thoughts:
            if t.event == QueueEvent.TIMEOUT:
                return RunStatus.TIMED_OUT.value, (t.observation or "")
        for t in all_thoughts:
            if t.event == QueueEvent.STOP:
                return RunStatus.CANCELLED.value, (t.observation or "")
        return RunStatus.SUCCEEDED.value, ""

    async def _build_history(self, llm: BaseLanguageModel, conversation: Conversation, dialog_round: int) -> list:
        """构建短期记忆历史消息（窗口内原文，未归档消息）"""
        token_buffer_memory = TokenBufferMemory(db=self.db, conversation=conversation, model_instance=llm)
        return await token_buffer_memory.get_history_prompt_messages(message_limit=dialog_round)

    async def _stream_and_persist(
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
            episodic_memory: str = "",
            procedural_instructions: str = "",
            memory_provider: MemoryProvider | None = None,
            run_id: UUID | None = None,
    ) -> AsyncGenerator[str, None]:
        """流式推理（async generator），将 AgentThought 序列化为 SSE；异常兜底；finally 落库"""
        from package.response import sse_format

        agent_thoughts = {}
        error_event = None
        client_disconnected = False
        seq = 0
        logger.info("[sse-write] 开始流 run=%s task=%s conv=%s message=%s",
                    run_id, run_id, conversation.id, message.id)
        try:
            # 附件文本注入：附件内容拼接到提问中，使模型可以读取文件内容
            llm_query = message.query
            attachment_text = getattr(message, "attachment_text", "")
            if attachment_text:
                llm_query = f"{message.query}\n\n[附件内容]\n{attachment_text}"
            async for agent_thought in _aiter_sync(agent.stream({
                "messages": [llm.convert_to_human_message(llm_query, message.image_urls)],
                "history": history,
                "long_term_memory": conversation.summary if conversation.summary else "",
                "user_profile": user_profile,
                "episodic_memory": episodic_memory,
                "procedural_instructions": procedural_instructions,
                "conversation_id": conversation.id,
                "app_id": app.id,
                "message_id": message.id,
                # 编排型 Agent 从 query 重建人类消息，需传富化后的 query（含附件内容）
                "query": llm_query,
                "resume": getattr(message, "resume_trigger", False) is True and not isinstance(agent, OrchestratorAgent),
                "resume_trigger": getattr(message, "resume_trigger", False) is True,
                # 断点续跑时原始消息 id（断点按 message_id 定位；编排器用它读/写断点）
                "resume_message_id": getattr(message, "resume_message_id", None),
                # 顶层 task_id 固定为本次 run_id（编排器下即父任务 id），保证 SSE run_id 稳定、可停止
                "task_id": run_id,
            })):
                first_of_id = merge_agent_thought(agent_thoughts, agent_thought)
                seq += 1
                # 统一走帧封装（真实流 + 续传端点共用），保证两端序列化完全一致。
                _frame = agent_thought_to_sse_frame(
                    agent_thought,
                    str(conversation.id),
                    str(message.id),
                    run_id,
                    seq,
                )
                # 记录到按 run 的事件缓冲，供断流后按 Last-Event-ID 补发（主流续传方案的地基）。
                # 帧内 `id: <seq>` 由 sse_format 输出，seq 即 Last-Event-ID 的序号。
                # 连同 AgentThought 对象一起存：续传端点落库时要拿回"断开前已发出"那批事件
                # （断开路径的 finally 在 GeneratorExit 解绕中 await 不动，那批其实没落库）。
                run_event_log.record(
                    str(run_id) if run_id is not None else str(agent_thought.task_id),
                    seq,
                    _frame,
                    agent_thought,
                )
                run_event_log.set_run_context(
                    str(run_id) if run_id is not None else str(agent_thought.task_id),
                    str(conversation.id),
                    str(message.id),
                )
                if agent_thought.event not in _QUIET_SSE_EVENTS or (
                        agent_thought.event == QueueEvent.AGENT_MESSAGE and first_of_id):
                    logger.info(
                        "[sse-write] run=%s seq=%d event=%s id=%s tool=%s tool_call_id=%s answer_len=%d",
                        run_id if run_id is not None else agent_thought.task_id,
                        seq, agent_thought.event.value, str(agent_thought.id)[:8],
                        agent_thought.tool or "", agent_thought.tool_call_id or "",
                        len(agent_thought.answer or ""),
                    )
                yield _frame
            # 正常跑完（AGENT_END，for 循环自然结束）→ 释放本 run 的事件缓冲。
            # 注意：客户端断流时 async generator 会被 aclose（GeneratorExit，BaseException），
            # 不会被下面 except Exception 捕获，会跳过这里直接进 finally —— 因此断流场景
            # 下缓冲保留，供后续"按 Last-Event-ID 重连补发"使用（解耦落地后生效）。
            logger.info("[sse-write] 流正常结束 run=%s 总帧=%d", run_id, seq)
            run_event_log.clear(str(run_id) if run_id is not None else "")
        except GeneratorExit:
            # 客户端断开/取消（uvicorn aclose）：记录断在哪个 seq，用于对比服务端写到哪一帧。
            # 注意：断开 ≠ 任务终止（评审语义：切走不停止时任务后台继续执行），
            # 因此 run 状态保持 running、不在此终结——由 run 终态判定逻辑在真正终态事件到达时收尾。
            logger.warning("[sse-write] 客户端断开/取消 run=%s seq=%d (GeneratorExit)", run_id, seq)
            client_disconnected = True
            # 但"由终态事件收尾"前提是还有人读队列。客户端一走再也没人回来，队列就没人消费：
            # 真机实测留下过 12 条 status=running 的孤儿 run，答案一个字都没落库。
            # 此刻原读者已经退出，队列没有第二个竞争者，交给一个脱离本请求的接管者读完并落库。
            self._start_takeover(
                run_id=run_id,
                store=agent_thoughts,
                seq=seq,
                app=app,
                app_config=app_config,
                conversation=conversation,
                message=message,
                account=account,
                invoke_from=invoke_from,
            )
            raise
        except Exception as e:
            logger.info("[sse-write] 流异常终止 run=%s seq=%d error=%r", run_id, seq, e)
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
                    "total_token_count", "total_price", "sub_task_id", "sub_task_title", "trace",
                    "sub_task_options", "model_name", "llm_output", "tool_calls",
                }),
                "id": str(error_event.id),
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "task_id": str(error_event.task_id),
                "run_id": str(run_id) if run_id is not None else str(error_event.task_id),
            }
            seq += 1
            yield sse_format(QueueEvent.ERROR.value, data, seq)
        finally:
            all_thoughts = [t for t in agent_thoughts.values()]
            if error_event:
                all_thoughts.append(error_event)
            if all_thoughts:
                try:
                    await self.conversation_service.save_agent_thoughts(
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

            # run 终结：按终态事件投影 run 状态 + message.status（权威来源）。
            # 客户端断开（GeneratorExit）≠ 任务终止：run 保持 running，等待真正终态/续跑收尾，
            # 否则会把"切走不停止、后台继续"的 run 误标 cancelled。
            if not client_disconnected and run_id is not None:
                terminal, err = self._derive_run_terminal(all_thoughts)
                await self._record_run_finish(
                    run_id=run_id,
                    terminal_status=terminal,
                    error=err,
                    total_token_count=sum(t.total_token_count or 0 for t in all_thoughts),
                    total_price=sum(t.total_price or 0 for t in all_thoughts),
                    latency=sum(t.latency or 0 for t in all_thoughts),
                )

            # 12、长期记忆开启时，异步触发记忆写侧管道（由 Provider 实现，线程内仅持纯值）
            # 记忆写侧 fire-and-forget——LLM 抽取可能耗时 60s+；若在此 await 会让
            # SSE 流在 agent_end 后一直挂起不结束。create_task 后台执行，
            # 失败仅记日志，绝不阻塞流结束。
            if app_config.get("long_term_memory", {}).get("enable") and memory_provider is not None:
                try:
                    task = asyncio.create_task(memory_provider.trigger_write(
                        app_config=app_config,
                        app_id=app.id,
                        user_id=account.id,
                        query=message.query,
                        answer=message.answer,
                    ))
                    _BG_MEMORY_TASKS.add(task)
                    task.add_done_callback(_BG_MEMORY_TASKS.discard)
                except Exception:
                    logger.exception("记忆写侧任务创建失败，message_id=%s", message.id)
