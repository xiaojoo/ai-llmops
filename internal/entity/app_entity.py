#!/usr/bin/env python
"""
@Time    : 2025/12/23 22:31
@Author  : sunxiaojie
@File    : app_entity.py
"""
from enum import Enum

class AppStatus(str, Enum):
    """应用状态枚举类"""
    DRAFT = "draft"
    PUBLISHED = "published"


class AppConfigType(str, Enum):
    """应用配置枚举类"""
    DRAFT = "draft"
    PUBLISHED = "published"


# 应用默认配置信息
DEFAULT_APP_CONFIG = {
    "model_config": {
        # "provider": "gpt_4o-mini",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "parameters": {
            "temperature": 0.5,
            "top_p": 0.85,
            "frequency_penalty": 0.2,
            "presence_penalty": 0.2,
            "max_tokens": 8192
        }
    },
    "dialog_round": 3,
    "preset_prompt": "",
    "tools": [],
    "skills": [],
    "workflows": [],
    "datasets": [],
    "retrieval_config": {
        "retrieval_strategy": "semantic",
        "k": 10,
        "score": 0.5,
    },
    "long_term_memory": {
        "enable": False,
    },
    "opening_statement": "",
    "opening_questions": [],
    "speech_to_text": {
        "enable": False,
    },
    "text_to_speech": {
        "enable": False,
        "voice": "echo",
        "auto_play": False,
    },
    "suggested_after_answer": {
        "enable": True,
    },
    "orchestrator_config": {
        "enable": False,          # 是否启用任务分解
        "max_sub_tasks": 5,       # 子任务数上限
        "max_parallel": 3,        # 最大并行数
        "sub_task_timeout": 300,  # 单子任务超时(秒)
        "resume_mode": "auto",    # 断点恢复触发：auto 自动续跑 / manual 仅显式触发
        "auto_replan_on_failure": True,  # 子任务 error/timeout 时自动重拆计划（与人工重拆共用 2 轮上限）
        # 编排引擎：空 = 跟随系统设置的全局默认（ORCHESTRATOR_ENGINE）；
        # subtask = 默认引擎 / guarded = 带预算熔断的引擎
        "engine": "",
        # 预算上限，仅 guarded 引擎读取；0 = 该项不限
        "budget": {
            "max_total_tokens": 0,
            "max_total_price": 0.0,
            "max_wall_clock_seconds": 0,
            "max_dispatched_sub_tasks": 0,
        },
    },
    "review_config": {
        "enable": False,
        "keywords": [],
        "inputs_config": {
            "enable": False,
            "preset_response": ""
        },
        "outputs_config": {
            "enable": False,
        }
    }
}
