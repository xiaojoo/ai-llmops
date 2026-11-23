#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2026/03/20 18:31
@author : sunxiaojie
@File   : skill_handler.py
"""
from dataclasses import dataclass

from fastapi import File, Form, UploadFile, Query

from internal.exception import ValidateException
from typing import Annotated
from internal.server.deps import CurrentUser
from internal.schema.upload_skill_schema import GetSkillListWithPageReq, SkillResp
from internal.service.skill_service import SkillService
from package.paginator import PageModel
from package.response import success_json, success_message_json


@dataclass
class SkillHandler:
    """Skill处理器"""
    skill_service: SkillService

    async def skill_upload(
        self,
        user: CurrentUser,
        file: UploadFile = File(...),
        icon: str = Form(""),
    ) -> None:
        """上传并创建技能，支持 .md 文件或 .zip 压缩包"""
        if not file.filename:
            raise ValidateException("请上传SKILL.md文件")

        filename = file.filename.lower()

        if filename.endswith(".zip"):
            file_bytes = await file.read()
            skills = await self.skill_service.upload_zip(user, file.filename, file_bytes, icon)
            return success_message_json(f"skill创建成功，共导入 {len(skills)} 个技能")

        elif filename.endswith(".md"):
            raw = await file.read()
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise ValidateException("文件编码错误，请上传UTF-8格式的Markdown文件")
            await self.skill_service.upload(user, content, icon)
        else:
            raise ValidateException("仅支持.md文件或.zip压缩包")

        return success_message_json("skill创建成功")

    async def get_skill_list_with_page(self, user: CurrentUser, req: Annotated[GetSkillListWithPageReq, Query()]) -> None:
        """获取技能分页列表（本人独占 + 分享）"""
        skills, paginator = await self.skill_service.get_skill_list_with_page(req, user)

        resp_list = []
        for s in skills:
            item = SkillResp.model_validate(s).model_dump(mode="json")
            item["is_owner"] = str(s.account_id) == str(user.id)
            resp_list.append(item)

        return success_json(PageModel(list=resp_list, paginator=paginator))

    async def get_skill(self, user: CurrentUser, skill_id: str) -> None:
        """获取技能详情（入口正文取自 DB content）"""
        skill = await self.skill_service.get_skill(skill_id, user)
        return success_json({
            "id": str(skill.id),
            "name": skill.name,
            "description": skill.description,
            "icon": skill.icon,
            "visibility": skill.visibility,
            "created_at": skill.created_at.isoformat(),
            "updated_at": skill.updated_at.isoformat(),
            "file_content": skill.content,
        })

    async def get_skill_detail(self, user: CurrentUser, skill_id: str) -> None:
        """获取技能详情及文件列表"""
        skill, files = await self.skill_service.get_skill_detail(skill_id, user)
        resp = SkillResp.model_validate(skill).model_dump(mode="json")
        resp["files"] = files
        return success_json(resp)

    async def toggle_skill_visibility(self, user: CurrentUser, skill_id: str) -> None:
        """切换技能可见性：独占 <-> 公共"""
        skill = await self.skill_service.toggle_visibility(skill_id, user)
        visibility = "公共" if skill.visibility == "public" else "独占"
        return success_message_json(f"已切换为{visibility}")

    async def delete_skill(self, user: CurrentUser, skill_id: str) -> None:
        """删除技能"""
        await self.skill_service.delete_skill(skill_id, user)
        return success_message_json("删除成功")

    async def download_skill(self, user: CurrentUser, skill_id: str) -> None:
        """下载技能文件压缩包"""
        return await self.skill_service.get_skill_zip(skill_id, user)
