#!/usr/bin/env python
"""
@Time    : 2025/12/13 20:50
@Author  : sunxiaojie
@File    : agent_queue_manager.py
"""
import json
import logging
import queue
import time
import uuid
from collections.abc import Generator
from queue import Queue
from uuid import UUID

from redis import Redis

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.conversation_entity import InvokeFrom
import internal.extensions.redis as redis_mod


def _sync_redis() -> Redis | None:
    """活引用 sync_redis_client：uvicorn lifespan init_redis() 后才赋值；
    from ... import 会在模块加载时快照为 None。"""
    return redis_mod.sync_redis_client


# 断流定位用三级日志（queue-publish / queue-listen / sse-write）共同忽略的高频事件：
# PING=10s 心跳；AGENT_MESSAGE/AGENT_THOUGHT=LLM 流式 chunk（一答可能上百条，逐条打会刷屏）。
# 其余（LOCAL_TOOL_CALL / ASK_USER / AGENT_ACTION / AGENT_END / ERROR / STOP 等）都是
# 一次一行的粗粒度事件，是判断"ask_user 之后事件到底断在哪一环"的关键标记。
_QUIET_STREAM_EVENTS = frozenset({
    QueueEvent.PING,
    QueueEvent.AGENT_MESSAGE,
    QueueEvent.AGENT_THOUGHT,
})

logger = logging.getLogger(__name__)


