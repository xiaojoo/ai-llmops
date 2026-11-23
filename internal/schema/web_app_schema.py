#!/usr/bin/env python
"""
@Time    : 2026/2/8 20:37
@Author  : sunxiaojie
@File    : web_app_schema.py
"""
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from internal.lib.helper import datetime_to_timestamp


class AppConfigSchema(BaseModel):
    """WebApp 配置结构"""
    opening_statement: str = ""
    opening_questions: list[str] = Field(default_factory=list)
    suggested_after_answer: list[str] = Field(default_factory=list)


class GetWebAppResp(BaseModel):
    """获取WebApp基础信息响应结构"""
    id: UUID | None = None
    icon: str = ""
    name: str = ""
    description: str = ""
    app_config: dict = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if isinstance(data, dict):
            app_config = data.get("app_config", {})
            return {
                "id": data.get("id", ""),
                "icon": data.get("icon", ""),
                "name": data.get("name", ""),
                "description": data.get("description", ""),
                "app_config": {
                    "opening_statement": app_config.get("opening_statement"),
                    "opening_questions": app_config.get("opening_questions"),
                    "suggested_after_answer": app_config.get("suggested_after_answer"),
                    "features": app_config.get("features"),
                    "text_to_speech": app_config.get("text_to_speech"),
                    "speech_to_text": app_config.get("speech_to_text"),
                    "dialog_round": app_config.get("dialog_round"),
                }
            }
        return data


class WebAppChatReq(BaseModel):
    """WebApp对话请求结构体"""
    conversation_id: str = Field(
        default="",
        description="会话id格式必须为uuid",
    )
    query: str = Field(max_length=2000, description="用户提问query不能为空且长度不能超过2000")
    image_urls: list[str] = Field(default_factory=list)
    file_ids: list[str] = Field(default_factory=list)
    resume: bool = False
    resume_message_id: str = Field(
        default="",
        description="断点续跑时被恢复的原始消息id（stop/timeout/error 后重发同 query 续跑时带回，用于按消息定位断点）",
    )
    mode: str = Field(
        default="chat",
        description="对话模式：chat=纯聊天(原 auto) / agent=智能体模式（可操控工作区文件与执行命令）",
    )
    project_root: str = Field(
        default="",
        max_length=1024,
        description="工作区根目录（VS Code 插件传入的当前工作区路径）；agent 模式且目录存在时注入文件系统/命令工具",
    )
    local_tool_runtime: bool = Field(
        default=False,
        description="本地工具运行时：True 时 agent 模式的文件/命令工具不服务器执行，改由插件对本地工作区执行（Remote Agent + Local Tool Runtime）",
    )

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, v: str) -> str:
        if v:
            try:
                UUID(v)
            except ValueError:
                raise ValueError("会话id格式必须为uuid")
        return v

    @field_validator("resume_message_id")
    @classmethod
    def validate_resume_message_id(cls, v: str) -> str:
        if v:
            try:
                UUID(v)
            except ValueError:
                raise ValueError("resume_message_id 格式必须为uuid")
        return v

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("用户提问query不能为空")
        return v

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        # 兼容旧值 auto → chat（纯聊天）
        if v == "auto":
            return "chat"
        if v not in ("chat", "agent"):
            raise ValueError("mode 只能是 chat/agent")
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


class ToolResultReq(BaseModel):
    """本地工具执行结果回传请求（task_id 走 URL 路径，不在 body）"""
    tool_call_id: str = Field(
        ...,
        description="本地工具调用的 id（与 LLM tool_calls 里的 id 一致，用于结果关联）",
    )
    result: str = Field(
        default="",
        max_length=1024 * 1024,
        description="本地工具执行结果（JSON 字符串），服务器作为 ToolMessage 内容回给 LLM",
    )
    error: str = Field(
        default="",
        max_length=10_000,
        description="本地工具执行错误信息（非空时视为失败）",
    )


class CodeActionReq(BaseModel):
    """编辑器选中代码的 AI 操作请求（右键菜单：优化/解释/注释）"""
    action: str = Field(
        ...,
        description="操作类型：optimize(优化) / explain(解释) / comment(注释)",
    )
    code: str = Field(
        ...,
        max_length=100_000,
        description="编辑器中选中的代码内容",
    )
    language: str = Field(
        default="",
        max_length=64,
        description="代码语言（编辑器文件类型，如 python / java），用于提示词",
    )

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in ("optimize", "explain", "comment"):
            raise ValueError("action 只能是 optimize/explain/comment")
        return v

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("代码内容不能为空")
        return v


class CodeActionResp(BaseModel):
    """编辑器选中代码的 AI 操作响应结构体"""
    code: str = ""
    explanation: str = ""


class GetConversationsReq(BaseModel):
    """获取WebApp会话列表请求结构体"""
    is_pinned: bool = False


class GetConversationsResp(BaseModel):
    """获取WebApp会话列表响应结构体"""
    id: UUID | None = None
    name: str = ""
    summary: str = ""
    created_at: int = 0
    dialog_round: int | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data) -> dict:
        if hasattr(data, "summary"):
            return {
                "id": data.id,
                "name": data.name,
                "summary": data.summary,
                "created_at": datetime_to_timestamp(data.created_at),
                "dialog_round": getattr(data, "dialog_round", None),
            }
        return data


class UpdateConversationSettingsReq(BaseModel):
    """更新WebApp会话设置请求结构体（短期记忆窗口轮数）"""
    dialog_round: int | None = Field(
        default=None,
        description="短期记忆窗口轮数（0-100，null=恢复使用应用默认）",
    )

    @field_validator("dialog_round")
    @classmethod
    def validate_dialog_round(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if not isinstance(v, int) or not (0 <= v <= 100):
            raise ValueError("短期记忆窗口轮数范围 0-100")
        return v
