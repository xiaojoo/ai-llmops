#!/usr/bin/env python
"""file_extractor 会话不泄漏 + ai_service 流式增量覆盖测试。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFileExtractorNoSessionLeak:
    """_get_cos_service 不创建 session（upload_file_service=None）"""

    def test_get_cos_service_uses_none_session(self):
        """_get_cos_service 不调用 get_default_session_factory，传 upload_file_service=None"""
        from internal.core.file_extractor.file_extractor import FileExtractor

        svc = FileExtractor._get_cos_service()

        # CosService 构造成功
        from internal.service.cos_service import CosService
        assert isinstance(svc, CosService)
        # upload_file_service 是 None（无 session 依赖）
        assert svc.upload_file_service is None
        # minio_service 存在
        assert svc.minio_service is not None

    def test_get_cos_service_no_session_factory_call(self):
        """_get_cos_service 不调用 get_default_session_factory（无 session 创建）"""
        from internal.core.file_extractor import file_extractor as fe_mod

        with patch("package.database.get_default_session_factory") as mock_factory:
            result = fe_mod.FileExtractor._get_cos_service()
            mock_factory.assert_not_called()

    def test_download_file_delegates_to_miniio(self):
        """download_file 正确委托到 minio_service（确认无 session 路径可用）"""
        from internal.core.file_extractor.file_extractor import FileExtractor
        from internal.service.cos_service import CosService
        from internal.service.minio_service import MinioService

        svc = FileExtractor._get_cos_service()
        # miniio 模式下 download_file 委托 minio_service
        with patch.object(MinioService, "download_file") as mock_dl:
            with patch.object(CosService, "_storage_provider", return_value="miniio"):
                svc.download_file("http://example.com/test.pdf", "/tmp/test.pdf")
                mock_dl.assert_called_once_with("http://example.com/test.pdf", "/tmp/test.pdf")


class TestAIServiceOptimizePromptStreaming:
    """optimize_prompt 逐块 yield（不缓冲全部结果）"""

    @pytest.mark.asyncio
    async def test_optimize_prompt_yields_incrementally(self):
        """optimize_prompt 每收到一个 chunk 就 yield 一个 SSE 事件（非批量）"""
        from internal.service.ai_service import AIService

        # 模拟 langchain stream 逐块产出
        chunks = ["Hello", " World", "!"]
        call_count = 0
        yielded_events = []

        def mock_stream(input_dict):
            for chunk in chunks:
                yield chunk

        mock_chain = MagicMock()
        mock_chain.stream = mock_stream

        with patch("langchain_core.prompts.ChatPromptTemplate.from_messages") as mock_tpl:
            mock_tpl.return_value = MagicMock(__or__=lambda self, other: mock_chain)
            with patch("langchain_deepseek.ChatDeepSeek") as mock_llm:
                mock_llm.return_value = MagicMock()
                # Patch the chain construction to return our mock
                with patch("langchain_core.output_parsers.StrOutputParser") as mock_parser:
                    mock_parser.return_value = MagicMock()
                    # 直接 patch 整个 optimize_chain.stream
                    with patch.object(AIService, "optimize_prompt", wraps=AIService.optimize_prompt) as _:
                        # We need to test the actual method; let's construct manually
                        pass

        # 直接测试增量行为：mock 掉 langchain 组件
        from collections.abc import AsyncGenerator

        mock_chain_obj = MagicMock()
        mock_chain_obj.stream = MagicMock(return_value=iter(chunks))

        # Patch 三个 langchain 组件
        with patch("internal.service.ai_service.OPTIMIZE_PROMPT_TEMPLATE", "test"):
            with patch("langchain_core.prompts.ChatPromptTemplate.from_messages") as mock_tpl:
                with patch("langchain_deepseek.ChatDeepSeek") as mock_llm:
                    with patch("langchain_core.output_parsers.StrOutputParser") as mock_parser:
                        # 构造链使 `prompt_template | llm | StrOutputParser` 返回 mock_chain_obj
                        intermediate = MagicMock()
                        intermediate.__or__ = MagicMock(return_value=mock_chain_obj)
                        mock_tpl.return_value.__or__ = MagicMock(return_value=intermediate)

                        events = []
                        async for event in AIService.optimize_prompt("test prompt"):
                            events.append(event)

        # 断言产出 3 个 SSE 事件（每个 chunk 一个）
        assert len(events) == len(chunks), f"Expected {len(chunks)} events, got {len(events)}"
        # 每个事件格式正确
        for event in events:
            assert event.startswith("event: optimize_prompt\ndata:")
            assert event.endswith("\n\n")
