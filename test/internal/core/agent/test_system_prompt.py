#!/usr/bin/env python
"""System Prompt 条件渲染测试：无长期记忆/用户画像时不产生空标签"""
from internal.core.agent.entities.agent_entity import (
    AGENT_SYSTEM_PROMPT_TEMPLATE,
    REACT_AGENT_SYSTEM_PROMPT_TEMPLATE,
    build_system_prompt,
)


class TestBuildSystemPrompt:
    def test_empty_memory_omits_blocks(self):
        prompt = build_system_prompt(
            AGENT_SYSTEM_PROMPT_TEMPLATE,
            preset_prompt="你是客服助手",
        )
        assert "长期记忆" not in prompt
        assert "用户画像" not in prompt

    def test_filled_blocks_rendered(self):
        prompt = build_system_prompt(
            AGENT_SYSTEM_PROMPT_TEMPLATE,
            preset_prompt="你是客服助手",
            long_term_memory="用户喜欢简洁回复",
            user_profile="用户常驻北京",
        )
        assert "用户喜欢简洁回复" in prompt
        assert "用户常驻北京" in prompt

    def test_react_template_tool_description_rendered(self):
        prompt = build_system_prompt(
            REACT_AGENT_SYSTEM_PROMPT_TEMPLATE,
            preset_prompt="",
            tool_description="gaode_weather - 查询天气",
        )
        assert "gaode_weather" in prompt

    def test_episodic_memory_block_rendered_when_present(self):
        prompt = build_system_prompt(
            AGENT_SYSTEM_PROMPT_TEMPLATE,
            preset_prompt="你是客服助手",
            episodic_memory="用户正在准备搬家到北京，已完成房源搜索",
        )
        assert "用户正在准备搬家到北京" in prompt

    def test_episodic_memory_block_omitted_when_empty(self):
        prompt = build_system_prompt(
            AGENT_SYSTEM_PROMPT_TEMPLATE,
            preset_prompt="你是客服助手",
        )
        assert "情景记忆" not in prompt
