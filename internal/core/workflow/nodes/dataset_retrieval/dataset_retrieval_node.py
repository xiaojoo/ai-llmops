# -*- coding: utf-8 -*-
"""
@Time    : 2026/1/25 0:16
@Author  : sunxiaojie
@File    : dataset_retrieval_node.py
"""
import time
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from pydantic import PrivateAttr

from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.core.workflow.utils.helper import extract_variables_from_state
from internal.entity.dataset_entity import RetrievalSource
from internal.exception import FailedException

from .dataset_retrieval_entity import DatasetRetrievalNodeData


class DatasetRetrievalNode(BaseNode):
    """知识库检索节点"""

    node_data: DatasetRetrievalNodeData
    _account_id: UUID = PrivateAttr()

    def __init__(
            self,
            *args: Any,
            account_id: UUID,
            **kwargs: Any,
    ):
        """构造函数，完成知识库检索节点的初始化（account_id 来自工作流配置）"""
        super().__init__(*args, **kwargs)
        self._account_id = account_id

    def run(self, state: WorkflowState, config: RunnableConfig | None = None, **kwargs) -> WorkflowState:
        """知识库检索节点调用函数，执行响应的知识库检索后返回"""
        # 1、提取节点输入变量字典映射
        start_at = time.perf_counter()
        inputs_dict = extract_variables_from_state(self.node_data.inputs, state)
        query = str(inputs_dict.get("query", "")).strip()
        if not query:
            raise FailedException("知识库检索 query 不能为空")

        # 2、在 worker 独立事件循环内执行检索（T13⑲）：
        #    原实现先在 asyncio.run 里建 session 建工具，再经工具 invoke 桥接回新 loop 检索 →
        #    "Future attached to a different loop"（session 跨 loop）。改用 worker_run +
        #    engine_factory，session/引擎/查询全在同一 loop 内完成。
        #    子图调试（node_ids → 线性子图）时 langgraph 单任务 fast path 在主事件循环
        #    inline 执行节点 → worker_run 守卫会拒绝，故经 run_sync_bridge 兜底丢新线程。
        from package.database import build_engine, run_sync_bridge, worker_run

        rc = self.node_data.retrieval_config
        rerank_enable = rc.rerank.enable
        rerank_top_n = rc.rerank.top_n
        query_rewrite_enable = rc.query_rewrite.enable

        async def _search(session):
            from internal.container import create_retrieval_service
            import internal.extensions.redis as redis_mod

            service = create_retrieval_service(
                session=session, redis_client=redis_mod.sync_redis_client
            )
            return await service.search_in_datasets(
                dataset_ids=self.node_data.dataset_ids,
                query=query,
                retrieval_strategy=rc.retrieval_strategy,
                k=rc.k,
                score=rc.score,
                retrieval_score=RetrievalSource.HIT_TESTING,
                account_id=self._account_id,
                rerank_enable=rerank_enable,
                rerank_top_n=rerank_top_n,
                query_rewrite_enable=query_rewrite_enable,
            )

        documents = run_sync_bridge(lambda: worker_run(_search, engine_factory=build_engine))

        # 3、格式化输出（与检索工具内截断逻辑一致）
        if len(documents) == 0:
            combine_documents = "知识库内没有检索到对应内容"
        else:
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
            combine_documents = "\n\n".join(texts) or "知识库内没有检索到对应内容"

        # 4、提取并构建输出数据结构
        outputs = {}
        if self.node_data.outputs:
            outputs[self.node_data.outputs[0].name] = combine_documents
        else:
            outputs["combine_documents"] = combine_documents

        # 5、返回响应状态
        return {
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    status=NodeStatus.SUCCEEDED,
                    inputs=inputs_dict,
                    outputs=outputs,
                    latency=(time.perf_counter() - start_at),
                )
            ]
        }