class AgentQueueManager:
    """智能体队列管理器"""
    user_id: UUID
    invoke_from: InvokeFrom
    redis_client: Redis
    # 进程级共享的任务事件队列（按 task_id 键）：让"断流后重连"的续传端点能
    # 取到在跑的 run 已经发布、但原 SSE 消费者已断开的事件。task_id 全局唯一，跨实例共享安全。
    _queues: dict[str, Queue] = {}

    def __init__(
            self,
            user_id: UUID,
            invoke_from: InvokeFrom,
            model_name: str = "",
    ) -> None:
        self.user_id = user_id
        self.invoke_from = invoke_from
        self.model_name = model_name
        # 注意：不在此设置 self._queues —— 用上面类级共享字典，续传端点才能复用同一批队列。
        # 一旦在此写 self._queues = {} 会造成实例私有队列，断流后新事件进的是原实例队列，
        # 续传端点（新实例）取不到，导致事件丢失。
        # 使用 internal.extensions.redis 模块级单例（活引用）。
        # 注意：不在此快照 redis_client——base_agent 可能在 uvicorn lifespan init_redis()
        # 之前构造（模块加载期），快照会把 None 锁死。所有使用点运行时经 _sync_redis() 活引用。

    def listen(self, task_id: UUID) -> Generator[str, None, None]:
        """监听队列返回生成式数据"""
        # 1、定义基础数据记录超时时间、开始时间、最后一次ping通时间
        listen_timeout = 600  # 10分钟超时
        start_time = time.time()
        last_ping_time = 0
        last_liveness_log = 0.0
        logger.info("[queue-listen] start task=%s invoke=%s", task_id, self.invoke_from)
        # 2、创建循环队列执行死循环读取数据，直到超时或者数据读取完毕
        while True:
            try:
                # 3、从队列中提取数据并检测数据是否存在，如果存在则使用yield返回
                item = self.queue(task_id).get(timeout=1)
                if item is None:
                    logger.info("[queue-listen] end task=%s elapsed=%.1fs (收到停止哨兵 None)",
                                task_id, time.time() - start_time)
                    break
                if isinstance(item, AgentThought):
                    if item.event not in _QUIET_STREAM_EVENTS:
                        logger.info(
                            "[queue-listen] got task=%s event=%s id=%s qsize=%d",
                            task_id, item.event.value, item.id, self.queue(task_id).qsize(),
                        )
                    yield item

            except queue.Empty:
                continue
            finally:
                # 4、计算获取数据的总耗时
                elapsed_time = time.time() - start_time
                # 5、每10秒发起一个ping请求
                if elapsed_time // 10 > last_ping_time:
                    self.publish(task_id, AgentThought(
                        id=uuid.uuid4(),
                        task_id=task_id,
                        event=QueueEvent.PING,
                    ))
                    last_ping_time = elapsed_time // 10
                # 5.1、每 30s 记一条活性日志：ask_user 等人为等待最长 300s，
                #      有活性日志才能区分"生成器还活着在空转"vs"生成器已死、事件堆积没人消费"
                if elapsed_time - last_liveness_log >= 30:
                    last_liveness_log = elapsed_time
                    logger.info(
                        "[queue-listen] alive task=%s elapsed=%.0fs qsize=%d",
                        task_id, elapsed_time, self.queue(task_id).qsize(),
                    )
                # 6、判断总耗时是否超时，如果超时则往队列中添加超时事件
                if elapsed_time >= listen_timeout:
                    self.publish(task_id, AgentThought(
                        id=uuid.uuid4(),
                        task_id=task_id,
                        event=QueueEvent.TIMEOUT,
                    ))
                # 7、检测是否停止，如果已经停止则添加停止事件
                if self._is_stopped(task_id):
                    self.publish(task_id, AgentThought(
                        id=uuid.uuid4(),
                        task_id=task_id,
                        event=QueueEvent.STOP,
                    ))

    def stop_listen(self, task_id: UUID) -> None:
        """停止监听"""
        self.queue(task_id).put(None)

    def forward(self, task_id: UUID, thought: AgentThought) -> None:
        """桥接事件到目标队列：仅写入，不触发 stop_listen 语义。"""
        if not thought.model_name:
            thought = thought.model_copy(update={"model_name": self.model_name})
        self.queue(task_id).put(thought)

    def publish(self, task_id: UUID, agent_though: AgentThought) -> None:
        """发布事件（自动补齐模型名，LangSmith 风格轨迹）"""
        if not agent_though.model_name:
            agent_though = agent_though.model_copy(update={"model_name": self.model_name})
        q = self.queue(task_id)
        q.put(agent_though)
        if agent_though.event in [QueueEvent.STOP, QueueEvent.ERROR, QueueEvent.TIMEOUT, QueueEvent.AGENT_END]:
            self.stop_listen(task_id)
        if agent_though.event not in _QUIET_STREAM_EVENTS:
            logger.info(
                "[queue-publish] task=%s event=%s id=%s qsize=%d",
                task_id, agent_though.event.value, agent_though.id, q.qsize(),
            )

    def publish_error(self, task_id: UUID, error) -> None:
        """发布错误信息到队列"""
        self.publish(task_id, AgentThought(
            id=uuid.uuid4(),
            task_id=task_id,
            event=QueueEvent.ERROR,
            observation=str(error),
        ))

    def _is_stopped(self, task_id: UUID) -> bool:
        """检测任务是否停止"""
        # Redis exists 接收的是 Key，返回 1 或 0
        task_stopped_cache_key = self.generate_task_stopped_cache_key(task_id)
        # 活引用（构造时可能早于 init_redis）；redis 未就绪视为未停止
        redis_client = _sync_redis()
        if redis_client is None:
            return False
        # 只要这个 key 存在，就代表任务被标记为停止了
        return redis_client.exists(task_stopped_cache_key) > 0

    def queue(self, task_id: UUID) -> Queue:
        """根据传递的task_id获取对应的任务队列信息"""
        # 1、从队列字典中获取对应的任务队列
        q = self._queues.get(str(task_id))
        # 2、检测队列是否存在，如果不存在则创建队列，并添加缓存键标识
        if not q:
            user_prefix = "account" if self.invoke_from in [
                InvokeFrom.WEB_APP,
                InvokeFrom.DEBUGGER,
                InvokeFrom.ASSISTANT_AGENT,
            ] else "end-user"
            # 活引用（构造时可能早于 init_redis）；redis 未就绪时跳过缓存键（不影响内存队列）
            redis_client = _sync_redis()
            if redis_client is not None:
                redis_client.set(
                    self.generate_task_belong_cache_key(task_id),
                    f"{user_prefix}-{self.user_id!s}",
                    ex=1800,
                )
            # 将任务队列添加到队列字典中
            q = Queue()
            self._queues[str(task_id)] = q

        return q

    @classmethod
    def set_stop_flag(cls, task_id: UUID, invoke_from: InvokeFrom, user_id: UUID) -> None:
        """根据传递的任务id+调用来源停止某次会话"""
        # 使用模块级单例（活引用）
        redis_client = _sync_redis()
        if redis_client is None:
            return

        # 1、获取当前任务的缓存键，如果任务没执行，则不需要停止
        result = redis_client.get(cls.generate_task_belong_cache_key(task_id))
        if not result:
            return

        # 2、计算对应缓存键的结果
        user_prefix = "account" if invoke_from in [
            InvokeFrom.WEB_APP,
            InvokeFrom.DEBUGGER,
            InvokeFrom.ASSISTANT_AGENT,
        ] else "end-user"
        if result.decode("utf-8") != f"{user_prefix}-{user_id!s}":
            return
        # 3、生成停止标识
        stopped_cache_key = cls.generate_task_stopped_cache_key(task_id)
        redis_client.set(stopped_cache_key, 1, ex=600)

    @classmethod
    def generate_task_belong_cache_key(cls, task_id: UUID) -> str:
        return f"gen_task:belong:{task_id!s}"

    @classmethod
    def generate_task_stopped_cache_key(cls, task_id: UUID) -> str:
        return f"gen_task:stopped:{task_id!s}"

    @classmethod
    def generate_choice_queue_key(cls, task_id: UUID) -> str:
        """生成用户选择队列 key"""
        return f"gen_task:choice:{task_id!s}"

    @classmethod
    def generate_tool_result_queue_key(cls, task_id: UUID) -> str:
        """生成本地工具结果队列 key"""
        return f"gen_task:toolresult:{task_id!s}"

    @classmethod
    def submit_tool_result(cls, task_id: UUID, tool_call_id: str, result: str, error: str = "") -> bool:
        """提交本地工具执行结果到 Redis 队列；同一 task_id 内按键过滤消费，天然忽略残留旧结果。"""
        redis_client = _sync_redis()
        if redis_client is None:
            return False
        if not tool_call_id:
            return False
        key = cls.generate_tool_result_queue_key(task_id)
        payload = {"tool_call_id": tool_call_id, "result": result, "error": error}
        redis_client.rpush(key, json.dumps(payload, ensure_ascii=False))
        redis_client.expire(key, 1800)
        return True

    @classmethod
    def wait_for_tool_result(cls, task_id: UUID, tool_call_id: str, timeout: int = 300) -> tuple[str, str]:
        """阻塞等待本地工具执行结果：返回 (result, error)；超时/异常按 (超时错误, 错误) 处理。"""
        redis_client = _sync_redis()
        if redis_client is None:
            return "", "本地工具结果通道未就绪"
        if not tool_call_id:
            return "", "缺失 tool_call_id"
        key = cls.generate_tool_result_queue_key(task_id)
        deadline = time.time() + timeout
        while True:
            remaining = max(0, int(deadline - time.time()))
            if remaining <= 0:
                return "", "本地工具执行超时"
            try:
                item = redis_client.blpop(key, timeout=min(remaining, 1))
            except Exception:  # noqa: BLE001
                return "", "本地工具结果通道异常"
            if not item:
                continue
            try:
                payload = json.loads(item[1])
            except (TypeError, ValueError):
                continue
            if payload.get("tool_call_id") != tool_call_id:
                continue  # 残留载荷，丢弃继续等
            return payload.get("result") or "", payload.get("error") or ""

    @classmethod
    def submit_choice(cls, task_id: UUID, choice: str | None = None, skip: bool = False, event_id: str | None = None,
                      action: str | None = None, keep_orders: list[int] | None = None, custom: str | None = None) -> bool:
        """提交用户选择到 Redis 队列；同一 task_id 已有未消费选择时忽略（幂等）"""
        redis_client = _sync_redis()
        if redis_client is None:
            return False
        key = cls.generate_choice_queue_key(task_id)
        if redis_client.exists(key) and redis_client.llen(key) > 0:
            return False
        payload = {
            "choice": choice,
            "skip": skip,
            "event_id": str(event_id) if event_id else "",
        }
        if action is not None:
            payload["action"] = action
        if keep_orders is not None:
            payload["keep_orders"] = keep_orders
        if custom is not None:
            payload["custom"] = custom
        redis_client.rpush(key, json.dumps(payload, ensure_ascii=False))
        redis_client.expire(key, 1800)
        return True

    @classmethod
    def wait_for_choice(cls, task_id: UUID, timeout: int = 300, event_id: str | None = None) -> tuple[str | None, bool, str]:
        """阻塞等待用户选择：返回 (choice, skipped, custom)；超时/异常按跳过处理。"""
        redis_client = _sync_redis()
        if redis_client is None:
            return None, True, ""  # redis 未就绪按跳过处理
        key = cls.generate_choice_queue_key(task_id)
        deadline = time.time() + timeout
        while True:
            remaining = max(0, int(deadline - time.time()))
            if remaining <= 0:
                return None, True, ""
            try:
                item = redis_client.blpop(key, timeout=min(remaining, 1))
            except Exception:  # noqa: BLE001
                return None, True, ""
            if not item:
                continue
            try:
                payload = json.loads(item[1])
            except (TypeError, ValueError):
                continue
            if event_id is not None and payload.get("event_id") != event_id:
                continue
            return payload.get("choice"), bool(payload.get("skip", False)), payload.get("custom") or ""

    @classmethod
    def wait_for_plan_choice(cls, task_id: UUID, timeout: int = 300, event_id: str | None = None) -> tuple[str, list[int], str, bool]:
        """等待任务分配确认：返回 (action, keep_orders, custom, skipped)。"""
        redis_client = _sync_redis()
        if redis_client is None:
            return "confirm", [], "", True  # redis 未就绪按跳过处理
        key = cls.generate_choice_queue_key(task_id)
        deadline = time.time() + timeout
        while True:
            remaining = max(0, int(deadline - time.time()))
            if remaining <= 0:
                return "confirm", [], "", True
            try:
                item = redis_client.blpop(key, timeout=min(remaining, 1))
            except Exception:  # noqa: BLE001 - Redis 异常统一按跳过处理
                return "confirm", [], "", True
            if not item:
                continue
            try:
                payload = json.loads(item[1])
            except (TypeError, ValueError):
                continue
            if event_id is not None and payload.get("event_id") != event_id:
                continue  # 残留载荷，丢弃继续等
            return (
                payload.get("action") or "confirm",
                payload.get("keep_orders") or [],
                payload.get("custom") or "",
                bool(payload.get("skip", False)),
            )
