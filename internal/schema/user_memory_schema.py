#!/usr/bin/env python
"""
@Time   : 2026/8/24
@Author : sunxiaojie
@File   : user_memory_schema.py
"""
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TestMemoryConfigReq(BaseModel):
    """测试腾讯记忆连通性请求结构体（全部可选）。

    - app_id/team_id/agent_id/user_id：作用域（app_id 提供时叠加该应用作用域覆盖）；
    - endpoint/api_key/service_id/admin_key：连接配置覆盖——由系统设置页把当前表单
      值随请求带上来测试（未保存时也可测），**非空才覆盖**，留空回退已保存系统配置。
    """
    app_id: str = ""
    team_id: str = ""
    agent_id: str = ""
    user_id: str = ""
    endpoint: str = ""
    api_key: str = ""
    service_id: str = ""
    admin_key: str = ""


class GetUserMemoryFactsAtReq(BaseModel):
    """按时间点检索用户事实请求结构体"""
    at: int = Field(description="时间点at最小值为0")

    @field_validator("at")
    @classmethod
    def validate_at(cls, v: int) -> int:
        if v is None:
            raise ValueError("时间点at不能为空")
        if v < 0:
            raise ValueError("时间点at最小值为0")
        return v


class GetUserMemoryFactsWindowReq(BaseModel):
    """按时间窗口检索用户事实请求结构体（通告类）"""
    start: int = Field(description="窗口开始时间start最小值为0")
    end: int = Field(description="窗口结束时间end最小值为0")

    @field_validator("start")
    @classmethod
    def validate_start(cls, v: int) -> int:
        if v is None:
            raise ValueError("窗口开始时间start不能为空")
        if v < 0:
            raise ValueError("窗口开始时间start最小值为0")
        return v

    @field_validator("end")
    @classmethod
    def validate_end(cls, v: int) -> int:
        if v is None:
            raise ValueError("窗口结束时间end不能为空")
        if v < 0:
            raise ValueError("窗口结束时间end最小值为0")
        return v


class UserMemoryFactResp(BaseModel):
    """用户事实记忆响应结构"""
    fact_key: str = ""
    fact_value: dict = Field(default_factory=dict)
    source: str = ""
    trust_score: float = 0.0
    confidence: float = 0.0
    is_implicit: bool = False
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    tx_created_at: datetime | None = None
    tx_invalidated_at: datetime | None = None
    status: str = ""

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "fact_key"):
            now = datetime.now()
            if data.valid_to is not None and data.valid_to <= now:
                status = "expired"
            elif data.valid_from > now:
                status = "upcoming"
            else:
                status = "active"
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
                "status": status,
            }
        return data


class EpisodicMemoryResp(BaseModel):
    """情景记忆响应结构"""
    id: UUID | None = None
    content: str = ""
    importance: float = 0.0
    source: str = ""
    trust_score: float = 0.0
    embedding_id: str = ""
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "importance"):
            return {
                "id": data.id,
                "content": data.content,
                "importance": data.importance,
                "source": data.source,
                "trust_score": data.trust_score,
                "embedding_id": data.embedding_id,
                "created_at": data.created_at,
            }
        return data


class ProceduralMemoryResp(BaseModel):
    """程序记忆响应结构"""
    id: UUID | None = None
    content: str = ""
    source: str = ""
    trust_score: float = 0.0
    version: int = 0
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "version"):
            return {
                "id": data.id,
                "content": data.content,
                "source": data.source,
                "trust_score": data.trust_score,
                "version": data.version,
                "created_at": data.created_at,
            }
        return data
