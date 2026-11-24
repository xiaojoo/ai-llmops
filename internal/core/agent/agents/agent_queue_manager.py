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
from internal.core.telemetry import current_trace_id
from internal.entity.conversation_entity import InvokeFrom
import internal.extensions.redis as redis_mod


def _sync_redis() -> Redis | None:
    """活引用 sync_redis_client：uvicorn lifespan init_redis() 后才赋值；
    from ... import 会在模块加载时快照为 None。"""
    return redis_mod.sync_redis_client


def _is_redis_client(client) -> bool:
    return isinstance(client, Redis)


# 断流定位用三级日志（queue-publish / queue-listen / sse-write）共同忽略的高频事件：
# PING=10s 心跳；AGENT_MESSAGE/AGENT_THOUGHT=LLM 流式 chunk（一答可能上百条，逐条打会刷屏）。
# 其余（LOCAL_TOOL_CALL / ASK_USER / AGENT_ACTION / AGENT_END / ERROR / STOP 等）都是
# 一次一行的粗粒度事件，是判断"ask_user 之后事件到底断在哪一环"的关键标记。
_QUIET_STREAM_EVENTS = frozenset({
    QueueEvent.PING,
    QueueEvent.AGENT_MESSAGE,
    QueueEvent.AGENT_THOUGHT,
})
_TERMINAL_EVENTS = frozenset({
    QueueEvent.STOP,
    QueueEvent.ERROR,
    QueueEvent.TIMEOUT,
    QueueEvent.AGENT_END,
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

    def listen(self, task_id: UUID) -> Generator[AgentThought, None, None]:
        """监听事件；真实 Redis 走跨 worker Stream，否则退回进程内队列。"""
        redis_client = _sync_redis()
        if _is_redis_client(redis_client):
            yield from self._listen_redis(task_id, redis_client)
            return

        listen_timeout = 600
        start_time = time.time()
        last_ping_time = 0
        last_liveness_log = 0.0
        logger.info("[queue-listen] start task=%s invoke=%s", task_id, self.invoke_from)
        while True:
            try:
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
                    if item.event in _TERMINAL_EVENTS:
                        break
            except queue.Empty:
                pass
            finally:
                elapsed = time.time() - start_time
                if elapsed // 10 > last_ping_time:
                    self.publish(task_id, AgentThought(
                        id=uuid.uuid4(), task_id=task_id, event=QueueEvent.PING,
                    ))
                    last_ping_time = elapsed // 10
                if elapsed - last_liveness_log >= 30:
                    last_liveness_log = elapsed
                    logger.info(
                        "[queue-listen] alive task=%s elapsed=%.0fs qsize=%d",
                        task_id, elapsed, self.queue(task_id).qsize(),
                    )
                if elapsed >= listen_timeout:
                    self.publish(task_id, AgentThought(
                        id=uuid.uuid4(), task_id=task_id, event=QueueEvent.TIMEOUT,
                    ))
                if self._is_stopped(task_id):
                    self.publish(task_id, AgentThought(
                        id=uuid.uuid4(), task_id=task_id, event=QueueEvent.STOP,
                    ))

    def _listen_redis(self, task_id: UUID, redis_client: Redis) -> Generator[AgentThought, None, None]:
        listen_timeout = 600
        start_time = time.time()
        last_ping_time = 0
        last_liveness_log = 0.0
        key = self.generate_event_stream_key(task_id)
        cursor_key = self.generate_queue_cursor_key(task_id)
        error_key = self.generate_queue_error_key(task_id)
        try:
            raw_cursor = redis_client.get(cursor_key)
            failures = 0
        except Exception:
            raw_cursor = None
            failures = 1
        last_id = raw_cursor.decode() if isinstance(raw_cursor, bytes) else (raw_cursor or "0-0")
        logger.info("[queue-listen] redis start task=%s key=%s cursor=%s", task_id, key, last_id)
        while True:
            try:
                raw_error = redis_client.get(error_key)
            except Exception:
                raw_error = "read_failed"
            if raw_error:
                yield AgentThought(
                    id=uuid.uuid4(), task_id=task_id, event=QueueEvent.ERROR,
                    observation="Redis 事件写入失败",
                )
                return
            try:
                response = redis_client.xread({key: last_id}, count=100, block=1000)
                failures = 0
            except Exception:
                failures += 1
                logger.warning("[queue-listen] Redis 读取失败 task=%s", task_id, exc_info=True)
                if failures >= 3:
                    yield AgentThought(
                        id=uuid.uuid4(), task_id=task_id, event=QueueEvent.ERROR,
                        observation="Redis 事件通道不可用",
                    )
                    return
                response = None
            for _key, entries in response or []:
                for event_id, fields in entries:
                    last_id = event_id
                    raw = fields.get(b"thought")
                    if not raw:
                        continue
                    try:
                        item = AgentThought.model_validate_json(raw)
                    except Exception:
                        logger.warning("[queue-listen] 事件反序列化失败 task=%s id=%s", task_id, event_id)
                        continue
                    if item.event not in _QUIET_STREAM_EVENTS:
                        logger.info("[queue-listen] redis got task=%s event=%s id=%s",
                                    task_id, item.event.value, item.id)
                    redis_client.set(cursor_key, event_id, ex=1800)
                    yield item
                    if item.event in _TERMINAL_EVENTS:
                        return
            elapsed = time.time() - start_time
            if elapsed // 10 > last_ping_time:
                self.publish(task_id, AgentThought(
                    id=uuid.uuid4(), task_id=task_id, event=QueueEvent.PING,
                ))
                last_ping_time = elapsed // 10
            if elapsed - last_liveness_log >= 30:
                last_liveness_log = elapsed
                logger.info("[queue-listen] redis alive task=%s elapsed=%.0fs", task_id, elapsed)
            if elapsed >= listen_timeout:
                self.publish(task_id, AgentThought(
                    id=uuid.uuid4(), task_id=task_id, event=QueueEvent.TIMEOUT,
                ))
            if self._is_stopped(task_id):
                self.publish(task_id, AgentThought(
                    id=uuid.uuid4(), task_id=task_id, event=QueueEvent.STOP,
                ))

    def stop_listen(self, task_id: UUID) -> None:
        """停止监听。"""
        redis_client = _sync_redis()
        if _is_redis_client(redis_client):
            redis_client.set(self.generate_queue_stop_key(task_id), 1, ex=1800)
            return
        self.queue(task_id).put(None)

    def _publish(self, task_id: UUID, thought: AgentThought, *, terminal: bool) -> None:
        if not thought.model_name:
            thought = thought.model_copy(update={"model_name": self.model_name})
        trace_id = current_trace_id()
        if trace_id and not thought.trace_id:
            thought = thought.model_copy(update={"trace_id": trace_id})
        q = self.queue(task_id)
        redis_client = _sync_redis()
        if _is_redis_client(redis_client):
            try:
                event_id = redis_client.xadd(
                    self.generate_event_stream_key(task_id),
                    {"thought": thought.model_dump_json()},
                )
                redis_client.expire(self.generate_event_stream_key(task_id), 1800)
                if terminal:
                    self.stop_listen(task_id)
                if thought.event not in _QUIET_STREAM_EVENTS:
                    logger.info("[queue-publish] redis task=%s event=%s id=%s stream_id=%s",
                                task_id, thought.event.value, thought.id, event_id)
                return
            except Exception:
                logger.warning("[queue-publish] Redis 写入失败 task=%s", task_id, exc_info=True)
                try:
                    redis_client.set(self.generate_queue_error_key(task_id), "publish_failed", ex=1800)
                except Exception:
                    pass
                return
        q.put(thought)
        if terminal:
            self.stop_listen(task_id)
        if thought.event not in _QUIET_STREAM_EVENTS:
            logger.info(
                "[queue-publish] task=%s event=%s id=%s qsize=%d",
                task_id, thought.event.value, thought.id, q.qsize(),
            )

    def forward(self, task_id: UUID, thought: AgentThought) -> None:
        """桥接事件到目标队列：仅写入，不触发停止语义。"""
        self._publish(task_id, thought, terminal=False)

    def publish(self, task_id: UUID, agent_though: AgentThought) -> None:
        """发布事件（自动补齐模型名，LangSmith 风格轨迹）。"""
        self._publish(task_id, agent_though, terminal=agent_though.event in _TERMINAL_EVENTS)

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
    def generate_event_stream_key(cls, task_id: UUID) -> str:
        return f"gen_task:queue:{task_id!s}"

    @classmethod
    def generate_queue_stop_key(cls, task_id: UUID) -> str:
        return f"gen_task:queue:stop:{task_id!s}"

    @classmethod
    def generate_queue_cursor_key(cls, task_id: UUID) -> str:
        return f"gen_task:queue:cursor:{task_id!s}"

    @classmethod
    def generate_queue_error_key(cls, task_id: UUID) -> str:
        return f"gen_task:queue:error:{task_id!s}"

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
