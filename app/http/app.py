#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
@Time   : 2025/11/15 14:41
@Author : sunxiaojie
@File   : app.py

FastAPI 入口。
- lifespan 装配（DB 配置注入 → settings 重建 → 引擎/扩展初始化）
- CORS（与旧 flask_cors 完全一致）
- 异常处理器（逐条对照旧 _register_error_handler）
- favicon / default-app-icon 路由
"""
import os

# .env 载入 os.environ（旧 Flask app 模块级 dotenv.load_dotenv() 的行为；JwtService 等用
# os.getenv 读取 JWT_SECRET_KEY，settings 单例只读 .env 不写 os.environ——缺失会导致
# "Expected a string value" 认证失败）。
import dotenv

dotenv.load_dotenv()

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import SQLAlchemyError

from internal.config.settings import get_settings
from internal.exception import CustomException
from internal.extensions.logging import init_logging
from internal.extensions.redis import init_redis
from internal.extensions.weaviate import init_weaviate

import warnings

# dashscope SDK 自身 __init__.py 会 import 已弃用的 dashscope.assistants（本项目未使用
# Assistants API，仅 OCR/向量/rerank/语音调用其原生接口），上游尚未移除该 import，
# 导致每次启动打印 DeprecationWarning。此处定向过滤这条上游噪音警告。
# 注意：必须放在 internal.service 等会触发 dashscope 导入的模块之前，且放在 weaviate
# 等重库导入之后——weaviate 导入时 simplefilter("default") 会插入全匹配的
# default::Warning 过滤器，若本过滤在其前注册会被遮蔽而失效。
# 若上游新版移除该 import，可删除此过滤。
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r"The Assistants API \(dashscope\.assistants\) is deprecated.*",
)

from internal.service import SystemConfigService
from package.database import (
    Base,
    build_engine,
    build_sessionmaker,
    get_default_session_factory,
    set_default_session_factory,
)
from package.response import HttpCode, Response as AppResponse, json

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时装配基础设施，关闭时清理。

    时序：
    1. build_engine + set_default_session_factory（DB 连接基础设施）
    2. worker_run(apply_to_env)（DB 配置注入 os.environ，必须在 get_settings 首次调用前）
    3. get_settings.cache_clear() + get_settings()（重建 settings 单例，读取 DB 注入后的 env）
    4. init_logging / init_redis / init_weaviate（依赖 settings 的扩展）
    5. create_all（非 celery/local 模式）
    """
    # 1. DB 连接基础设施（get_settings 内部惰性调用，此处确保连接就绪）
    engine = build_engine()
    set_default_session_factory(build_sessionmaker(engine))
    app.state.engine = engine

    # 2. DB 配置注入 os.environ（system_config 表 → os.environ）
    # apply_to_env 已 async，直接异步会话调用；不能用 worker_run（其运行中-loop 守卫
    # 会拦截 lifespan 的异步上下文，导致注入静默失效）。
    try:
        factory = get_default_session_factory()
        async with factory() as s:
            await SystemConfigService(db=s).apply_to_env()
    except Exception as e:
        logger.warning("DB 配置注入失败，使用 .env/compose 配置: %s", e)

    # 3. 重建 settings 单例（读取 DB 注入后的 os.environ）
    get_settings.cache_clear()
    settings = get_settings()

    # 4. 扩展初始化（依赖 settings 的配置值）
    init_logging()
    init_redis()
    init_weaviate()

    # 5. 建表（非 celery/local 模式）
    # 表已存在时跳过 create_all：默认 checkfirst=True 会对元数据里每张表各发一次
    # has_table 探测（本 schema 约 28 张表 → 每次启动约 28 条 pg_class 查询），
    # 生产 schema 由 Alembic 迁移维护，重复探测属冗余。仅当 system_config 缺失
    # （首次部署/空库）才执行全量建表，首次建表行为与原来一致。
    if settings.mode not in ("celery", "local"):
        async with engine.begin() as conn:
            # has_table 是惰性 IO，必须在 run_sync 的 greenlet 上下文内一次完成
            # （先建 inspector 再在外面调用会抛 MissingGreenlet）。
            table_exists = await conn.run_sync(
                lambda c: sa_inspect(c).has_table("system_config")
            )
            if not table_exists:
                await conn.run_sync(Base.metadata.create_all)

    # 6. 注册路由——直接添加到 app（handler 持 RequestSessionProxy，无需 lifespan 一次性 session）
    from internal.router.router import register_routes_from_container
    register_routes_from_container(app=app)

    yield

    await engine.dispose()


# ---- request_context_dependency 挂 app 级（所有路由生效） ----
# get_db 不挂 app 级——挂 llmops_router/openapi_router 级（见 router.py），
# 健康/静态路由（/healthz、/favicon.ico、/default-app-icon、/docs、/webhook）不再建 DB 会话
# （DB 挂时这些路由仍正常返回，健康探测语义不被污染）。
from internal.server.deps import request_context_dependency

