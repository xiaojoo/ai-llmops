#!/usr/bin/env python
"""pptx_from_template —— 内置模板生成 PPT 工具。

用内置设计模板（GordenPPTSkill 精选）把 markdown 内容生成精美 .pptx：
保留模板排版/配色，只替换文字；返回可下载地址。

markdown 约定：
    # 标题            → 封面标题（第一行，其后第一段普通文本为副标题）
    ## 小节标题       → 一张内容页
    - 要点            → 该页正文槽（无标题时首个要点充当标题）
    其它普通文本      → 视为要点
"""
import logging
import os
import uuid

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from .template_engine import generate_pptx, list_available_templates
from .upload import upload_pptx

logger = logging.getLogger(__name__)

_TEMPLATES_HINT = "、".join(list_available_templates())


class PPTXFromTemplateArgsSchema(BaseModel):
    """模板生成 PPT 的参数"""

    markdown: str = Field(
        description=(
            "要生成PPT的markdown文档字符串。约定：第一行 `# 标题` 为封面标题（"
            "其后的第一段普通文本作为副标题）；每个 `## 小节标题` 生成一张内容页；"
            "小节下的 `- 要点` 填充该页正文。"
            "**内容饱满要求**：写 8~15 个 `##` 小节；每个小节下写 3~6 条要点，"
            "每条 20~60 字、内容具体（含解释/数据/案例），不要只写 2~4 字短语；"
            "小节越多、要点越详实，成品页数越多、每页越充实。"
        )
    )
    template: str = Field(
        default="minimal-business-summary",
        description=(
            f"模板：内置模板 slug（可选：{_TEMPLATES_HINT}）；"
            f"或本地 .pptx 模板文件路径（如 '树形模版.pptx'，自动从项目根目录 templates/ 目录查找，"
            f"也支持相对项目根目录路径或绝对路径）；"
            f"传 'none' 使用基础无模板渲染。不传默认 minimal-business-summary（简约商务总结）。"
        ),
    )


def _generate_impl(markdown: str, template: str = "minimal-business-summary") -> str:
    """生成 PPT 并上传，返回下载 URL；失败返回错误描述字符串。"""
    work_dir = None
    try:
        if template == "none":
            from .markdown_to_pptx import _generate_pptx_impl

            return _generate_pptx_impl(markdown)

        # 沙箱下系统临时目录/0o700 目录不可写，用项目内可写工作目录
        from .workdir import cleanup_pptx_work_dir, create_pptx_work_dir

        work_dir = create_pptx_work_dir()
        filename = f"{uuid.uuid4().hex}.pptx"
        filepath = os.path.join(str(work_dir), filename)
        warnings, error = generate_pptx(markdown, template, filepath)
        if error:
            return error
        url = upload_pptx(filepath)
        if warnings:
            note = "；".join(warnings[:5])
            return f"{url}\n\n（生成提示：{note}）"
        return url
    except Exception as e:  # 工具兜底：不把异常泄漏给 Agent
        logger.exception("pptx_from_template 生成失败")
        return f"生成PPT演示文稿失败，错误原因: {e!s}"
    finally:
        if work_dir is not None:
            cleanup_pptx_work_dir(work_dir)


pptx_from_template = StructuredTool.from_function(
    func=_generate_impl,
    name="pptx_from_template",
    description=(
        "使用设计模板将 Markdown 内容生成精美的 PowerPoint 演示文稿（.pptx），"
        "保留模板的排版/配色/字体，只替换文字；返回文件下载地址。"
        f"模板可选：内置模板（{_TEMPLATES_HINT}）、本地 .pptx 文件路径（自动从项目根目录 templates/ 目录查找，"
        "也支持相对项目根目录路径或绝对路径）；"
        "传 template='none' 使用基础无模板渲染。"
        "生成时请提供内容饱满的 markdown：8~15 个 `##` 小节、每节 3~6 条 20~60 字的详细要点"
        "（含解释/数据/案例），避免 2~4 字短词，否则成品每页内容会偏少。"
    ),
    args_schema=PPTXFromTemplateArgsSchema,
)
