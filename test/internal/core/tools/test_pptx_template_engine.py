#!/usr/bin/env python
"""pptx 模板引擎单测：markdown 解析、模板选页、文字填充、剪枝、出框提示。

不依赖数据库与对象存储：只测引擎（纯 python-pptx 管线）。
注意：沙箱拒绝在系统临时目录与 0o700 权限目录（tempfile.mkdtemp 的默认）中写文件，
故 work_dir 用 os.mkdir 默认权限在工作区 tmp/ 下建目录。
"""
import os
import shutil
import uuid
from pathlib import Path

import pytest
from pptx import Presentation

from internal.core.tools.builtin_tools.providers.pptx import template_engine as eng

SAMPLE = """# AI Agent 技术汇报
2026 年度技术总结

## 核心成果
- 上线 3 个智能体应用
- 平均响应时间下降 40%
- 用户满意度提升到 92%

## 技术挑战
- 长上下文窗口管理
- 工具调用稳定性
- 成本控制
"""


@pytest.fixture
def work_dir():
    """工作区内的临时目录（os.mkdir 默认权限；沙箱拒绝 0o700 目录内写文件）。"""
    base = Path(__file__).resolve().parents[4] / "tmp" / "pptx-test"
    base.mkdir(parents=True, exist_ok=True)
    d = base / f"case-{uuid.uuid4().hex[:8]}"
    os.mkdir(d)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _all_text(pptx_path: Path) -> str:
    """抽取成稿所有形状文本（含组合图形内部），用于断言内容与占位符泄漏。"""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(str(pptx_path))
    parts = []

    def walk(shapes):
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                walk(shape.shapes)
            elif shape.has_text_frame:
                parts.append(shape.text)

    for slide in prs.slides:
        walk(slide.shapes)
    return "\n".join(parts)


def test_parse_markdown():
    plan = eng.parse_markdown(SAMPLE)
    assert plan.deck_title == "AI Agent 技术汇报"
    assert plan.subtitle == "2026 年度技术总结"
    assert [s.title for s in plan.slides] == ["核心成果", "技术挑战"]
    assert plan.slides[0].items == [
        "上线 3 个智能体应用",
        "平均响应时间下降 40%",
        "用户满意度提升到 92%",
    ]


def test_list_available_templates():
    slugs = eng.list_available_templates()
    assert "minimal-business-summary" in slugs
    assert len(slugs) >= 5


def test_generate_output_structure(work_dir):
    """封面 + 2 内容 + 结尾 = 4 页"""
    out = work_dir / "out.pptx"
    _warnings, error = eng.generate_pptx(SAMPLE, "minimal-business-summary", out)
    assert error is None
    assert out.exists()
    prs = Presentation(str(out))
    assert len(prs.slides) == 4


def test_generate_no_placeholder_leak(work_dir):
    out = work_dir / "out.pptx"
    _, error = eng.generate_pptx(SAMPLE, "minimal-business-summary", out)
    assert error is None
    joined = _all_text(out)
    assert "AI Agent 技术汇报" in joined
    assert "核心成果" in joined
    assert "技术挑战" in joined
    for bad in ("Rice Husk", "工作计划模板", "Question", "Vivamus", "Quam Dolor"):
        assert bad not in joined, f"占位文本泄漏: {bad}"


def test_generate_collection_template(work_dir):
    """合辑型模板（无 cover/ending 角色）也能生成，首页当封面。"""
    out = work_dir / "out.pptx"
    _warnings, error = eng.generate_pptx(SAMPLE, "architecture-deck", out)
    assert error is None
    joined = _all_text(out)
    assert "AI Agent 技术汇报" in joined


def test_unknown_template(work_dir):
    out = work_dir / "out.pptx"
    _, error = eng.generate_pptx(SAMPLE, "no-such-template", out)
    assert error is not None and "不存在" in error


def test_empty_markdown(work_dir):
    out = work_dir / "out.pptx"
    _, error = eng.generate_pptx("", "minimal-business-summary", out)
    assert error is not None and "没有可用" in error


def test_more_slides_than_pages_rotates(work_dir):
    """内容页超出模板容量时自动复制模板页：20 张内容页一张不丢，且各页内容独立。"""
    md = "# 标题\n" + "".join(f"## 第{i}节\n- 要点1\n- 要点2\n" for i in range(1, 21))
    out = work_dir / "out.pptx"
    _, error = eng.generate_pptx(md, "minimal-business-summary", out)
    assert error is None
    prs = Presentation(str(out))
    # 封面 1 + 内容 20 + 结尾 1
    assert len(prs.slides) == 22
    joined = _all_text(out)
    for i in range(1, 21):
        assert f"第{i}节" in joined, f"第{i}节内容丢失"


