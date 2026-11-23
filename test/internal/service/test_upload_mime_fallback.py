#!/usr/bin/env python
"""FileStorage → (BinaryIO, filename, content_type) 后 MIME 兜底。

背景：旧 werkzeug `FileStorage(stream=..., filename=...)` 会按文件名猜 mimetype（绝不 None）；
新签名下内部调用点（app_service icon.png / cos_service 嵌入图 / skill_service 技能归档 zip）
省略 content_type。服务级兜底 `mimetypes.guess_type(filename)[0]` 保证：
- COS 记录不再落 NULL mime_type；
- miniio 不再落 "application/octet-stream"（mall 白名单拒 octet-stream）。
显式 content_type 仍优先。
"""
import io
from unittest.mock import AsyncMock, MagicMock

import pytest

from internal.service.cos_service import CosService
from internal.service.minio_service import MinioService

# ---------- MinioService._normalize_mimetype（静态兜底） ----------


def test_miniio_normalize_guesses_mime_from_filename_when_none():
    # icon.png + content_type=None → image/png（不落 octet-stream）
    assert MinioService._normalize_mimetype("icon.png", None) == "image/png"


def test_miniio_normalize_explicit_content_type_wins():
    assert MinioService._normalize_mimetype("icon.png", "image/webp") == "image/webp"


def test_miniio_normalize_mapping_beats_guess():
    assert MinioService._normalize_mimetype("x.md", None) == "text/markdown"


def test_miniio_normalize_zip_archive_guessed():
    # skill_service._archive_bytes 归档技能 zip：省略 content_type 时按文件名猜出 zip 类 MIME
    # （Windows mimetypes 返回 application/x-zip-compressed，POSIX 返回 application/zip——
    # 与旧 werkzeug FileStorage.mimetype（同为 guess_type）平台行为一致）
    assert MinioService._normalize_mimetype("my-skill.zip", None) in (
        "application/zip",
        "application/x-zip-compressed",
    )


def test_miniio_normalize_unknown_ext_falls_back_to_octet_stream():
    assert MinioService._normalize_mimetype("archive.unknownext", None) == "application/octet-stream"


# ---------- MinioService.upload_file 全路径（mock requests.post） ----------


def test_miniio_upload_guesses_mime_for_icon_png(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 0, "message": "ok", "data": "http://minio/icon.png"}

    def fake_post(url, files=None, params=None, timeout=None):
        captured["files"] = files
        return _Resp()

    monkeypatch.setattr("requests.post", fake_post)
    svc = MinioService()

    url = svc.upload_file(io.BytesIO(b"png-bytes"), "icon.png")

    assert url == "http://minio/icon.png"
    name, stream, mime = captured["files"]["file"]
    assert name == "icon.png"
    assert mime == "image/png", "content_type=None 时应按文件名猜出 image/png，而非 octet-stream"


# ---------- CosService（COS 后端） ----------


def _cos_service():
    svc = CosService(upload_file_service=MagicMock(), minio_service=MagicMock())
    # create_upload_file 已 async（写库）——mock 需 AsyncMock 才能被 await
    svc.upload_file_service.create_upload_file = AsyncMock(return_value=MagicMock())
    return svc


@pytest.mark.asyncio
async def test_cos_upload_guesses_mime_for_icon_png(monkeypatch):
    svc = _cos_service()
    monkeypatch.setattr(CosService, "_storage_provider", classmethod(lambda cls: "cos"))
    monkeypatch.setattr(CosService, "get_client", classmethod(lambda cls: MagicMock()))
    monkeypatch.setattr(CosService, "get_bucket", classmethod(lambda cls: "bucket"))
    account = MagicMock()

    await svc.upload_file(io.BytesIO(b"png-bytes"), "icon.png", account=account)

    kwargs = svc.upload_file_service.create_upload_file.call_args.kwargs
    assert kwargs["mime_type"] == "image/png", "content_type=None 时 COS 记录不应落 NULL mime_type"


@pytest.mark.asyncio
async def test_cos_upload_explicit_content_type_wins(monkeypatch):
    svc = _cos_service()
    monkeypatch.setattr(CosService, "_storage_provider", classmethod(lambda cls: "cos"))
    monkeypatch.setattr(CosService, "get_client", classmethod(lambda cls: MagicMock()))
    monkeypatch.setattr(CosService, "get_bucket", classmethod(lambda cls: "bucket"))
    account = MagicMock()

    await svc.upload_file(io.BytesIO(b"png-bytes"), "icon.png", "image/webp", account=account)

    kwargs = svc.upload_file_service.create_upload_file.call_args.kwargs
    assert kwargs["mime_type"] == "image/webp", "显式 content_type 应优先于文件名猜测"


# ---------- CosService（MinIO 后端） ----------


@pytest.mark.asyncio
async def test_cos_miniio_backend_guesses_mime_for_icon_png(monkeypatch):
    svc = _cos_service()
    monkeypatch.setattr(CosService, "_storage_provider", classmethod(lambda cls: "miniio"))
    account = MagicMock()

    await svc.upload_file(io.BytesIO(b"png-bytes"), "icon.png", account=account)

    # 记录落库的 mime_type 由 cos_service 兜底（不落 NULL）
    kwargs = svc.upload_file_service.create_upload_file.call_args.kwargs
    assert kwargs["mime_type"] == "image/png"
    # 透传给 miniio 的是原始 content_type（None），由 miniio._normalize_mimetype 兜底
    svc.minio_service.upload_file.assert_called_once()
    _file, fname, ctype, folder_arg = svc.minio_service.upload_file.call_args.args
    assert fname == "icon.png"
    assert ctype is None
    assert folder_arg == "document/dataset_documents"
