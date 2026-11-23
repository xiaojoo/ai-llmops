# RAG 生产级全量重构设计

日期：2026-05-20
状态：已确认
范围：`internal/service/retrieval_service.py`、`internal/core/retrievers/*`、`internal/service/embeddings_service.py`、`internal/service/indexing_service.py`、`internal/service/process_rule_service.py`、`internal/core/workflow/nodes/dataset_retrieval/dataset_retrieval_entity.py`、`internal/service/app_service.py`（校验）、`config/config.py`、`.env`、`scripts/eval_rag.py`

## 目标

把当前 demo 级 RAG（假全文检索、无 rerank、固定加权融合、硬编码 embedding、非幂等索引）升级为生产级：

1. Embedding 抽象：本地 bge-m3 与 DashScope API 可配
2. 多路召回：语义向量 + Weaviate BM25 + LTP 关键词，RRF 融合
3. Rerank：本地 bge-reranker 或 API rerank，可配
4. 结构感知切分 + 可选父子块
5. 幂等索引：hash 去重、增量更新、单事务一致性
6. 可选查询改写（默认关）
7. 检索质量评估脚本（hit_rate / MRR）

## 架构

```
摄取：UploadFile → FileExtractor → 结构感知切分(标题/父子块) → Segment(DB)
      → EmbeddingProvider(本地bge-m3|API) → Weaviate(向量+BM25)
      → KeywordTable(LTP)

检索：query → QueryRewrite(可选) → 多路召回 → RRF融合 → Rerank → top-k
      ├ Semantic(Weaviate 向量)
      ├ BM25(Weaviate 内置)
      └ LTP 关键词(词频表)
```

## 组件设计

### 1. EmbeddingProvider（新增 `internal/core/embeddings/embedding_provider.py`）

```python
class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    @abstractmethod
    def embed_query(self, text: str) -> list[float]: ...
```

- `LocalEmbeddingProvider`：HuggingFaceEmbeddings(bge-m3)，离线推理
- `ApiEmbeddingProvider`：DashScope text-embedding-v3，走 dashscope SDK
- 配置：`EMBEDDING_PROVIDER=local|api`、`EMBEDDING_MODEL`、`EMBEDDING_API_KEY`、`EMBEDDING_API_BASE`
- `EmbeddingsService` 改为按配置实例化 provider，保留 Redis 向量缓存（CacheBackedEmbeddings 包装），对外接口不变

### 2. 检索器

- `SemanticRetriever`：修正 `search_kwargs.pop("k")` 改共享 dict 的 bug（改 get），保留 dataset/文档启用过滤
- `BM25Retriever`（新增）：直接调 Weaviate collection `query.bm25`，filters 同向量检索，返回带 score 的文档
- `FullTextRetriever`：保留 LTP 词频表，作为第三路
- `rrf.py`（新增）：`rrf_fusion(results: list[list[Document]], k=60) -> list[(doc, score)]`
- `rerank.py`（新增）：`Reranker` 抽象 + `LocalReranker`(bge-reranker-v2-m3) + `ApiReranker`(DashScope)，输入候选文档列表，输出重排后列表

### 3. RetrievalService 重写

- `search_in_datasets` 按 strategy 走多路召回 + RRF + 可选 rerank
- 签名向后兼容（新增参数带默认值：`rerank_enable=False, rerank_top_n=20, query_rewrite_enable=False`）
- 保留 DatasetQuery 记录 + hit_count 统计
- metadata 增加 `score`、`source` 字段

### 4. 切分升级（process_rule_service）

- 新增 `HeadingAwareTextSplitter`：按标题层级切分，chunk 携带 `headings` 元数据
- 可选父子块：`ParentChildSplitter`（父块=节，子块=节内小段），命中子块返回父块上下文
- 默认走现有规则，新特性由 process_rule 配置开关

### 5. 幂等索引（indexing_service）

- hash 去重：重建时对比已有 Segment.hash，未变的跳过（不重写 Weaviate）
- 变更的才 upsert（node_id 作 id，天然幂等）
- 修复 bug：`search_kwargs.pop`、`document_enabled` 布尔过滤、`position` 起点、空列表崩溃
- DB 与向量库一致性：先写向量库，成功后单事务更新 DB；失败标记错误

### 6. QueryRewrite（默认关）

- LLM 将口语 query 改写为检索友好形式，仅查询改写（不做 HyDE，YAGNI）

### 7. 配置兼容

- `retrieval_config` 扩展：`{retrieval_strategy, k, score, rerank: {enable, top_n}, query_rewrite: {enable}, parent_child: {enable}}`
- `app_service.py:1000` 校验放宽：允许新增可选键，旧结构兼容
- `RetrievalConfig`（dataset_retrieval_entity）扩展字段
- `config/config.py` + `.env` 增加 embedding/rerank 配置项

### 8. 评估脚本 `scripts/eval_rag.py`

- 输入：测试集（query + 期望 doc/segment id 列表）
- 输出：三路召回 + 融合后的 hit_rate / MRR 对比

## 不做（YAGNI）

- HyDE（收益不确定）
- 监控大盘（用现有 DatasetQuery 表 + 评估脚本代替）
- 增量同步（文档级 hash 去重已覆盖主要场景）

## 验证

- 语法检查 + 现有测试通过
- `scripts/eval_rag.py` 可运行（无测试集时输出空报告并提示）
