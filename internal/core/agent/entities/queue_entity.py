#!/usr/bin/env python
"""
@Time    : 2025/12/13 20:33
@Author  : sunxiaojie
@File    : queue_entity.py
"""
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from internal.entity.conversation_entity import MessageStatus


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
    ASK_USER = "ask_user"  # 向用户提问，等待选择
    LOCAL_TOOL_CALL = "local_tool_call"  # 本地工具调用：服务器暂停，等待插件本地执行结果


class AgentThought(BaseModel):
    """智能体推理观察输出内容"""
    id: UUID  # 事件对应的id，同一个事件的id是一样的
    task_id: UUID  # 任务id

    # 事件的推理与观察
    event: QueueEvent
    thought: str = ""  # LLM推理内容
    observation: str = ""  # 观察内容

    chunk: str = ""

    # LLM 调用轨迹字段（LangSmith 风格：记录每一步大模型做了什么）
    model_name: str = ""  # 本轮调用使用的模型名
    llm_output: str = ""  # 本轮 LLM 完整输出（纯文本回答 = 回答全文；工具调用轮 = 输出文本）
    tool_calls: list = Field(default_factory=list)  # 本轮 LLM 声明的工具调用列表 [{name, args, id, type}]

    # 工具相关的字段
    tool: str = ""  # 调用工具的名字
    tool_input: dict = Field(default_factory=dict)  # 工具的输入

    # Agentic 重检轨迹（知识库检索开启 agentic 时：每轮 {round, strategy, query, k, hits, sufficient, score, missing}）
    trace: list = Field(default_factory=list)

    # 交互式选项选择（ask_user 事件专用）
    question: str = ""  # 向用户展示的问题
    options: list[str] = Field(default_factory=list)  # 可选项列表
    allow_custom: bool = True  # 是否允许用户自定义输入
    choice: str = ""  # 用户最终选择（落库回显用）
    # 本地工具调用（local_tool_call 事件专用）：LLM 工具调用的 id，插件回传结果时按此关联
    tool_call_id: str = ""  # 工具调用 id（与 LLM tool_calls 里的 id 一致）
    # 编排器任务分配确认（confirm_plan 事件专用）：子任务方案 [{order, title, role_prompt, expect_output, required_tools}]
    sub_task_options: list[dict] = Field(default_factory=list)

    # 消息的相关数据
    message: list[dict] = Field(default_factory=list)  # 推理使用的消息列表
    message_token_count: int = 0  # 消息话费的token数
    message_unit_price: float = 0  # 单价
    message_price_unit: float = 0  # 价格单位

    # 答案相关数据
    answer: str = ""  # LLM生成的最终答案
    answer_token_count: int = 0  # LLM生产答案的token数
    answer_unit_price: float = 0  # 单价
    answer_price_unit: float = 0  # 价格单位
    reasoning_content: str = ""  # LLM 的推理过程（DeepSeek thinking reasoning_content），跨轮次重建历史时回传用

    # Agent推理统计相关
    total_token_count: int = 0  # 总token消耗数量
    total_price: float = 0  # 总价格
    latency: float = 0  # 步骤推理耗时

    # 编排器子任务相关（桥接事件填充，非编排器事件为空）
    sub_task_id: UUID | None = None  # 所属子任务id
    sub_task_title: str = ""  # 所属子任务标题（前端分组展示用）

    # def to_json_bytes(self) -> bytes:
    #     return (self.model_dump_json(ensure_ascii=False) + "\n").encode("utf-8")
    def to_json(self) -> str:
        return self.model_dump_json(ensure_ascii=False) + "\n"


class AgentResult(BaseModel):
    """智能体推理观察最终结果"""
    query: str = ""  # 原始用户提问
    image_urls: list[str] = Field(default_factory=list)  # 用户的图片输入列表

    message: list[dict] = Field(default_factory=list)  # 产生最终答案的消息列表
    message_token_count: int = 0  # 消息花费的token数
    message_unit_price: float = 0  # 单价
    message_price_unit: float = 0  # 价格单位

    answer: str = ""  # Agent产生的最终答案
    answer_token_count: int = 0  # LLM生成答案的token数
    answer_unit_price: float = 0  # 单价
    answer_price_unit: float = 0  # 价格单位

    total_token_count: int = 0  # 总token消耗数量
    total_price: float = 0  # 总价格
    latency: float = 0  # 总耗时

    status: str = MessageStatus.NORMAL  # 消息的状态
    error: str = ""  # 错误信息

    agent_thoughts: list[AgentThought] = Field(default_factory=list)  # 产生答案的推理步骤
