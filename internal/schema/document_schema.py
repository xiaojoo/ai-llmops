#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/12/2 19:58
@Author : sunxiaojie
@File   : document_schema.py
"""
import uuid
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from internal.entity.dataset_entity import DEFAULT_PROCESS_RULE, ProcessType
from internal.lib.helper import datetime_to_timestamp
from package.paginator import PaginatorReq


class CreateDocumentsReq(BaseModel):
    """创建/新增文档列表请求"""
    upload_file_ids: list[str] = Field(default_factory=list)
    process_type: str = Field(description="文档处理类型不能为空")
    rule: dict = Field(default_factory=dict)

    @field_validator("process_type")
    @classmethod
    def validate_process_type(cls, v: str) -> str:
        valid_values = [ProcessType.AUTOMATIC, ProcessType.HEADING, ProcessType.CUSTOM]
        if v not in valid_values:
            raise ValueError("处理类型格式错误")
        return v

    @field_validator("upload_file_ids")
    @classmethod
    def validate_upload_file_ids(cls, v: list[str]) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("文件id列表格式必须是数组")
        if len(v) == 0 or len(v) > 10:
            raise ValueError("新增的文档数范围在0-10")
        for upload_file_id in v:
            try:
                uuid.UUID(upload_file_id)
            except ValueError:
                raise ValueError(f"文件id的格式必须是UUID：{upload_file_id}")
        # 删除重复数据并保持顺序
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def validate_rule(self):
        """校验上传处理规则"""
        if self.process_type == ProcessType.AUTOMATIC:
            self.rule = DEFAULT_PROCESS_RULE["rule"]
        else:
            if not isinstance(self.rule, dict) or len(self.rule) == 0:
                raise ValueError("自定义处理模式下，rule不能为空")

            # 校验 pre_process_rules
            if "pre_process_rules" not in self.rule or not isinstance(self.rule["pre_process_rules"], list):
                raise ValueError("pre_process_rules必须为列表")

            unique_pre_process_rule_dict = {}
            for pre_process_rule in self.rule["pre_process_rules"]:
                if (
                        "id" not in pre_process_rule
                        or pre_process_rule["id"] not in ["remove_extra_space", "remove_url_and_email"]
                ):
                    raise ValueError("预处理id格式错误")
                if (
                        "enabled" not in pre_process_rule
                        or not isinstance(pre_process_rule["enabled"], bool)
                ):
                    raise ValueError("预处理enabled格式错误")
                unique_pre_process_rule_dict[pre_process_rule["id"]] = {
                    "id": pre_process_rule["id"],
                    "enabled": pre_process_rule["enabled"],
                }

            if len(unique_pre_process_rule_dict) != 2:
                raise ValueError("预处理规则格式错误，请重试")

            self.rule["pre_process_rules"] = list(unique_pre_process_rule_dict.values())

            # 校验 segment
            if "segment" not in self.rule or not isinstance(self.rule["segment"], dict):
                raise ValueError("分段设置不能为空且为字典")

            if "separators" not in self.rule["segment"] or not isinstance(self.rule["segment"]["separators"], list):
                raise ValueError("分隔符列表不能为空且为列表")
            for separator in self.rule["segment"]["separators"]:
                if not isinstance(separator, str):
                    raise ValueError("分隔符列表元素类型错误")
            if len(self.rule["segment"]["separators"]) == 0:
                raise ValueError("分隔符列表不能为空列表")

            if "chunk_size" not in self.rule["segment"] or not isinstance(self.rule["segment"]["chunk_size"], int):
                raise ValueError("分隔符列表不能为空列表")
            if self.rule["segment"]["chunk_size"] < 100 or self.rule["segment"]["chunk_size"] > 1000:
                raise ValueError("分割快大小在100-1000之间")

            if (
                    "chunk_overlap" not in self.rule["segment"]
                    or not isinstance(self.rule["segment"]["chunk_overlap"], int)
            ):
                raise ValueError("块重叠大小不能为空且为整数")

            if not (0 <= self.rule["segment"]["chunk_overlap"] <= self.rule["segment"]["chunk_size"] * 0.5):
                raise ValueError(f"块重叠大小在0-{int(self.rule['segment']['chunk_size'] * 0.5)}")

            # recognition (optional)
            recognition = self.rule.get("recognition")
            if recognition is not None:
                if not isinstance(recognition, dict):
                    raise ValueError("识别设置格式错误")
                for key in ("image", "table", "pdf_ocr"):
                    if key in recognition and not isinstance(recognition[key], bool):
                        raise ValueError(f"识别选项 {key} 必须为布尔值")
                ocr_provider = recognition.get("ocr_provider", "api")
                if ocr_provider not in ("local", "api"):
                    raise ValueError("ocr_provider 仅支持 local / api")
                summary_model = recognition.get("summary_model", "")
                if summary_model and not isinstance(summary_model, str):
                    raise ValueError("summary_model 必须为字符串")

            summary_mode = self.rule["segment"].get("summary_mode", "prefix")
            if summary_mode not in ("llm", "prefix"):
                raise ValueError("summary_mode 仅支持 llm / prefix")

            self.rule = {
                "pre_process_rules": self.rule["pre_process_rules"],
                "segment": {
                    "separators": self.rule["segment"]["separators"],
                    "chunk_size": self.rule["segment"]["chunk_size"],
                    "chunk_overlap": self.rule["segment"]["chunk_overlap"],
                    "summary_mode": summary_mode,
                }
            }
            if recognition is not None:
                self.rule["recognition"] = recognition

            if self.process_type == ProcessType.HEADING:
                self.rule["segment"]["mode"] = "heading"

        return self


class CreateDocumentsResp(BaseModel):
    """创建文档列表响应结构"""
    documents: list[dict] = Field(default_factory=list)
    batch: str = ""

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if isinstance(data, tuple):
            return {
                "documents": [{
                    "id": document.id,
                    "name": document.name,
                    "status": document.status,
                    "create_at": int(document.created_at.timestamp()),
                } for document in data[0]],
                "batch": data[1]
            }
        return data


class GetDocumentResp(BaseModel):
    """获取文档基础信息响应结构"""
    id: UUID | None = None
    dataset_id: UUID | None = None
    name: str = ""
    title: str = ""
    page_count: int = 0
    footer: str = ""
    segment_count: int = 0
    character_count: int = 0
    hit_count: int = 0
    position: int = 0
    enabled: bool = False
    disabled_at: int = 0
    status: str = ""
    error: str = ""
    updated_at: int = 0
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "dataset_id"):
            return {
                "id": data.id,
                "dataset_id": data.dataset_id,
                "name": data.name,
                "title": data.title or "",
                "page_count": data.page_count or 0,
                "footer": data.footer or "",
                "segment_count": data.segment_count,
                "character_count": data.character_count,
                "hit_count": data.hit_count,
                "position": data.position,
                "enabled": data.enabled,
                "disabled_at": datetime_to_timestamp(data.updated_at),
                "status": data.status,
                "error": data.error,
                "updated_at": datetime_to_timestamp(data.updated_at),
                "created_at": datetime_to_timestamp(data.created_at),
            }
        return data


class UpdateDocumentNameReq(BaseModel):
    """更新文档名称/基础信息请求"""
    name: str = Field(description="文档的名称长度不能超过100")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("文档名称不能为空")
        if len(v) > 100:
            raise ValueError("文档的名称长度不能超过100")
        return v


class GetDocumentsWithPageReq(PaginatorReq):
    """获取文档分页列表请求"""
    search_word: str = ""


class GetDocumentsWithPageResp(BaseModel):
    """获取文档分页列表响应结构"""
    id: UUID | None = None
    name: str = ""
    title: str = ""
    page_count: int = 0
    footer: str = ""
    character_count: int = 0
    hit_count: int = 0
    position: int = 0
    enabled: bool = False
    disabled_at: int = 0
    status: str = ""
    error: str = ""
    segment_count: int = 0
    completed_segment_count: int = 0
    updated_at: int = 0
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "dataset_id"):
            return {
                "id": data.id,
                "name": data.name,
                "title": data.title or "",
                "page_count": data.page_count or 0,
                "footer": data.footer or "",
                "character_count": data.character_count,
                "hit_count": data.hit_count,
                "position": data.position,
                "enabled": data.enabled,
                "disabled_at": datetime_to_timestamp(data.updated_at),
                "status": data.status,
                "error": data.error,
                "segment_count": getattr(data, "segment_count", 0),
                "completed_segment_count": getattr(data, "completed_segment_count", 0),
                "updated_at": datetime_to_timestamp(data.updated_at),
                "created_at": datetime_to_timestamp(data.created_at),
            }
        return data


class UpdateDocumentEnableReq(BaseModel):
    """更新文档启用状态请求"""
    enabled: bool = Field(description="enabled状态不能为空且必须为布尔值")
