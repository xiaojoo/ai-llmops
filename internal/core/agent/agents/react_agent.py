#!/usr/bin/env python
"""
@Time    : 2026/2/2 22:42
@Author  : sunxiaojie
@File    : react_agent.py
"""
import json
import logging
import re
import time
import uuid

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
    messages_to_dict,
)
from langchain_core.tools import render_text_description_and_args

from internal.core.agent.entities.agent_entity import (
    REACT_AGENT_SYSTEM_PROMPT_TEMPLATE,
    AgentState,
    build_system_prompt,
)
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import ModelFeature
from internal.core.telemetry import traced_llm_stream
from internal.exception import FailedException

from .function_call_agent import FunctionCallAgent, _filter_xml_tool_call_stream
from .base_agent import _format_agent_error

logger = logging.getLogger(__name__)



class ReACTAgent(FunctionCallAgent):
    """基于ReACT推理的智能体，兼容不支持原生工具调用的模型"""

    def _long_term_memory_recall_node(self, state: AgentState) -> AgentState:
        """重写长期记忆召回节点，构建 ReACT System Prompt"""
        # 1、如果模型本身支持Native Tool Call，直接复用父类逻辑
        if ModelFeature.TOOL_CALL in self.llm.features:
            return super()._long_term_memory_recall_node(state)

        # 2、处理长期记忆
        long_term_memory = ""
        if self.agent_config.enable_long_term_memory:
            long_term_memory = state["long_term_memory"]
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=uuid.uuid4(),
                task_id=state["task_id"],
                event=QueueEvent.LONG_TERM_MEMORY_RECALL,
                observation=long_term_memory,
            ))

        # 3、构建 System Message
        # ReACT 模式必须包含工具描述，否则模型不知道如何生成 JSON
        tools_render = render_text_description_and_args(self.agent_config.tools)

        # 即使 features 里没有 agent_thought，为了能跑通工具，也必须注入 ReACT 模板
        logger.debug("不能调用工具模型（features 无 TOOL_CALL），注入 ReACT 模板")
        preset_messages = [
            SystemMessage(build_system_prompt(
                REACT_AGENT_SYSTEM_PROMPT_TEMPLATE,
                preset_prompt=self.agent_config.preset_prompt,
                long_term_memory=long_term_memory,
                user_profile=state.get("user_profile", ""),
                episodic_memory=state.get("episodic_memory", ""),
                procedural_instructions=state.get("procedural_instructions", ""),
                tool_description=tools_render,
            ))
        ]

        # 4、处理历史消息
        history = state["history"]
        if isinstance(history, list) and len(history) > 0:
            if len(history) % 2 != 0:
                error_msg = f"智能体历史消息列表格式错误，len={len(history)}"
                self.agent_queue_manager.publish_error(state["task_id"], "智能体历史消息列表格式错误")
                logger.exception(error_msg)
                raise FailedException("智能体历史消息列表格式错误")
            preset_messages.extend(history)

        # 5、添加当前用户提问
        human_message = state["messages"][-1]
        preset_messages.append(HumanMessage(human_message.content))

        # 6、返回更新后的消息列表
        return {
            "messages": [RemoveMessage(id=human_message.id), *preset_messages],
        }

    def _llm_node(self, state: AgentState) -> AgentState:
        """重写 LLM 节点：融合了 UX 优化与强壮解析"""
        if ModelFeature.TOOL_CALL in self.llm.features:
            return super()._llm_node(state)

        if state["iteration_count"] > self.agent_config.max_iteration_count:
            return self._publish_iteration_limit_response(state)

        task_id = state["task_id"]
        start_at = time.perf_counter()
        msg_id = uuid.uuid4()

        # 发送前上下文总预算校验：超过模型上下文窗口时裁剪最旧消息
        input_messages = self._check_and_trim_context(state["messages"])
        converted_messages = self._convert_messages_for_react(input_messages)

        gathered_chunks = []
        is_thought = False
        # XML 工具调用区段状态：进入后持续抑制输出直到闭合（防参数值单独成 chunk 漏过滤）
        in_xml_section = False

        try:
            for chunk in traced_llm_stream(self.llm, converted_messages):
                content = getattr(chunk, "content", "")
                if not content:
                    continue

                gathered_chunks.append(content)
                full_text = "".join(gathered_chunks).strip()

                if len(full_text) < 15:
                    if full_text.startswith(("```", "Observation")):
                        is_thought = True
                    continue

                if is_thought:
                    pass
                else:
                    # 模型误输出 XML 工具调用标签：不回显给用户（仍会被解析执行）。
                    # 区段状态过滤：跨 chunk 持续抑制，直到闭合标签出现，
                    # 避免参数值单独成 chunk 时漏过滤显示 XML 原文。
                    visible, in_xml_section = _filter_xml_tool_call_stream(content, in_xml_section)
                    if visible:
                        self._publish_message_chunk(task_id, msg_id, visible, state["messages"], start_at)

            final_content = "".join(gathered_chunks)

        except Exception as e:
            logger.error(f"LLM Stream Error: {e}")
            self.agent_queue_manager.publish_error(task_id, _format_agent_error(e))
            raise

        # 本轮 token：优先用响应里的官方 usage，其次官方分词器估算
        input_token_count, output_token_count = self.llm.count_round_usage(
            input_messages, gathered_chunks,
        )
        # 未知按 0 落库（列是 NOT NULL），前端对 0 不显示 token 量；不再用 cl100k 猜
        input_token_count = input_token_count or 0
        output_token_count = output_token_count or 0

        # 获取输入/输出价格和单位
        input_price, output_price, unit = self.llm.get_pricing()

        # 计算总token+总成本
        total_token_count = input_token_count + output_token_count
        total_price = (input_token_count * input_price + output_token_count * output_price) * unit

        # 尝试解析工具调用：```json 代码块优先，其次 Anthropic 风格 XML（模型误输出时兜底）
        tool_calls = []
        if "```json" in final_content:
            try:
                tool_calls = self._parse_tool_calls_from_text(final_content)
            except Exception as e:
                logger.warning(f"JSON解析失败，尝试XML解析: {e}")
        if not tool_calls and "<invoke" in final_content:
            try:
                tool_calls = self._parse_tool_calls_from_xml(final_content)
            except Exception as e:
                logger.warning(f"XML解析失败，回退为普通文本: {e}")

        if tool_calls and not self._is_task_stopped(state):
            # 软停止：本步已生成，若 task 已停止则不再进入工具/LLM 循环，以当前文本收尾
            # （与 FunctionCallAgent._llm_node 的软停止语义一致）。
            # 发布完整的 LLM 调用轨迹事件（LangSmith 风格：输入 / 完整输出 / 工具调用声明 / 模型名 / token）。
            # 与流式 AGENT_MESSAGE 同 msg_id：消费端按 id 覆盖合并，最终该轮只保留一条完整记录。
            self.agent_queue_manager.publish(task_id, AgentThought(
                id=msg_id,
                task_id=task_id,
                event=QueueEvent.AGENT_THOUGHT,
                thought=final_content,
                llm_output=final_content,
                tool_calls=tool_calls,
                message=messages_to_dict(input_messages),
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
            ))

            return {
                "messages": [AIMessage(content="", tool_calls=tool_calls)],
                "iteration_count": state["iteration_count"] + 1
            }

        # 普通文本回答：先发带统计信息的 AGENT_MESSAGE，再发 AGENT_END
        self.agent_queue_manager.publish(task_id, AgentThought(
            id=msg_id,  # 和流式 chunk 同 id，chat() 叠加时会更新统计字段
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

        # 普通文本回答结束
        self.agent_queue_manager.publish(task_id, AgentThought(
            id=uuid.uuid4(),
            task_id=task_id,
            event=QueueEvent.AGENT_END,
        ))

        return {
            "messages": [AIMessage(content=final_content)],
            "iteration_count": state["iteration_count"] + 1
        }

    def _convert_messages_for_react(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """
        将包含 ToolMessage/AIMessage(tool_calls) 的消息列表转换为 ReACT 格式的 Prompt 列表。
        这样可以避免发给不支持 Function Call 的 API 时报 400 错误。
        """
        new_messages = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                # 将工具结果转换为 Observation
                new_messages.append(HumanMessage(content=f"Observation: {msg.content}"))

            elif isinstance(msg, AIMessage) and msg.tool_calls and not msg.content:
                # 将之前的工具调用决策还原为JSON文本
                thoughts = []
                for tc in msg.tool_calls:
                    thought = {
                        "name": tc["name"],
                        "args": tc["args"]
                    }
                    thoughts.append(json.dumps(thought, ensure_ascii=False))

                json_str = "\n".join([f"```json\n{t}\n```" for t in thoughts])
                new_messages.append(AIMessage(content=json_str))

            else:
                new_messages.append(msg)

        return new_messages

    def _parse_tool_calls_from_text(self, text: str) -> list[dict]:
        """解析ReACT格式的JSON输出"""
        pattern = r"```json(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)

        if not matches:
            raise ValueError("未找到 JSON 代码块")

        tool_calls = []
        for match in matches:
            json_str = match.strip()
            try:
                data = json.loads(json_str)
                tool_calls.append({
                    "id": str(uuid.uuid4()),
                    "type": "tool_call",
                    "name": data.get("name"),
                    "args": data.get("args", {})
                })
            except json.JSONDecodeError:
                continue

        if not tool_calls:
            raise ValueError("JSON 解析为空或格式不正确")

        return tool_calls

    def _publish_message_chunk(self, task_id, msg_id, content, messages, start_at):
        """推送消息块"""
        self.agent_queue_manager.publish(task_id, AgentThought(
            id=msg_id,
            task_id=task_id,
            event=QueueEvent.AGENT_MESSAGE,
            thought=content,
            message=messages_to_dict(messages),
            answer=content,
            latency=(time.perf_counter() - start_at),
        ))

    def _publish_end_event(self, state, content):
        """推送结束/错误事件"""
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(),
            task_id=state["task_id"],
            event=QueueEvent.AGENT_MESSAGE,
            thought=content,
            message=messages_to_dict(state["messages"]),
            answer=content,
            latency=0,
        ))
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(),
            task_id=state["task_id"],
            event=QueueEvent.AGENT_END,
        ))
