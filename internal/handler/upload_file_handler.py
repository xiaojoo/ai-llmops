#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/30 14:34
@author : sunxiaojie
@File   : upload_file_handler.py
"""
from dataclasses import dataclass

from fastapi import File, UploadFile

from internal.server.deps import CurrentUser
from internal.schema.update_file_schema import UploadFileResp
from internal.service import CosService, UploadFileService
from package.response import success_json, success_message_json


@dataclass
class UploadFileHandler:
    """上传文件处理器"""
    cos_service: CosService
    upload_file_service: UploadFileService

    async def upload_file(self, user: CurrentUser, file: UploadFile = File(...)) -> None:
        """上传文件/文档"""
        upload_file = await self.cos_service.upload_file(file.file, file.filename, file.content_type, account=user)
        resp = UploadFileResp.model_validate(upload_file)
        return success_json(resp.model_dump(mode="json"))

    async def upload_image(self, user: CurrentUser, file: UploadFile = File(...)) -> None:
        """上传图片"""
        upload_file = await self.cos_service.upload_file(file.file, file.filename, file.content_type, only_image=True, account=user)
        image_url = self.cos_service.get_fresh_file_url(upload_file.key)
        return success_json({'image_url': image_url})

    async def pending_upload_files(self, user: CurrentUser) -> None:
        """查询当前账号已上传但尚未创建文档（孤儿）的文件列表"""
        upload_files = await self.upload_file_service.get_pending_upload_files(user.id)
        resp = [
            UploadFileResp.model_validate(f).model_dump(mode="json")
            for f in upload_files
        ]
        return success_json(resp)

    async def delete_upload_file(self, user: CurrentUser, upload_file_id: str) -> None:
        """删除已上传但未创建文档的文件（同步删除 OSS 对象）"""
        upload_file = await self.upload_file_service.delete_upload_file(upload_file_id, user.id)
        self.cos_service.delete_file(upload_file.key)
        return success_message_json("删除成功")

    async def get_file_url(self, user: CurrentUser, upload_file_id: str) -> None:
        """按需获取文件访问 URL"""
        upload_file = await self.upload_file_service.get_owned_upload_file(upload_file_id, user.id)
        return success_json({"url": self.cos_service.get_fresh_file_url(upload_file.key)})
