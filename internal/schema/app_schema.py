#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/15 14:41
@Author : sunxiaojie
@File   : app_schema.py
"""
import re
from datetime import datetime
from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_serializer, field_validator, model_validator

from internal.core.agent.entities.queue_entity import QueueEvent
from internal.entity.app_entity import AppStatus
from internal.lib.helper import datetime_to_timestamp
from package.paginator import PaginatorReq


class CreateAppReq(BaseModel):
    """创建Agent应用请求结构体"""
    name: str = Field(description="应用名称最大长度为40字符")
    icon: str = Field(description="应用图标必须是图片URL链接")
    description: str = Field(default="", description="应用描述信息不能超过800字符")
    app_type: str = Field(default="agent", description="应用类型仅支持 agent 或 orchestrator")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("应用名称不能为空")
        if len(v) > 40:
            raise ValueError("应用名称最大长度为40字符")
        return v

    @field_validator("icon")
    @classmethod
    def validate_icon(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("应用图标不能为空")
        result = urlparse(v)
        if not all([result.scheme, result.netloc]):
            raise ValueError("应用图标必须是图片URL链接")
        return v

    @field_validator("app_type")
    @classmethod
    def validate_app_type(cls, v: str) -> str:
        if v not in ("agent", "orchestrator"):
            raise ValueError("应用类型仅支持 agent 或 orchestrator")
        return v


class UpdateAppReq(BaseModel):
    """更新Agent应用请求结构体"""
    name: str = Field(description="应用名称最大长度为40字符")
    icon: str = Field(description="应用图标必须是图片URL链接")
    description: str = Field(default="", description="应用描述信息不能超过800字符")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("应用名称不能为空")
        if len(v) > 40:
            raise ValueError("应用名称最大长度为40字符")
        return v

    @field_validator("icon")
    @classmethod
    def validate_icon(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("应用图标不能为空")
        result = urlparse(v)
        if not all([result.scheme, result.netloc]):
            raise ValueError("应用图标必须是图片URL链接")
        return v


class GetAppsWithPageReq(PaginatorReq):
    """获取应用分页列表数据请求"""
    search_word: str = ""


class GetAppsWithPageResp(BaseModel):
    """获取应用分页列表数据响应结构"""
    id: UUID | None = None
    name: str = ""
    icon: str = ""
    description: str = ""
    preset_prompt: str = ""
    model_config_data: dict = Field(default_factory=dict, alias="model_config")
    status: str = ""
    updated_at: int = 0
    created_at: int = 0
    token: str = ""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data) -> dict:
        if hasattr(data, "app_config"):
            app_config = data.app_config if data.status == AppStatus.PUBLISHED.value else data.draft_app_config
            mc = dict(app_config.model_config)
            return {
                "id": data.id,
                "name": data.name,
                "icon": data.icon,
                "description": data.description,
                "preset_prompt": app_config.preset_prompt,
                "model_config": {
                    "provider": mc.get("provider", ""),
                    "model": mc.get("model", "")
                },
                "status": data.status,
                "updated_at": datetime_to_timestamp(data.updated_at),
                "created_at": datetime_to_timestamp(data.created_at),
                "token": getattr(data, "token", ""),
            }
        return data


TimestampInt = Annotated[int, BeforeValidator(datetime_to_timestamp)]


class GetAppResp(BaseModel):
    """获取应用基础信息响应结构"""
    id: UUID | None = None
    debug_conversation_id: UUID | None = None
    name: str = ""
    icon: str = ""
    description: str = ""
    status: str = ""
    app_type: str = "agent"
    draft_updated_at: TimestampInt = 0
    updated_at: TimestampInt = 0
    created_at: TimestampInt = 0

    model_config = ConfigDict(from_attributes=True)


class GetPublishHistoriesWithPageReq(PaginatorReq):
    """获取应用发布历史配置分页列表请求"""
    pass


class GetPublishHistoriesWithPageResp(BaseModel):
    """获取应用发布历史配置列表分页数据"""
    id: UUID = Field(default_factory=UUID)
    version: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at", return_type=int)
    def serialize_created_at(self, value: datetime, _info):
        return datetime_to_timestamp(value)


class FallbackHistoryToDraftReq(BaseModel):
    """回退历史版本到草稿请求结构体"""
    app_config_version_id: str = Field(description="回退配置版本id不能为空")

    @field_validator("app_config_version_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("回退配置版本id不能为空")
        try:
            UUID(v)
        except ValueError:
            raise ValueError("回退配置版本id必须为UUID")
        return v


class UpdateDebugConversationSummaryReq(BaseModel):
    """更新应用调试会话长期记忆请求体"""
    summary: str = ""


class DebugChatReq(BaseModel):
    """应用调试会话请求结构体"""
    image_urls: list[str] = Field(default_factory=list)
    file_ids: list[str] = Field(default_factory=list)
    query: str = Field(max_length=2000, description="用户提问query不能为空且长度不能超过2000")
    resume: bool = False
    resume_message_id: str = Field(
        default="",
        description="断点续跑时被恢复的原始消息id（stop/timeout/error 后重发同 query 续跑时带回，用于按消息定位断点）",
    )

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


class GetDebugConversationMessagesWithPageReq(PaginatorReq):
    """获取调试会话消息列表分页请求结构体"""
    created_at: int = Field(default=0, ge=0, description="created_at游标最小值为0")


class GetDebugConversationMessagesWithPageResp(BaseModel):
    """获取调试会话消息列表分页响应结构体"""
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
