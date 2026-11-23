#!/usr/bin/env python
"""
@Time    : 2025/12/9 20:46
@Author  : sunxiaojie
@File    : retrieval_service.py
"""
import asyncio
import logging
import os
from dataclasses import dataclass
from uuid import UUID

import weaviate
from langchain_core.documents import Document as LCDocument
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from anyio import to_thread
from starlette.concurrency import run_in_threadpool

from internal.core.agent.entities.agent_entity import DATASET_RETRIEVAL_TOOL_NAME
from internal.entity.dataset_entity import RetrievalSource, RetrievalStrategy
from internal.exception import NotFoundException
from internal.extensions.weaviate import get_weaviate_client
from internal.lib.helper import combine_documents
from internal.model import Account, Dataset, DatasetQuery, Segment

from .base_service import BaseService
from .ltp_service import LtpService
from .vector_database_service import VectorDatabaseService

logger = logging.getLogger(__name__)


# 查询改写提示词模板
QUERY_REWRITE_PROMPT_TEMPLATE = (
    "你是检索查询改写助手。请把用户的口语化问题改写为适合知识库检索的"
    "简洁关键词式查询，只输出改写后的查询本身，不要任何解释。\n"
    "用户问题：{query}"
)

# Agentic 重检补充查询生成提示词模板：
# 上一轮检索不充分时，基于原查询 + 缺失信息生成一轮新的精炼检索查询。
# 关键：只保留可检索的关键词/短语，剔除解释性长文本（"缺少…""现有片段…"等），
# 确保每轮生成的查询聚焦且与上一轮不同。
AGENTIC_QUERY_GENERATE_PROMPT_TEMPLATE = (
    "你是知识库检索查询生成助手。上一轮检索不充分，需要基于原查询和缺失信息"
    "重新生成一轮更完整的检索查询。\n"
    "要求：\n"
    "1. 只输出检索查询本身，不要解释；\n"
    "2. 把缺失信息中可检索的关键词/概念融入查询（例如人物名、章节名、资料类型等）；\n"
    "3. 剔除解释性长文本（如\"缺少…\"\"现有片段…\"\"无法…\"等描述），只保留检索词；\n"
    "4. 不要重复上一轮已有的内容，让新查询更聚焦、覆盖缺失点。\n\n"
    "上一轮查询：{query}\n"
    "缺失信息：{missing}"
)

# 检索结果评估提示词模板（Agentic RAG：判断召回是否充分覆盖问题）
RETRIEVAL_EVALUATE_PROMPT_TEMPLATE = (
    "你是检索质量评估员。判断下面的检索结果是否足以回答用户问题。\n"
    "只输出 JSON，格式：{{\"sufficient\": true/false, \"score\": 0-10 整数, "
    "\"missing\": \"缺失的关键信息或关键词（不足时填写，充足时留空）\"}}\n\n"
    "用户问题：{query}\n\n"
    "检索到的文档片段：\n{documents}"
)


