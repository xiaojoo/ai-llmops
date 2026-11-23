#!/usr/bin/env python
"""用户选择提交服务：校验任务归属 → 写入 Redis 选择队列（ask_user 交互）"""
import logging
from dataclasses import dataclass
from uuid import UUID

from redis import Redis

from internal.core.agent.agents import AgentQueueManager
from internal.entity.conversation_entity import InvokeFrom
from internal.exception import ForbiddenException
from internal.model import Account

logger = logging.getLogger(__name__)


@dataclass
class ChoiceService:
    """选择提交服务：Redis 同步客户端，线程安全同步调用，不做线程池桥接"""
    redis_client: Redis

    def assert_task_belong(self, task_id: UUID, account: Account, invoke_from: InvokeFrom) -> None:
        """校验 task_id 归属当前账号：归属键缺失=任务不存在/已过期，不匹配=越权。

        归属键由 AgentQueueManager.queue() 在首次建队时写入（ex=1800，覆盖 run 的 600s 监听期）。
        """
        key = AgentQueueManager.generate_task_belong_cache_key(task_id)
        belong = self.redis_client.get(key)
        if not belong:
            raise ForbiddenException("该任务不存在或已过期")
        user_prefix = "account" if invoke_from in [
            InvokeFrom.WEB_APP, InvokeFrom.DEBUGGER, InvokeFrom.ASSISTANT_AGENT,
        ] else "end-user"
        expected = f"{user_prefix}-{account.id!s}"
        if belong.decode("utf-8") != expected:
            raise ForbiddenException("该任务不存在或不属于当前用户")

    async def submit(self, task_id: UUID, choice: str, skip: bool, account: Account, invoke_from: InvokeFrom, event_id: str | None = None, action: str = "", keep_orders: list | None = None, custom: str = "") -> None:
        """校验 task_id 归属后提交用户选择（event_id 绑定本次 ask_user 事件，防残留载荷污染；
        plan 模式经 action/keep_orders/custom 透传）"""
        self.assert_task_belong(task_id, account, invoke_from)
        ok = AgentQueueManager.submit_choice(
            task_id, choice=choice, skip=skip, event_id=event_id,
            action=action or None, keep_orders=keep_orders or None, custom=custom or None,
        )
        if not ok:
            logger.warning("重复提交用户选择被忽略 task_id=%s", task_id)
        else:
            logger.info(
                "choice 已写入选择队列 task_id=%s event_id=%s choice=%r skip=%s action=%r",
                task_id, event_id, choice, skip, action or "",
            )

    async def submit_tool_result(self, task_id: UUID, tool_call_id: str, result: str, error: str, account: Account, invoke_from: InvokeFrom) -> None:
        """校验任务归属后提交本地工具执行结果（复用 ask_user 的归属校验逻辑）"""
        self.assert_task_belong(task_id, account, invoke_from)
        ok = AgentQueueManager.submit_tool_result(task_id, tool_call_id, result or "", error or "")
        logger.info(
            "submit_tool_result task_id=%s tool_call_id=%s ok=%s result_len=%d",
            task_id, tool_call_id, ok, len(result or ""),
        )
        if not ok:
            logger.warning("提交本地工具结果失败（Redis 未就绪或缺 tool_call_id）task_id=%s", task_id)
