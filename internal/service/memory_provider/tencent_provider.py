#!/usr/bin/env python
"""腾讯记忆提供者：包装 TencentDB-Agent-Memory SDK（懒加载，配置缺失/SDK 缺失回退为无记忆）。

SDK 是纯 HTTP 客户端，记忆流水线（L0→L3）运行在 MemoryCore 服务端，
因此本 provider 不构造 LLM，只读三个系统配置（endpoint/api_key/service_id）。
"""
import logging
from dataclasses import dataclass
from uuid import UUID

from package.database import build_engine, worker_run
from sqlalchemy.ext.asyncio import AsyncSession

from internal.service.system_config_service import SystemConfigService

from .base import MemoryProvider, MemoryReadContext
from .tencent_client import SdkTencentMemoryClient, TencentMemoryClient

logger = logging.getLogger(__name__)

ENDPOINT_KEY = "TENCENT_MEMORY_ENDPOINT"
API_KEY_KEY = "TENCENT_MEMORY_API_KEY"
SERVICE_ID_KEY = "TENCENT_MEMORY_SERVICE_ID"
# 面板管理 Key（可选）：用于测试连通时校验 team/agent/user 实体真实存在
ADMIN_KEY_KEY = "TENCENT_MEMORY_ADMIN_KEY"
# 作用域（对齐 Panel 可见的 team/agent/user；缺省时 SDK 走默认 "default"）
TEAM_ID_KEY = "TENCENT_MEMORY_TEAM_ID"
AGENT_ID_KEY = "TENCENT_MEMORY_AGENT_ID"
USER_ID_KEY = "TENCENT_MEMORY_USER_ID"


