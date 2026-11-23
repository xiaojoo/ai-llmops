#!/usr/bin/env python
"""
@Time    : 2026/3/22 18:28
@Author  : sunxiaojie
@File    : chroma_file_service.py
"""
import os
from datetime import datetime
from pathlib import Path
from typing import BinaryIO



class ChromaFileService:
    """文档文件管理服务"""

    docs_dir: str

    def __init__(self):
        # 与 ChromaService 保持一致：项目根目录/storage/vector_store
        base_dir = Path(__file__).resolve().parent.parent
        # 向上找到项目根目录（假设本文件在 internal/ 下某层）
        # 兼容不同层级：找到包含 storage 目录的根路径
        path = os.path.dirname(base_dir)
        for _ in range(6):
            candidate = os.path.join(path, "storage", "vector_store")
            if os.path.exists(os.path.dirname(candidate)):
                self.docs_dir = candidate
                break
            path = os.path.dirname(path)
        else:
            # fallback：使用工作目录
            self.docs_dir = os.path.join(os.getcwd(), "storage", "vector_store")

        os.makedirs(self.docs_dir, exist_ok=True)

    def list_files(self) -> list[dict]:
        """获取文档目录下所有文件列表"""
        result = []
        for filename in os.listdir(self.docs_dir):
            # 跳过隐藏文件和子目录
            if filename.startswith('.'):
                continue
            file_path = os.path.join(self.docs_dir, filename)
            if not os.path.isfile(file_path):
                continue
            stat = os.stat(file_path)
            result.append({
                "name": filename,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "path": filename,  # 用文件名作为 path，前端删除/下载时传回
            })
        # 按修改时间倒序
        result.sort(key=lambda x: x["modified"], reverse=True)
        return result

    def upload_file(
        self,
        file: BinaryIO,
        filename: str,
        content_type: str | None = None,
    ) -> dict:
        """上传文件到文档目录，并立即同步向量库（分段入库）"""
        if not filename:
            raise ValueError("文件名不能为空")

        # 安全处理文件名，防路径穿越
        filename = os.path.basename(filename)
        save_path = os.path.join(self.docs_dir, filename)
        with open(save_path, "wb") as f:
            f.write(file.read())

        # 上传即同步：分段向量化，立即可检索
        try:
            self._sync_now()
        except Exception as e:
            print(f"[ChromaFileService] 上传后同步向量失败: {e}")

        stat = os.stat(save_path)
        return {
            "name": filename,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "path": filename,
        }

    def _sync_now(self):
        """延迟获取 ChromaService 并同步（避免包间循环依赖；ChromaService 无 session 依赖，直接构造）"""
        from internal.service.chroma_service import ChromaService

        ChromaService(embeddings_service=self._get_embeddings_service()).sync_local_documents()

    @staticmethod
    def _get_embeddings_service():
        """延迟获取 EmbeddingsService（避免循环导入）"""
        from internal.service.embeddings_service import EmbeddingsService
        return EmbeddingsService(redis=None)

    def delete_file(self, filename: str) -> None:
        """删除指定文件，并同步清理向量库中的对应记录"""
        # 安全处理，防止路径穿越攻击
        filename = os.path.basename(filename)
        file_path = os.path.join(self.docs_dir, filename)

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件 {filename} 不存在")
        if not os.path.isfile(file_path):
            raise ValueError(f"{filename} 不是文件")

        os.remove(file_path)

        # 删除后同步清理向量（source=filename 的记录）
        try:
            from internal.service.chroma_service import ChromaService

            chroma = ChromaService(embeddings_service=self._get_embeddings_service())
            chroma._collection.delete(where={"source": filename})
        except Exception as e:
            print(f"[ChromaFileService] 删除后清理向量失败: {e}")

    def get_file_path(self, filename: str) -> str:
        """获取文件绝对路径（用于下载）"""
        filename = os.path.basename(filename)
        file_path = os.path.join(self.docs_dir, filename)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件 {filename} 不存在")
        return file_path
