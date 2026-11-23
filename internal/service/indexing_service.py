#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/12/3 18:47
@Author : sunxiaojie
@File   : indexing_service.py
"""
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from langchain_core.documents import Document as LCDocument
from redis import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from anyio import to_thread
from starlette.concurrency import run_in_threadpool
from weaviate.classes.query import Filter

from internal.core.file_extractor import FileExtractor
from internal.entity.cache_entity import LOCK_DOCUMENT_UPDATE_ENABLE
from internal.entity.dataset_entity import DocumentStatus, SegmentStatus
from internal.exception import NotFoundException
from internal.lib.helper import generate_text_hash
from internal.model import DatasetQuery, Document, KeywordTable, Segment

from .base_service import BaseService
from .embeddings_service import EmbeddingsService
from .keyword_table_service import KeywordTableService
from .ltp_service import LtpService
from .process_rule_service import ProcessRuleService
from .vector_database_service import VectorDatabaseService

logger = logging.getLogger(__name__)



@dataclass
class IndexingService(BaseService):
    """索引构建服务"""
    db: AsyncSession
    file_extractor: FileExtractor
    process_rule_service: ProcessRuleService
    embeddings_service: EmbeddingsService
    ltp_service: LtpService
    keyword_table_service: KeywordTableService
    vector_database_service: VectorDatabaseService
    redis_client: Redis

    async def build_documents(self, document_ids: list[UUID]) -> None:
        """根据传递的文档id列表构建知识库文档，涵盖了加载、分割、索引构建、数据存储等内容。

        幂等：片段按内容 hash 去重，未变更的片段跳过，变更的片段 upsert。
        """
        # 1、根据传递的文档id获取所有文档
        stmt = select(Document).where(
            Document.id.in_(document_ids)
        )
        documents = (await self.db.execute(stmt)).scalars().all()

        # 2、执行循环遍历所有文档完成对每个文档的构建
        for document in documents:
            try:
                # 2.1、跳过已暂停（stopped）的文档，等待用户继续后再构建
                if document.status == DocumentStatus.STOPPED:
                    continue

                # 3、更新当前状态为解析中，并记录开始处理的时间
                await self.update(document, status=DocumentStatus.PARSING, processing_started_at=datetime.now())

                # 4、执行文档加载步骤，并更新文档的状态与时间
                lc_document = await self._parsing(document)
                if await self._is_paused(document.id):
                    await self.update(document, status=DocumentStatus.STOPPED)
                    continue

                # 5、执行文档分割步骤，并更新文档状态与时间，涵盖了片段信息
                lc_segments = await self._splitting(document, lc_document)
                if await self._is_paused(document.id):
                    await self.update(document, status=DocumentStatus.STOPPED)
                    continue

                # 6、执行文档索引构建，涵盖关键词提取、向量、并更新数据状态
                await self._indexing(document, lc_segments)
                if await self._is_paused(document.id):
                    await self.update(document, status=DocumentStatus.STOPPED)
                    continue

                # 7、存储操作，涵盖文档状态更新，以及向量数据库存储
                await self._completed(document, lc_segments)

            except Exception as e:
                logger.exception("构建文档发生错误，错误信息：%(error)s")
                await self.update(
                    document,
                    status=DocumentStatus.ERROR,
                    error=str(e),
                    stopped_at=datetime.now()
                )
                # 重新抛出：交给 Celery 自动重试（指数退避），临时性异常（DB 抖动/OCR 超时）
                # 有机会自愈；幂等 hash 保证重试不会产生重复片段。业务错误重试耗尽后任务失败。
                raise

    async def _is_paused(self, document_id: UUID) -> bool:
        """检查文档是否已被用户暂停（软暂停：阶段之间生效）"""
        stmt = select(Document.status).where(Document.id == document_id)
        status = await self.db.scalar(stmt)
        return status == DocumentStatus.STOPPED

    async def update_document_enabled(self, document_id: UUID) -> None:
        """根据传递的文档id更新文档状态，同时更新weaviate"""
        # 1、构建缓存键
        cache_key = LOCK_DOCUMENT_UPDATE_ENABLE.format(document_id=document_id)
        # 2、根据传递的document_id获取文档记录
        document = await self.get(Document, document_id)
        if document is None:
            logger.exception(f"当前文档不存在，文档id：{document_id}")
            raise NotFoundException("当前文档不存在")
        # 3、查询归属于当前文档的素有片段的节点id
        stmt = select(Segment.id, Segment.node_id, Segment.enabled).where(
            Segment.document_id == document.id,
            Segment.status == SegmentStatus.COMPLETED
        )
        segments = (await self.db.execute(stmt)).all()
        segment_ids = [id for id, _, _ in segments]
        node_ids = [node_id for _, node_id, _ in segments]

        # 4、执行循环遍历所有node_ids并更新向量数据（weaviate 同步客户端桥接）
        try:
            collection = self.vector_database_service.collection
            for node_id in node_ids:
                try:
                    await run_in_threadpool(
                        collection.data.update,
                        uuid=node_id,
                        properties={
                            "document_enabled": document.enabled,
                        }
                    )
                except Exception as e:
                    # 独立事务边界
                    stmt = (
                        update(Segment)
                        .where(Segment.node_id == node_id)
                        .values(
                            error=str(e),
                            status=SegmentStatus.ERROR,
                            enabled=False,
                            disabled_at=datetime.now(),
                            stopped_at=datetime.now(),
                        )
                    )
                    await self.db.execute(stmt)
                    await self.db.commit()  # 独立事务边界

            # 5、更新关键词表对应的数据（enabled为false表示从关键词表中删除数据，enabLed为true表示在关键词表中新增数据）
            if document.enabled is True:
                # 6、从禁用改为启用，需要新增关键词
                enable_segment_ids = [id for id, _, enabled in segments if enabled is True]
                await self.keyword_table_service.add_keyword_table_from_ids(document.dataset_id, enable_segment_ids)
            else:
                # 7、从启用改为禁用，需要剔除关键词
                await self.keyword_table_service.delete_keyword_table_from_ids(document.dataset_id, segment_ids)
        except Exception:
            # 8、记录日志并将状态还原
            logger.exception("修改向量数据库文档启用状态失败：%(error)s")
            origin_enabled = not document.enabled
            await self.update(
                document,
                enabled=origin_enabled,
                disabled_at=None if origin_enabled else datetime.now(),
            )
        finally:
            self.redis_client.delete(cache_key)

    async def delete_document(self, dataset_id: UUID, document_id: UUID) -> None:
        """根据传递的知识库id+文档id删除文档信息"""
        # 1、查找该文档下的所有片段id列表
        stmt = select(Segment.id).where(
            Segment.document_id == document_id
        )
        segment_ids = [
            uid for uid in (await self.db.execute(stmt)).scalars().all()
        ]
        # 2、调用向量数据库删除其关联记录（weaviate 同步客户端桥接）
        # 注意：filter 需用字符串 UUID，weaviate-client 对 UUID 对象匹配不上
        collection = self.vector_database_service.collection
        await run_in_threadpool(
            collection.data.delete_many,
            where=Filter.by_property("document_id").equal(str(document_id))
        )
        # 3. 删除postgres关联的segment记录
        # 独立事务边界
        stmt = delete(Segment).where(
            Segment.document_id == document_id
        )
        await self.db.execute(stmt)
        await self.db.commit()  # 独立事务边界
        # 4、删除片段id对应的关键词记录
        await self.keyword_table_service.delete_keyword_table_from_ids(dataset_id, segment_ids)

    async def delete_dataset(self, dataset_id: UUID) -> None:
        """根据传递的知识库id执行删除操作"""
        try:
            # 独立事务边界
            # 1、删除关联文档记录
            stmt = delete(Document).where(Document.dataset_id == dataset_id)
            await self.db.execute(stmt)

            # 2、删除关联的片段记录
            stmt = delete(Segment).where(Segment.dataset_id == dataset_id)
            await self.db.execute(stmt)

            # 3、删除关联的关键词表记录
            stmt = delete(KeywordTable).where(KeywordTable.dataset_id == dataset_id)
            await self.db.execute(stmt)

            # 4、删除知识库查询记录
            stmt = delete(DatasetQuery).where(DatasetQuery.dataset_id == dataset_id)
            await self.db.execute(stmt)

            await self.db.commit()  # 独立事务边界

            # 5、调用向量数据库删除知识库关联记录（weaviate 同步客户端桥接）
            await run_in_threadpool(
                self.vector_database_service.collection.data.delete_many,
                where=Filter.by_property("dataset_id").equal(str(dataset_id))
            )
        except Exception:
            logger.exception("异步删除知识库关联内容出错：%(error)s")

    def _build_ocr_provider(self, process_rule) -> object | None:
        """根据处理规则的识别设置构建 OCR 提供者。

        规则中 recognition 段控制：
        - image / pdf_ocr 任一开启才创建 OCR 提供者
        - ocr_provider 选择 local（本地 RapidOCR）/ api（DashScope qwen-vl-ocr）/ custom（自定义）
        """
        if process_rule is None:
            return None
        recognition = (process_rule.rule or {}).get("recognition", {})
        if not recognition:
            return None
        # 图片/扫描PDF 识别开关均关闭时不需要 OCR
        if not recognition.get("image", False) and not recognition.get("pdf_ocr", False):
            return None
        from internal.core.ocr.ocr_provider import create_ocr_provider

        # 规则指定 OCR 提供者时优先使用，否则回退环境变量 OCR_PROVIDER
        ocr_provider = recognition.get("ocr_provider", "")
        try:
            import os as _os
            if ocr_provider:
                _os.environ["OCR_PROVIDER"] = ocr_provider
            # custom 模式：把用户自定义 API 配置传给提供者
            custom = recognition.get("custom") or {}
            return create_ocr_provider(
                provider_name=ocr_provider,
                api_key=custom.get("api_key", ""),
                api_base=custom.get("api_base", ""),
                model=custom.get("model", ""),
            )
        except Exception as e:
            logger.warning("OCR 提供者创建失败（本次构建跳过 OCR）: %s", e)
            return None

    async def _parsing(self, document: Document) -> list[LCDocument]:
        """解析传递的文档为LangChain文档列表（文件提取经 run_in_threadpool 桥接）"""
        # 1、获取upload_file并加载LangChain文档
        from internal.model import ProcessRule, UploadFile
        _upload_file = await self.db.get(UploadFile, document.upload_file_id)
        # 1.1、按处理规则的识别设置创建 OCR 提供者（图片/扫描PDF 需要时）
        process_rule = await self.db.get(ProcessRule, document.process_rule_id)
        ocr_provider = self._build_ocr_provider(process_rule)
        lc_documents = await run_in_threadpool(
            self.file_extractor.load, _upload_file, False, True, ocr_provider=ocr_provider
        )

        # 2、循环处理LangChain文档，并删除多余的空白字符串
        doc_meta: dict = {}
        for lc_document in lc_documents:
            lc_document.page_content = self._clean_extra_text(lc_document.page_content)
            # 提取文档级元数据（标题/页数/页脚），并从 metadata 移除避免污染片段
            if "_doc_meta" in lc_document.metadata:
                doc_meta.update(lc_document.metadata.pop("_doc_meta") or {})

        # 2.1、落库文档元数据（PDF/Word 的标题、页数、页脚）
        if doc_meta:
            try:
                await self.update(
                    document,
                    title=(doc_meta.get("title") or ""),
                    page_count=int(doc_meta.get("page_count") or 0),
                    footer=(doc_meta.get("footer") or ""),
                )
            except Exception as e:
                logger.warning("文档元数据落库失败: %s", e)

        # 3、更新文档状态并记录时间
        await self.update(
            document,
            character_count=sum([len(lc_document.page_content) for lc_document in lc_documents]),
            status=DocumentStatus.SPLITTING,
            processing_completed_at=datetime.now()
        )

        return lc_documents

    async def _splitting(self, document: Document, lc_documents: list[LCDocument]) -> list[LCDocument]:
        """根据传递的信息进行文档分割，拆分成小块片段"""
        # 1、根据process_rule获取文本分割器
        from internal.model import ProcessRule
        process_rule = await self.db.get(ProcessRule, document.process_rule_id)
        text_splitter = self.process_rule_service.get_text_splitter_by_process_rule(
            process_rule,
            self.embeddings_service.calculate_token_count,
        )
        # 2、按照process_rule规则清除多余的字符串
        for lc_document in lc_documents:
            lc_document.page_content = self.process_rule_service.clean_text_by_process_rule(
                lc_document.page_content,
                process_rule,
            )

        # 3、分割文档列表为片段列表（CPU 活，经 run_in_threadpool 桥接避免阻塞事件循环）
        lc_segments = await run_in_threadpool(text_splitter.split_documents, lc_documents)

        # 4、获取对应文档下得到最大片段位置（幂等：重复构建从已有位置继续）
        stmt = select(func.coalesce(func.max(Segment.position), 0)).where(
            Segment.document_id == document.id
        )
        position = await self.db.scalar(stmt)

        # 5、加载文档已存在的片段 hash → 记录映射，用于幂等去重（复用记录）
        stmt = select(Segment).where(
            Segment.document_id == document.id,
            Segment.status == SegmentStatus.COMPLETED,
        )
        existing_segments = (await self.db.execute(stmt)).scalars().all()
        hash_to_segment = {segment.hash: segment for segment in existing_segments}

        # 6、循环处理片段数据并添加元数据，同时存储到postgres数据库中
        doc_footer = (document.footer or "") if hasattr(document, "footer") else ""
        doc_title = (document.title or "") if hasattr(document, "title") else ""
        segments = []
        for lc_segment in lc_segments:
            position += 1
            content = lc_segment.page_content
            content_hash = generate_text_hash(content)

            page_number = int(lc_segment.metadata.get("page_number") or 0)
            headings = lc_segment.metadata.get("headings") or []
            section_title = (headings[-1] if headings else doc_title) or ""
            segment_footer = doc_footer

            # 幂等：内容未变更的片段复用已有记录，跳过向量库写入
            existing = hash_to_segment.get(content_hash)
            if existing is not None:
                segments.append(existing)
                lc_segment.metadata = {
                    "account_id": str(existing.account_id),
                    "dataset_id": str(existing.dataset_id),
                    "document_id": str(existing.document_id),
                    "segment_id": str(existing.id),
                    "node_id": str(existing.node_id),
                    "document_enabled": True,
                    "segment_enabled": True,
                    "skip_indexing": True,
                    "headings": headings,
                    "content_type": existing.content_type,
                    "image_url": existing.image_url,
                    "summary": existing.summary,
                    "parent_segment_id": str(existing.parent_segment_id) if existing.parent_segment_id else "",
                }
                continue

            content_type = lc_segment.metadata.get("content_type", "text")
            image_url = lc_segment.metadata.get("image_url", "")

            segment_instance = await self.create(
                Segment,
                account_id=document.account_id,
                dataset_id=document.dataset_id,
                document_id=document.id,
                node_id=uuid.uuid4(),
                position=position,
                content=content,
                character_count=len(content),
                token_count=self.embeddings_service.calculate_token_count(content),
                hash=content_hash,
                status=SegmentStatus.WAITING,
                content_type=content_type,
                image_url=image_url,
                page_number=page_number,
                section_title=section_title,
                footer=segment_footer,
            )

            lc_segment.metadata = {
                "account_id": str(document.account_id),
                "dataset_id": str(document.dataset_id),
                "document_id": str(document.id),
                "segment_id": str(segment_instance.id),
                "node_id": str(segment_instance.node_id),
                "document_enabled": False,
                "segment_enabled": False,
                "skip_indexing": False,
                "headings": headings,
                "content_type": content_type,
                "image_url": image_url,
                "summary": "",
                "parent_segment_id": "",
                "page_number": page_number,
                "section_title": section_title,
                "footer": segment_footer,
            }

            segments.append(segment_instance)

        # 7、层级化索引
        try:
            await self._build_hierarchy(lc_segments, process_rule=process_rule)
        except Exception as e:
            logger.warning("构建片段层级关系失败（不影响主体索引）: %s", e)

        # 8、更新文档的数据、涵盖状态、token数等内容
        await self.update(
            document,
            token_count=sum([segment.token_count for segment in segments]),
            status=DocumentStatus.INDEXING,
            splitting_completed_at=datetime.now()
        )

        return lc_segments

    async def _build_hierarchy(self, lc_segments: list[LCDocument], process_rule=None) -> None:
        """按一级标题分组构建父子层级（RAPTOR 简化版）"""
        summary_mode = "prefix"
        summary_model = ""
        try:
            rule = (process_rule.rule or {}) if process_rule else {}
            segment_rule = rule.get("segment") or {}
            recognition = rule.get("recognition") or {}
            summary_mode = recognition.get("summary_mode") or segment_rule.get("summary_mode", "prefix")
            summary_model = recognition.get("summary_model", "") or ""
        except Exception:
            pass

        groups: dict[str, list] = {}
        for lc in lc_segments:
            if lc.metadata.get("content_type") in ("table", "image"):
                continue
            headings = lc.metadata.get("headings") or []
            if not headings:
                continue
            chapter_key = headings[0]
            groups.setdefault(chapter_key, []).append(lc)

        for chapter_key, group in groups.items():
            chapter = group[0]
            summary = await self._make_summary(chapter.page_content, mode=summary_mode, model=summary_model)
            chapter.metadata["summary"] = summary
            chapter.metadata["content_type"] = "heading"
            await self._update_segment_fields(
                chapter.metadata["segment_id"],
                summary=summary,
                content_type="heading",
            )
            for sub in group[1:]:
                sub_meta = sub.metadata
                sub_meta["parent_segment_id"] = str(chapter.metadata["segment_id"])
                await self._update_segment_fields(
                    sub_meta["segment_id"],
                    parent_segment_id=chapter.metadata["segment_id"],
                )

    async def _make_summary(self, content: str, mode: str = "prefix", model: str = "", max_len: int = 300) -> str:
        """章节摘要生成（LLM 调用经 run_in_threadpool 桥接）。"""
        text = (content or "").strip()
        if not text:
            return ""
        if mode == "llm":
            summary = await self._llm_summarize(text, model=model)
            if summary:
                return summary
        return text[:max_len]

    async def _llm_summarize(self, content: str, model: str = "", max_len: int = 300) -> str:
        """调用指定 LLM 生成章节摘要（run_in_threadpool 桥接）；
        失败/无 Key 时返回空串（调用方回退 prefix）"""
        provider_name, _, model_name = model.partition("/")
        if not provider_name or not model_name:
            provider_name, model_name = "deepseek", "deepseek-v4-flash"
        try:
            from langchain_core.prompts import ChatPromptTemplate

            from internal.core.language_model import LanguageModelManager

            manager = LanguageModelManager()
            model_class = manager.get_model_class_by_provider_and_model(provider_name, model_name)
            llm = model_class(model=model_name, temperature=0)
            prompt = ChatPromptTemplate.from_messages([
                ("system", "你是文档摘要助手。请用简洁的中文概括给定章节的核心内容，不超过 200 字，直接输出摘要正文。"),
                ("human", "章节内容：\n{content}"),
            ])
            # LLM 同步 invoke 经 run_in_threadpool 桥接，不阻塞事件循环
            result = await run_in_threadpool((prompt | llm).invoke, {"content": content[:4000]})
            summary = (result.content or "").strip()
            return summary[:max_len]
        except Exception as e:
            logger.warning("LLM 章节摘要失败（%s/%s），回退截取前缀: %s", provider_name, model_name, e)
            return ""

    async def _update_segment_fields(self, segment_id, **fields) -> None:
        """更新 Segment 记录的层级/类型字段（供 Weaviate metadata 使用）"""
        # 独立事务边界
        await self.db.execute(
            update(Segment)
            .where(Segment.id == segment_id)
            .values(**fields)
        )
        await self.db.commit()  # 独立事务边界

    async def _indexing(self, document: Document, lc_segments: list[LCDocument]) -> None:
        """根据传递的信息构建索引，涵盖关键词提取、词表构建"""
        for lc_segment in lc_segments:
            # 1、提取每一片段对应的关键词（asyncio.to_thread 线程池桥接，避免跨 loop 死锁）
            import asyncio
            keywords = await asyncio.to_thread(
                self.ltp_service.extract_keywords, lc_segment.page_content, 10
            )

            # 2、逐条更新文档片段的关键词
            # 独立事务边界
            await self.db.execute(
                update(Segment)
                .where(Segment.id == lc_segment.metadata["segment_id"])
                .values(
                    keywords=keywords,
                    status=SegmentStatus.INDEXING,
                    indexing_completed_at=datetime.now()
                )
            )
            await self.db.commit()  # 独立事务边界

            # 3、获取当前知识库的关键词表
            keyword_table_record = await self.keyword_table_service.get_keyword_table_from_dataset_id(document.dataset_id)

            keyword_table = {
                field: set(value) for field, value in keyword_table_record.keyword_table.items()
            }

            # 4、循环将新关键词添加到关键词表中
            for keyword in keywords:
                if keyword not in keyword_table:
                    keyword_table[keyword] = set()
                keyword_table[keyword].add(lc_segment.metadata["segment_id"])

            # 5、更新关键词表
            await self.update(
                keyword_table_record,
                keyword_table={field: list(value) for field, value in keyword_table.items()}
            )

        # 6、更新文档状态
        await self.update(
            document,
            indexing_completed_at=datetime.now()
        )

    async def _completed(self, document: Document, lc_segments: list[LCDocument]) -> None:
        """存储文档片段到向量数据库，并完成状态更新（幂等）"""
        # 1、循环遍历片段列表数据，将文档状态及片段状态设置成True
        for lc_segment in lc_segments:
            lc_segment.metadata["document_completed"] = True
            lc_segment.metadata["document_enabled"] = True
            lc_segment.metadata["segment_enabled"] = True

        # 2. 分批写入向量数据库（weaviate 同步客户端经 run_in_threadpool 桥接）
        ids_to_write = []
        try:
            for i in range(0, len(lc_segments), 10):
                chunks = lc_segments[i:i + 10]
                write_chunks = []
                for chunk in chunks:
                    if chunk.metadata.get("skip_indexing"):
                        continue
                    if (
                        chunk.metadata.get("content_type") == "image"
                        and not (chunk.page_content or "").strip()
                    ):
                        continue
                    write_chunks.append(chunk)
                if not write_chunks:
                    continue

                write_ids = [chunk.metadata["node_id"] for chunk in write_chunks]
                await run_in_threadpool(
                    self.vector_database_service.vector_store.add_documents,
                    write_chunks, ids=write_ids
                )
                ids_to_write.extend(write_ids)

            # 3、统一更新实际写入的片段状态
            if ids_to_write:
                # 独立事务边界
                await self.db.execute(
                    update(Segment)
                    .where(Segment.node_id.in_(ids_to_write))
                    .values(
                        status=SegmentStatus.COMPLETED,
                        completed_at=datetime.now(),
                        enabled=True,
                    )
                )
                await self.db.commit()  # 独立事务边界
        except Exception:
            logger.exception(
                "构建文档片段索引发生异常"
            )
            if ids_to_write:
                # 独立事务边界
                await self.db.execute(
                    update(Segment)
                    .where(Segment.node_id.in_(ids_to_write))
                    .values(status=SegmentStatus.ERROR)
                )
                await self.db.commit()  # 独立事务边界
        # 更新文档的状态数据
        await self.update(
            document,
            status=DocumentStatus.COMPLETED,
            completed_at=datetime.now(),
            enabled=True,
        )

    @classmethod
    def _clean_extra_text(cls, text: str) -> str:
        """清除过滤传递的多余空白字符串"""
        text = re.sub(r'<\|', '<', text)
        text = re.sub(r'\|>', '>', text)
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\xEF\xBF\xBE]', '', text)
        text = re.sub('\uFFFE', '', text)
        return text
