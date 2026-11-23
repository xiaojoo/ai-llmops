#!/usr/bin/env python
"""
@Time    : 2026/3/21 22:49
@author  : sunxiaojie
@File    : feishu_handler.py
"""
from dataclasses import dataclass

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from internal.service import FeishuService
from package.response import success_json


@dataclass
class FeishuHandler:
    """飞书机器人处理器"""
    feishu_service: FeishuService

    async def webhook(self, request: Request) -> None:
        """飞书事件回调入口"""
        try:
            body = await request.json()
        except Exception:
            body = {}

        # 飞书服务器验证（配置 Webhook URL 时发一次 url_verification）
        if body.get("type") == "url_verification":
            return success_json({"challenge": body.get("challenge")})

        # I3: handle_event 同步方法经 run_in_threadpool 桥接
        await run_in_threadpool(self.feishu_service.handle_event, body)

        return success_json({})
