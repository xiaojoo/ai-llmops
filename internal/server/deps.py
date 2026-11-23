"""FastAPI Web 侧认证与请求上下文依赖。

认证依赖：
- get_current_user：llmops 路由，Bearer JWT → Account
- get_api_key_account：openapi 路由，api_key → ApiKey(active) → account

request_context 依赖：
- 从 Request 写入 contextvar（scheme/host/remote_addr）
- 挂为 llmops/openapi 两个 router 的 dependencies

CurrentUser / ApiKeyUser 类型别名，供 handler 参数注入使用。
FastAPI 同请求内依赖缓存：router 级 dependencies + handler 参数 Depends 不会重复调用。

凭证解析逻辑与 middleware.py 的 _validate_credential 保持一致。
"""
from typing import Annotated

from fastapi import Depends, Request

from internal.core.request_context import RequestContext, reset_request_context, set_request_context
from internal.exception import UnauthorizedException
from internal.model import Account
from internal.service import AccountService, ApiKeyService, JwtService
from internal.container import create_account_service, create_api_key_service
from package.database import AsyncSession, get_db


def _validate_credential(authorization: str) -> str:
    """校验请求头中的凭证信息。"""
    if not authorization:
        raise UnauthorizedException("该接口需要授权才能访问，请登录后尝试")
    if " " not in authorization:
        raise UnauthorizedException("该接口需要授权才能访问，验证格式失败")
    auth_schema, credential = authorization.split(None, 1)
    if auth_schema.lower() != "bearer":
        raise UnauthorizedException("该接口需要授权才能访问，验证格式失败")
    return credential


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Account:
    """llmops 路由：Bearer <JWT> → Account。"""
    authorization = request.headers.get("authorization", "")
    access_token = _validate_credential(authorization)
    payload = JwtService.parse_token(access_token)
    access_id = payload.get("sub")
    account_service = create_account_service(db)
    account = await account_service.get_account(access_id)
    if account is None:
        raise UnauthorizedException("该接口需要授权才能访问，请登录后尝试")
    return account


async def get_api_key_account(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Account:
    """openapi 路由：api_key → ApiKey 记录(active) → account。"""
    authorization = request.headers.get("authorization", "")
    api_key = _validate_credential(authorization)
    api_key_service = create_api_key_service(db)
    api_key_record = await api_key_service.get_api_by_by_credential(api_key)
    if not api_key_record or not api_key_record.is_active:
        raise UnauthorizedException("该秘钥不存在或未激活")
    return api_key_record.account


async def request_context_dependency(request: Request) -> RequestContext:
    """从 FastAPI Request 写入请求上下文 contextvar。

    挂为 llmops/openapi 两个 router 的依赖（dependencies=[Depends(request_context)]），
    服务层 get_request_context() 生效。
    """
    host = request.url.hostname or request.url.netloc.split(":")[0] or ""
    ctx = RequestContext(
        scheme=request.url.scheme,
        host=host,
        remote_addr=request.client.host if request.client else None,
    )
    token = set_request_context(ctx)
    try:
        yield ctx
    finally:
        reset_request_context(token)


# 类型别名，供 handler 参数注入使用。
# FastAPI 同请求内依赖缓存：router 级 dependencies + handler 参数 Depends 不会重复调用。
CurrentUser = Annotated[Account, Depends(get_current_user)]
ApiKeyUser = Annotated[Account, Depends(get_api_key_account)]
