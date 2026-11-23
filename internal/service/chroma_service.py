#!/usr/bin/env python
"""
@Time    : 2026/2/12 20:33
@Author  : sunxiaojie
@File    : chroma_service.py
"""
import os

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from internal.core.agent.entities.agent_entity import DATASET_RETRIEVAL_TOOL_NAME
from internal.lib.helper import combine_documents
from internal.service import EmbeddingsService



class ChromaService:
    """Chroma向量数据库服务"""

    chroma: Chroma
    embeddings_service: EmbeddingsService
    docs_dir: str

    def __init__(self, embeddings_service: EmbeddingsService, docs_dir: str | None = None):
        """构造函数，完成Chroma向量数据库的初始化"""

        # 1、赋值 embeddings_service
        self.embeddings_service = embeddings_service

        # 2、计算路径
        current_file_path = os.path.abspath(__file__)
        internal_path = os.path.dirname(os.path.dirname(current_file_path))
        project_root_path = os.path.dirname(internal_path)
        base_path = project_root_path

        # 向量数据库持久化路径
        chroma_vector_store_path = os.path.join(base_path, "internal", "core", "vector_store")

        # 文档目录
        self.docs_dir = docs_dir or os.path.join(base_path, "storage", "vector_store")

        if not os.path.exists(self.docs_dir):
            os.makedirs(self.docs_dir, exist_ok=True)

        # 3、初始化Chroma
        self.chroma = Chroma(
            collection_name="my_knowledge_base",
            persist_directory=chroma_vector_store_path,
            embedding_function=self.embeddings_service.embeddings,
        )

    def clear_local_documents(self):
        """清空向量数据库中的所有数据"""
        try:
            # 1、获取当前所有的ID
            all_ids = self.chroma.get()['ids']

            if not all_ids:
                return

            # 2、调用delete删除数据库
            self.chroma.delete(ids=all_ids)

        except Exception as e:
            print(f"[ChromaService] 清除数据时发生错误: {e}")

    def sync_local_documents(self):
        """同步本地文档到向量库（分段入库 + 覆盖更新模式）。

        每个文件用 FileExtractor 解析（支持 txt/md/pdf/docx/csv/xlsx 等），
        再按 Recursive splitter 分段，每段一条向量（metadata: source=文件名 + chunk_index）。
        同一文件旧向量按 source 覆盖删除后重新写入。
        """
        if not os.path.exists(self.docs_dir):
            return

        from langchain_text_splitters import RecursiveCharacterTextSplitter

        from internal.core.file_extractor import FileExtractor

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
            length_function=len,
        )

        new_documents = []
        target_ids = []

        for filename in sorted(os.listdir(self.docs_dir)):
            file_path = os.path.join(self.docs_dir, filename)

            # 只处理文件，跳过隐藏/系统文件
            if not os.path.isfile(file_path) or filename.startswith('.'):
                continue

            try:
                # 1、用 FileExtractor 解析（支持 txt/md/pdf/docx/csv/xlsx 等）
                docs = FileExtractor.load_from_file(file_path, ocr_provider=None)
                if not docs:
                    continue
                if isinstance(docs, str):
                    docs = [Document(page_content=docs)]

                # 2、逐文档分段，每段一条向量
                for doc in docs:
                    content = (doc.page_content or "").strip()
                    if not content:
                        continue
                    chunks = splitter.split_text(content)
                    for idx, chunk in enumerate(chunks):
                        if not chunk.strip():
                            continue
                        metadata = {"source": filename, "chunk_index": idx}
                        # 保留结构类型（表格/图片等），便于溯源
                        if doc.metadata.get("content_type"):
                            metadata["content_type"] = doc.metadata["content_type"]
                        new_documents.append(Document(page_content=chunk, metadata=metadata))
                        target_ids.append(f"{filename}::chunk_{idx}")

            except Exception:
                continue

        if new_documents:
            # 覆盖更新：删除已存在的同文件旧向量（分段格式 source=filename）
            try:
                sources = sorted({doc.metadata.get("source", "") for doc in new_documents})
                if sources:
                    self._collection.delete(where={"source": {"$in": sources}})
            except Exception:
                pass

            # 清理孤儿向量：文件已删除但向量仍在（source 不在当前文件列表）
            try:
                existing = self._collection.get(include=["metadatas"])
                orphan_ids = [
                    doc_id
                    for doc_id, meta in zip(existing["ids"], existing["metadatas"])
                    if (meta or {}).get("source", "") not in sources
                ]
                if orphan_ids:
                    self._collection.delete(ids=orphan_ids)
            except Exception:
                pass

            # 分批写入（避免一次过大）
            for i in range(0, len(new_documents), 100):
                self.chroma.add_documents(
                    documents=new_documents[i:i + 100],
                    ids=target_ids[i:i + 100],
                )

    @property
    def _collection(self):
        """底层 chromadb collection（支持 where 删除）"""
        return self.chroma._collection

    def convert_chroma_to_tool(self) -> BaseTool:
        """将Chroma向量数据库检索器转换成LangChain工具"""
        # 1、转换成检索器
        retrieval = self.chroma.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 5, "fetch_k": 20},
        )

        # 2、构建检索链
        search_chain = retrieval | combine_documents

        class DatasetRetrievalInput(BaseModel):
            """知识库检索工具输入结构"""
            query: str = Field(description="知识库检索query语句，类型为字符串")

        @tool(DATASET_RETRIEVAL_TOOL_NAME, args_schema=DatasetRetrievalInput)
        def dataset_retrieval(query: str) -> str:
            """当用户问题超出模型知识范围时调用该工具"""
            return search_chain.invoke(query)

        return dataset_retrieval
