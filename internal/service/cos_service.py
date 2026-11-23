#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
@Time   : 2025/11/30 15:37
@Author : sunxiaojie
@File   : cos_service.py

文件存储服务：支持腾讯云 COS 与 MinIO（调用 mall-third-party 接口）两种后端，
通过环境变量 STORAGE_PROVIDER 切换（cos | miniio，默认 cos）。
"""
import hashlib
import logging
import mimetypes
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO

from qcloud_cos import CosConfig, CosS3Client
from starlette.concurrency import run_in_threadpool

from internal.entity.upload_file_entity import (
    ALLOWED_DOCUMENT_EXTENSION,
    ALLOWED_IMAGE_EXTENSIONS,
)
from internal.exception import FailedException
from internal.model import Account

from .minio_service import MinioService
from .upload_file_service import UploadFileService

logger = logging.getLogger(__name__)



@dataclass
class CosService:
    """文件存储服务（COS / MinIO 可切换）"""
    upload_file_service: UploadFileService
    minio_service: MinioService

    async def upload_file(
        self,
        file: BinaryIO,
        filename: str,
        content_type: str | None = None,
        only_image: bool = False,
        account: Account = None,
    ):
        """上传文件到存储后端，上传后返回文件信息"""
        # 1、提取文件扩展名并检测是否可以上传
        extension = filename.rsplit(".", 1)[1] if "." in filename else ""
        if extension.lower() not in (ALLOWED_IMAGE_EXTENSIONS + ALLOWED_DOCUMENT_EXTENSION):
            raise FailedException(f"该.{extension}扩展的文件不允许上传")
        elif only_image and extension not in ALLOWED_IMAGE_EXTENSIONS:
            raise FailedException(f"该.{extension}扩展的文件不支持上传，请上传正确图片")

        # 2、按配置选择存储后端
        if self._storage_provider() == "miniio":
            return await self._upload_to_minio(file, filename, extension, content_type, account, only_image=only_image)

        return await self._upload_to_cos(file, filename, extension, content_type, account)

    async def _upload_to_cos(
        self,
        file: BinaryIO,
        filename: str,
        extension: str,
        content_type: str | None,
        account: Account = None,
    ):
        """上传文件到腾讯云 COS"""
        # 1、获取客户端+存储桶名字
        client = self.get_client()
        bucket = self.get_bucket()

        # 2、生成一个随机的名字
        random_filename = str(uuid.uuid4()) + "." + extension
        now = datetime.now()
        upload_filename = f"{now.year}/{now.month:02d}/{now.day:02d}/{random_filename}"

        # 3、流式读取上传的数据并将其上传到cos中
        file_content = file.read()
        try:
            client.put_object(bucket, file_content, upload_filename)
        except Exception as e:
            raise FailedException(f"上传文件失败，请稍后重试{e}")

        # 4、创建upload_file记录
        return await self.upload_file_service.create_upload_file(
            account_id=account.id,
            name=filename,
            key=upload_filename,
            size=len(file_content),
            extension=extension,
            # content_type 省略时按文件名猜 MIME
            mime_type=content_type or mimetypes.guess_type(filename)[0],
            hash=hashlib.sha3_256(file_content).hexdigest(),
        )

    async def _upload_to_minio(
            self,
            file: BinaryIO,
            filename: str,
            extension: str,
            content_type: str | None,
            account: Account = None,
            only_image: bool = False,
    ):
        """上传文件到 MinIO（调用 mall 接口），key 为文件访问 URL。

        only_image=True（头像/图标等）不传 folder，mall 按类型自动归类到 image/；
        文档上传传 folder=dataset_documents，固定落在 document/dataset_documents/ 目录。
        """
        file_content = file.read()
        # 重置流指针，供 requests 重新读取
        file.seek(0)

        folder = None if only_image else "document/dataset_documents"
        # miniio 为同步 requests 网络 IO → run_in_threadpool 桥接，避免阻塞事件循环
        file_url = await run_in_threadpool(
            self.minio_service.upload_file, file, filename, content_type, folder
        )

        return await self.upload_file_service.create_upload_file(
            account_id=account.id,
            name=filename,
            key=file_url,  # MinIO 模式下 key 即完整 URL
            size=len(file_content),
            extension=extension,
            # content_type 省略时按文件名猜 MIME
            mime_type=content_type or mimetypes.guess_type(filename)[0],
            hash=hashlib.sha3_256(file_content).hexdigest(),
        )

    def upload_embedded_image(self, local_path: str) -> str:
        """上传文档内嵌图片（如 xlsx 中的图片）到存储后端，返回可访问 URL。

        与 upload_file 不同：不创建 upload_file 记录（内嵌图片非独立上传文件，
        避免孤儿文件检测误判），仅上传拿 URL 供 image_url 元数据使用。
        """
        filename = os.path.basename(local_path)
        try:
            if self._storage_provider() == "miniio":
                with open(local_path, "rb") as f:
                    # folder=None：mall 按图片类型自动归类到 image/ 目录；
                    # 返回的预签名 URL 会过期，剥掉签名参数存永久公开 URL（同 get_fresh_file_url）
                    url = self.minio_service.upload_file(f, filename, folder=None)
                    return self.get_fresh_file_url(url)
            # COS 后端：上传到日期目录，返回访问 URL
            client = self.get_client()
            bucket = self.get_bucket()
            now = datetime.now()
            upload_filename = f"images/{now.year}/{now.month:02d}/{now.day:02d}/{uuid.uuid4()}_{filename}"
            with open(local_path, "rb") as f:
                client.put_object(bucket, f.read(), upload_filename)
            return self.get_file_url(upload_filename)
        except Exception as e:
            logger.warning("内嵌图片上传失败: %s", e)
            return ""

    def download_file(self, key: str, target_file_path: str):
        """下载文件到本地（COS 用 key 路径，MinIO 用 URL）"""
        if self._storage_provider() == "miniio":
            self.minio_service.download_file(key, target_file_path)
            return
        client = self.get_client()
        bucket = self.get_bucket()
        client.download_file(bucket, key, target_file_path)

    def delete_file(self, key: str):
        """删除存储中的文件（COS 用 key 路径，MinIO 用 URL）"""
        if self._storage_provider() == "miniio":
            self.minio_service.delete_file(key)
            return
        client = self.get_client()
        bucket = self.get_bucket()
        client.delete_object(bucket, key)

    @classmethod
    def get_file_url(cls, key: str) -> str:
        """根据 key 获取文件访问 URL（MinIO 的 key 本身即 URL）"""
        if cls._storage_provider() == "miniio":
            return key
        cos_domain = os.getenv('COS_DOMAIN')
        if not cos_domain:
            bucket = os.getenv('COS_BUCKET')
            scheme = os.getenv('COS_SCHEME')
            region = os.getenv('COS_REGION')
            cos_domain = f'{scheme}://{bucket}.cos.{region}.myqcloud.com'
        return f'{cos_domain}/{key}'

    @classmethod
    def get_fresh_file_url(cls, key: str) -> str:
        """按需获取可长期访问的文件 URL（用于历史附件链接刷新）。

        - MinIO：存储桶为公开读（mall 建桶时已配置公开读策略），
          剥离旧预签名查询参数即为永久公开 URL，不依赖已过期的签名；
        - COS：返回静态域名 URL，本身无过期。
        """
        if cls._storage_provider() == "miniio":
            return key.split("?", 1)[0]
        return cls.get_file_url(key)

    @classmethod
    def _storage_provider(cls) -> str:
        """当前存储提供者：cos | miniio"""
        return os.getenv("STORAGE_PROVIDER", "cos").strip().lower()

    @classmethod
    def get_client(cls):
        """获取腾讯云cos对象存储客户端"""
        conf = CosConfig(
            Region=os.getenv('COS_REGION'),
            SecretId=os.getenv('COS_SECRET_ID'),
            SecretKey=os.getenv('COS_SECRET_KEY'),
            Token=None,
            Scheme=os.getenv('COS_SCHEME', 'https'),
        )
        return CosS3Client(conf)

    @classmethod
    def get_bucket(cls):
        """获取存储桶的名字"""
        return os.getenv('COS_BUCKET')
