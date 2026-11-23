#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""
@Time   : 2026/08/25
@Author : sunxiaojie
@File   : test_app_config_skill_tool.py
"""
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from internal.service.app_config_service import AppConfigService

CACHE = Path("storage/skills/test-skill-cache")


@pytest.fixture(autouse=True)
def _clean_cache():
    if CACHE.exists():
        shutil.rmtree(CACHE, ignore_errors=True)
    yield
    if CACHE.exists():
        shutil.rmtree(CACHE, ignore_errors=True)


def _write_skill(dir_name: str, name: str, desc: str, extra: str = "") -> None:
    d = CACHE / dir_name
    d.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n{extra}"
    (d / "SKILL.md").write_text(content, encoding="utf-8")


class TestCollectSubSkills:
    """技能包子技能收集"""

    def test_empty_cache(self):
        assert AppConfigService._collect_sub_skills(CACHE) == []

    def test_excludes_entry(self):
        """排除入口正文（内容与 entry_content 相同的文件）"""
        _write_skill("alpha", "alpha", "技能A")
        _write_skill("beta", "beta", "技能B")

        entry = (CACHE / "alpha" / "SKILL.md").read_text(encoding="utf-8")
        subs = AppConfigService._collect_sub_skills(CACHE, entry)

        names = [n for n, _, _ in subs]
        assert names == ["beta"]

    def test_collects_all_without_entry(self):
        """不传 entry_content 时收集全部"""
        _write_skill("alpha", "alpha", "技能A")
        _write_skill("beta", "beta", "技能B")
        _write_skill("gamma", "gamma", "技能C")

        subs = AppConfigService._collect_sub_skills(CACHE)

        names = [n for n, _, _ in subs]
        assert names == ["alpha", "beta", "gamma"]
        # 每个含全文
        assert all(len(full) > 0 for _, _, full in subs)


class TestSkillToolContext:
    """技能工具上下文构建（skill_tool_func）"""

    async def _build_tool(self):
        """构造 Skill 对象 + 收集子技能，mock LLM 捕获 SystemMessage

        _create_langchain_tool_from_skill 已 async 化（await load_language_model），
        故 mock 用 AsyncMock 并 await 工具构建。
        """
        _write_skill("alpha", "alpha", "技能A 的说明")
        _write_skill("beta", "beta", "技能B 的说明")

        skill = MagicMock()
        skill.name = "test-pack"
        skill.description = "测试技能包"
        skill.content = (CACHE / "alpha" / "SKILL.md").read_text(encoding="utf-8")
        # id 需对应 _cache_dir 解析出的目录（storage/skills/{id}），与 CACHE 一致
        skill.id = "test-skill-cache"

        svc = AppConfigService(
            db=MagicMock(),
            api_provider_manager=MagicMock(),
            builtin_provider_manager=MagicMock(),
            language_model_manager=MagicMock(),
            language_model_service=MagicMock(),
        )
        captured = {}

        mock_llm = MagicMock()

        def fake_invoke(messages):
            captured["system"] = messages[0].content
            captured["human"] = messages[1].content
            resp = MagicMock()
            resp.content = "done"
            return resp

        mock_llm.invoke.side_effect = fake_invoke
        svc.language_model_service = MagicMock()
        svc.language_model_service.load_language_model = AsyncMock(return_value=mock_llm)

        tool = await svc._create_langchain_tool_from_skill(skill)
        return tool, captured

    @pytest.mark.asyncio
    async def test_index_included_for_generic_query(self):
        """普通 query：SystemMessage 包含子技能索引"""
        tool, captured = await self._build_tool()
        tool.invoke({"query": "帮我分析一下"})

        system = captured["system"]
        # 入口内容 + 子技能索引
        assert "技能A 的说明" in system or "alpha" in system
        assert "子技能" in system
        assert "beta" in system

    @pytest.mark.asyncio
    async def test_named_sub_full_content_injected(self):
        """点名子技能：注入该子技能完整内容"""
        tool, captured = await self._build_tool()
        tool.invoke({"query": "请使用 beta 技能来处理"})

        system = captured["system"]
        assert "子技能「beta」完整内容" in system
        assert "技能B 的说明" in system

    @pytest.mark.asyncio
    async def test_entry_not_in_sub_index(self):
        """入口本身不在子技能索引里"""
        tool, captured = await self._build_tool()
        tool.invoke({"query": "随便问问"})

        system = captured["system"]
        # 入口 alpha 的 frontmatter name 不应出现在索引行（- alpha: ...）
        assert "\n- alpha:" not in system

    @pytest.mark.asyncio
    async def test_tool_description_includes_sub_skills(self):
        """工具描述包含子技能能力清单（供模型判断何时调用）"""
        tool, _ = await self._build_tool()
        assert "子技能" in tool.description
        assert "beta" in tool.description
        assert "必须调用本工具" in tool.description
