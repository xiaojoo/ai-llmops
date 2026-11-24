#!/usr/bin/env python
"""
@Time    : 2025/12/13 17:50
@Author  : sunxiaojie
@File    : base_agent.py
"""
import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from langchain_core.load import Serializable
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from pydantic import ConfigDict, PrivateAttr

from internal.core.agent.entities.agent_entity import AgentConfig, AgentState
from internal.core.agent.entities.queue_entity import (
    AgentResult,
    AgentThought,
    QueueEvent,
)
from internal.core.language_model.entities.model_entity import BaseLanguageModel
from internal.core.telemetry import agent_span, attach_traceparent
from internal.exception import FailedException, extract_exception_message

try:
    from openai import LengthFinishReasonError as _LengthFinishReasonError
except Exception:  # pragma: no cover - openai 版本差异兜底
    _LengthFinishReasonError = ()

from .agent_queue_manager import AgentQueueManager
from internal.core.agent.run_context import RunContext

logger = logging.getLogger(__name__)

# 图线程异常透传上限：供应商 SDK 报错含长英文堆栈/报文，超出部分截断
_AGENT_ERROR_MAX_LEN = 500


def is_length_overflow_error(error: Exception) -> bool:
    """判断是否为"输出/上下文超长"导致的不可恢复错误。

    典型为 openai.LengthFinishReasonError（响应在 length 终止且内容为空），
    或供应商返回的最大上下文长度超限（"context length"/"context window"）。
    这类错误重试也无效，必须透传前端，避免静默降级导致"无返回、任务莫名停止"。
    """
    try:
        if isinstance(error, _LengthFinishReasonError):
            return True
    except TypeError:
        pass
    lower = extract_exception_message(error).lower()
    return any(
        kw in lower
        for kw in (
            "length limit was reached",
            "maximum context length",
            "context length",
            "output length",
            "context window",
            "context_length",
            "reasoning_tokens",
        )
    )


def _format_agent_error(error: Exception) -> str:
    """把图线程内异常映射为面向用户的提示。

    模型 API 错误（余额不足 402 / Key 无效 401 / 频率超限 429 / 超时 / 5xx）直接
    透传 str(e) 会展示一长串英文报文；此处按状态码+文本特征归类为可读的中文提示。
    其余异常保留原文（业务自定义异常消息本就是中文）。
    """
    text = extract_exception_message(error)
    lower = text.lower()

    # openai SDK 异常带 status_code，其余供应商按文本特征兜底
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        status_code = getattr(error, "code", None)
    try:
        status_code = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        status_code = None

    if status_code == 402 or "insufficient balance" in lower or "insufficient_quota" in lower or "余额不足" in text:
        return "模型 API 余额不足，请充值后重试"
    if status_code == 401 or "invalid api key" in lower or "authentication" in lower:
        return "模型 API Key 无效或已过期，请检查模型配置"
    if status_code == 429 or "rate limit" in lower or "请求过于频繁" in text:
        return "模型 API 请求过于频繁，请稍后重试"
    if status_code is not None and status_code >= 500:
        return "模型服务暂时不可用，请稍后重试"
    if isinstance(error, TimeoutError) or "timeout" in lower or "timed out" in lower:
        return "模型 API 请求超时，请稍后重试"
    if is_length_overflow_error(error):
        return "模型输出超出长度/上下文限制（上下文超长），未生成完整内容。请缩短任务描述，或提高模型输出上限后重试。"
    if not text:
        return "推理过程发生异常，请稍后重试"
    return text[: _AGENT_ERROR_MAX_LEN]


