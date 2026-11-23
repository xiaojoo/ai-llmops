#!/usr/bin/env python
"""PPTX 上传公共函数（COS / MinIO 双后端）。

与 markdown_to_pptx 共用，避免两个工具重复维护上传逻辑。
内部惰性导入 internal.service，保持工具包模块导入轻量。

返回地址统一转为同源代理地址（/api/files/proxy?url=...），
由后端代拉对象存储文件，避免浏览器对 http://<minio-host> 文件的
"insecure connection" 提示。
"""
import os
from urllib.parse import quote

_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _to_proxy_url(file_url: str) -> str:
    """把对象存储原始 URL 转为同源代理 URL（走后端 /files/proxy 转发）。"""
    base = os.getenv("LLMOPS_WEB_BASE", "http://localhost:5173").rstrip("/")
    return f"{base}/api/files/proxy?url={quote(file_url, safe='')}"


def upload_pptx(filepath: str) -> str:
    """上传 .pptx 文件到存储后端，返回同源可访问 URL。"""
    # 惰性导入：避免在工具包模块加载时拉起服务层（模型/配置等）
    from internal.service import CosService, MinioService

    filename = os.path.basename(filepath)
    minio_service = MinioService()
    cos_service = CosService(upload_file_service=None, minio_service=minio_service)

    if cos_service._storage_provider() == "miniio":
        with open(filepath, "rb") as f:
            file_url = minio_service.upload_file(f, filename, _PPTX_MIME)
            return _to_proxy_url(file_url)

    client = cos_service.get_client()
    bucket = cos_service.get_bucket()
    key = f"builtin-tools/markdown-to-pptx/{filename}"
    client.upload_file(
        Bucket=bucket,
        Key=key,
        LocalFilePath=filepath,
        EnableMD5=False,
        progress_callback=None,
    )
    return _to_proxy_url(cos_service.get_file_url(key))
