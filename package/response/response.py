#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
@Time   : 2025/11/16 13:14
@Author : sunxiaojie
@File   : response.py

Flask → FastAPI。所有 helper 签名不变（handler 调用点零改动）。
"""
from collections.abc import Generator, AsyncGenerator
from dataclasses import asdict, dataclass, field
import json
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse

from .http_code import HttpCode


@dataclass
class Response:
    """基础HTTP接口响应格式"""
    code: HttpCode = HttpCode.SUCCESS
    message: str = ""
    data: Any = field(default_factory=dict)


def json(data: Response = None, status_code: int = 200):
    """基础的响应接口"""
    # jsonable_encoder：UUID/datetime → JSON 安全类型（等价 Flask jsonify 的全局支持；
    # FastAPI JSONResponse 用标准 json.dumps，遇到 UUID 会抛 TypeError）
    return JSONResponse(content=jsonable_encoder(asdict(data or Response())), status_code=status_code)


def success_json(data: Any = None):
    """成功数据响应"""
    return json(Response(code=HttpCode.SUCCESS, message="", data=data))


def fail_json(data: Any = None):
    """失败数据响应"""
    return json(Response(code=HttpCode.FAIL, message="", data=data))


def validation_error_json(errors: dict | None = None):
    """数据验证错误响应"""
    if not errors:
        return json(Response(code=HttpCode.VALIDATION_ERROR, message="", data={}))
    first_key = next(iter(errors))
    if first_key is not None:
        message = errors.get(first_key)
    else:
        message = ""
    return json(Response(code=HttpCode.VALIDATION_ERROR, message=message, data=errors))


def message_json(code: HttpCode, message: str = ""):
    """基础的消息响应，固定返回消息提示，数据固定为空字典"""
    return json(Response(code=code, message=message, data={}))


def success_message_json(message: str = ""):
    """成功的消息响应"""
    return message_json(code=HttpCode.SUCCESS, message=message)


def fail_message_json(message: str = ""):
    """失败的消息响应"""
    return message_json(code=HttpCode.FAIL, message=message)


def not_found_message_json(message: str = ""):
    """未找到的消息响应"""
    return message_json(code=HttpCode.NOT_FOUND, message=message)


def unauthorized_message_json(message: str = ""):
    """未授权的消息响应"""
    return message_json(code=HttpCode.UNAUTHORIZED, message=message)


def forbidden_message_json(message: str = ""):
    """无权限的消息响应"""
    return message_json(code=HttpCode.FORBIDDEN, message=message)


def compact_generate_response(response: Response | Generator | AsyncGenerator | tuple) -> JSONResponse | StreamingResponse:
    """统一合并处理快输出以及流式事件输出。

    - Response → JSONResponse（status 200）
    - 元组 (Response, status_code) → JSONResponse(status_code)
    - 生成器（sync 或 async）→ StreamingResponse(text/event-stream)
    """
    status_code = None

    if isinstance(response, tuple):
        response, status_code = response

    # 1、检测下是否为快输出 (自定义 Response 对象)
    if isinstance(response, Response):
        return JSONResponse(
            content=jsonable_encoder(asdict(response)),
            status_code=status_code if status_code is not None else 200,
        )

    elif isinstance(response, JSONResponse):
        if status_code is not None:
            response.status_code = status_code
        return response

    else:
        # 2、response格式为生成器，代表本次响应需要执行流式事件输出
        return StreamingResponse(
            response,
            status_code=status_code if status_code is not None else 200,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )


# SSE 协议层——敏感字段（trace/observation 可能含完整请求/响应）裁剪长度
# 注意：tool_input 对本地工具（local_tool_call）是"必须完整执行"的指令字段，绝不能裁剪
# （fs_write 的 content 可能很大）；因此只裁剪回显类字段 trace/observation。
_SENSITIVE_FIELD_MAX = 2000
_SENSITIVE_LIST_MAX = 50
# 单事件 data 体 UTF-8 大小上限：本地工具帧需携带 fs_write 完整内容（单文件上限 2MB），
# 且 SSE 帧已不再携带全量历史 message（见 chat_runner.agent_thought_to_sse_frame），
# 4MB 足以覆盖所有合法帧。超限时**绝不输出截断的非法 JSON**，改用安全降级帧。
_SSE_MAX_BYTES = 4 * 1024 * 1024
_SENSITIVE_FIELDS = ("trace", "observation")
# 超限后按序摘除的"大而可弃"字段（仅影响回显；重试/落库走独立通道，不依赖 SSE 帧）
_SSE_DROP_ON_OVERFLOW = ("llm_output", "tool_calls", "thought", "answer", "observation", "trace")


def _truncate_sse_body(body: str, max_bytes: int) -> str:
    """把超长 data JSON 降级为合法 JSON：
    1) 逐字段摘除 llm_output/tool_calls/thought/answer 等"可弃回显字段"（用 json 反序列化后重建，
       确保结果始终是合法 JSON）；
    2) 仍超限（理论上仅剩 tool_input 超大场景，单文件已被 LocalToolRuntime 限制在 2MB 内，不应发生）
       → 返回最小合法降级帧，绝不给客户端发被 [:N] 硬切的中断 JSON。
    """
    import json as _json
    try:
        obj = _json.loads(body)
    except Exception:
        obj = None
    if not isinstance(obj, dict):
        return _json.dumps({"truncated": True, "error": "sse_payload_invalid"})
    for key in _SSE_DROP_ON_OVERFLOW:
        obj.pop(key, None)
    rebuilt = _json.dumps(obj, ensure_ascii=False, default=str)
    if len(rebuilt.encode("utf-8")) <= max_bytes:
        return rebuilt
    # 保底：payload 里只剩 tool_input/事件元信息仍超上限（异常场景），发最小合法错误帧
    return _json.dumps({"truncated": True, "error": "sse_frame_too_large"})


def sse_format(event: str, data: dict, seq: int, *, retry: int | None = None, max_bytes: int = _SSE_MAX_BYTES) -> str:
    """统一 SSE 帧序列化：`id: <序号>` + `event: <类型>` + 可选 `retry:` + `data: <json>`。

    - ensure_ascii=False（中文直出，前端/日志可读）
    - 敏感字段裁剪：trace/observation 超长字符串截断、长列表截断
      （tool_input 不在裁剪之列——本地工具指令必须原样到达插件）
    - 事件大小上限：超过 max_bytes 时按 _truncate_sse_body 降级为合法 JSON 并标记 truncated
    - data 内 id/event 等字段由调用方组装（payload 语义不变），seq 由调用方递增
    """
    import json as _json  # 本模块顶层 def json(...) 为响应助手函数，需遮蔽使用标准库

    payload = dict(data)
    for key in _SENSITIVE_FIELDS:
        val = payload.get(key)
        if isinstance(val, str) and len(val) > _SENSITIVE_FIELD_MAX:
            payload[key] = val[:_SENSITIVE_FIELD_MAX] + "…(truncated)"
        elif isinstance(val, list) and len(val) > _SENSITIVE_LIST_MAX:
            payload[key] = val[:_SENSITIVE_LIST_MAX]
    body = _json.dumps(payload, ensure_ascii=False, default=str)
    if len(body.encode("utf-8")) > max_bytes:
        payload["truncated"] = True
        body = _truncate_sse_body(_json.dumps(payload, ensure_ascii=False, default=str), max_bytes)
    lines = [f"id: {seq}", f"event: {event}", f"data: {body}"]
    if retry is not None:
        lines.insert(2, f"retry: {retry}")
    return "\n".join(lines) + "\n\n"
