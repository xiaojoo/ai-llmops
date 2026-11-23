#!/usr/bin/env python
"""腾讯记忆客户端：唯一接触 TencentDB-Agent-Memory SDK 的模块（懒加载）。

SDK 确切 API 以 Task 6 Step 1 验证结果为准（GitHub TencentCloud/TencentDB-Agent-Memory
v2.0.1 tag 源码）：PyPI 包名 tencentdb-agent-memory-sdk-python-v2（README 称发布名为
tencentdb-agent-memory-sdk-python，PyPI 发布状态待用户机器确认），Python 模块
tencentdb_agent_memory，同步客户端 MemoryClient(endpoint, api_key, service_id)。
与下列代码不一致时仅修改本文件方法体（类名/方法名/参数），
recall / write_round 接口与 TencentMemoryProvider 保持不变。
SDK 缺失时构造抛 ImportError，由 TencentMemoryProvider 捕获回退为无记忆。
"""
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class TencentMemoryClient(ABC):
    """内部客户端接口：TencentMemoryProvider 只依赖此接口"""

    @abstractmethod
    def recall(self, query: str, top_k: int = 5) -> list[dict]:
        """记忆召回，返回 [{type: "core"|"scene", content: str, score: float}, ...]"""

    @abstractmethod
    def write_round(self, query: str, answer: str) -> None:
        """写入一轮对话并触发记忆流水线（提取→整合→反思→复盘）"""


class SdkTencentMemoryClient(TencentMemoryClient):
    """基于 TencentDB-Agent-Memory SDK 的实现（懒加载，SDK 缺失抛 ImportError）"""

    def __init__(
            self,
            endpoint: str,
            api_key: str,
            service_id: str,
            *,
            session_id: str = "default",
            team_id: str | None = None,
            agent_id: str | None = None,
            user_id: str | None = None,
            task_id: str | None = None,
    ):
        # 懒加载：SDK 未安装时抛 ImportError（包名以 Task 6 验证结果为准）
        from tencentdb_agent_memory import MemoryClient  # noqa: PLC0415
        self._client = MemoryClient(endpoint=endpoint, api_key=api_key, service_id=service_id)
        self._session_id = session_id
        # 作用域：对齐 Panel 可见的 team/agent/user（None 时 SDK 走默认 "default"）
        self._scope = {
            "team_id": team_id,
            "agent_id": agent_id,
            "user_id": user_id,
            "task_id": task_id,
        }

    def recall(self, query: str, top_k: int = 5) -> list[dict]:
        # L1 原子记忆检索：search_atomic 返回 {"items": [{id, type, content, score, ...}]}
        # 空 query 时 search_atomic 会 400，改用 query_atomic 拉最近记忆
        if query and query.strip():
            result = self._client.search_atomic(query=query, limit=top_k, **self._scope)
        else:
            result = self._client.query_atomic(limit=top_k, **self._scope)
        items = result.get("items", []) if isinstance(result, dict) else []
        return [
            {
                "type": item.get("type", "scene"),
                "content": item.get("content", ""),
                "score": item.get("score", 0.0),
            }
            for item in items
        ]

    def write_round(self, query: str, answer: str) -> None:
        # L0 写入本轮 user/assistant 消息，服务端异步触发记忆流水线
        self._client.add_conversation(
            session_id=self._session_id,
            messages=[
                {"role": "user", "content": query},
                {"role": "assistant", "content": answer},
            ],
            **self._scope,
        )
