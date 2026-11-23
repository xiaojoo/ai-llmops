#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/15 14:18
@Author : sunxiaojie
@File   : function_call_agent.py
"""
import html
import json
import logging
import re
import time
import uuid
from typing import Literal

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
    messages_to_dict,
)
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.entities.agent_entity import (
    AGENT_SYSTEM_PROMPT_TEMPLATE,
    ASK_USER_TOOL_NAME,
    ASK_USER_WAIT_TIMEOUT,
    DATASET_RETRIEVAL_TOOL_NAME,
    LOCAL_TOOL_TIMEOUT_ERROR_MARKERS,
    LOCAL_TOOL_TIMEOUT_STREAK_LIMIT,
    LOCAL_TOOL_WAIT_TIMEOUT,
    MAX_ITERATION_RESPONSE,
    AgentState,
    build_system_prompt,
)
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.tools.workspace_tools import LOCAL_TOOL_NAMES
from internal.core.language_model.entities.model_entity import ModelFeature
from internal.exception import FailedException

# XML 工具调用标签关键词（Anthropic 风格：<tool_calls><invoke name=...><parameter name=...>）
_XML_TOOL_CALL_MARKERS = ("<invoke", "<tool_calls", "<parameter", "</invoke>", "</tool_calls>", "</parameter>")
_XML_OPEN_MARKERS = ("<invoke", "<tool_calls", "<parameter")
_XML_CLOSE_TAGS = ("</invoke>", "</tool_calls>")


def _contains_xml_tool_call(text: str) -> bool:
    """判断文本是否包含 XML 工具调用标签（用于流式发布前过滤，不回显给用户）。"""
    return any(marker in text for marker in _XML_TOOL_CALL_MARKERS)


def _filter_xml_tool_call_stream(text: str, in_xml_section: bool) -> tuple[str, bool]:
    """流式 XML 工具调用区段过滤：把可回显文本与 XML 工具调用区段分开。

    LLM 流式输出时 XML 标签可能被拆到多个 chunk（如参数值 `["-m", ...]` 单独成块
    不含任何标签），逐 chunk 判断会漏过滤导致 XML 原文显示给用户。这里维护
    "是否处于 XML 区段"的状态：一旦出现 <invoke>/<tool_calls>/<parameter> 开始标签，
    持续抑制输出直到 </invoke>/</tool_calls> 闭合；同一 chunk 内可能同时含
    普通文本（开头）+ XML（中间）+ 普通文本（闭合后），按顺序切分拼接。

    Returns:
        (可回显文本, 新的 in_xml_section 状态)
    """
    if in_xml_section:
        # 处于 XML 区段内：寻找闭合标签，未闭合则整段抑制
        for close_tag in _XML_CLOSE_TAGS:
            idx = text.find(close_tag)
            if idx != -1:
                tail = text[idx + len(close_tag):]
                disp, new_in = _filter_xml_tool_call_stream(tail, False)
                return disp, new_in
        return "", True

    # 普通文本区段：找第一个开始标签，之前的文本可回显
    starts = [text.find(m) for m in _XML_OPEN_MARKERS]
    starts = [i for i in starts if i != -1]
    if not starts:
        return text, False
    start = min(starts)
    head = text[:start]
    disp, new_in = _filter_xml_tool_call_stream(text[start:], True)
    return head + disp, new_in


def _parse_xml_param_value(raw: str):
    """XML 工具调用参数值解析：JSON 数组/对象字符串 → 结构化值，其余原样返回。

    模型误输出 XML 工具调用时，数组/对象参数常写成 JSON 字符串
    （如 `<parameter name="args">["-m", "pip", "install", "pygame"]</parameter>`），
    若不解析，pydantic 工具 schema 校验会失败（期望 list 却收到 str），
    导致工具调用失败并回退为普通文本。
    """
    stripped = raw.strip()
    if stripped.startswith(("[", "{")):
        try:
            return json.loads(stripped)
        except (ValueError, TypeError):
            return raw
    # 数字/布尔字符串 → 原生类型（pydantic 通常能自动转换，这里显式转换更稳）
    if stripped in ("true", "false"):
        return stripped == "true"
    try:
        return int(stripped)
    except (ValueError, TypeError):
        pass
    try:
        return float(stripped)
    except (ValueError, TypeError):
        return raw

from .base_agent import BaseAgent, _format_agent_error

logger = logging.getLogger(__name__)



class FunctionCallAgent(BaseAgent):
    """基于函数/工具调用的智能体"""

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

    def _preset_operation_node(self, state: AgentState) -> AgentState:
        """预设操作，涵盖：输入审核、数据预处理、条件边等"""
        # 1、获取审核配置与用户输入query
        review_config = self.agent_config.review_config
        query = state["messages"][-1].content

        # 2、检测是否开启审核配置
        if review_config["enable"] and review_config["inputs_config"]["enable"]:
            if any(keyword in query for keyword in review_config["keywords"]):
                preset_response = review_config["inputs_config"]["preset_response"]
                self.agent_queue_manager.publish(state["task_id"], AgentThought(
                    id=uuid.uuid4(),
                    task_id=state["task_id"],
                    event=QueueEvent.AGENT_MESSAGE,
                    thought=preset_response,
                    message=messages_to_dict(state["messages"]),
                    answer=preset_response,
                    latency=0,
                ))
                self.agent_queue_manager.publish(state["task_id"], AgentThought(
                    id=uuid.uuid4(),
                    task_id=state["task_id"],
                    event=QueueEvent.AGENT_END,
                ))
                return {"messages": [AIMessage(preset_response)]}

            return {"messages": []}

    def _long_term_memory_recall_node(self, state: AgentState) -> AgentState:
        """长期记忆召回节点"""
        # 1、根据传递的智能体配置判断是否需要召回长期记忆
        long_term_memory = ""
        if self.agent_config.enable_long_term_memory:
            long_term_memory = state["long_term_memory"]
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=uuid.uuid4(),
                task_id=state["task_id"],
                event=QueueEvent.LONG_TERM_MEMORY_RECALL,
                observation=long_term_memory,
                message=messages_to_dict(state["messages"]),
            ))

        # 2、构建预设消息列表，并将preset_prompt+long_term_memory填充到系统消息中
        preset_messages = [
            SystemMessage(build_system_prompt(
                AGENT_SYSTEM_PROMPT_TEMPLATE,
                preset_prompt=self.agent_config.preset_prompt,
                long_term_memory=long_term_memory,
                user_profile=state.get("user_profile", ""),
                episodic_memory=state.get("episodic_memory", ""),
                procedural_instructions=state.get("procedural_instructions", ""),
            ))
        ]

        # 3、将短期历史消息添加到消息列表中
        history = state["history"]
        if isinstance(history, list) and len(history) > 0:
            # 4、校验历史消息是不是复数形式，也就是[人类消息，AI消息，人类消息，AI消息，……]
            if len(history) % 2 != 0:
                self.agent_queue_manager.publish_error(state["task_id"], "智能体历史消息列表格式错误")
                logger.exception(
                    
                        f"智能体历史消息列表格式错误，len(history)={len(history)}, history={json.dumps(messages_to_dict(history))}"
                    
                )
                raise FailedException("智能体历史消息列表格式错误")
            # 5、拼接历史消息
            preset_messages.extend(history)

        # 6、凭借当前用户的提问信息
        human_message = state["messages"][-1]
        preset_messages.append(HumanMessage(human_message.content))

        # 7、处理预设消息，将预设消息添加到用户消息前，先去删除用户的原始消息，然后补充一个新的代替
        return {
            "messages": [RemoveMessage(id=human_message.id), *preset_messages],
        }

    def _check_and_trim_context(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """发送前上下文总预算校验。

        估算消息总量，超过模型上下文窗口（扣除输出预留 max_tokens 与 15% 安全余量）时，
        从最旧的对话消息开始裁剪，保留系统提示词与最新消息，避免上下文超限导致接口报错。
        模型窗口未知时不做裁剪。
        """
        context_window = self.llm.context_window or 0
        if context_window <= 0:
            return messages

        max_tokens = self.llm.max_tokens or 0
        budget = context_window - max_tokens - int(context_window * 0.15)
        if budget <= 0:
            return messages

        if (self.llm.get_num_tokens_safe(messages) or 0) <= budget:
            return messages

        # 保留系统提示词（第一条），从最旧的对话消息开始裁剪；
        # 裁剪后若开头是 ai/tool 消息（会导致消息序列非法）则一并丢弃
        kept = []
        rest = list(messages)
        if rest and getattr(rest[0], "type", "") == "system":
            kept.append(rest.pop(0))

        while len(rest) > 1 and (self.llm.get_num_tokens_safe(kept + rest) or 0) > budget:
            rest.pop(0)
            while rest and getattr(rest[0], "type", "") in ("ai", "tool"):
                rest.pop(0)

        return kept + rest

    def _llm_node(self, state: AgentState) -> AgentState:
        """大语言模型节点（修复版：支持 DeepSeek 混合输出模式）"""
        # 1、检测迭代次数
        if state["iteration_count"] > self.agent_config.max_iteration_count:
            return self._publish_iteration_limit_response(state)

        llm = self.llm
        # 2、检测大语言模型实例是否有bind_tooLs方法，如果没有则不绑定，如果有还需要检测tooLs是否为空，不为空则绑定
        if (
                ModelFeature.TOOL_CALL in llm.features
                and hasattr(llm, "bind_tools")
                and callable(llm.bind_tools)
                and len(self.agent_config.tools) > 0
        ):
            llm = llm.bind_tools(self.agent_config.tools)

        # 2.1、发送前上下文总预算校验：超过模型上下文窗口时裁剪最旧消息
        input_messages = self._check_and_trim_context(state["messages"])

        # 软停止（入口检查）：task 已停止则不再调用 LLM，避免停止后还生成新内容——
        # 直接以"无新内容"收尾发 AGENT_END（等价当前步已完成、不再续轮）。
        # 走到此处说明上一轮要么无 tool_calls（可直接结束），要么 tools 已为 tool_calls
        # 补齐空 ToolMessage（消息序列合法）。
        if self._is_task_stopped(state):
            logger.info("[stop] LLM 节点拦截：task 已停止，不再调用 LLM task=%s", state["task_id"])
            return self._publish_stop_finish(state)

        # 3、流式调用
        stream_id = uuid.uuid4()
        start_at = time.perf_counter()

        gathered = None
        is_first_chunk = True

        # 标记是否检测到了工具调用
        has_tool_calls = False
        # XML 工具调用区段状态：进入后持续抑制输出直到闭合（防参数值单独成 chunk 漏过滤）
        in_xml_section = False

        try:
            for chunk in llm.stream(input_messages):
                if is_first_chunk:
                    gathered = chunk
                    is_first_chunk = False
                else:
                    gathered += chunk

                # 1. 实时监测是否有工具调用信号
                if chunk.tool_calls:
                    has_tool_calls = True
                    self.agent_queue_manager.publish(state["task_id"], AgentThought(
                        id=stream_id,
                        task_id=state["task_id"],
                        event=QueueEvent.AGENT_THOUGHT,
                        thought=json.dumps(chunk.tool_calls),
                        message=messages_to_dict(state["messages"]),
                        latency=(time.perf_counter() - start_at),
                    ))

                # 2. 实时推送文本内容（如果有的话）
                if chunk.content:
                    # 模型误输出 XML 工具调用（<invoke>/<tool_calls>/<parameter>）时，
                    # 标签文本不回显给用户（工具仍由 _parse_tool_calls_from_xml 解析执行）。
                    # 区段状态过滤：跨 chunk 持续抑制，直到 </invoke>/</tool_calls> 闭合，
                    # 避免参数值（如 ["-m", ...]）单独成 chunk 时漏过滤显示 XML 原文。
                    visible, in_xml_section = _filter_xml_tool_call_stream(
                        chunk.content, in_xml_section,
                    )
                    if not visible:
                        continue
                    review_config = self.agent_config.review_config
                    content = visible
                    if review_config["enable"] and review_config["outputs_config"]["enable"]:
                        for keyword in review_config["keywords"]:
                            pattern = re.compile(re.escape(keyword), re.IGNORECASE)
                            content = pattern.sub("**", content)

                    self.agent_queue_manager.publish(state["task_id"], AgentThought(
                        id=stream_id,
                        task_id=state["task_id"],
                        event=QueueEvent.AGENT_MESSAGE,
                        thought=content,
                        message=messages_to_dict(state["messages"]),
                        answer=content,
                        latency=(time.perf_counter() - start_at),
                    ))
        except Exception as e:
            logger.exception("LLM节点发生错误：%s", e)
            self.agent_queue_manager.publish_error(state["task_id"], _format_agent_error(e))
            raise

        # 本轮 token：优先用响应里的官方 usage，其次官方分词器估算
        input_token_count, output_token_count = llm.count_round_usage(input_messages, gathered)
        # 未知按 0 落库（列是 NOT NULL），前端对 0 不显示 token 量；不再用 cl100k 猜
        input_token_count = input_token_count or 0
        output_token_count = output_token_count or 0

        # 获取输入/输出价格和单位
        input_price, output_price, unit = llm.get_pricing()

        # 计算总token+总成本
        total_token_count = input_token_count + output_token_count
        total_price = (input_token_count * input_price + output_token_count * output_price) * unit

        # 4.1、模型可能误输出 Anthropic 风格 XML 工具调用（<invoke name=...>），
        #      原生 tool_calls 检测不到时尝试 XML 解析，避免工具调用沦为普通文本
        if not has_tool_calls and "<invoke" in (getattr(gathered, "content", "") or ""):
            try:
                xml_calls = self._parse_tool_calls_from_xml(gathered.content or "")
            except Exception as e:
                logger.warning("XML 工具调用解析失败，回退为普通文本: %s", e)
                xml_calls = []
            if xml_calls:
                has_tool_calls = True
                gathered = AIMessage(
                    content="",
                    tool_calls=xml_calls,
                    id=getattr(gathered, "id", None),
                    additional_kwargs=getattr(gathered, "additional_kwargs", None) or {},
                )

        # 4、循环结束后，根据最终结果判断是否发送 END
        if not has_tool_calls:
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=stream_id,
                task_id=state["task_id"],
                event=QueueEvent.AGENT_MESSAGE,
                # 消息相关字段
                message=messages_to_dict(state["messages"]),
                message_token_count=input_token_count,
                message_unit_price=input_price,
                message_price_unit=unit,
                # 答案相关字段
                answer="",
                answer_token_count=output_token_count,
                answer_unit_price=output_price,
                answer_price_unit=unit,
                # Agent推理统计相关
                total_token_count=total_token_count,
                total_price=total_price,
                latency=(time.perf_counter() - start_at),
                # LLM 调用轨迹（LangSmith 风格：完整输出 + 模型名）
                llm_output=getattr(gathered, "content", "") or "",
                # DeepSeek thinking 模式的推理过程：随消息持久化，跨轮次重建历史时回传
                reasoning_content=getattr(gathered, "additional_kwargs", {}).get("reasoning_content", ""),
            ))
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=uuid.uuid4(),
                task_id=state["task_id"],
                event=QueueEvent.AGENT_END,
            ))
            return {"messages": [gathered], "iteration_count": state["iteration_count"] + 1}

        # 5、检测到工具调用：下一轮 LLM 输入中的 AI 消息 content 置空（只保留 tool_calls）。
        #    DeepSeek 混合输出模式下 LLM 常在工具调用前输出大段文本（如自我介绍/开场白），
        #    该文本会留在上下文中污染下一轮：LLM 看到自己"已经回答过"，工具返回后仍继续
        #    输出开场白而非基于检索内容回答（对照实验验证：content 为空时 LLM 正确基于
        #    工具结果作答）。此处清空 content，保证工具执行后的生成干净。
        #    同时规范化 tool_calls：过滤流式占位/空参数条目，按 (name, args) 去重，
        #    并限制单次最多执行 1 个工具——避免 DeepSeek 一次并行返回多个大体积工具
        #    结果（如知识库检索）挤爆上下文导致 LLM 后续轮次跑题/循环。
        valid_calls = []
        seen = set()
        for tc in (gathered.tool_calls or []):
            name = tc.get("name") or ""
            args = tc.get("args") or {}
            if not name:
                continue
            key = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
            if key in seen:
                continue
            seen.add(key)
            valid_calls.append({"name": name, "args": args, "id": tc.get("id"), "type": "tool_call"})
            if len(valid_calls) >= 1:
                break
        clean_ai = AIMessage(
            content="",
            tool_calls=valid_calls,
            id=gathered.id,
            additional_kwargs=getattr(gathered, "additional_kwargs", None) or {},
        )
        # 发布完整的 LLM 调用轨迹事件（LangSmith 风格：输入 messages / 完整输出 / 工具调用声明 / 模型名 / token）。
        # 与流式 AGENT_MESSAGE/AGENT_THOUGHT 同 stream_id：消费端按 id 覆盖合并，最终该轮只保留一条完整记录。
        llm_output_text = getattr(gathered, "content", "") or ""
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=stream_id,
            task_id=state["task_id"],
            event=QueueEvent.AGENT_THOUGHT,
            thought=llm_output_text,
            llm_output=llm_output_text,
            tool_calls=valid_calls,
            message=messages_to_dict(input_messages),
            message_token_count=input_token_count,
            message_unit_price=input_price,
            message_price_unit=unit,
            answer_token_count=output_token_count,
            answer_unit_price=output_price,
            answer_price_unit=unit,
            total_token_count=total_token_count,
            total_price=total_price,
            latency=(time.perf_counter() - start_at),
        ))
        return {"messages": [clean_ai], "iteration_count": state["iteration_count"] + 1}

    @staticmethod
    def _parse_tool_calls_from_xml(text: str) -> list[dict]:
        """解析 Anthropic 风格 XML 工具调用。

        兼容模型误输出 `<invoke name="x"><parameter name="k">v</parameter></invoke>`
        （可能带 <tool_calls> 包裹、parameter 带 string 属性、值含 HTML 实体）的场景，
        避免工具调用沦为普通文本展示。输出与 langchain tool_calls 结构一致。

        参数值若为 JSON 数组/对象字符串（如 `["-m", "pip", ...]`），会解析为
        结构化值（list/dict），保证 pydantic 工具 schema（如 ShellRunInput.args: list[str]）
        能通过校验。
        """
        tool_calls = []
        for invoke in re.finditer(
            r"<invoke\s+name=[\"']([^\"']+)[\"']\s*>(.*?)</invoke>", text, re.DOTALL,
        ):
            name = invoke.group(1).strip()
            if not name:
                continue
            args = {}
            for param in re.finditer(
                r"<parameter\s+name=[\"']([^\"']+)[\"'](?:\s+[^>]*)?>(.*?)</parameter>",
                invoke.group(2), re.DOTALL,
            ):
                raw_value = html.unescape(param.group(2).strip())
                args[param.group(1).strip()] = _parse_xml_param_value(raw_value)
            tool_calls.append({
                "id": str(uuid.uuid4()),
                "type": "tool_call",
                "name": name,
                "args": args,
            })
        if not tool_calls:
            raise ValueError("XML 中未找到 <invoke> 工具调用")
        return tool_calls

    def _publish_iteration_limit_response(self, state: AgentState) -> AgentState:
        """迭代超限时的兜底回答：基于本轮已积累的工具返回内容尽力作答。"""
        task_id = state["task_id"]
        start_at = time.perf_counter()
        msg_id = uuid.uuid4()

        # 1、在已有消息（含全部 ToolMessage）基础上追加系统提示，禁止再次调用工具
        limit_hint = SystemMessage(
            content=(
                "注意：本次会话已达到最大迭代次数，禁止再调用任何工具。"
                "请直接基于对话中已有的工具返回内容，组织一个尽可能完整、有用的最终回答；"
                "如果信息不足以完整回答，请明确说明已获取到哪些、还缺少哪些。"
            )
        )
        input_messages = [*state["messages"], limit_hint]

        gathered = None
        is_first_chunk = True
        try:
            # 2、用未绑定工具的原始 llm 流式生成最终回答
            for chunk in self.llm.stream(input_messages):
                if is_first_chunk:
                    gathered = chunk
                    is_first_chunk = False
                else:
                    gathered += chunk

                if chunk.content:
                    self.agent_queue_manager.publish(state["task_id"], AgentThought(
                        id=msg_id,
                        task_id=task_id,
                        event=QueueEvent.AGENT_MESSAGE,
                        thought=chunk.content,
                        message=messages_to_dict(state["messages"]),
                        answer=chunk.content,
                        latency=(time.perf_counter() - start_at),
                    ))
        except Exception as e:
            logger.exception("迭代超限兜底回答失败：%(error)s")
            self.agent_queue_manager.publish_error(task_id, f"LLM错误：{e!s}")
            return {"messages": [AIMessage(MAX_ITERATION_RESPONSE)]}

        final_content = (gathered.content if gathered is not None else "") or MAX_ITERATION_RESPONSE

        # 3、发布带统计信息的最终消息 + END
        # 本轮 token：优先响应里的官方 usage（gathered 为 None 时没有响应，只能本地估）
        if gathered is not None:
            input_token_count, output_token_count = self.llm.count_round_usage(input_messages, gathered)
        else:
            input_token_count = self.llm.get_num_tokens_safe(input_messages)
            output_token_count = 0
        # 未知按 0 落库（列是 NOT NULL），前端对 0 不显示 token 量；不再用 cl100k 猜
        input_token_count = input_token_count or 0
        output_token_count = output_token_count or 0
        input_price, output_price, unit = self.llm.get_pricing()
        total_token_count = input_token_count + output_token_count
        total_price = (input_token_count * input_price + output_token_count * output_price) * unit

        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=msg_id,
            task_id=task_id,
            event=QueueEvent.AGENT_MESSAGE,
            message=messages_to_dict(state["messages"]),
            message_token_count=input_token_count,
            message_unit_price=input_price,
            message_price_unit=unit,
            answer="",
            answer_token_count=output_token_count,
            answer_unit_price=output_price,
            answer_price_unit=unit,
            total_token_count=total_token_count,
            total_price=total_price,
            latency=(time.perf_counter() - start_at),
            llm_output=final_content,
        ))
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(),
            task_id=task_id,
            event=QueueEvent.AGENT_END,
        ))
        return {"messages": [AIMessage(content=final_content)]}

    def _tools_node(self, state: AgentState) -> AgentState:
        """工具执行节点"""
        # 软停止：已停止则不执行任何工具，直接返回空消息——图回到 llm 节点，由 llm 节点
        # 的停止检测以当前内容收尾（不执行剩余工具/不再续轮）。
        if self._is_task_stopped(state):
            logger.info("[stop] 工具节点拦截：task 已停止，跳过工具执行 task=%s", state["task_id"])
            # 为被跳过的 tool_calls 补齐空 ToolMessage，保持"AI(tool_calls) → ToolMessage"
            # 消息序列合法——否则 llm 节点收尾时 LLM 收到无 ToolMessage 配对的 AI 消息会报错。
            tool_calls = state["messages"][-1].tool_calls or []
            empty_tools = [
                ToolMessage(
                    tool_call_id=tc.get("id") or str(uuid.uuid4()),
                    content="", name=tc.get("name") or "",
                )
                for tc in tool_calls
            ]
            return {"messages": empty_tools}

        # 1、将工具列表转换成字典，便于调用指定的工具
        tools_by_name = {tool.name: tool for tool in self.agent_config.tools}

        # 2、提取消息中的工具调用参数
        tool_calls = state["messages"][-1].tool_calls

        # 3、循环执行工具组装工具消息
        messages = []
        current_messages = state["messages"].copy()
        # 本地工具连续超时计数（熔断用）：本轮每个本地工具调用都会读取/更新，最后随节点返回值回写状态
        local_tool_streak = int(state.get("local_tool_timeout_streak") or 0)

        for tool_call in tool_calls:
            id = uuid.uuid4()
            start_at = time.perf_counter()
            trace: list = []

            try:
                if tool_call["name"] == ASK_USER_TOOL_NAME:
                    # 交互式选项：不执行工具，发布 ask_user 事件并阻塞等待用户选择
                    tool_result = self._handle_ask_user(state, tool_call)
                elif self.agent_config.local_tool_runtime and tool_call["name"] in LOCAL_TOOL_NAMES:
                    # 本地工具运行时：不服务器执行，发布 local_tool_call 事件并阻塞等待插件本地执行结果
                    logger.info(
                        "[local-tool-runtime] 拦截本地工具 %s (tool_call_id=%s) → LOCAL_TOOL_CALL",
                        tool_call["name"], tool_call.get("id"),
                    )
                    tool_result, local_tool_streak = self._exec_local_tool(state, tool_call)
                else:
                    if tool_call["name"] in LOCAL_TOOL_NAMES:
                        logger.warning(
                            "[local-tool-runtime] 本地工具 %s 未被拦截：local_tool_runtime=%s（应透传到底层 Agent）",
                            tool_call["name"], self.agent_config.local_tool_runtime,
                        )
                    tool = tools_by_name[tool_call["name"]]
                    tool_result = tool.invoke(tool_call["args"])
                # 读取知识库检索工具的 Agentic 重检轨迹（未开启 agentic 时为空列表）
                if tool_call["name"] == DATASET_RETRIEVAL_TOOL_NAME:
                    trace = list(getattr(tool, "agentic_trace", None) or [])
            except Exception as e:
                tool_result = f"工具执行出错：{e!s}"

            tool_msg = ToolMessage(
                tool_call_id=tool_call["id"],
                content=json.dumps(tool_result, ensure_ascii=False),
                name=tool_call["name"],
            )
            messages.append(tool_msg)

            display_messages = current_messages + [tool_msg]

            # 4、判断执行工具的名字，提交不同事件，涵盖智能体动作以及知识库检索
            event = (
                QueueEvent.AGENT_ACTION
                if tool_call["name"] != DATASET_RETRIEVAL_TOOL_NAME
                else QueueEvent.DATASET_RETRIEVAL
            )
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=id,
                task_id=state["task_id"],
                event=event,
                observation=json.dumps(tool_result, ensure_ascii=False),
                tool=tool_call["name"],
                tool_input=tool_call["args"],
                trace=trace,
                latency=(time.perf_counter() - start_at),
                message=messages_to_dict(display_messages),
            ))

        return {"messages": messages, "local_tool_timeout_streak": local_tool_streak}

    def _is_task_stopped(self, state: AgentState) -> bool:
        """判断当前 task（或编排器 run）是否被标记停止（软停止检查点）。

        停止请求经 set_stop_flag 写 Redis 标志；listen 检测后发布 STOP 事件终止输出，
        但 langgraph 图线程不能因此中断——这里在图节点边界显式检查，让图在"当前步
        完成后"尽快收尾、不再续轮（真正实现软停止）。非编排子任务复用同一 task_id。
        """
        try:
            return self.agent_queue_manager._is_stopped(state["task_id"])
        except Exception:
            # Redis 未就绪等异常按未停止处理（不影响主流程）
            return False

    def _publish_stop_finish(self, state: AgentState) -> AgentState:
        """软停止收尾：不生成新内容，仅发布 AGENT_END 并返回当前消息。

        用于 LLM 节点在 task 已停止时跳过生成、直接结束本轮。
        """
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(),
            task_id=state["task_id"],
            event=QueueEvent.AGENT_END,
            message=messages_to_dict(state["messages"]),
        ))
        # 返回最后一条消息保持消息队列推进；空消息时兜底空列表避免索引越界
        return {"messages": state["messages"][-1:], "iteration_count": state["iteration_count"] + 1}

    def _handle_ask_user(self, state: AgentState, tool_call: dict) -> str:
        """ask_user 特殊分支：发布 ASK_USER 事件 → 阻塞等待用户选择 → 返回选择文本。

        返回字符串作为 ToolMessage 内容给 LLM，继续推理（同轮续跑）。
        """
        args = tool_call.get("args") or {}
        question = str(args.get("question", ""))
        options = [str(o) for o in (args.get("options") or [])]
        allow_custom = bool(args.get("allow_custom", True))

        ask_event_id = uuid.uuid4()
        logger.info(
            "[ask-user] 发布 ASK_USER 开始等待 task_id=%s event_id=%s question=%r",
            state["task_id"], ask_event_id, question[:80],
        )
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=ask_event_id,
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

        choice, skipped, _custom = AgentQueueManager.wait_for_choice(
            state["task_id"], timeout=ASK_USER_WAIT_TIMEOUT, event_id=str(ask_event_id),
        )
        logger.info(
            "[ask-user] 收到选择/超时 task_id=%s event_id=%s choice=%r skipped=%s 继续本 run",
            state["task_id"], ask_event_id, choice, skipped,
        )
        if not (skipped or not choice):
            # 用户已选择：同 event_id 重新发布带 choice 的事件（覆盖首次发布，供落库/回显）
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=ask_event_id,
                task_id=state["task_id"],
                event=QueueEvent.ASK_USER,
                question=question,
                options=options,
                allow_custom=allow_custom,
                choice=choice,
                tool=ASK_USER_TOOL_NAME,
                tool_input=args,
                message=messages_to_dict(state["messages"]),
                latency=0,
            ))
        if skipped or not choice:
            return "用户跳过了选择，请基于已有信息自行决策并继续。"
        return f"用户选择了：{choice}"

    def _handle_local_tool(self, state: AgentState, tool_call: dict) -> str:
        """本地工具运行时特殊分支（兼容薄壳）：返回 ToolMessage 内容文本。

        熔断计数由完整实现 _exec_local_tool 计算，_tools_node 负责回写状态。
        """
        return self._exec_local_tool(state, tool_call)[0]

    @staticmethod
    def _is_local_tool_timeout_error(error: str) -> bool:
        """是否"超时类"错误：插件结果通道失联/未就绪/异常，或插件看门狗回传的
        "本地工具执行超时（插件看门狗 …）"。这类错误说明执行器断流，计入连续熔断计数；
        普通执行错误说明插件在回传结果，执行器存活，不计入。
        """
        return any(error.startswith(marker) for marker in LOCAL_TOOL_TIMEOUT_ERROR_MARKERS)

    def _exec_local_tool(self, state: AgentState, tool_call: dict) -> tuple[str, int]:
        """本地工具运行时特殊分支完整实现：发布 LOCAL_TOOL_CALL → 等待插件结果 → 返回。

        连续超时熔断：连续 LOCAL_TOOL_TIMEOUT_STREAK_LIMIT 次"超时类"错误后，本 run 内
        后续本地工具调用快速失败（不再发布/等待 60s），并把"失败原因 + 兜底输出"指引注入
        给模型，避免执行器断流时无限 60s×N 重试。

        Returns:
            (ToolMessage 内容文本, 更新后的 local_tool_timeout_streak 计数)
        """
        tool_name = tool_call["name"]
        tool_call_id = str(tool_call.get("id") or "")
        args = tool_call.get("args") or {}
        task_id = state["task_id"]
        streak = int(state.get("local_tool_timeout_streak") or 0)

        # 熔断生效：不发布/不等待，快速失败并把"失败原因 + 兜底输出"指引给模型（单次开销≈0）
        if streak >= LOCAL_TOOL_TIMEOUT_STREAK_LIMIT:
            logger.info(
                "[local-tool-runtime] 本地工具熔断生效，跳过 tool=%s task_id=%s tool_call_id=%s",
                tool_name, task_id, tool_call_id,
            )
            return (
                f"本地工具执行熔断生效中：{tool_name} 已连续 {LOCAL_TOOL_TIMEOUT_STREAK_LIMIT} 次超时，"
                "本会话不再执行/等待任何 fs_* 本地工具。请立即停止调用本地文件工具，直接向用户输出"
                "最终兜底回复：① 说明失败原因（IDE 插件本地执行器未回传结果：插件未重启 / WebApp 工具窗"
                "未打开 / SSE 连接断流 / 本地文件 I/O 卡死）；② 把本应写入工作区的文件内容以代码块形式完整给出。",
                streak,
            )

        start_at = time.perf_counter()
        logger.info(
            "[local-tool-runtime] 发布 LOCAL_TOOL_CALL 等待结果 task_id=%s tool=%s tool_call_id=%s",
            task_id, tool_name, tool_call_id,
        )
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(),
            task_id=state["task_id"],
            event=QueueEvent.LOCAL_TOOL_CALL,
            tool=tool_name,
            tool_input=args,
            tool_call_id=tool_call_id,
            message=messages_to_dict(state["messages"]),
            latency=0,
        ))
        result, error = AgentQueueManager.wait_for_tool_result(
            task_id, tool_call_id, timeout=LOCAL_TOOL_WAIT_TIMEOUT,
        )
        latency = time.perf_counter() - start_at
        logger.info(
            "[local-tool-runtime] 收到本地工具结果 task_id=%s tool=%s tool_call_id=%s error=%r result_len=%d latency=%.2fs",
            task_id, tool_name, tool_call_id, error, len(result or ""), latency,
        )
        if not error:
            return str(result or ""), 0

        timeout_error = self._is_local_tool_timeout_error(error)
        if timeout_error:
            new_streak = streak + 1
            crossed = new_streak >= LOCAL_TOOL_TIMEOUT_STREAK_LIMIT
            if crossed:
                note = (
                    f"⛔ 本地工具执行器熔断：{tool_name} 已连续 {LOCAL_TOOL_TIMEOUT_STREAK_LIMIT} 次执行超时"
                    f"（等待 {latency:.0f}s 后插件仍未回传结果：{error}）。原因通常是：IDE 插件未重启、"
                    "WebApp 工具窗未打开、SSE 连接断流或本地文件 I/O 卡死。本会话不再等待本地工具，"
                    "将以兜底内容收尾；请重启 IDE 并确认工具窗已打开后重发任务。"
                )
            else:
                note = (
                    f"⏱️ 本地工具 {tool_name} 执行超时/出错：{error}（已等待 {latency:.0f}s，插件未回传结果，"
                    f"请检查插件是否已安装并重启；连续 {new_streak}/{LOCAL_TOOL_TIMEOUT_STREAK_LIMIT} 次后将熔断）"
                )
        else:
            new_streak = 0
            note = f"⚠️ 本地工具 {tool_name} 执行出错：{error}"
        # 关键：本地工具超时/出错不能只当作 ToolMessage 回给 LLM（用户侧永远看不到，
        # 表现为"工具调用中"然后流默默结束）。这里再发一条 AGENT_MESSAGE，把超时/错误
        # 作为可见输出回显给前端（idea/vscode/dsh 均渲染 agent_message）。
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(),
            task_id=state["task_id"],
            event=QueueEvent.AGENT_MESSAGE,
            thought=note,
            answer=note,
            tool=tool_name,
            tool_input=args,
            tool_call_id=tool_call_id,
            message=messages_to_dict(state["messages"]),
            latency=latency,
        ))
        if crossed:
            return (
                f"本地工具执行熔断：{tool_name} 已连续 {LOCAL_TOOL_TIMEOUT_STREAK_LIMIT} 次超时（最近错误：{error}）。"
                "原因：WebApp 插件本地执行器未回传结果（插件未重启 / 工具窗未打开 / SSE 断流）。"
                "请立即停止调用任何 fs_* 本地工具，直接给用户最终兜底回复：先说明失败原因，"
                "再把本应写入工作区的文件内容以代码块形式完整输出。",
                new_streak,
            )
        return f"本地工具执行出错：{error}", new_streak

    @classmethod
    def _entry_condition(cls, state: AgentState) -> Literal["preset_operation", "llm"]:
        """入口条件：恢复模式直接进 llm 节点（断点消息已含系统提示词），正常模式走预设操作"""
        return "llm" if state.get("resume") else "preset_operation"

    @classmethod
    def _tools_condition(cls, state: AgentState) -> Literal["tools", "__end__"]:
        """检测下一个节点是执行tools节点，还是直接结束"""
        # 1、提取状态中的最后一条消息（AI消息）
        messages = state["messages"]
        ai_message = messages[-1]

        # 2、检测是否存在tools_calls这个参数，如果存在则执行tools节点，否则结束
        if hasattr(ai_message, "tool_calls") and len(ai_message.tool_calls) > 0:
            return "tools"

        return END

    @classmethod
    def _preset_operation_condition(cls, state: AgentState) -> Literal["long_term_memory_recall", "__end__"]:
        """预设操作条件边，用于判断是否触发预设响应"""
        # 1、提取状态的最后一条消息
        message = state["messages"][-1]
        # 2、判断消息的类型，如果是AI消息则说明触发了审核机制，直接结束
        if message.type == "ai":
            return END

        return "long_term_memory_recall"
