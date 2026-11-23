#!/usr/bin/env python
"""
@Time    : 2026/1/18 17:54
@Author  : sunxiaojie
@File    : assistant_agent_schema.py
"""
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from internal.core.agent.entities.queue_entity import QueueEvent
from internal.lib.helper import datetime_to_timestamp
from package.paginator import PaginatorReq


class AssistantAgentChat(BaseModel):
    """辅助Agent会话请求结构体"""
    image_urls: list[str] = Field(default_factory=list)
    file_ids: list[str] = Field(default_factory=list)
    query: str = Field(max_length=2000, description="用户提问query不能为空且长度不能超过2000")

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("用户提问query不能为空")
        return v

    @field_validator("image_urls")
    @classmethod
    def validate_image_urls(cls, v: list[str]) -> list[str]:
        if not isinstance(v, list):
            return []
        if len(v) > 5:
            raise ValueError("上传的图片数量不能超过5，请核实后重试")
        for image_url in v:
            result = urlparse(image_url)
            if not all([result.scheme, result.netloc]):
                raise ValueError("上传的图片URL地址格式错误，请核实后重试")
        return v

    @field_validator("file_ids")
    @classmethod
    def validate_file_ids(cls, v: list[str]) -> list[str]:
        if not isinstance(v, list):
            return []
        if len(v) > 5:
            raise ValueError("上传的附件文件数量不能超过5，请核实后重试")
        for file_id in v:
            if not isinstance(file_id, str) or not file_id.strip():
                raise ValueError("上传的附件文件ID格式错误，请核实后重试")
        return v


class GetAssistantAgentMessagesWithPageReq(PaginatorReq):
    """获取辅助智能体消息列表分页请求"""
    created_at: int = Field(default=0, ge=0, description="created_at游标最小值为0")


class GetAssistantAgentMessagesWithPageResp(BaseModel):
    """获取辅助智能体消息列表分页响应结构"""
    id: UUID | None = None
    conversation_id: UUID | None = None
    query: str = ""
    image_urls: list[str] = Field(default_factory=list)
    file_urls: list[dict] = Field(default_factory=list)
    answer: str = ""
    total_token_count: int = 0
    latency: float = 0.0
    feedback: str = ""
    agent_thoughts: list[dict] = Field(default_factory=list)
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data) -> dict:
        if hasattr(data, "query"):
            return {
                "id": data.id,
                "conversation_id": data.conversation_id,
                "query": data.query,
                "image_urls": data.image_urls,
                "file_urls": data.file_urls,
                "answer": data.answer,
                "total_token_count": data.total_token_count,
                "latency": data.latency,
                "feedback": data.feedback,
                "agent_thoughts": [{
                    "id": agent_thought.id,
                    "position": agent_thought.position,
                    "event": agent_thought.event,
                    "model_name": agent_thought.model_name,
                    "thought": agent_thought.thought,
                    "observation": agent_thought.observation,
                    "llm_output": agent_thought.llm_output,
                    "tool_calls": agent_thought.tool_calls,
                    "message": agent_thought.message,
                    "tool": agent_thought.tool,
                    "tool_input": agent_thought.tool_input,
                    "trace": agent_thought.trace,
                    "latency": agent_thought.latency,
                    "total_token_count": agent_thought.total_token_count,
                    "total_price": agent_thought.total_price,
                    "created_at": datetime_to_timestamp(agent_thought.created_at),
                    "task_id": str(getattr(agent_thought, "task_id", None)) if getattr(agent_thought, "task_id", None) else "",
                    "question": (agent_thought.tool_input or {}).get("question", "") if agent_thought.event == QueueEvent.ASK_USER.value else "",
                    "options": (agent_thought.tool_input or {}).get("options", []) if agent_thought.event == QueueEvent.ASK_USER.value else [],
                    "sub_task_options": (agent_thought.tool_input or {}).get("sub_task_options", []) if agent_thought.event == QueueEvent.ASK_USER.value else [],
                    "allow_custom": (agent_thought.tool_input or {}).get("allow_custom", True) if agent_thought.event == QueueEvent.ASK_USER.value else True,
                    "choice": agent_thought.observation if agent_thought.event == QueueEvent.ASK_USER.value else "",
                } for agent_thought in data.agent_thoughts],
                "created_at": datetime_to_timestamp(data.created_at),
            }
        return data
