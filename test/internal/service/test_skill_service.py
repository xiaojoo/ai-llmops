#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
@Time   : 2026/08/24
@Author : sunxiaojie
@File   : test_skill_service.py
"""
import io
import shutil
import zipfile
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from internal.exception import FailedException, ValidateException
from internal.service.skill_service import SKILL_CACHE_ROOT, SkillService


def _build_zip(files: dict[str, str]) -> bytes:
    """根据 路径->内容 字典构建 zip 二进制"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    buf.seek(0)
    return buf.getvalue()


SKILL_MD_TEMPLATE = "---\nname: {name}\ndescription: {desc}\n---\n\n# {name}"


@pytest.fixture(autouse=True)
def _clean_skills_root():
    """每个测试前清理缓存目录，结束后清理"""
    if SKILL_CACHE_ROOT.exists():
        shutil.rmtree(SKILL_CACHE_ROOT, ignore_errors=True)
    yield
    if SKILL_CACHE_ROOT.exists():
        shutil.rmtree(SKILL_CACHE_ROOT, ignore_errors=True)


def _make_service(existing_name: str | None = None, user_id="user-1") -> SkillService:
    """构建 SkillService，mock 掉 db 会话、create、MinioService"""
    db_mock = AsyncMock()
    db_mock.get = AsyncMock(return_value=None)
    svc = SkillService(db=db_mock, minio_service=MagicMock())
    svc.create = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = MagicMock() if existing_name else None
    db_mock.execute = AsyncMock(return_value=mock_result)

    svc.current_user = MagicMock()
    svc.current_user.id = user_id
    return svc


