#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Agent 工具调用解析测试：Anthropic 风格 XML 兜底解析（模型误输出时工具仍能真正执行）。"""
import pytest

from internal.core.agent.agents.function_call_agent import (
    FunctionCallAgent,
    _contains_xml_tool_call,
    _filter_xml_tool_call_stream,
    _parse_xml_param_value,
)
from internal.core.agent.agents.react_agent import ReACTAgent

# FunctionCallAgent 是 ReACTAgent 的父类，解析器在父类上，两个 agent 各验一遍
AGENTS = [FunctionCallAgent, ReACTAgent]


@pytest.mark.parametrize("agent_cls", AGENTS)
def test_parse_xml_invoke_basic(agent_cls):
    """基础格式：<invoke name="x"><parameter name="k">v</parameter></invoke>"""
    parser = agent_cls._parse_tool_calls_from_xml
    calls = parser(
        '<invoke name="browser">\n'
        '<parameter name="task">打开 http://localhost:5173/home 页面</parameter>\n'
        "</invoke>"
    )
    assert len(calls) == 1
    assert calls[0]["name"] == "browser"
    assert calls[0]["args"] == {"task": "打开 http://localhost:5173/home 页面"}
    assert calls[0]["type"] == "tool_call"
    assert calls[0]["id"]