def test_work_dir_writable():
    """工作目录必须可写可清理（沙箱下 tempfile 的 0o700 目录不可写，这是修复点）。"""
    from internal.core.tools.builtin_tools.providers.pptx.workdir import (
        cleanup_pptx_work_dir,
        create_pptx_work_dir,
    )

    d = create_pptx_work_dir()
    try:
        assert d.is_dir()
        f = d / "t.txt"
        f.write_text("hi", encoding="utf-8")
        assert f.read_text(encoding="utf-8") == "hi"
    finally:
        cleanup_pptx_work_dir(d)
    assert not d.exists()


def _make_custom_template(path: Path) -> None:
    """构造一个含占位符的自定义 .pptx（封面 + 2 张内容页）。"""
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    blank = prs.slide_layouts[6]
    # 封面：占位标题
    s = prs.slides.add_slide(blank)
    tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
    tb.text = "添加标题"
    # 内容页 1：标题 + 正文占位 + 装饰性数字（不应被改动）
    s2 = prs.slides.add_slide(blank)
    t1 = s2.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
    t1.text = "添加标题"
    t2 = s2.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(2))
    t2.text = "单击此处输入你的正文内容"
    n = s2.shapes.add_textbox(Inches(1), Inches(4), Inches(4), Inches(1))
    n.text = "75%"
    prs.save(str(path))


def test_custom_template_path(work_dir):
    """模式 B：任意 .pptx 路径作为模板，占位符被填充且不泄漏。"""
    tpl = work_dir / "custom.pptx"
    _make_custom_template(tpl)
    out = work_dir / "out.pptx"
    _, error = eng.generate_pptx(SAMPLE, str(tpl), out)
    assert error is None
    joined = _all_text(out)
    assert "AI Agent 技术汇报" in joined
    assert "核心成果" in joined
    assert "技术挑战" in joined
    for bad in ("添加标题", "单击此处输入你的正文内容"):
        assert bad not in joined, f"占位文本泄漏: {bad}"
    # 装饰文本（75%）原样保留
    assert "75%" in joined


def test_project_root_custom_templates(work_dir):
    """项目根目录 templates/ 专属目录的两个真实模板（按文件名解析），各生成一份样例。"""
    root = Path(__file__).resolve().parents[4]
    for name in ("树形模版.pptx", "指标走向.pptx"):
        tpl = root / "templates" / name
        if not tpl.exists():
            pytest.skip(f"{name} 不在项目根目录 templates/ 下")
        out = work_dir / f"{name}.pptx"
        _, error = eng.generate_pptx(SAMPLE, name, out)  # 仅文件名：应自动从 templates/ 解析
        assert error is None, f"{name} 生成失败: {error}"
        joined = _all_text(out)
        assert "AI Agent 技术汇报" in joined, f"{name} 封面标题缺失"


def test_custom_template_skips_graphic_pages(work_dir):
    """模式 B：图标页/数据页（5k、10K、图标）不进内容页，避免成品像没填内容。"""
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    blank = prs.slide_layouts[6]
    # 封面
    s = prs.slides.add_slide(blank)
    tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
    tb.text = "添加标题"
    # 干净内容页
    s2 = prs.slides.add_slide(blank)
    t1 = s2.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
    t1.text = "添加标题"
    t2 = s2.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(2))
    t2.text = "单击此处输入正文内容"
    # 图标页（PUA 区字符）
    s3 = prs.slides.add_slide(blank)
    for i in range(3):
        tb = s3.shapes.add_textbox(Inches(1), Inches(1 + i), Inches(4), Inches(0.5))
        tb.text = chr(0xF0C8 + i)
    # 数据页（10K/25K/7K）
    s4 = prs.slides.add_slide(blank)
    for i, v in enumerate(("10K", "25K", "7K")):
        tb = s4.shapes.add_textbox(Inches(1), Inches(1 + i), Inches(4), Inches(0.5))
        tb.text = v

    tpl = work_dir / "graphic.pptx"
    prs.save(str(tpl))
    out = work_dir / "out.pptx"
    md = "# 标题\n## 第一节\n- 要点A\n- 要点B"
    _, error = eng.generate_pptx(md, str(tpl), out)
    assert error is None
    prs2 = Presentation(str(out))
    # 封面 + 干净内容页（图标页/数据页被排除）
    assert len(prs2.slides) == 2
    joined = _all_text(out)
    assert "第一节" in joined
    for bad in ("10K", "25K", "7K", "\uf0c8"):
        assert bad not in joined, f"图形页混入成品: {bad!r}"


def test_all_bundled_templates_generate(work_dir):
    """每套内置模板都能用同一份 markdown 出稿。"""
    for slug in eng.list_available_templates():
        out = work_dir / f"{slug}.pptx"
        _, error = eng.generate_pptx(SAMPLE, slug, out)
        assert error is None, f"模板 {slug} 生成失败: {error}"
        assert out.exists()
