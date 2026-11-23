#!/usr/bin/env python
"""
@Time    : 2026/9/7
@Author  : sw
@File    : event_replay.py

SSE 事件缓冲 + Last-Event-ID 重放（服务器端为主流"断线续传"方案准备的地基）。

背景
----
插件(本地工具运行时)通过一个长连接的 SSE 流接收 `local_tool_call` 等事件并回传结果。
该长连接一旦被硬断（服务器连接异常 / uvicorn 回收 / 网络抖动，SSE 规范里用 `id:` +
`Last-Event-ID` 处理），后续事件会丢失 → 服务器 `wait_for_tool_result` 只能超时。

本模块提供按 run_id 的已发 SSE 事件日志，支持按 Last-Event-ID 游标续读：
  * `record(run_id, seq, frame, thought)`  记录一条已发帧（含其 AgentThought 对象）
  * `history_after(run_id, last_seq)`      返回 seq > last_seq 的帧（按原顺序）
  * `history_thoughts_after(...)`          同上但返回 AgentThought 对象，供续传侧落库
  * `last_seq(run_id)` / `clear(run_id)`   游标查询与运行结束清理

后端有两种：`RedisRunEventLog`（Redis Stream，持久、跨 worker、无条数上限）与
`EventReplayBuffer`（进程内环形缓冲，Redis 不可用时的兜底）。对外统一用门面 `run_event_log`。
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Deque

logger = logging.getLogger(__name__)

# 单个 run 最多缓冲的已发事件条数：足够覆盖"断流到重连"之间漏掉的事件，又不至于无限膨胀。
# 仅内存兜底路径用；Redis Stream 后端没有这个上限（真机一次长回答堆过 20964 个事件）。
_MAX_HISTORY = 500


class EventReplayBuffer:
    """按 run_id 保存最近的已发 SSE 帧，支持按 Last-Event-ID 重放。"""

    def __init__(self, maxlen: int = _MAX_HISTORY) -> None:
        self._maxlen = maxlen
        self._lock = threading.Lock()
        # run_id -> deque[(seq_int, frame_str, AgentThought|None)]，seq 单调递增（= sse_format 的 id）
        # 同时留 AgentThought 对象：断流重连后要把"断开前已发出"的那些事件也落库，
        # 只拿字符串帧就得反向解析，而断开路径的 finally 在 GeneratorExit 解绕中根本 await 不动。
        self._buffers: dict[str, Deque[tuple[int, str, object | None]]] = {}
        # run_id -> {"conversation_id": ..., "message_id": ...}，供续传端点格式化实时事件用
        self._contexts: dict[str, dict[str, str]] = {}
        # 已认领落库的 run：断开接管者与重连端点可能同时想写库，而 save_agent_thoughts
        # 是纯 INSERT，写两次会长出双份推理过程行
        self._persisted: set[str] = set()

    def set_run_context(self, run_id: str, conversation_id: str, message_id: str) -> None:
        """记录该 run 的会话/消息上下文，续传端点格式化实时队列事件时需要。"""
        if not run_id:
            return
        with self._lock:
            self._contexts[run_id] = {
                "conversation_id": conversation_id,
                "message_id": message_id,
            }

    def get_run_context(self, run_id: str) -> dict[str, str] | None:
        """返回该 run 的上下文；未记录返回 None。"""
        if not run_id:
            return None
        with self._lock:
            return self._contexts.get(run_id)

    def record(self, run_id: str, seq: int, frame: str, thought=None) -> None:
        """记录一条已发 SSE 帧。seq 为该帧的 `id:` 数值，frame 为 sse_format 完整输出，
        thought 为该帧对应的 AgentThought 对象（可选，供续传侧落库回读）。"""
        if not run_id or frame is None:
            return
        with self._lock:
            buf = self._buffers.get(run_id)
            if buf is None:
                buf = deque(maxlen=self._maxlen)
                self._buffers[run_id] = buf
            buf.append((seq, frame, thought))

    def history_after(self, run_id: str, last_seq: int) -> list[str]:
        """返回 seq > last_seq 的已发帧（按原顺序）。last_seq <= 0 表示全量重放。"""
        if not run_id:
            return []
        with self._lock:
            buf = self._buffers.get(run_id)
            if buf is None:
                return []
            return [f for s, f, _t in buf if s > last_seq]

    def history_thoughts_after(self, run_id: str, last_seq: int) -> list:
        """返回 seq > last_seq 那些帧对应的 AgentThought 对象（未登记对象的记录自动跳过）。

        续传端点落库要用：断开时原流的 finally 在 GeneratorExit 解绕中 await 不动，
        断开前那批事件其实一条都没落库，只把实时事件落库会缺头一段。
        """
        if not run_id:
            return []
        with self._lock:
            buf = self._buffers.get(run_id)
            if buf is None:
                return []
            return [t for s, _f, t in buf if s > last_seq and t is not None]

    def last_seq(self, run_id: str) -> int:
        """该 run 当前最大的已发 seq；无记录返回 0。"""
        if not run_id:
            return 0
        with self._lock:
            buf = self._buffers.get(run_id)
            if not buf:
                return 0
            return buf[-1][0]

    def clear(self, run_id: str) -> None:
        """运行结束（AGENT_END / 退出）时调用，释放缓冲与上下文。"""
        if not run_id:
            return
        with self._lock:
            self._buffers.pop(run_id, None)
            self._contexts.pop(run_id, None)
            self._persisted.discard(run_id)

    def claim_persist(self, run_id: str) -> bool:
        """落库认领：第一次返回 True，之后返回 False（断开接管者与重连端点只能有一个写库）。"""
        if not run_id:
            return False
        with self._lock:
            if run_id in self._persisted:
                return False
            self._persisted.add(run_id)
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffers)


# Redis Stream 版持久事件日志的键与 TTL（TTL 与 gen_task:belong 的 1800s 同量级）
_STREAM_KEY = "gen_task:events:{run_id}"
_CTX_KEY = "gen_task:evtctx:{run_id}"
# 落库认领键：断开接管者与重连端点都可能在终态时写库，SETNX 保证只有一个赢家
_PERSIST_KEY = "gen_task:persist:{run_id}"
_STREAM_TTL_SECONDS = 1800


def _sync_redis():
    """活引用 sync_redis_client：uvicorn lifespan init_redis() 之后才有值。"""
    import internal.extensions.redis as redis_mod

    return redis_mod.sync_redis_client


def _dec(value) -> str:
    """decode_responses=False，XRANGE 回来的是 bytes。"""
    if value is None:
        return ""
    return value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)


class RedisRunEventLog:
    """按 run 的持久事件日志（Redis Stream）。

    换掉进程内环形缓冲的两个理由，都是真机量出来的：
      * 上限 500 帧——一次长回答在无人消费期间堆了 20964 个事件，断开再刷新会把整段头部丢掉；
      * 进程内状态多 worker 不共享（这也是 API 被迫固定 1 worker 的根因）。

    游标直接用 SSE 的 seq 当 stream ID 的毫秒段：单写者、seq 单调递增，既合法又天然有序，
    于是"取 seq>N 的帧"退化成一次 `(N-1 +` 的 XRANGE，不必扫全量。
    """

    def __init__(self, client_factory=_sync_redis) -> None:
        self._client_factory = client_factory

    def available(self) -> bool:
        return self._client_factory() is not None

    @staticmethod
    def _key(run_id: str) -> str:
        return _STREAM_KEY.format(run_id=run_id)

    def record(self, run_id: str, seq: int, frame: str, thought=None) -> bool:
        """写入一条事件。返回 False 表示 Redis 不可用，调用方应退回内存实现。"""
        client = self._client_factory()
        if client is None or not run_id or frame is None:
            return False
        payload: dict[str, str] = {"seq": str(seq), "frame": frame}
        if thought is not None:
            try:
                payload["thought"] = thought.model_dump_json()
            except Exception:  # noqa: BLE001 - 序列化不了就只存帧，落库路径自己会跳过
                logger.warning("事件对象序列化失败 run=%s seq=%d", run_id, seq, exc_info=True)
        key = self._key(run_id)
        try:
            client.xadd(key, payload, id=f"{seq}-1")
            client.expire(key, _STREAM_TTL_SECONDS)
            return True
        except Exception:  # noqa: BLE001
            logger.warning("事件日志写入 Redis 失败 run=%s seq=%d", run_id, seq, exc_info=True)
            return False

    def _entries_after(self, run_id: str, last_seq: int) -> list[dict]:
        client = self._client_factory()
        if client is None or not run_id:
            return []
        start = f"({last_seq}-1" if last_seq and last_seq > 0 else "-"
        try:
            entries = client.xrange(self._key(run_id), min=start, max="+")
        except Exception:  # noqa: BLE001
            logger.warning("事件日志读取 Redis 失败 run=%s", run_id, exc_info=True)
            return []
        # decode_responses=False：字段名也是 bytes，不归一化的话 d.get("frame") 恒为 None，
        # 于是"读到了 N 条"却每条都解成空串——写路径一切正常，只有读会静默变空。
        return [{_dec(k): v for k, v in fields.items()} for _id, fields in entries]

    def history_after(self, run_id: str, last_seq: int) -> list[str]:
        return [_dec(d.get("frame")) for d in self._entries_after(run_id, last_seq)]

    def history_thoughts_after(self, run_id: str, last_seq: int) -> list:
        from internal.core.agent.entities.queue_entity import AgentThought

        out = []
        for d in self._entries_after(run_id, last_seq):
            raw = _dec(d.get("thought"))
            if not raw:
                continue
            try:
                out.append(AgentThought.model_validate_json(raw))
            except Exception:  # noqa: BLE001
                logger.warning("事件日志反序列化失败 run=%s", run_id, exc_info=True)
        return out

    def last_seq(self, run_id: str) -> int:
        client = self._client_factory()
        if client is None or not run_id:
            return 0
        try:
            entries = client.xrevrange(self._key(run_id), count=1)
        except Exception:  # noqa: BLE001
            logger.warning("事件日志读 last_seq 失败 run=%s", run_id, exc_info=True)
            return 0
        if not entries:
            return 0
        # 同样要归一化字段名：xrevrange 不经过 _entries_after，bytes 键会让 .get("seq") 取空
        fields = {_dec(k): v for k, v in entries[0][1].items()}
        return int(_dec(fields.get("seq")) or 0)

    def set_run_context(self, run_id: str, conversation_id: str, message_id: str) -> None:
        client = self._client_factory()
        if client is None or not run_id:
            return
        try:
            key = _CTX_KEY.format(run_id=run_id)
            client.hset(key, mapping={"conversation_id": conversation_id, "message_id": message_id})
            client.expire(key, _STREAM_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            logger.warning("事件上下文写入 Redis 失败 run=%s", run_id, exc_info=True)

    def get_run_context(self, run_id: str) -> dict[str, str] | None:
        client = self._client_factory()
        if client is None or not run_id:
            return None
        try:
            raw = client.hgetall(_CTX_KEY.format(run_id=run_id))
        except Exception:  # noqa: BLE001
            logger.warning("事件上下文读取 Redis 失败 run=%s", run_id, exc_info=True)
            return None
        if not raw:
            return None
        return {_dec(k): _dec(v) for k, v in raw.items()}

    def clear(self, run_id: str) -> None:
        client = self._client_factory()
        if client is None or not run_id:
            return
        try:
            client.delete(self._key(run_id), _CTX_KEY.format(run_id=run_id),
                          _PERSIST_KEY.format(run_id=run_id))
        except Exception:  # noqa: BLE001
            logger.warning("事件日志清理失败 run=%s", run_id, exc_info=True)

    def claim_persist(self, run_id: str) -> bool:
        """SETNX 认领落库权：跨 worker 也只有一个写者。Redis 不可用时返回 False（不认领）。"""
        client = self._client_factory()
        if client is None or not run_id:
            return False
        try:
            return bool(client.set(
                _PERSIST_KEY.format(run_id=run_id), "1",
                nx=True, ex=_STREAM_TTL_SECONDS,
            ))
        except Exception:  # noqa: BLE001
            logger.warning("落库认领失败 run=%s", run_id, exc_info=True)
            return False


class RunEventLog:
    """事件日志门面：优先 Redis Stream，不可用时按 run 退回进程内缓冲。

    后端选择按 run 固定下来（记在 _backend 里）：一个 run 的帧不能一半在 Redis 一半在内存，
    否则重连按游标读会读到残缺序列。Redis 中途挂掉时该 run 之后的帧改走内存，
    已写进 Redis 的那部分仍在内存里补不上——这种降级会丢尾部，所以记 warning。
    """

    def __init__(self, redis_log: RedisRunEventLog, mem_log: EventReplayBuffer) -> None:
        self._redis = redis_log
        self._mem = mem_log
        self._lock = threading.Lock()
        self._backend: dict[str, str] = {}

    def _pick(self, run_id: str) -> str:
        with self._lock:
            backend = self._backend.get(run_id)
            if backend is None:
                backend = "redis" if self._redis.available() else "memory"
                self._backend[run_id] = backend
            return backend

    def record(self, run_id: str, seq: int, frame: str, thought=None) -> None:
        if not run_id or frame is None:
            return
        if self._pick(run_id) == "redis" and self._redis.record(run_id, seq, frame, thought):
            return
        if self._pick(run_id) == "redis":
            logger.warning("run=%s 的事件日志退回内存：Redis 中途不可用，已写入的帧无法合并", run_id)
            with self._lock:
                self._backend[run_id] = "memory"
        self._mem.record(run_id, seq, frame, thought)

    def history_after(self, run_id: str, last_seq: int) -> list[str]:
        if self._pick(run_id) == "redis":
            return self._redis.history_after(run_id, last_seq)
        return self._mem.history_after(run_id, last_seq)

    def history_thoughts_after(self, run_id: str, last_seq: int) -> list:
        if self._pick(run_id) == "redis":
            return self._redis.history_thoughts_after(run_id, last_seq)
        return self._mem.history_thoughts_after(run_id, last_seq)

    def last_seq(self, run_id: str) -> int:
        if self._pick(run_id) == "redis":
            return self._redis.last_seq(run_id)
        return self._mem.last_seq(run_id)

    def set_run_context(self, run_id: str, conversation_id: str, message_id: str) -> None:
        if self._pick(run_id) == "redis":
            self._redis.set_run_context(run_id, conversation_id, message_id)
            return
        self._mem.set_run_context(run_id, conversation_id, message_id)

    def get_run_context(self, run_id: str) -> dict[str, str] | None:
        if self._pick(run_id) == "redis":
            return self._redis.get_run_context(run_id) or self._mem.get_run_context(run_id)
        return self._mem.get_run_context(run_id)

    def clear(self, run_id: str) -> None:
        backend = self._backend.pop(run_id, None)
        if backend == "redis" or backend is None:
            self._redis.clear(run_id)
        self._mem.clear(run_id)

    def backend_of(self, run_id: str) -> str | None:
        """该 run 当前使用的后端（测试与排障用）。"""
        with self._lock:
            return self._backend.get(run_id)

    def claim_persist(self, run_id: str) -> bool:
        """认领这个 run 的落库权；只有返回 True 的一方可以写库。

        断开接管者与重连端点都会在终态时落库，而 save_agent_thoughts 是纯 INSERT，
        两边都写会让推理过程行翻倍。Redis 在时走 SETNX（跨进程也只有一个赢家）。
        """
        if self._redis.available():
            return self._redis.claim_persist(run_id)
        return self._mem.claim_persist(run_id)


# 进程级单例：`_stream_and_persist` 记录，重连端点/接管消费者统一引用。
run_event_log = RunEventLog(RedisRunEventLog(), EventReplayBuffer())