class BaseAgent(Serializable, Runnable[AgentState, AgentResult], ABC):
    """基于Runnable的基础智能体基类"""
    llm: BaseLanguageModel
    agent_config: AgentConfig
    _agent: CompiledStateGraph = PrivateAttr(None)
    _agent_queue_manager: AgentQueueManager = PrivateAttr(None)
    _checkpointer: Any = PrivateAttr(None)
    _run_context: RunContext | None = PrivateAttr(None)

    # 字段允许接受任意类型，且不需要检验器
    model_config = ConfigDict(
        arbitrary_types_allowed=True
    )

    def __init__(
            self,
            llm: BaseLanguageModel,
            agent_config: AgentConfig,
            *args,
            checkpointer: Any = None,
            run_context: RunContext | None = None,
            **kwargs,
    ):
        """构造函数，初始化智能体图结构程序"""
        self._checkpointer = checkpointer
        self._run_context = run_context
        super().__init__(*args, llm=llm, agent_config=agent_config, **kwargs)
        self._checkpointer = checkpointer
        self._run_context = run_context
        self._agent = self._build_agent()
        self._agent_queue_manager = AgentQueueManager(
            user_id=self.agent_config.user_id,
            invoke_from=agent_config.invoke_from,
            model_name=str(getattr(llm, "model_name", "") or ""),
        )

    @abstractmethod
    def _build_agent(self) -> CompiledStateGraph:
        """构建智能体函数，等待子类实现"""
        raise NotImplementedError("_build_agent()未实现")

    def invoke(
            self, input: AgentState,
            config: RunnableConfig | None = None,
            **kwargs: Any
    ) -> AgentResult:
        """块内容响应，一次性生成完整内容后返回"""
        content = input['messages'][0].content
        query = ""
        image_urls = []

        if isinstance(content, str):
            query = content
        elif isinstance(content, list):
            # 1、安全地查找文本内容（遍历列表寻找 type='text'）
            for item in content:
                if item.get("type") == "text":
                    query = item.get("text", "")
                    break

            # 2、提取图片URL
            for chunk in content:
                if chunk.get("type") == "image_url":
                    # 尝试深层获取url防止报错
                    img_data = chunk.get("image_url", {})
                    if isinstance(img_data, dict) and "url" in img_data:
                        image_urls.append(img_data["url"])
        agent_result = AgentResult(query=query, image_urls=image_urls)
        agent_thoughts = {}

        for agent_thought in self.stream(input, config):
            # 2、提取事件id并转换成字符串
            event_id = str(agent_thought.id)

            # 3、除了ping事件，其他事件全部记录
            if agent_thought.event != QueueEvent.PING:
                # 4、单独处理agent_message事件，因为该事件为数据叠加
                if agent_thought.event == QueueEvent.AGENT_MESSAGE:
                    # 5、检测是否已存储了事件
                    if event_id not in agent_thoughts:
                        # 6、初始化智能体消息事件
                        agent_thoughts[event_id] = agent_thought
                    else:
                        # 7、叠加智能体消息事件
                        agent_thoughts[event_id] = agent_thoughts[event_id].model_copy(update={
                            "thought": agent_thoughts[event_id].thought + agent_thought.thought,
                            "answer": agent_thoughts[event_id].answer + agent_thought.answer,
                            "latency": agent_thought.latency,
                            "llm_output": agent_thought.llm_output or agent_thoughts[event_id].llm_output,
                            "model_name": agent_thought.model_name or agent_thoughts[event_id].model_name,
                        })
                        # 8、更新智能体消息答案
                        agent_result.answer += agent_thought.answer
                else:
                    # 9、处理其他类型的智能体事件，类型均为覆盖
                    agent_thoughts[event_id] = agent_thought

                    # 10、单独判断是否为异常消息类型，如果是则修改状态并记录错误
                    if agent_thought.event in [QueueEvent.STOP, QueueEvent.TIMEOUT, QueueEvent.ERROR]:
                        agent_result.status = agent_thought.event
                        agent_result.error = agent_thought.observation if agent_thought.event == QueueEvent.ERROR else ""

        # 11、将推理字典转换成列表并存储
        agent_result.agent_thoughts = [agent_thought for agent_thought in agent_thoughts.values()]

        # 12、完善message
        agent_result.message = next(
            (agent_thought.message for agent_thought in agent_thoughts.values()
             if agent_thought.event == QueueEvent.AGENT_MESSAGE),
            []
        )

        # 13、更新总耗时
        agent_result.latency = sum([agent_thought.latency for agent_thought in agent_thoughts.values()])
        return agent_result

    def stream(
            self,
            input: AgentState,
            config: RunnableConfig | None = None,
            **kwargs: Any | None,
    ) -> Iterator[AgentThought]:
        """流式输出，每个Not节点或者LLM每生成一个token时则会返回相应内容"""
        # 1、检测子类是否已构建Agent智能体，如果未构建则抛出错误
        if not self._agent:
            raise FailedException("智能体未成功构建，请核实后尝试")

        # 2、构建对应的任务id及数据初始化
        input["task_id"] = input.get("task_id") or (
            self._run_context.task_id if self._run_context is not None else uuid.uuid4()
        )
        input["history"] = input.get("history", [])
        input["iteration_count"] = input.get("iteration_count", 0)
        run_context = self._run_context or RunContext(
            run_id=input["task_id"],
            task_id=input["task_id"],
            thread_id=str(input["task_id"]),
        )
        config = run_context.config(config)

        # Agent 图在独立线程中执行，langgraph invoke 是同步的。
        def _invoke_agent():
            try:
                traceparent = self._run_context.traceparent if self._run_context is not None else ""
                with attach_traceparent(traceparent), agent_span(str(input["task_id"]), getattr(self, "name", "agent")):
                    if self._checkpointer is not None and (input.get("resume") or input.get("resume_trigger")):
                        snapshot = self._agent.get_state(config)
                        if snapshot is not None and snapshot.next:
                            self._agent.update_state(config, {"task_id": input["task_id"]})
                            self._agent.invoke(None, config)
                            return
                    self._agent.invoke(input, config)
            except Exception as e:
                logger.exception("Agent 图执行异常，task_id=%s", input.get("task_id"))
                try:
                    self._agent_queue_manager.publish_error(input["task_id"], _format_agent_error(e))
                except Exception:
                    logger.exception("发布 Agent 错误事件失败，task_id=%s", input.get("task_id"))

        # 4、创建子线程并执行（langgraph 图 invoke 是同步的，保留在子线程中执行）
        from threading import Thread
        thread = Thread(target=_invoke_agent)
        thread.start()

        # 5、调用队列管理器监听数据并返回迭代器
        yield from self._agent_queue_manager.listen(input["task_id"])

    @property
    def agent_queue_manager(self) -> AgentQueueManager:
        """只读属性，返回智能体队列管理器"""
        return self._agent_queue_manager