@dataclass
class TencentMemoryProvider(MemoryProvider):
    """腾讯记忆提供者：SDK/配置不可用回退为无记忆（等效关闭长期记忆）"""
    system_config_service: SystemConfigService

    async def _cfg(self, overrides: dict | None, field: str, sys_key: str,
                   cfg: SystemConfigService | None = None) -> str:
        """读取连接配置：请求 overrides 非空字段优先，其次 DB/环境变量。

        cfg 缺省用本 provider 的配置服务（绑定请求 loop）；写侧 worker 内必须传入
        绑定 worker session/loop 的 SystemConfigService，避免跨 loop / 争用请求会话。"""
        value = (overrides or {}).get(field)
        if value:
            return value
        svc = cfg or self.system_config_service
        return await svc.get_config(sys_key)

    async def _resolve_client_params(
            self, app_config: dict, app_id: UUID, user_id: UUID,
            *, overrides: dict | None = None, cfg: SystemConfigService | None = None,
    ) -> dict | None:
        """解析 SdkTencentMemoryClient 构造参数（连接配置 + 作用域），三件缺失返回 None。

        cfg 的 session 必须与**当前事件循环**绑定：请求 loop 下不传（用
        self.system_config_service）；写侧 worker 内传绑定 worker session 的服务。

        overrides：测试连通时由系统设置页把当前表单的连接配置带上来
        （字段名 endpoint/api_key/service_id/admin_key），**非空才覆盖**已保存配置。
        作用域（team/agent/user）：应用配置 long_term_memory 覆盖 > 系统全局配置。"""
        endpoint = await self._cfg(overrides, "endpoint", ENDPOINT_KEY, cfg)
        api_key = await self._cfg(overrides, "api_key", API_KEY_KEY, cfg)
        service_id = await self._cfg(overrides, "service_id", SERVICE_ID_KEY, cfg)
        if not endpoint or not api_key or not service_id:
            logger.warning("腾讯记忆配置不完整（endpoint/api_key/service_id），回退为无记忆")
            return None
        ltm = (app_config or {}).get("long_term_memory") or {}
        svc = cfg or self.system_config_service

        async def _scope(app_key: str, sys_key: str) -> str | None:
            value = ltm.get(app_key)
            if value:
                return str(value)
            return (await svc.get_config(sys_key)) or None

        return {
            "endpoint": endpoint,
            "api_key": api_key,
            "service_id": service_id,
            "session_id": f"{app_id}:{user_id}",
            "team_id": await _scope("team_id", TEAM_ID_KEY),
            "agent_id": await _scope("agent_id", AGENT_ID_KEY),
            "user_id": await _scope("user_id", USER_ID_KEY),
        }

    async def _build_client(
            self, app_config: dict, app_id: UUID, user_id: UUID,
            *, overrides: dict | None = None,
    ) -> TencentMemoryClient | None:
        """按系统配置构建 SDK 客户端；配置缺失/SDK 缺失/初始化失败返回 None。"""
        params = await self._resolve_client_params(app_config, app_id, user_id, overrides=overrides)
        if params is None:
            return None
        try:
            return SdkTencentMemoryClient(**params)
        except ImportError:
            logger.warning("腾讯记忆 SDK 未安装，回退为无记忆（等效关闭长期记忆）")
            return None
        except Exception:
            logger.exception("腾讯记忆初始化失败，回退为无记忆")
            return None

    async def test_connection(self, app_config: dict, app_id: UUID, user_id: UUID,
                              *, overrides: dict | None = None) -> tuple[bool, str]:
        """测试连通性：校验作用域格式 → 实体存在性 → 构建客户端探活，返回 (是否成功, 说明)。

        overrides：请求携带的连接配置覆盖（endpoint/api_key/service_id/admin_key 非空字段优先）。"""
        # 1. 作用域格式校验
        ltm = (app_config or {}).get("long_term_memory") or {}

        async def _scope(app_key: str, sys_key: str) -> str | None:
            value = ltm.get(app_key)
            if value:
                return str(value)
            return (await self.system_config_service.get_config(sys_key)) or None

        PREFIX = {"team_id": "team-", "agent_id": "agt-", "user_id": "usr-"}
        LABEL = {"team_id": "Team ID", "agent_id": "Agent ID", "user_id": "User ID"}
        SYS_KEY = {"team_id": TEAM_ID_KEY, "agent_id": AGENT_ID_KEY, "user_id": USER_ID_KEY}
        for key, prefix in PREFIX.items():
            value = await _scope(key, SYS_KEY[key])
            if value and not value.startswith(prefix):
                hint = (
                    "会话名/记忆块名（如 chat_memory-...）不是用户 ID，请在记忆面板的用户管理中复制"
                    if key == "user_id" else
                    "请在记忆面板的组织权限/Agent 管理中复制对应的 id"
                )
                return False, f"{LABEL[key]} 格式不正确：应以「{prefix}」开头（{hint}）"

        # 2. 实体存在性校验（配置了管理 Key 时）
        admin_key = await self._cfg(overrides, "admin_key", ADMIN_KEY_KEY)
        if admin_key:
            try:
                from tencentdb_agent_memory.v3 import MetadataClient
                from tencentdb_agent_memory.errors import TDAMError

                meta = MetadataClient(
                    endpoint=await self._cfg(overrides, "endpoint", ENDPOINT_KEY),
                    api_key=await self._cfg(overrides, "api_key", API_KEY_KEY),
                    service_id=await self._cfg(overrides, "service_id", SERVICE_ID_KEY),
                    user_key=admin_key,
                )
                checks = (
                    ("team_id", "get_team", "Team ID"),
                    ("agent_id", "get_agent", "Agent ID"),
                    ("user_id", "get_user", "User ID"),
                )
                for key, method, label in checks:
                    value = await _scope(key, SYS_KEY[key])
                    if not value:
                        continue
                    try:
                        getattr(meta, method)(value)
                    except TDAMError as e:
                        if e.code == 404:
                            return False, f"{label} 不存在：{value}（请在记忆面板确认该 {label} 是否正确）"
                        raise
            except ImportError:
                logger.warning("腾讯记忆管理面 SDK 未安装，跳过实体存在性校验")
            except Exception:
                logger.exception("腾讯记忆实体存在性校验失败，跳过该校验")

        # 3. 构建客户端并探活
        client = await self._build_client(app_config, app_id, user_id, overrides=overrides)
        if client is None:
            endpoint = await self._cfg(overrides, "endpoint", ENDPOINT_KEY)
            api_key = await self._cfg(overrides, "api_key", API_KEY_KEY)
            service_id = await self._cfg(overrides, "service_id", SERVICE_ID_KEY)
            missing = [n for n, v in (
                ("endpoint", endpoint), ("api_key", api_key), ("service_id", service_id),
            ) if not v]
            if missing:
                return False, f"配置不完整，缺少：{', '.join(missing)}（请先在系统设置 → 记忆系统填写）"
            return False, "腾讯记忆客户端初始化失败（SDK 未安装或初始化异常）"
        try:
            await self._sync_recall(client, query="连通性测试", top_k=1)
            return True, "连接正常，腾讯记忆服务可达"
        except Exception as e:
            return False, f"连接失败：{type(e).__name__}: {e}"

    @staticmethod
    async def _sync_recall(client: TencentMemoryClient, query: str, top_k: int = 5) -> list[dict]:
        """同步 SDK 调用经线程池桥接"""
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(client.recall, query=query, top_k=top_k)

    async def get_user_profile(self, app_config: dict, app_id: UUID, user_id: UUID) -> str:
        client = await self._build_client(app_config, app_id, user_id)
        if client is None:
            return ""
        try:
            items = await self._sync_recall(client, query="", top_k=10)
            return "\n".join(
                f"- {i['content']}" for i in items if i.get("type") in ("persona", "instruction", "core")
            )
        except Exception:
            logger.exception("腾讯记忆画像读取失败")
            return ""

    async def get_read_context(self, app_config: dict, app_id: UUID, user_id: UUID, query: str) -> MemoryReadContext:
        client = await self._build_client(app_config, app_id, user_id)
        if client is None:
            return MemoryReadContext()
        ctx = MemoryReadContext()
        try:
            items = await self._sync_recall(client, query=query, top_k=5)
            ctx.episodic_memory = "\n".join(
                f"- {i['content']}" for i in items if i.get("type") in ("episodic", "persona", "scene")
            )
            ctx.procedural_instructions = "\n".join(
                f"- {i['content']}" for i in items if i.get("type") in ("instruction", "core")
            )
        except Exception:
            logger.exception("腾讯记忆召回失败")
        return ctx

    async def get_memory_tools(self, app_config: dict, app_id: UUID, user_id: UUID) -> list:
        logger.info("腾讯记忆模式下不注入内置记忆工具（流水线自管理，避免双写）")
        return []

    async def trigger_write(self, *, app_config: dict, app_id: UUID, user_id: UUID, query: str, answer: str) -> None:
        """写侧管道：L0 追加本轮对话（conversation/add），触发服务端记忆流水线。

        腾讯记忆写侧不落本库业务表，但读 system_config 拿连接配置。与 builtin 写侧
        一致走 worker_run：**子线程新 loop + engine_factory=build_engine 新 session**，
        配置读取绑定在 worker session 上执行——绝不在后台任务里用请求 loop 的
        self.system_config_service：跨 loop 复用会抛 RuntimeError/InterfaceError，
        并发争用请求事务会把池连接毒化回池（表现为后续请求 "cannot use
        Connection.transaction() in a manually started transaction" / 数据库操作失败）。

        调用方处于 async 上下文时 worker_run 的运行中-loop 守卫会抛 RuntimeError；
        用 asyncio.to_thread 将 worker_run 移到线程池——线程内无运行中 loop，守卫放行。
        """
        import asyncio

        async def _coro(session: AsyncSession) -> None:
            # worker loop + worker session 上解析连接参数（独立事务，互不干扰）
            cfg = SystemConfigService(db=session)
            try:
                params = await self._resolve_client_params(app_config, app_id, user_id, cfg=cfg)
            except Exception:
                logger.exception("腾讯记忆写侧参数解析失败")
                return
            if params is None:
                return
            try:
                client = SdkTencentMemoryClient(**params)
            except ImportError:
                logger.warning("腾讯记忆 SDK 未安装，跳过写侧")
                return
            except Exception:
                logger.exception("腾讯记忆写侧客户端初始化失败")
                return
            try:
                client.write_round(query=query, answer=answer)
            except Exception:
                logger.exception("腾讯记忆写入失败")

        # to_thread 内无运行中 loop，worker_run 守卫放行
        # 线程内 asyncio.run 新 loop，必须 engine_factory=build_engine
        await asyncio.to_thread(worker_run, _coro, commit_on_success=True, engine_factory=build_engine)
