#!/usr/bin/env python
"""
@Time    : 2026/3/21 22:50
@Author  : sunxiaojie
@File    : feishu_service.py
"""
# -*- coding: utf-8 -*-
import json
import os
import threading
from dataclasses import dataclass, field

import requests

from internal.config.settings import get_settings


@dataclass
class FeishuService:
    """飞书机器人服务"""

    # 飞书应用配置（从环境变量读取）
    feishu_app_id: str = field(default_factory=lambda: os.environ.get("FEISHU_APP_ID", ""))
    feishu_app_secret: str = field(default_factory=lambda: os.environ.get("FEISHU_APP_SECRET", ""))

    # 飞书开放平台基础地址（系统设置，默认 https://open.feishu.cn/open-apis）
    feishu_open_api_base: str = field(default_factory=lambda: get_settings().feishu_open_api_base)

    # LLMOps 配置
    llmops_base_url: str = field(default_factory=lambda: os.environ.get("LLMOPS_BASE_URL", "http://localhost:5000"))
    llmops_app_id: str = field(default_factory=lambda: os.environ.get("LLMOPS_APP_ID", ""))
    llmops_access_token: str = field(default_factory=lambda: os.environ.get("LLMOPS_ACCESS_TOKEN", ""))

    # 用飞书 open_id 隔离不同用户的 conversation_id（多轮对话）
    _user_conversation_map: dict = field(default_factory=dict)
    # 同一用户串行处理，防止并发乱序
    _user_lock_map: dict = field(default_factory=dict)

    # ── 公开方法 ──────────────────────────────────────────

    def handle_event(self, body: dict):
        """
        解析飞书事件，只处理文本消息，其余事件直接忽略。
        在后台线程处理，调用方可立即返回 200。
        """
        header = body.get("header", {})
        if header.get("event_type") != "im.message.receive_v1":
            return

        event = body.get("event", {})
        message = event.get("message", {})

        if message.get("message_type") != "text":
            return

        try:
            content = json.loads(message.get("content", "{}"))
            query = content.get("text", "").strip()
        except (json.JSONDecodeError, AttributeError):
            return

        if not query:
            return

        open_id = event.get("sender", {}).get("sender_id", {}).get("open_id", "")
        if not open_id:
            return

        # 后台线程处理，避免飞书 3 秒超时
        thread = threading.Thread(target=self._process_message, args=(open_id, query))
        thread.daemon = True
        thread.start()

    def reset_conversation(self, open_id: str):
        """清除指定用户的会话，下次对话将开启新会话"""
        self._user_conversation_map.pop(open_id, None)

    # ── 私有方法 ──────────────────────────────────────────

    def _process_message(self, open_id: str, query: str):
        """在后台线程中：调用 LLMOps → 回复飞书"""
        if open_id not in self._user_lock_map:
            self._user_lock_map[open_id] = threading.Lock()

        with self._user_lock_map[open_id]:
            answer = self._chat_with_llmops(open_id, query)
            self._send_feishu_message(open_id, answer)

    def _chat_with_llmops(self, open_id: str, query: str) -> str:
        """
        调用 LLMOps SSE 流式接口，拼接完整回答后返回。
        自动维护每个用户的 conversation_id 实现多轮对话。
        """
        conversation_id = self._user_conversation_map.get(open_id, "")

        url = f"{self.llmops_base_url}/web_apps/{self.llmops_app_id}/chat"
        # url = f"{self.llmops_base_url}/openapi/chat"
        headers = {
            "Authorization": f"Bearer {self.llmops_access_token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        body = {
            "query": query,
            "conversation_id": conversation_id,
            "image_urls": [],
        }

        # body = {
        #     "app_id": "bf35bac7-070d-4ae2-917b-f405d5f00c68",
        #     "query": query,
        #     "stream": 'false',
        # }

        full_answer = ""
        new_conversation_id = conversation_id

        try:
            with requests.post(url, headers=headers, json=body, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line

                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if not data_str:
                        continue

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event = data.get("event", "")

                    if data.get("conversation_id"):
                        new_conversation_id = data["conversation_id"]

                    if event == "agent_message":
                        full_answer += data.get("answer", "")

                    if event == "agent_end":
                        break

        except requests.RequestException as e:
            return f"调用 AI 服务失败：{e}"

        # 保存 conversation_id，维持多轮对话
        if new_conversation_id:
            self._user_conversation_map[open_id] = new_conversation_id

        return full_answer.strip() or "（AI 未返回内容）"

    def _get_feishu_token(self) -> str:
        """获取飞书 tenant_access_token"""
        resp = requests.post(
            f"{self.feishu_open_api_base}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.feishu_app_id, "app_secret": self.feishu_app_secret},
            timeout=10,
        )
        return resp.json().get("tenant_access_token", "")

    def _send_feishu_message(self, open_id: str, text: str):
        """调用飞书 API 回复消息"""
        token = self._get_feishu_token()
        requests.post(
            f"{self.feishu_open_api_base}/im/v1/messages?receive_id_type=open_id",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": open_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
            timeout=10,
        )