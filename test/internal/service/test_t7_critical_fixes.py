#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
关键修复覆盖测试：
- retry_document 使用 container 工厂构造 IndexingService（不崩）
- _recall 对 FullTextRetriever 使用同步 Session（full_text/hybrid 路径可跑）
- _llm_summarize 经 run_in_threadpool 桥接（不阻塞事件循环）
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from uuid import uuid4


class TestCritical1RetryDocumentUsesFactory:
    """retry_document 应使用 container 工厂构造 IndexingService，不传 None 依赖。"""

    @pytest.mark.asyncio
    async def test_retry_document_uses_container_factory(self):
        """retry_document 应 import create_indexing_service 而非直接构造 IndexingService"""
        import inspect
        from internal.service.document_service import DocumentService

        # 验证 retry_document 源码包含 create_indexing_service 调用（而非 IndexingService 构造）
        source = inspect.getsource(DocumentService.retry_document)
        assert "create_indexing_service" in source, \
            "retry_document 应使用 container 工厂 create_indexing_service"
        assert "IndexingService(" not in source, \
            "retry_document 不应直接构造 IndexingService"

    @pytest.mark.asyncio
    async def test_retry_document_calls_delete_document(self):
        """retry_document 调用 indexing_service.delete_document"""
        from internal.service.document_service import DocumentService
        from internal.entity.dataset_entity import DocumentStatus

        svc = DocumentService(db=AsyncMock(), redis_client=MagicMock())
        account = MagicMock(id=uuid4())

        doc = MagicMock()
        doc.id = uuid4()
        doc.dataset_id = uuid4()
        doc.account_id = account.id
        doc.status = DocumentStatus.ERROR

        mock_indexing = MagicMock()
        mock_indexing.delete_document = AsyncMock()

        # Patch get + create_indexing_service + update
        with patch.object(svc, "get", AsyncMock(return_value=doc)), \
             patch.object(svc, "update", AsyncMock(return_value=doc)), \
             patch("internal.container.create_indexing_service", return_value=mock_indexing), \
             patch("internal.service.document_service.build_documents"):
            await svc.retry_document(doc.dataset_id, doc.id, account)

        mock_indexing.delete_document.assert_called_once_with(doc.dataset_id, doc.id)


class TestCritical2FullTextRetrieverSyncSession:
    """_recall 对 FullTextRetriever 使用同步 Session。"""

    @pytest.mark.asyncio
    async def test_recall_full_text_uses_sync_session_source_check(self):
        """验证 _recall 源码使用 get_sync_session_factory 而非 self.db"""
        import inspect
        from internal.service.retrieval_service import RetrievalService

        source = inspect.getsource(RetrievalService._recall)
        assert "get_sync_session_factory" in source, \
            "_recall 应使用 get_sync_session_factory 创建同步 session"
        assert "sync_session.close()" in source, \
            "_recall 应在 finally 块关闭同步 session"

    @pytest.mark.asyncio
    async def test_recall_full_text_uses_sync_session_runtime(self):
        """full_text 策略路径应创建同步 Session 传给 FullTextRetriever（运行时验证）"""
        from internal.service.retrieval_service import RetrievalService
        from internal.core import retrievers as retrievers_module

        mock_db = AsyncMock()
        svc = RetrievalService(db=mock_db, ltp_service=MagicMock(), vector_database_service=MagicMock())

        mock_sync_session = MagicMock()
        mock_factory = MagicMock(return_value=mock_sync_session)
        mock_rtp = AsyncMock(return_value=[])

        # Mock retriever classes at the package level where they're imported from
        mock_ft_class = MagicMock()
        mock_ft_instance = MagicMock()
        mock_ft_instance.invoke = MagicMock(return_value=[])
        mock_ft_class.return_value = mock_ft_instance

        mock_sem_class = MagicMock()
        mock_bm25_class = MagicMock()

        with patch("package.database.get_sync_session_factory", return_value=mock_factory), \
             patch.object(retrievers_module, "FullTextRetriever", mock_ft_class), \
             patch.object(retrievers_module, "SemanticRetriever", mock_sem_class), \
             patch.object(retrievers_module, "BM25Retriever", mock_bm25_class), \
             patch("internal.core.retrievers.rrf.rrf_fusion", return_value=[]), \
             patch("internal.service.retrieval_service.run_in_threadpool", mock_rtp), \
             patch("internal.service.retrieval_service.get_weaviate_client", return_value=MagicMock()):

            await svc._recall(
                dataset_ids=[uuid4()],
                query="test",
                retrieval_strategy="full_text",
                k=4,
                score=0,
            )

        # 关键：FullTextRetriever 被构造时传入同步 session
        mock_ft_class.assert_called_once()
        call_kwargs = mock_ft_class.call_args
        assert call_kwargs.kwargs.get("db") is mock_sync_session or call_kwargs[1].get("db") is mock_sync_session
        # 同步 session 被关闭
        mock_sync_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_recall_hybrid_uses_sync_session_runtime(self):
        """hybrid 策略路径同样使用同步 Session"""
        from internal.service.retrieval_service import RetrievalService
        from internal.core import retrievers as retrievers_module

        mock_db = AsyncMock()
        svc = RetrievalService(db=mock_db, ltp_service=MagicMock(), vector_database_service=MagicMock())

        mock_sync_session = MagicMock()
        mock_factory = MagicMock(return_value=mock_sync_session)
        mock_rtp = AsyncMock(return_value=[])

        mock_ft_class = MagicMock()
        mock_ft_instance = MagicMock()
        mock_ft_instance.invoke = MagicMock(return_value=[])
        mock_ft_class.return_value = mock_ft_instance

        mock_sem_class = MagicMock()
        mock_bm25_class = MagicMock()

        with patch("package.database.get_sync_session_factory", return_value=mock_factory), \
             patch.object(retrievers_module, "FullTextRetriever", mock_ft_class), \
             patch.object(retrievers_module, "SemanticRetriever", mock_sem_class), \
             patch.object(retrievers_module, "BM25Retriever", mock_bm25_class), \
             patch("internal.core.retrievers.rrf.rrf_fusion", return_value=[]), \
             patch("internal.service.retrieval_service.run_in_threadpool", mock_rtp), \
             patch("internal.service.retrieval_service.get_weaviate_client", return_value=MagicMock()):

            await svc._recall(
                dataset_ids=[uuid4()],
                query="test",
                retrieval_strategy="hybrid",
                k=4,
                score=0,
            )

        mock_ft_class.assert_called_once()
        call_kwargs = mock_ft_class.call_args
        assert call_kwargs.kwargs.get("db") is mock_sync_session or call_kwargs[1].get("db") is mock_sync_session
        mock_sync_session.close.assert_called_once()


