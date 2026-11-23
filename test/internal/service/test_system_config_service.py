#!/usr/bin/env python
"""SystemConfigService 测试。

- 纯函数部分（不依赖 DB）：TENCENT_MEMORY_API_KEY 进 SENSITIVE_KEYS + AES 加解密往返；
- async 化后的 DB 行为（真实 Postgres + db_session 事务回滚）：
  save_configs/get_config/get_config_map/apply_to_env（DB > env 优先级、force 清空语义、时序约束）。
"""
import os

import pytest
from sqlalchemy import select

from internal.model import SystemConfig
from internal.service.system_config_service import SENSITIVE_KEYS, SystemConfigService


def test_tencent_memory_api_key_is_sensitive():
    """腾讯记忆 API Key 必须进 SENSITIVE_KEYS：入库加密、GET 掩码（'********'）"""
    assert "TENCENT_MEMORY_API_KEY" in SENSITIVE_KEYS


def test_tencent_memory_api_key_aes_round_trip():
    """TENCENT_MEMORY_API_KEY 值走 AES 加密存储，解密后原文一致"""
    enc = SystemConfigService._encrypt_value("sk-secret")
    assert enc != "sk-secret"
    assert SystemConfigService._decrypt_value(enc) == "sk-secret"


def _svc(db):
    return SystemConfigService(db=db)


@pytest.mark.asyncio
async def test_save_configs_and_get_config_roundtrip(db_session):
    svc = _svc(db_session)
    await svc.save_configs({"FOO_BAR": "baz", "OPENAI_API_KEY": "sk-secret-1"}, account_id="acc-1")

    assert await svc.get_config("FOO_BAR") == "baz"
    assert await svc.get_config("OPENAI_API_KEY") == "sk-secret-1", "敏感键加密存储，读取自动解密"

    plain = (
        await db_session.execute(select(SystemConfig).where(SystemConfig.key == "FOO_BAR"))
    ).scalar_one()
    assert plain.is_encrypted is False and plain.value == "baz"

    sensitive = (
        await db_session.execute(select(SystemConfig).where(SystemConfig.key == "OPENAI_API_KEY"))
    ).scalar_one()
    assert sensitive.is_encrypted is True
    assert sensitive.value != "sk-secret-1"


@pytest.mark.asyncio
async def test_save_configs_empty_clears_record(db_session, monkeypatch):
    svc = _svc(db_session)
    await svc.save_configs({"FOO_BAR": "baz"})
    assert await svc.get_config("FOO_BAR") == "baz"

    monkeypatch.delenv("FOO_BAR", raising=False)
    await svc.save_configs({"FOO_BAR": ""})
    assert await svc.get_config("FOO_BAR") == "", "空值删除记录，回退环境变量（空）"
    records = (
        await db_session.execute(select(SystemConfig).where(SystemConfig.key == "FOO_BAR"))
    ).scalars().all()
    assert records == []


@pytest.mark.asyncio
async def test_get_config_db_overrides_env(db_session, monkeypatch):
    monkeypatch.setenv("SOME_KEY", "env-value")
    svc = _svc(db_session)
    assert await svc.get_config("SOME_KEY") == "env-value", "无 DB 记录时回退环境变量"

    await svc.save_configs({"SOME_KEY": "db-value"})
    assert await svc.get_config("SOME_KEY") == "db-value", "DB 记录优先于环境变量"


@pytest.mark.asyncio
async def test_apply_to_env_injects_db_config(db_session, monkeypatch):
    svc = _svc(db_session)
    await svc.save_configs({"CONFIG_INJECT_KEY": "from-db"})
    monkeypatch.delenv("CONFIG_INJECT_KEY", raising=False)

    await svc.apply_to_env()
    assert os.getenv("CONFIG_INJECT_KEY") == "from-db"


@pytest.mark.asyncio
async def test_apply_to_env_db_overrides_existing_env(db_session, monkeypatch):
    """DB 配置 > 环境变量：apply_to_env 注入覆盖同键环境变量。"""
    monkeypatch.setenv("CONFIG_INJECT_KEY", "from-env")
    svc = _svc(db_session)
    await svc.save_configs({"CONFIG_INJECT_KEY": "from-db"})

    await svc.apply_to_env()
    assert os.getenv("CONFIG_INJECT_KEY") == "from-db"


@pytest.mark.asyncio
async def test_apply_to_env_force_removes_emptied_key(db_session, monkeypatch):
    """DB 记录值为空时：默认保留环境变量；force=True 时删除环境变量（原语义）。"""
    svc = _svc(db_session)
    # save_configs 对空值会删除记录；force 语义针对「记录存在但值为空」——直接插入空值记录
    db_session.add(SystemConfig(key="CONFIG_INJECT_KEY", value="", is_encrypted=False, group="third"))
    await db_session.flush()
    monkeypatch.setenv("CONFIG_INJECT_KEY", "from-env")

    await svc.apply_to_env()
    assert os.getenv("CONFIG_INJECT_KEY") == "from-env", "空值默认不删除环境变量"

    await svc.apply_to_env(force=True)
    assert "CONFIG_INJECT_KEY" not in os.environ, "force=True 清掉环境变量"


@pytest.mark.asyncio
async def test_get_config_map_decrypts_sensitive(db_session):
    svc = _svc(db_session)
    await svc.save_configs({"MAP_KEY": "v1", "GITHUB_CLIENT_SECRET": "s2"})

    config_map = await svc.get_config_map()
    assert config_map["MAP_KEY"] == "v1"
    assert config_map["GITHUB_CLIENT_SECRET"] == "s2", "get_config_map 应返回解密后的明文"