@dataclass
class RetrievalService(BaseService):
    """检索服务"""
    db: AsyncSession
    ltp_service: LtpService
    vector_database_service: VectorDatabaseService

    async def search_in_datasets(
            self,
            dataset_ids: list[UUID],
            query: str,
            retrieval_strategy: str = RetrievalStrategy.SEMANTIC,
            k: int = 4,
            score: float = 0,
            retrieval_score: str = RetrievalSource.HIT_TESTING,
            account_id: UUID | None = None,
            rerank_enable: bool = False,
            rerank_top_n: int = 20,
            query_rewrite_enable: bool = False,
            actual_query_holder: list | None = None,
            **kwargs,
    ) -> list[LCDocument]:
        """根据传递的query+知识库列表执行检索，返回检索的文档+得分数据"""
        # 0、可选查询改写
        if "query_rewrite" in kwargs:
            query_rewrite_config = kwargs["query_rewrite"]
            if isinstance(query_rewrite_config, dict):
                query_rewrite_enable = query_rewrite_config.get("enable", query_rewrite_enable)
        if query_rewrite_enable:
            query = await self._rewrite_query(query)
        if actual_query_holder is not None:
            actual_query_holder.append(query)

        # 1、提取知识库列表并校验权限同时更新知识库id
        stmt = select(Dataset).where(
            Dataset.id.in_(dataset_ids), Dataset.account_id == account_id
        )
        datasets = (await self.db.execute(stmt)).scalars().all()
        if datasets is None or len(datasets) == 0:
            raise NotFoundException("当前无知识库可执行检索")
        dataset_ids = [dataset.id for dataset in datasets]

        # 2、执行多路召回（同步核心逻辑，线程池桥接）
        candidate_documents = await self._recall(
            dataset_ids=dataset_ids,
            query=query,
            retrieval_strategy=retrieval_strategy,
            k=k,
            score=score,
        )

        # 3、可选 rerank 精排（同步 reranker 桥接）
        if rerank_enable and candidate_documents:
            from internal.core.retrievers.rerank import create_reranker

            reranker = create_reranker(enable=True, top_n=rerank_top_n)
            if reranker is not None:
                candidate_documents = await run_in_threadpool(reranker.rerank, query, candidate_documents)
                candidate_documents = candidate_documents[:k]

        # 4、截断到 top-k
        lc_documents = candidate_documents[:k]

        # 4.1、层级下钻
        if lc_documents:
            lc_documents = await self._hierarchical_expand(lc_documents, k)

        # 5、添加知识库查询记录
        unique_dataset_ids = list({str(doc.metadata["dataset_id"]) for doc in lc_documents})
        for dataset_id in unique_dataset_ids:
            await self.create(
                DatasetQuery,
                dataset_id=dataset_id,
                query=query,
                source=retrieval_score,
                source_app_id=None,
                created_by=str(account_id) if account_id is not None else None,  # 列类型 VARCHAR
            )

        # 6、批量更新片段命中次数
        segment_ids = [doc.metadata.get("segment_id") for doc in lc_documents if doc.metadata.get("segment_id")]
        if segment_ids:
            # 独立事务边界
            await self.db.execute(
                update(Segment)
                .where(Segment.id.in_(segment_ids))
                .values(hit_count=Segment.hit_count + 1)
            )
            await self.db.commit()  # 独立事务边界

        return lc_documents

    async def search_agentic(
            self,
            dataset_ids: list[UUID],
            query: str,
            retrieval_strategy: str = RetrievalStrategy.SEMANTIC,
            k: int = 4,
            score: float = 0,
            account_id: UUID | None = None,
            max_rounds: int = 2,
            evaluate_threshold: int = 7,
            rerank_enable: bool = False,
            rerank_top_n: int = 20,
            query_rewrite_enable: bool = False,
            trace: list | None = None,
            **kwargs,
    ) -> list[LCDocument]:
        """Agentic 检索：多轮召回 + LLM 结果校验 + 不充分自动重检。"""
        strategies = ["hybrid", "semantic"] if retrieval_strategy != "hybrid" else ["semantic", "hybrid"]
        all_docs: dict[str, LCDocument] = {}
        current_query = query
        if trace is None:
            trace = []

        for round_index in range(max_rounds):
            round_strategy = retrieval_strategy if round_index == 0 else strategies[min(round_index, len(strategies) - 1)]
            round_k = k + round_index * 2
            round_score = 0 if round_index > 0 else score

            actual_query_holder: list = []
            docs = await self.search_in_datasets(
                dataset_ids=dataset_ids,
                query=current_query,
                retrieval_strategy=round_strategy,
                k=round_k,
                score=round_score,
                retrieval_score=RetrievalSource.HIT_TESTING,
                account_id=account_id,
                rerank_enable=rerank_enable,
                rerank_top_n=rerank_top_n,
                query_rewrite_enable=query_rewrite_enable,
                actual_query_holder=actual_query_holder,
                **kwargs,
            )
            round_query = actual_query_holder[0] if actual_query_holder else current_query
            for doc in docs:
                seg_id = str(doc.metadata.get("segment_id", ""))
                if seg_id and seg_id not in all_docs:
                    doc.metadata["agentic_round"] = round_index + 1
                    all_docs[seg_id] = doc

            if round_index >= max_rounds - 1:
                trace.append({
                    "round": round_index + 1,
                    "strategy": round_strategy,
                    "query": round_query,
                    "k": round_k,
                    "hits": len(docs),
                    "sufficient": True,
                    "score": evaluate_threshold,
                    "missing": "",
                })
                break

            verdict = await self._evaluate_results(round_query, list(all_docs.values())[:k], threshold=evaluate_threshold)
            trace.append({
                "round": round_index + 1,
                "strategy": round_strategy,
                "query": round_query,
                "k": round_k,
                "hits": len(docs),
                "sufficient": verdict.get("sufficient", True),
                "score": verdict.get("score", evaluate_threshold),
                "missing": verdict.get("missing", ""),
            })
            if verdict.get("sufficient", True):
                break
            missing = (verdict.get("missing") or "").strip()
            if missing:
                base_query = round_query if round_query else current_query
                current_query = await self._generate_agentic_query(base_query, missing) or base_query
            else:
                break

        merged = list(all_docs.values())
        merged.sort(key=lambda d: d.metadata.get("score", 0), reverse=True)
        return merged[:k]

    async def _evaluate_results(self, query: str, documents: list, threshold: int = 7) -> dict:
        """LLM 评估检索结果充分性；失败时默认充分（不阻塞检索）。LLM 调用经线程池桥接。"""
        try:
            import json as _json

            from langchain_deepseek import ChatDeepSeek

            snippets = []
            for i, doc in enumerate(documents[:5], start=1):
                content = (doc.page_content or "")[:300].replace("\n", " ")
                snippets.append(f"[{i}] {content}")
            if not snippets:
                return {"sufficient": True, "score": threshold, "missing": ""}

            llm = ChatDeepSeek(
                model=os.getenv("RETRIEVAL_EVAL_MODEL", "deepseek-v4-flash"),
                temperature=0,
            )
            prompt = RETRIEVAL_EVALUATE_PROMPT_TEMPLATE.format(
                query=query,
                documents="\n".join(snippets),
            )
            output = await asyncio.to_thread(llm.invoke, prompt)
            output = output.content or "{}"
            start, end = output.find("{"), output.rfind("}")
            if start >= 0 and end > start:
                output = output[start:end + 1]
            verdict = _json.loads(output)
            score = int(verdict.get("score", threshold))
            sufficient = bool(verdict.get("sufficient", True)) or score >= threshold
            return {
                "sufficient": sufficient,
                "score": score,
                "missing": str(verdict.get("missing", "") or ""),
            }
        except Exception as e:
            logger.warning("检索结果评估失败，默认充分: %s", e)
            return {"sufficient": True, "score": threshold, "missing": ""}

    async def _rewrite_query(self, query: str) -> str:
        """使用 LLM 把口语化 query 改写为检索友好形式；失败时回退原 query（LLM 调用经线程池桥接）。"""
        try:
            from langchain_deepseek import ChatDeepSeek

            llm = ChatDeepSeek(
                model=os.getenv("QUERY_REWRITE_MODEL", "deepseek-v4-flash"),
                temperature=0,
            )
            result = await asyncio.to_thread(
                llm.invoke, QUERY_REWRITE_PROMPT_TEMPLATE.format(query=query)
            )
            rewritten = result.content
            rewritten = rewritten.strip().strip('"').strip("'")
            return rewritten or query
        except Exception as e:
            logger.warning(f"查询改写失败，回退原始 query: {e}")
            return query

    async def _generate_agentic_query(self, query: str, missing: str) -> str:
        """Agentic 重检：基于上一轮查询 + 缺失信息生成新一轮精炼检索查询（LLM 调用经线程池桥接）。"""
        try:
            from langchain_deepseek import ChatDeepSeek

            llm = ChatDeepSeek(
                model=os.getenv("QUERY_REWRITE_MODEL", "deepseek-v4-flash"),
                temperature=0,
            )
            result = await asyncio.to_thread(
                llm.invoke,
                AGENTIC_QUERY_GENERATE_PROMPT_TEMPLATE.format(query=query, missing=missing),
            )
            generated = result.content
            generated = generated.strip().strip('"').strip("'")
            if generated and generated != query:
                return generated
        except Exception as e:
            logger.warning(f"Agentic 补充查询生成失败，回退拼接形式: {e}")
        return f"{query} {missing}" if missing not in query else query

    async def _hierarchical_expand(self, documents: list[LCDocument], k: int) -> list[LCDocument]:
        """层级下钻：命中章节块时，紧跟插入其子段落块"""
        chapter_ids = [
            str(doc.metadata["segment_id"])
            for doc in documents
            if doc.metadata.get("content_type") == "heading" and doc.metadata.get("segment_id")
        ]

        children_by_parent: dict[str, list[Segment]] = {}
        if chapter_ids:
            stmt = (
                select(Segment)
                .where(
                    Segment.parent_segment_id.in_(chapter_ids),
                    Segment.enabled.is_(True),
                )
                .order_by(Segment.position)
            )
            for child in (await self.db.execute(stmt)).scalars().all():
                children_by_parent.setdefault(str(child.parent_segment_id), []).append(child)

        result: list[LCDocument] = []
        seen_ids = set()

        for doc in documents:
            seg_id = str(doc.metadata.get("segment_id", ""))
            if seg_id and seg_id not in seen_ids:
                seen_ids.add(seg_id)
                result.append(doc)
            if len(result) >= k:
                break
            if doc.metadata.get("content_type") == "heading" and seg_id in children_by_parent:
                for child in children_by_parent[seg_id]:
                    if len(result) >= k:
                        break
                    child_id = str(child.id)
                    if child_id in seen_ids:
                        continue
                    seen_ids.add(child_id)
                    summary = doc.metadata.get("summary") or child.summary
                    content = child.content
                    if summary:
                        content = f"[章节摘要] {summary}\n\n{content}"
                    result.append(LCDocument(
                        page_content=content,
                        metadata={
                            "segment_id": child_id,
                            "node_id": str(child.node_id),
                            "document_id": str(child.document_id),
                            "dataset_id": str(child.dataset_id),
                            "account_id": str(child.account_id),
                            "content_type": child.content_type,
                            "summary": child.summary,
                            "parent_segment_id": str(child.parent_segment_id),
                            "source": "hierarchy",
                            "score": 0,
                        },
                    ))

        return result[:k]

    async def _recall(
            self,
            dataset_ids: list[UUID],
            query: str,
            retrieval_strategy: str,
            k: int,
            score: float,
    ) -> list[LCDocument]:
        """执行多路召回并融合（同步检索器经 run_in_threadpool 桥接）。

        FullTextRetriever 为纯同步（self.db.session.execute），需要同步 Session 而非
        AsyncSession。使用 package.database.get_sync_session_factory() 创建临时同步会话，
        用完即关。
        """
        from internal.core.retrievers import (
            BM25Retriever,
            FullTextRetriever,
            SemanticRetriever,
        )
        from internal.core.retrievers.rrf import rrf_fusion
        from package.database import get_sync_session_factory

        semantic_retriever = SemanticRetriever(
            dataset_ids=dataset_ids,
            vector_store=self.vector_database_service.vector_store,
            search_kwargs={
                "k": k,
                "score_threshold": score,
            }
        )
        bm25_retriever = BM25Retriever(
            dataset_ids=dataset_ids,
            weaviate_client=get_weaviate_client(),
            search_kwargs={"k": k},
        )

        # FullTextRetriever 用同步 Session（run_in_threadpool 内安全使用）
        sync_factory = get_sync_session_factory()
        sync_session = sync_factory()
        try:
            full_text_retriever = FullTextRetriever(
                db=sync_session,
                dataset_ids=dataset_ids,
                ltp_service=self.ltp_service,
                search_kwargs={"k": k},
            )

            if retrieval_strategy == RetrievalStrategy.SEMANTIC:
                return (await run_in_threadpool(semantic_retriever.invoke, query))[:k]

            if retrieval_strategy == RetrievalStrategy.FULL_TEXT:
                bm25_results = await run_in_threadpool(bm25_retriever.invoke, query)
                ft_results = await run_in_threadpool(full_text_retriever.invoke, query)
                ranked = rrf_fusion([bm25_results, ft_results])
                return self._ranked_to_documents(ranked)

            # hybrid：三路召回 + RRF 融合
            sem_results = await run_in_threadpool(semantic_retriever.invoke, query)
            bm25_results = await run_in_threadpool(bm25_retriever.invoke, query)
            ft_results = await run_in_threadpool(full_text_retriever.invoke, query)
            ranked = rrf_fusion([sem_results, bm25_results, ft_results])
            return self._ranked_to_documents(ranked)
        finally:
            sync_session.close()

    @staticmethod
    def _ranked_to_documents(ranked: list[tuple[LCDocument, float]]) -> list[LCDocument]:
        """把 RRF 融合结果 [(doc, rrf_score)] 转成文档列表，并写入融合得分"""
        documents = []
        for doc, rrf_score in ranked:
            doc.metadata["rrf_score"] = rrf_score
            documents.append(doc)
        return documents

    async def create_langchain_tool_from_search(
            self,
            dataset_ids: list[UUID],
            account_id: Account,
            retrieval_strategy: str = RetrievalStrategy.SEMANTIC,
            k: int = 4,
            score: float = 0,
            retrieval_score: str = RetrievalSource.HIT_TESTING,
            rerank_enable: bool = False,
            rerank_top_n: int = 20,
            agentic_enable: bool = False,
            max_rounds: int = 2,
            **kwargs,
    ) -> BaseTool:
        """根据传递的参数构建一个LangChain知识库搜索工具

        兼容来自 retrieval_config 的扩展字段（rerank/query_rewrite/agentic 字典），
        自动解析为布尔开关。
        """
        # 1、解析扩展配置：rerank 字典
        if "rerank" in kwargs:
            rerank_config = kwargs["rerank"]
            if isinstance(rerank_config, dict):
                rerank_enable = rerank_config.get("enable", rerank_enable)
                rerank_top_n = rerank_config.get("top_n", rerank_top_n)

        # 2、解析扩展配置：query_rewrite 字典
        query_rewrite_enable = False
        if "query_rewrite" in kwargs:
            query_rewrite_config = kwargs["query_rewrite"]
            if isinstance(query_rewrite_config, dict):
                query_rewrite_enable = query_rewrite_config.get("enable", False)

        # 3、解析扩展配置：agentic 字典
        if "agentic" in kwargs:
            agentic_config = kwargs["agentic"]
            if isinstance(agentic_config, dict):
                agentic_enable = agentic_config.get("enable", agentic_enable)
                max_rounds = int(agentic_config.get("max_rounds", max_rounds) or max_rounds)

        class DatasetRetrievalInput(BaseModel):
            """知识库检索工具输入结构"""
            query: str = Field(description="知识库搜索query语句，类型为字符串")

        # Agentic 重检轨迹容器
        trace_holder: list = []

        @tool(DATASET_RETRIEVAL_TOOL_NAME, args_schema=DatasetRetrievalInput)
        def dataset_retrieval(query: str) -> str:
            """如果需要搜索扩展的知识库内容，当你觉得用户的提问超过你的知识范围时，可以尝试调用该工具，输入为搜索query语句，返回数据为检索内容字符串"""
            import asyncio

            # 工具可能在独立 loop（线程桥接）或调用方 loop 内执行，但创建时捕获的
            # 请求 session 绑定主 loop——复用会报 "Future attached to a different loop"。
            # 改为在 _do_search 实际执行的 loop 内自建 engine+session（创建与使用同 loop），
            # 用后 dispose；对单次检索调用成本可忽略。
            async def _do_search():
                from package.database import build_engine, build_sessionmaker
                from internal.container import create_retrieval_service
                import internal.extensions.redis as redis_mod

                engine = build_engine()
                try:
                    session_factory = build_sessionmaker(engine)
                    async with session_factory() as session:
                        local_svc = create_retrieval_service(
                            session=session, redis_client=redis_mod.sync_redis_client
                        )
                        if agentic_enable:
                            return await local_svc.search_agentic(
                                dataset_ids=dataset_ids,
                                query=query,
                                retrieval_strategy=retrieval_strategy,
                                k=k,
                                score=score,
                                account_id=account_id,
                                max_rounds=max_rounds,
                                rerank_enable=rerank_enable,
                                rerank_top_n=rerank_top_n,
                                query_rewrite_enable=query_rewrite_enable,
                                trace=trace_holder,
                            )
                        return await local_svc.search_in_datasets(
                            dataset_ids=dataset_ids,
                            query=query,
                            retrieval_strategy=retrieval_strategy,
                            k=k,
                            score=score,
                            retrieval_score=retrieval_score,
                            account_id=account_id,
                            rerank_enable=rerank_enable,
                            rerank_top_n=rerank_top_n,
                            query_rewrite_enable=query_rewrite_enable,
                        )
                finally:
                    await engine.dispose()

            # 如果已在事件循环内（agent worker），直接用同步桥接
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # 已在运行的事件循环中：创建新线程运行 asyncio.run
                import threading

                # TODO: remove bridge, make tool async-native (langchain 支持 async @tool)
                result_box = []
                error_box = []

                def _run_in_new_loop():
                    try:
                        result_box.append(asyncio.run(_do_search()))
                    except Exception as e:
                        error_box.append(e)

                t = threading.Thread(target=_run_in_new_loop)
                t.start()
                t.join()
                if error_box:
                    raise error_box[0]
                documents = result_box[0]
            else:
                documents = asyncio.run(_do_search())

            if len(documents) == 0:
                return "知识库内没有检索到对应内容"
            max_docs = 6
            max_chars_per_doc = 500
            max_total_chars = 3500
            texts = []
            total = 0
            for doc in documents[:max_docs]:
                piece = (doc.page_content or "").strip()
                if not piece:
                    continue
                if len(piece) > max_chars_per_doc:
                    piece = piece[:max_chars_per_doc] + "…"
                texts.append(piece)
                total += len(piece)
                if total >= max_total_chars:
                    break
            return "\n\n".join(texts) or "知识库内没有检索到对应内容"

        object.__setattr__(dataset_retrieval, "agentic_trace", trace_holder)
        return dataset_retrieval
