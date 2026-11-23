#!/usr/bin/env python
"""SdkTencentMemoryClient 测试：用假 SDK 模块验证懒加载与接口形态（SDK 差异隔离点）"""
import sys
import types
from unittest.mock import MagicMock

import pytest

from internal.service.memory_provider.tencent_client import SdkTencentMemoryClient


def _install_fake_sdk(monkeypatch):
    """向 sys.modules 注入假 tencentdb_agent_memory 模块（SDK 未安装环境可测）"""
    fake = types.ModuleType("tencentdb_agent_memory")
    fake.MemoryClient = MagicMock()
    monkeypatch.setitem(sys.modules, "tencentdb_agent_memory", fake)
    return fake


def test_missing_sdk_raises_import_error(monkeypatch):
    # 与 SDK 是否已安装/vendor 解耦：sys.modules 中置 None 会强制 import 抛 ImportError
    monkeypatch.setitem(sys.modules, "tencentdb_agent_memory", None)
    with pytest.raises(ImportError):
        SdkTencentMemoryClient(endpoint="http://127.0.0.1:8420", api_key="sk-test", service_id="mem-test")


def test_client_builds_and_recalls(monkeypatch):
    fake = _install_fake_sdk(monkeypatch)
    client = SdkTencentMemoryClient(endpoint="http://127.0.0.1:8420", api_key="sk-test", service_id="mem-test")
    fake.MemoryClient.assert_called_once()
    fake.MemoryClient.return_value.search_atomic.return_value = {
        "items": [
            {"type": "scene", "content": "用户准备搬家", "score": 0.9},
        ],
    }
    items = client.recall("搬家", top_k=5)
    assert items[0]["content"] == "用户准备搬家"
    fake.MemoryClient.return_value.search_atomic.assert_called_once()


def test_client_writes_round(monkeypatch):
    fake = _install_fake_sdk(monkeypatch)
    client = SdkTencentMemoryClient(endpoint="http://127.0.0.1:8420", api_key="sk-test", service_id="mem-test")
    client.write_round(query="你好", answer="你好！")
    fake.MemoryClient.return_value.add_conversation.assert_called_once()
