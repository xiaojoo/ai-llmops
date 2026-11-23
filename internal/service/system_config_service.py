#!/usr/bin/env python
"""
系统配置服务：/settings 页面的配置项管理。

存储：system_config 表（key/value），敏感值用主密钥 AES 加密后入库。
读取优先级：system_config（DB 用户配置）> 环境变量 > 默认值。
加密主密钥：CONFIG_MASTER_KEY 环境变量，缺省回退 JWT_SECRET_KEY。
"""
import logging
import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.lib.crypto import build_master_key, decrypt_value, encrypt_value
from internal.model import SystemConfig

from .base_service import BaseService

logger = logging.getLogger(__name__)


# 敏感配置项清单：值为空时不回显（GET 返回掩码），保存时加密
# 说明：API_KEY（百度千帆）已从界面移除，保留在清单中以掩码历史存量数据，避免 GET 泄露旧值。
SENSITIVE_KEYS = {
    "JWT_SECRET_KEY", "WEAVIATE_API_KEY", "REDIS_PASSWORD", "SQLALCHEMY_DATABASE_URI",
    "COS_SECRET_ID", "COS_SECRET_KEY", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET",
    "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "DASHSCOPE_API_KEY",
    "QWEN3_API_KEY", "QWEN3_5_PLUS_API_KEY", "LOCAL_LLM_API_KEY",
    "EMBEDDING_API_KEY", "RERANK_API_KEY", "OCR_API_KEY",
    "LANGSMITH_API_KEY", "GAODE_API_KEY", "SERPER_API_KEY", "HUGGINGFACEHUB_API_TOKEN",
    "API_KEY", "FEISHU_APP_ID", "FEISHU_APP_SECRET", "LLMOPS_ACCESS_TOKEN",
    "TENCENT_MEMORY_API_KEY", "TENCENT_MEMORY_ADMIN_KEY",
}


@dataclass
class SystemConfigService(BaseService):
    """系统配置服务"""
    db: AsyncSession

    @staticmethod
    def _master_key() -> bytes:
        """获取加密主密钥（32 字节）：CONFIG_MASTER_KEY 优先，回退 JWT_SECRET_KEY"""
        secret = os.getenv("CONFIG_MASTER_KEY") or os.getenv("JWT_SECRET_KEY") or "llmops-default-master-key"
        return build_master_key(secret)

    @staticmethod
    def _encrypt_value(plain: str) -> str:
        """AES-CBC 加密明文，返回 base64(iv + ciphertext)"""
        return encrypt_value(plain, SystemConfigService._master_key())

    @staticmethod
    def _decrypt_value(encoded: str) -> str:
        """解密 base64(iv + ciphertext)；失败返回原文（兼容未加密旧数据）"""
        return decrypt_value(encoded, SystemConfigService._master_key())

    async def get_config_map(self) -> dict[str, str]:
        """读取全部 DB 配置（已解密），供运行时合并到环境变量"""
        stmt = select(SystemConfig)
        records = (await self.db.execute(stmt)).scalars().all()
        result = {}
        for record in records:
            value = record.value
            if record.is_encrypted and value:
                value = self._decrypt_value(value)
            result[record.key] = value
        return result

    async def get_config(self, key: str) -> str:
        """读取单个配置：DB > 环境变量 > 空"""
        stmt = select(SystemConfig).where(SystemConfig.key == key)
        record = (await self.db.execute(stmt)).scalar_one_or_none()
        if record and record.value:
            if record.is_encrypted:
                return self._decrypt_value(record.value)
            return record.value
        return os.getenv(key, "")

    async def apply_to_env(self, force: bool = False) -> None:
        """把 DB 中的配置覆盖到 os.environ（DB 优先于 .env/compose 环境变量）。

        - 业务代码统一走 os.getenv，此处注入后零改动生效
        - 默认只覆盖「DB 中已存在」的项；force=True 时连空值也清掉环境变量
        - 幂等：重复调用安全（取 DB 最新值覆盖）

        **时序约束**：本方法必须在 `get_settings()` 首次调用前执行（由 lifespan
        startup 调用），否则 system_config 的 DB 配置（含 EMBEDDING_DEVICE/RERANK_DEVICE
        等设备项）在 settings 单例构建后不再生效。
        """
        try:
            config_map = await self.get_config_map()
        except Exception as e:
            logger.warning("DB 配置注入环境变量失败（可能 DB 未就绪），沿用 .env/compose 配置: %s", e)
            return
        for key, value in config_map.items():
            if value:
                os.environ[key] = value
            elif force and key in os.environ:
                os.environ.pop(key, None)

    async def save_configs(self, configs: dict[str, str], account_id=None) -> None:
        """批量保存配置（幂等 upsert）。空值不写入（保持已有配置）。

        configs: {key: value}；敏感键自动加密存储。
        """
        for key, value in configs.items():
            if value is None:
                continue
            # 空字符串视为"清空该配置"：删除记录，回退环境变量
            if value == "":
                await self._delete_config(key)
                continue
            record = (await self.db.execute(
                select(SystemConfig).where(SystemConfig.key == key)
            )).scalar_one_or_none()
            is_sensitive = key in SENSITIVE_KEYS
            stored = self._encrypt_value(value) if is_sensitive else value
            if record:
                await self.update(
                    record,
                    value=stored,
                    is_encrypted=is_sensitive,
                    updated_by=str(account_id) if account_id else "",
                )
            else:
                await self.create(
                    SystemConfig,
                    key=key,
                    value=stored,
                    is_encrypted=is_sensitive,
                    group=self._guess_group(key),
                    updated_by=str(account_id) if account_id else "",
                )

    async def _delete_config(self, key: str) -> None:
        """删除单个配置记录（清空后回退环境变量）"""
        record = (await self.db.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )).scalar_one_or_none()
        if record:
            await self.delete(record)

    @staticmethod
    def _guess_group(key: str) -> str:
        """根据配置项名猜测分组（前端 tab）"""
        key_upper = key.upper()
        if "OPENAI" in key_upper or "DEEPSEEK" in key_upper or "MOONSHOT" in key_upper or "DASHSCOPE" in key_upper or "LANGSMITH" in key_upper or "HF_" in key_upper or "HUGGINGFACE" in key_upper or "SERPER" in key_upper or "GAODE" in key_upper or "BROWSER_" in key_upper or "EMBEDDING" in key_upper or "RERANK" in key_upper or "OCR_" in key_upper or "QUERY_REWRITE" in key_upper or "RETRIEVAL" in key_upper or "TRANSFORMERS" in key_upper or "API_KEY" in key_upper or "BASE_URL" in key_upper or "QWEN" in key_upper or "WENXIN" in key_upper or "LOCAL_LLM" in key_upper:
            return "llm"
        if "COS_" in key_upper or "MINIO" in key_upper or "STORAGE" in key_upper:
            return "oss"
        if "SQLALCHEMY" in key_upper or "DATABASE" in key_upper:
            return "database"
        if "REDIS" in key_upper or "CELERY" in key_upper:
            return "redis"
        if "WEAVIATE" in key_upper or "VECTOR" in key_upper:
            return "vector"
        if "FEISHU" in key_upper or "LLMOPS" in key_upper:
            return "feishu"
        if "JWT" in key_upper or "GITHUB" in key_upper or "ASSISTANT" in key_upper or "MIGRATION" in key_upper:
            return "third"
        return "third"
