#!/usr/bin/env python
"""
@Time    : 2026/3/22 18:20
@author  : sunxiaojie
@File    : chroma_file_handler.py
"""
from dataclasses import dataclass

from fastapi import File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from internal.service.chroma_file_service import ChromaFileService
from internal.exception import ValidateException
from package.response import success_json, success_message_json


class ChromaFileDeleteReq(BaseModel):
    """Chroma 文件删除请求"""
    path: str = ""


@dataclass
class ChromaFileHandler:
    """文档文件管理处理器"""
    chroma_file_service: ChromaFileService

    async def list(self) -> None:
        """获取文档列表"""
        files = self.chroma_file_service.list_files()
        return success_json({"files": files})

    async def upload(self, file: UploadFile = File(...)) -> None:
        """上传文件"""
        if not file.filename:
            raise ValidateException("请选择要上传的文件")
        file_info = self.chroma_file_service.upload_file(file.file)
        return success_json({"file": file_info})

    async def download(self, path: str = "") -> None:
        """下载文件"""
        if not path or not path.strip():
            raise ValidateException("缺少文件路径参数")
        file_path = self.chroma_file_service.get_file_path(path.strip())
        with open(file_path, "rb") as f:
            content = f.read()
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{path}"'},
        )

    async def delete(self, req: ChromaFileDeleteReq) -> None:
        """删除文件

        契约对齐：原 Flask 实现读 JSON body（request.get_json），
        此处为 body 模型（默认），与其余 POST req 模型一致。
        """
        filename = (req.path or "").strip()
        if not filename:
            raise ValidateException("缺少文件路径参数")
        self.chroma_file_service.delete_file(filename)
        return success_message_json("删除成功")
