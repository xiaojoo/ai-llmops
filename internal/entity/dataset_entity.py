#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/12/1 18:31
@Author : sunxiaojie
@File   : dataset_entity.py
"""
from enum import Enum

DEFAULT_DATASET_DESCRIPTION_FORMATTER = "当你需要回答关于《{name}》的时候可以引用该知识库。"


class ProcessType(str, Enum):
    """文档处理规则类型枚举"""
    AUTOMATIC = "automatic"
    HEADING = "heading"
    CUSTOM = "custom"


# 默认的处理规则
DEFAULT_PROCESS_RULE = {
    "mode": "custom",
    "rule": {
        "pre_process_rules": [
            {"id": "remove_extra_space", "enable": True},
            {"id": "remove_url_and_email", "enable": True},
        ],
        "segment": {
            "separators": [
                r"\n\n",
                r"\n",
                r"。|！|？",
                r"\.\s|!\s\?\s",
                r"；|;\s",
                r"，|;\s",
                r" ",
                r"",
            ],
            "chunk_size": 500,
            "chunk_overlap": 50,
        },
        # 识别设置：图片/扫描PDF/表格 的处理方式与 OCR 模型选择
        "recognition": {
            "image": True,          # 识别图片（OCR 提取文字）
            "table": True,          # 表格结构化（转 Markdown 表格）
            "pdf_ocr": True,        # 扫描版 PDF 逐页 OCR
            "ocr_provider": "api",  # OCR 模型：local（本地 RapidOCR）/ api（DashScope qwen-vl-ocr）
        }
    }
}


class DocumentStatus(str, Enum):
    """文档状态类型枚举"""
    WAITING = "waiting"
    PARSING = "parsing"
    SPLITTING = "splitting"
    INDEXING = "indexing"
    COMPLETED = "completed"
    ERROR = "error"
    STOPPED = "stopped"


class SegmentStatus(str, Enum):
    """片段状态类型枚举"""
    WAITING = "waiting"
    PARSING = "parsing"
    INDEXING = "indexing"
    COMPLETED = "completed"
    ERROR = "error"


class RetrievalStrategy(str, Enum):
    """检索策略类型枚举"""
    FULL_TEXT = "full_text"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class RetrievalSource(str, Enum):
    """检索来源"""
    HIT_TESTING = "hit_testing"
    APP = "app"
    DEBUGGER= "debugger"
