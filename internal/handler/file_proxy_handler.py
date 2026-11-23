#!/usr/bin/env python
"""文件代理 Handler：按 URL 代理流式返回文件（限白名单主机）。

背景：PPT 工具返回的对象存储地址是 http://<minio-host>:9000/...，
浏览器会提示 "loaded over an insecure connection"。通过本接口把文件地址
改为同源 /api/files/proxy?url=...，由后端代拉文件并以附件流式返回，
消除跨源 http 加载提示。

安全：仅允许代理 MINIO_PUBLIC_HOST / COS_DOMAIN 配置的主机，防止 SSRF。
存储桶本身为公开读，代理不增加新的暴露面。
"""
import mimetypes
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from internal.config.settings import get_settings
from internal.exception import ValidateException
from internal.service import CosService, MinioService


@dataclass
class FileProxyHandler:
    """文件代理处理器（公开只读端点，无需登录）"""

    def proxy(self, url: str = Query(..., description="需要代理访问的文件 URL")) -> FileResponse:
        """按 URL 下载并流式返回文件；URL 主机必须在白名单内。"""
        target = unquote(url)
        parsed = urlparse(target)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValidateException("无效的文件 URL")

        allowed = self._allowed_hosts()
        if parsed.netloc not in allowed:
            raise ValidateException(
                f"不允许代理的主机：{parsed.netloc}（允许：{', '.join(sorted(allowed)) or '未配置'}）"
            )

        # 下载到可写临时目录（沙箱下系统临时目录/0o700 目录不可写，用项目内目录）
        root = Path(get_settings().project_root) / "storage" / "tmp" / "fileproxy"
        root.mkdir(parents=True, exist_ok=True)
        work_dir = root / uuid.uuid4().hex
        os.mkdir(work_dir)  # 默认权限

        basename = Path(parsed.path).name or "file"
        local_path = work_dir / basename
        try:
            if parsed.netloc in self._minio_hosts():
                MinioService().download_file(target, str(local_path))
            else:
                CosService(
                    upload_file_service=None, minio_service=MinioService()
                ).download_file(parsed.path.lstrip("/"), str(local_path))
        except Exception as e:  # 下载失败：清理并抛业务异常
            shutil.rmtree(work_dir, ignore_errors=True)
            raise ValidateException(f"文件下载失败：{e!s}") from e

        media_type = mimetypes.guess_type(basename)[0] or "application/octet-stream"
        return FileResponse(
            str(local_path),
            media_type=media_type,
            filename=basename,
            background=BackgroundTask(_cleanup, work_dir),
        )

    @staticmethod
    def _allowed_hosts() -> set[str]:
        """允许代理的主机集合（MINIO_PUBLIC_HOST / COS_DOMAIN）。"""
        hosts: set[str] = set()
        minio_host = os.getenv("MINIO_PUBLIC_HOST", "").strip()
        if minio_host:
            hosts.add(minio_host.lower())
        cos_domain = os.getenv("COS_DOMAIN", "").strip()
        if cos_domain:
            raw = cos_domain if "://" in cos_domain else f"https://{cos_domain}"
            hosts.add(urlparse(raw).netloc.lower())
        return hosts

    @staticmethod
    def _minio_hosts() -> set[str]:
        """MinIO 公开主机集合。"""
        minio_host = os.getenv("MINIO_PUBLIC_HOST", "").strip()
        return {minio_host.lower()} if minio_host else set()


def _cleanup(work_dir: Path) -> None:
    """FileResponse 发送完成后清理临时目录。"""
    shutil.rmtree(work_dir, ignore_errors=True)