class TestSkillServiceUploadZip:
    """SkillService.upload_zip 单元测试：一个 zip = 一个技能"""

    @pytest.mark.asyncio
    async def test_upload_single_skill_in_root(self):
        """单技能包：SKILL.md 在 zip 根目录，技能名用 zip 文件名"""
        svc = _make_service()
        zip_bytes = _build_zip({
            "SKILL.md": SKILL_MD_TEMPLATE.format(name="my-skill", desc="测试技能"),
            "helper.py": "print('hello')",
            "scripts/tool.sh": "#!/bin/bash",
        })

        created = await svc.upload_zip(svc.current_user, "my-skill.zip", zip_bytes)

        assert len(created) == 1
        call_kwargs = svc.create.call_args.kwargs
        assert call_kwargs["name"] == "my-skill"
        skill_id = call_kwargs["id"]
        cache_dir = SKILL_CACHE_ROOT / str(skill_id)
        # 根目录文件保留原结构
        assert (cache_dir / "SKILL.md").exists()
        assert (cache_dir / "helper.py").exists()
        assert (cache_dir / "scripts" / "tool.sh").exists()
        # 归档到 MinIO
        svc.minio_service.upload_file.assert_called()
        # 正文入库
        assert call_kwargs["content"].startswith("---")

    @pytest.mark.asyncio
    async def test_upload_collection_pack_as_one(self):
        """技能集合包（superpowers 结构）：整个 zip 作为一个技能，子目录保留"""
        svc = _make_service()
        zip_bytes = _build_zip({
            "superpowers/skills/alpha/SKILL.md": SKILL_MD_TEMPLATE.format(name="alpha", desc="技能A"),
            "superpowers/skills/alpha/extra.md": "extra",
            "superpowers/skills/beta/SKILL.md": SKILL_MD_TEMPLATE.format(name="beta", desc="技能B"),
            "superpowers/skills/beta/scripts/run.py": "print('run')",
            "superpowers/README.md": "readme",
        })

        created = await svc.upload_zip(svc.current_user, "superpowers.zip", zip_bytes)

        # 一个 zip 只产生一个技能，名称用 zip 文件名
        assert len(created) == 1
        call_kwargs = svc.create.call_args.kwargs
        assert call_kwargs["name"] == "superpowers"
        cache_dir = SKILL_CACHE_ROOT / str(call_kwargs["id"])
        # 去掉公共根前缀 superpowers/，子目录结构保留
        assert (cache_dir / "skills" / "alpha" / "SKILL.md").exists()
        assert (cache_dir / "skills" / "alpha" / "extra.md").exists()
        assert (cache_dir / "skills" / "beta" / "SKILL.md").exists()
        assert (cache_dir / "skills" / "beta" / "scripts" / "run.py").exists()
        assert (cache_dir / "README.md").exists()

    @pytest.mark.asyncio
    async def test_upload_collection_no_root_prefix(self):
        """集合包不带顶层目录（skills/ 直接开头）：也作为一个技能"""
        svc = _make_service()
        zip_bytes = _build_zip({
            "skills/alpha/SKILL.md": SKILL_MD_TEMPLATE.format(name="alpha", desc="A"),
            "skills/beta/SKILL.md": SKILL_MD_TEMPLATE.format(name="beta", desc="B"),
        })

        created = await svc.upload_zip(svc.current_user, "superpowers.zip", zip_bytes)

        assert len(created) == 1
        call_kwargs = svc.create.call_args.kwargs
        assert call_kwargs["name"] == "superpowers"
        cache_dir = SKILL_CACHE_ROOT / str(call_kwargs["id"])
        # 公共根是 skills/，去掉后保留 alpha/beta 子目录
        assert (cache_dir / "alpha" / "SKILL.md").exists()
        assert (cache_dir / "beta" / "SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_upload_existing_raises(self):
        """同名技能已存在时抛出异常"""
        svc = _make_service(existing_name="superpowers")
        zip_bytes = _build_zip({
            "skills/alpha/SKILL.md": SKILL_MD_TEMPLATE.format(name="alpha", desc="A"),
        })

        with pytest.raises(FailedException) as exc_info:
            await svc.upload_zip(svc.current_user, "superpowers.zip", zip_bytes)
        assert "已存在" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_upload_invalid_zip(self):
        """非法 zip 抛出校验异常"""
        svc = _make_service()
        with pytest.raises(ValidateException) as exc_info:
            await svc.upload_zip(svc.current_user, "bad.zip", b"not-a-zip")
        assert "不是合法的 zip" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_upload_missing_skill_md(self):
        """zip 中没有 SKILL.md 抛出异常"""
        svc = _make_service()
        zip_bytes = _build_zip({"README.md": "hello"})
        with pytest.raises(ValidateException) as exc_info:
            await svc.upload_zip(svc.current_user, "x.zip", zip_bytes)
        assert "未找到 SKILL.md" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_upload_md_single(self):
        """单 .md 上传：正文入库 + 本地缓存 SKILL.md + MinIO 归档"""
        svc = _make_service()
        content = SKILL_MD_TEMPLATE.format(name="my-skill", desc="测试技能")

        skill = await svc.upload(svc.current_user, content)

        call_kwargs = svc.create.call_args.kwargs
        assert call_kwargs["name"] == "my-skill"
        assert call_kwargs["visibility"] == "private"
        assert call_kwargs["content"] == content
        assert call_kwargs["account_id"] == "user-1"
        cache_dir = SKILL_CACHE_ROOT / str(call_kwargs["id"])
        assert (cache_dir / "SKILL.md").exists()
        svc.minio_service.upload_file.assert_called()


class TestSkillServiceFrontmatter:
    """frontmatter 解析测试"""

    @pytest.mark.parametrize("fm, expect_desc", [
        # 单行描述
        ("---\nname: alpha\ndescription: 单行描述\n---\n# x", "单行描述"),
        # 多行描述（YAML 块标量）
        ("---\nname: alpha\ndescription: |\n  第一行\n  第二行\n---\n# x", "第一行\n第二行"),
        # 描述内含冒号（非严格 YAML，走回退解析）
        ("---\nname: alpha\ndescription: 描述: 带冒号的内容\n---\n# x", "描述: 带冒号的内容"),
    ])
    def test_parse_frontmatter(self, fm, expect_desc):
        """多行/含冒号 frontmatter 都能正确解析"""
        meta = SkillService._parse_frontmatter(fm)
        assert meta["name"] == "alpha"
        assert meta["description"] == expect_desc

    def test_missing_name(self):
        """缺少 name 抛出异常"""
        with pytest.raises(ValidateException):
            SkillService._parse_frontmatter("---\ndescription: x\n---\n# y")