@pytest.mark.parametrize("agent_cls", AGENTS)
def test_parse_xml_tool_calls_wrapper_and_attributes(agent_cls):
    """带 <tool_calls> 包裹 + parameter 带 string 属性（与 scripts/tmp_llm3.txt 一致）。"""
    parser = agent_cls._parse_tool_calls_from_xml
    text = (
        "<tool_calls>\n"
        '<invoke name="dataset_retrieval">\n'
        '<parameter name="query" string="true">唐宇 吴梦婷 人物介绍 角色设定</parameter>\n'
        "</invoke>\n"
        "</tool_calls>"
    )
    calls = parser(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "dataset_retrieval"
    assert calls[0]["args"] == {"query": "唐宇 吴梦婷 人物介绍 角色设定"}


@pytest.mark.parametrize("agent_cls", AGENTS)
def test_parse_xml_multiple_invokes_and_entities(agent_cls):
    """多个 invoke + HTML 实体转义。"""
    parser = agent_cls._parse_tool_calls_from_xml
    text = (
        '<invoke name="browser"><parameter name="task">a &lt; b</parameter></invoke>\n'
        '<invoke name="current_time"><parameter name="tz">UTC+8</parameter></invoke>'
    )
    calls = parser(text)
    assert len(calls) == 2
    assert calls[0]["args"] == {"task": "a < b"}
    assert calls[1]["name"] == "current_time"
    assert calls[1]["args"] == {"tz": "UTC+8"}


@pytest.mark.parametrize("agent_cls", AGENTS)
def test_parse_xml_no_invoke_raises(agent_cls):
    """没有 <invoke> 时抛错（调用方回退为普通文本）。"""
    parser = agent_cls._parse_tool_calls_from_xml
    with pytest.raises(ValueError):
        parser("普通文本，没有工具调用")


def test_system_prompt_forbids_xml():
    """提示词必须明确禁止 XML 工具调用格式。"""
    from internal.core.agent.entities.agent_entity import (
        AGENT_SYSTEM_PROMPT_TEMPLATE,
        REACT_AGENT_SYSTEM_PROMPT_TEMPLATE,
    )
    for template in (AGENT_SYSTEM_PROMPT_TEMPLATE, REACT_AGENT_SYSTEM_PROMPT_TEMPLATE):
        assert "XML" in template
        assert "<invoke>" in template


def test_contains_xml_tool_call_detects_tags():
    """流式发布过滤：含 XML 工具调用标签的 chunk 不应回显给用户。"""
    xml_samples = [
        '<invoke name="browser"><parameter name="task">打开页面</parameter></invoke>',
        '<tool_calls>\n<invoke name="x">...</invoke>\n</tool_calls>',
        '开场白<parameter name="task" string="true">值</parameter>',
        "前半段</invoke>后半段",
    ]
    for text in xml_samples:
        assert _contains_xml_tool_call(text), text

    normal_samples = [
        "让我先打开页面看看情况。",
        "浏览器刚执行过任务需要等待，让我稍后再试。",
        "普通文本 < 和 > 不是标签",
    ]
    for text in normal_samples:
        assert not _contains_xml_tool_call(text), text


# ===== 流式区段过滤（XML 标签被拆成多个 chunk 时不得漏显示） =====

def _stream_visible(chunks):
    """按顺序喂 chunk，返回所有可回显文本拼接结果。"""
    out = []
    in_xml = False
    for c in chunks:
        visible, in_xml = _filter_xml_tool_call_stream(c, in_xml)
        if visible:
            out.append(visible)
    return "".join(out)


def test_stream_filter_single_chunk_xml():
    """整段 XML 在一个 chunk：完全抑制。"""
    xml = '<invoke name="shell_run"><parameter name="command">python</parameter></invoke>'
    assert _stream_visible([xml]) == ""


def test_stream_filter_xml_split_across_chunks():
    """XML 标签被拆成多个 chunk（参数值单独成 chunk 不带标签）：仍应完全抑制。"""
    chunks = [
        '我来启动并测试一下这个俄罗斯方块游戏。\n',
        '<invoke name="shell_run">\n',
        '<parameter name="args">["-m", "pip", "install", "pygame"]</parameter>\n',
        '<parameter name="command">python</parameter>\n',
        '<parameter name="timeout" string="false">120</parameter>\n',
        '</invoke>',
    ]
    assert _stream_visible(chunks) == "我来启动并测试一下这个俄罗斯方块游戏。\n"


def test_stream_filter_xml_mid_chunk_preserves_prefix():
    """同一 chunk 内普通文本 + XML：普通文本保留，XML 抑制。"""
    text = '我先安装依赖。<invoke name="shell_run"><parameter name="command">python</parameter></invoke>'
    assert _stream_visible([text]) == "我先安装依赖。"


def test_stream_filter_closes_and_resumes():
    """闭合标签后继续输出普通文本：应恢复回显。"""
    chunks = [
        '<invoke name="shell_run">\n',
        '<parameter name="command">python</parameter>\n',
        '</invoke>',
        '安装完成，继续。',
    ]
    assert _stream_visible(chunks) == "安装完成，继续。"


def test_stream_filter_plain_text_unchanged():
    """普通文本不经过 XML 区段时原样回显。"""
    assert _stream_visible(["你好", "，", "世界"]) == "你好，世界"


# ===== XML 参数值解析（JSON 数组/对象字符串 → 结构化值） =====

def test_parse_xml_param_json_array():
    """参数值为 JSON 数组字符串 → 解析为 list（shell_run 的 args 场景）。"""
    parser = FunctionCallAgent._parse_tool_calls_from_xml
    calls = parser(
        '<invoke name="shell_run">\n'
        '<parameter name="args">["-m", "pip", "install", "pygame"]</parameter>\n'
        '<parameter name="command">python</parameter>\n'
        '<parameter name="timeout" string="false">120</parameter>\n'
        "</invoke>"
    )
    assert calls[0]["name"] == "shell_run"
    assert calls[0]["args"]["command"] == "python"
    assert calls[0]["args"]["args"] == ["-m", "pip", "install", "pygame"]
    assert calls[0]["args"]["timeout"] == 120


def test_parse_xml_param_json_object():
    """参数值为 JSON 对象字符串 → 解析为 dict。"""
    parser = FunctionCallAgent._parse_tool_calls_from_xml
    calls = parser(
        '<invoke name="x">'
        '<parameter name="cfg">{"a": 1, "b": [2, 3]}</parameter>'
        "</invoke>"
    )
    assert calls[0]["args"]["cfg"] == {"a": 1, "b": [2, 3]}


def test_parse_xml_param_plain_string_unchanged():
    """普通字符串参数保持原样（数字/布尔仍转原生类型）。"""
    assert _parse_xml_param_value("打开页面") == "打开页面"
    assert _parse_xml_param_value("42") == 42
    assert _parse_xml_param_value("true") is True
    assert _parse_xml_param_value("3.14") == 3.14
