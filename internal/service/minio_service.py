#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
@Time    : 2026/8/22
@Author  : sunxiaojie
@File    : minio_service.py

MinIO 存储服务：通过调用 mall-third-party 模块的上传接口实现文件存储，
替代腾讯云 COS。所有请求走 mall 的 HTTP 接口。

mall 接口：
- POST /file/upload        单文件上传（multipart file），返回 Result<String>，data 为文件 URL
- DELETE /file/delete      删除文件（fileUrl）
- GET  /file/health        健康检查
"""
import logging
import mimetypes
import os
from typing import BinaryIO

import requests

logger = logging.getLogger(__name__)



class MinioService:
    """MinIO 存储服务（调用 mall-third-party 接口）"""

    def __init__(self):
        self.base_url = os.getenv("MINIO_API_URL", "http://localhost:9001").rstrip("/")
        self.upload_url = f"{self.base_url}/file/upload"
        self.delete_url = f"{self.base_url}/file/delete"
        self.health_url = f"{self.base_url}/file/health"
        self.timeout = int(os.getenv("MINIO_TIMEOUT", "60"))

    def upload_file(
        self,
        file: BinaryIO,
        filename: str,
        content_type: str | None = None,
        folder: str | None = None,
    ) -> str:
        """上传文件到 MinIO，返回文件基础 URL（不含签名查询参数，作为存储 key）。

        folder：指定上传目录（如 dataset_documents / document/dataset_documents），
        不传时 mall 按文件类型自动归类（image/document/...）。
        存储桶为公开读策略（mall 建桶时自动设置公开读），预签名参数非必需且会过期
        （默认 7 天）——无论 mall 端 publicRead 开关如何，统一剥掉签名参数，
        key 即永久公开 URL，避免落库后过期失效。
        """
        try:
            data = {"file": (filename, file, self._normalize_mimetype(filename, content_type))}
            params = {"folder": folder} if folder else None
            resp = requests.post(
                self.upload_url,
                files=data,
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            # mall Result 结构：{code, message, data}
            if body.get("code") not in (0, 200, "0", "200", "success"):
                raise RuntimeError(f"MinIO 上传失败: {body.get('message', body)}")
            url = body.get("data")
            if not url:
                raise RuntimeError(f"MinIO 上传响应缺少文件 URL: {body}")
            # 剥掉预签名查询参数（?X-Amz-...），公开桶下签名非必需且会过期
            return url.split("?", 1)[0]
        except requests.RequestException as e:
            logger.exception("调用 mall MinIO 上传接口失败")
            raise RuntimeError(f"MinIO 上传失败: {e}")

    @staticmethod
    def _normalize_mimetype(filename: str, content_type: str | None) -> str:
        """按扩展名规范化 Content-Type，规避 mall 类型白名单拒绝（浏览器对 .md 等常发 octet-stream）"""
        ext = (filename or "").rsplit(".", 1)[-1].lower()
        mapping = {
            "txt": "text/plain",
            "md": "text/markdown",
            "markdown": "text/markdown",
            "csv": "text/csv",
            "pdf": "application/pdf",
            "doc": "application/msword",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xls": "application/vnd.ms-excel",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "ppt": "application/vnd.ms-powerpoint",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "html": "text/html",
            "htm": "text/html",
            "webm": "video/webm",
            "wav": "audio/wav",
        }
        if ext in mapping:
            return mapping[ext]
        # 显式 content_type 优先，否则按文件名猜 MIME，最后才退回 octet-stream 由 mall 白名单裁决
        return content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

    def download_file(self, file_url: str, target_file_path: str) -> None:
        """根据文件 URL 下载文件到本地路径"""
        try:
            resp = requests.get(file_url, timeout=self.timeout)
            resp.raise_for_status()
            with open(target_file_path, "wb") as f:
                f.write(resp.content)
        except requests.RequestException as e:
            logger.exception("MinIO 文件下载失败")
            raise RuntimeError(f"MinIO 文件下载失败: {e}")

    def delete_file(self, file_url: str) -> None:
        """根据文件 URL 删除 MinIO 中的文件"""
        try:
            resp = requests.delete(
                self.delete_url,
                params={"fileUrl": file_url},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") not in (0, 200, "0", "200", "success"):
                raise RuntimeError(f"MinIO 删除失败: {body.get('message', body)}")
        except requests.RequestException as e:
            logger.exception("调用 mall MinIO 删除接口失败")
            raise RuntimeError(f"MinIO 删除失败: {e}")

    def health_check(self) -> bool:
        """健康检查：mall 文件服务是否可用"""
        try:
            resp = requests.get(self.health_url, timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def get_file_url(self, file_url: str) -> str:
        """MinIO 模式下 key 即完整 URL，直接返回"""
        return file_url