class TestCritical3LlmSummarizeBridged:
    """_llm_summarize 应为 async 并经 run_in_threadpool 桥接 LLM 调用。"""

    @pytest.mark.asyncio
    async def test_llm_summarize_is_async(self):
        """_llm_summarize 应为 async def"""
        from internal.service.indexing_service import IndexingService
        import inspect
        assert inspect.iscoroutinefunction(IndexingService._llm_summarize), \
            "_llm_summarize 应为 async def"

    @pytest.mark.asyncio
    async def test_make_summary_is_async(self):
        """_make_summary 应为 async def"""
        from internal.service.indexing_service import IndexingService
        import inspect
        assert inspect.iscoroutinefunction(IndexingService._make_summary), \
            "_make_summary 应为 async def"

    @pytest.mark.asyncio
    async def test_llm_summarize_calls_run_in_threadpool(self):
        """_llm_summarize 应通过 run_in_threadpool 桥接 LLM invoke"""
        from internal.service.indexing_service import IndexingService

        svc = IndexingService(
            db=AsyncMock(), file_extractor=None, process_rule_service=None,
            embeddings_service=None, ltp_service=None, keyword_table_service=None,
            vector_database_service=None, redis_client=MagicMock(),
        )

        # Mock LLM chain invoke
        mock_result = MagicMock()
        mock_result.content = "这是摘要"

        with patch("internal.service.indexing_service.run_in_threadpool", new_callable=AsyncMock, return_value=mock_result) as mock_rtp:
            result = await svc._llm_summarize("很长的文本内容", model="deepseek/deepseek-v4-flash")

        # 关键：run_in_threadpool 被调用（LLM invoke 被桥接）
        mock_rtp.assert_called_once()
        assert result == "这是摘要"

    @pytest.mark.asyncio
    async def test_build_hierarchy_awaits_make_summary(self):
        """_build_hierarchy 应 await _make_summary（不同步调用）"""
        from internal.service.indexing_service import IndexingService
        from langchain_core.documents import Document as LCDocument

        svc = IndexingService(
            db=AsyncMock(), file_extractor=None, process_rule_service=None,
            embeddings_service=None, ltp_service=None, keyword_table_service=None,
            vector_database_service=None, redis_client=MagicMock(),
        )

        # 创建带 headings 的 lc_segment
        lc_seg = LCDocument(
            page_content="章节内容",
            metadata={"headings": ["第一章"], "segment_id": str(uuid4()), "content_type": "text"}
        )

        # Patch _make_summary 为 AsyncMock
        svc._make_summary = AsyncMock(return_value="摘要文本")
        svc._update_segment_fields = AsyncMock()

        await svc._build_hierarchy([lc_seg])

        # 关键：_make_summary 被 await（AsyncMock 被调用）
        svc._make_summary.assert_called_once()
