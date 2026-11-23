#!/usr/bin/env python
"""
@Time    : 2026/2/8 21:49
@Author  : sunxiaojie
@File    : conversation_schema.py
"""
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from internal.core.agent.entities.queue_entity import QueueEvent
from internal.lib.helper import datetime_to_timestamp
from package.paginator import PaginatorReq


class GetConversationMessagesWithPageReq(PaginatorReq):
    """获取指定会话消息列表分页数据请求结构"""
    created_at: int = Field(default=0, ge=0, description="created_at游标最小值为0")


class GetConversationMessagesWithPageResp(BaseModel):
    """获取指定会话消息列表分页数据响应结构"""
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
    is_archived: bool = False
    can_resume: bool = False
    status: str = ""          # 消息状态投影：normal / stop / timeout / error
    run_status: str = ""      # 最新 run 终态：succeeded / cancelled / timed_out / failed / ""(无 run)
    run_id: str = ""          # 最新 run 的 id；run_status=running 时前端据此调 resume 端点重挂
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
                    "sub_task_id": str(agent_thought.sub_task_id) if agent_thought.sub_task_id else None,
                    "sub_task_title": agent_thought.sub_task_title,
                    "task_id": str(getattr(agent_thought, "task_id", None)) if getattr(agent_thought, "task_id", None) else "",
                    "question": (agent_thought.tool_input or {}).get("question", "") if agent_thought.event == QueueEvent.ASK_USER.value else "",
                    "options": (agent_thought.tool_input or {}).get("options", []) if agent_thought.event == QueueEvent.ASK_USER.value else [],
                    "sub_task_options": (agent_thought.tool_input or {}).get("sub_task_options", []) if agent_thought.event == QueueEvent.ASK_USER.value else [],
                    "allow_custom": (agent_thought.tool_input or {}).get("allow_custom", True) if agent_thought.event == QueueEvent.ASK_USER.value else True,
                    "choice": agent_thought.observation if agent_thought.event == QueueEvent.ASK_USER.value else "",
                } for agent_thought in data.agent_thoughts],
                "is_archived": data.is_archived,
                "can_resume": getattr(data, "can_resume", False),
                "status": getattr(data, "status", "") or "",
                "run_status": getattr(data, "run_status", "") or "",
                "run_id": getattr(data, "run_id", "") or "",
                "created_at": datetime_to_timestamp(data.created_at),
            }
        return data


class UpdateConversationNameReq(BaseModel):
    """更新会话名字请求结构体"""
    name: str = Field(description="会话名字长度不能超过100个字符")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v:
            raise ValueError("会话名字不能为空")
        if len(v) > 100:
            raise ValueError("会话名字长度不能超过100个字符")
        return v


class UpdateConversationIsPinnedReq(BaseModel):
    """更新会话置顶选项请求结构体"""
    is_pinned: bool = False


class UpdateMessageFeedbackReq(BaseModel):
    """更新消息反馈请求结构体（'' 取消反馈 / like 点赞 / dislike 点踩）"""
    feedback: str = Field(
        default="",
        max_length=20,
        description="反馈类型长度不能超过20个字符",
    )

    @field_validator("feedback")
    @classmethod
    def validate_feedback(cls, v: str) -> str:
        if v not in ("like", "dislike", ""):
            raise ValueError("反馈类型仅支持 like、dislike 或空字符串")
        return v