app = FastAPI(
    title="llmops",
    lifespan=lifespan,
    dependencies=[Depends(request_context_dependency)],
)


# ---- CORS（与旧 flask_cors 配置完全一致） ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


# ---- 请求审计日志（IP/UA/认证凭据掩码/耗时） ----
@app.middleware("http")
async def audit_log_middleware(request: Request, call_next):
    """记录每个 HTTP 请求的基础审计信息：时间/方法/路径/客户端 IP/User-Agent/
    认证凭据前缀（掩码，避免完整 JWT 落日志）/状态码/耗时。

    认证身份（账号/api_key）在依赖层解析，这里仅记录凭据来源掩码；SSE 流的
    duration 为响应对象返回耗时（流式传输本身不阻塞请求）。
    """
    import time as _time

    start = _time.perf_counter()
    auth_header = request.headers.get("authorization", "")
    # 凭据掩码：Bearer <前16字符>… 或 api_key 前缀，避免完整 token 进日志
    auth_masked = (auth_header[:24] + "…") if auth_header else "-"
    client_ip = request.client.host if request.client else "-"
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    user_agent = (request.headers.get("user-agent", "") or "")[:200]
    status = "-"
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        elapsed = _time.perf_counter() - start
        logger.info(
            "AUDIT method=%s path=%s status=%s ip=%s ua=%s auth=%s dur=%.3fs",
            request.method, request.url.path, status, client_ip, user_agent,
            auth_masked, elapsed,
        )


# ---- 异常处理器（逐条对照旧 internal/server/http.py:_register_error_handler） ----

@app.exception_handler(CustomException)
async def custom_exception_handler(request: Request, exc: CustomException):
    """自定义异常 → 200 + {code, message, data}"""
    logger.error("An error occurred: %s", exc)
    return json(AppResponse(
        code=exc.code,
        message=exc.message,
        data=exc.data if exc.data is not None else {},
    ))


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    """Pydantic 校验异常 → 200 + {code=validation_error, message=首个错误, data=errors}"""
    logger.error("An error occurred: %s", exc)
    errors = {str(err["loc"][0]): err["msg"] for err in exc.errors()}
    first_message = next(iter(errors.values()), "参数校验失败")
    return json(AppResponse(
        code=HttpCode.VALIDATION_ERROR,
        message=first_message,
        data=errors,
    ))


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError):
    """FastAPI 请求体/参数校验异常 → 200 + {code=validation_error, message=首个错误, data={field: msg}}

    旧 Flask 契约：请求校验失败返回 HTTP 200 + code=validation_error（非 422）。
    FastAPI 在进入 handler 前对 body/query 参数做校验，抛 RequestValidationError（与 pydantic.ValidationError 不同类）。
    """
    logger.error("An error occurred: %s", exc)
    errors: dict[str, str] = {}
    for err in exc.errors():
        loc = err.get("loc") or ("body",)
        key = str(loc[-1])
        errors.setdefault(key, err.get("msg", "参数校验失败"))
    first_message = next(iter(errors.values()), "参数校验失败")
    return json(AppResponse(
        code=HttpCode.VALIDATION_ERROR,
        message=first_message,
        data=errors,
    ))


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    """数据库异常 → 200 + {code=fail, message=数据库操作失败, data={}}"""
    logger.error("An error occurred: %s", exc)
    return json(AppResponse(
        code=HttpCode.FAIL,
        message="数据库操作失败",
        data={},
    ))


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """通用异常 → 开发模式重抛；生产模式 200 + {code=fail, message=str(error), data={}}"""
    logger.error("An error occurred: %s", exc)
    if os.getenv("ENV") == "development":
        raise exc
    return json(AppResponse(
        code=HttpCode.FAIL,
        message=str(exc),
        data={},
    ))


# ---- 公开路由（不进认证 router） ----

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/default-app-icon")
async def default_app_icon():
    """返回内置默认应用图标（PNG user 头像）：替代外部占位图

    - 前端 `<img>`/`<a-avatar>` 直接展示
    - auto_create_app 会 requests.get 下载该 URL 后上传 COS
    """
    project_root = Path(__file__).resolve().parents[2]
    icon_path = project_root / "internal" / "core" / "builtin_apps" / "default-user-icon.png"
    with open(icon_path, "rb") as f:
        content = f.read()
    return Response(content=content, media_type="image/png")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ---- router include 已移入 lifespan（路由注册后 include） ----


# ---- 公开路由：/webhook（feishu 回调，无认证） ----
def _get_feishu_handler():
    """惰性获取 feishu handler 实例（避免 import 期触发 handler 旧 Flask 导入）。"""
    from internal.container import create_feishu_handler
    return create_feishu_handler()


@app.post("/webhook")
async def feishu_webhook(request: Request):
    """飞书 webhook 回调（公开路由，无认证）。"""
    handler = _get_feishu_handler()
    return await handler.webhook(request)
