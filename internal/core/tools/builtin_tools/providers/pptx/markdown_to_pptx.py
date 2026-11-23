#!/usr/bin/env python
"""
@Time    : 2026/3/6 20:43
@Author  : sunxiaojie
@File    : markdown_to_pptx.py
"""
import logging
import os
import urllib.request
import uuid
from typing import Any

import mistune
from langchain_core.tools import StructuredTool
from pptx import Presentation, presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Length, Pt
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)



class PPTRenderer(mistune.HTMLRenderer):
    """借助HTML渲染器重写并定义PPT渲染器"""
    prs: presentation.Presentation
    font_name: str  # 字体名字
    image_folder: str  # 存储图片的文件夹
    content_left: Length  # 内容距离左侧的距离
    content_top: Length  # 内容距离顶部的距离
    content_width: Length  # 内容的宽度
    line_height: Length  # 内容行高

    def __init__(
            self,
            prs: presentation.Presentation,  # PPT演示文稿
            image_folder: str,  # 存储图片的文件夹
    ):
        """构造函数，完成PPT渲染器的初始化"""
        super().__init__()
        self.prs = prs
        self.current_slide = None
        self.font_name = "微软雅黑"
        self.image_folder = image_folder
        self.content_left = Inches(1)
        self.content_top = Inches(1.5)
        self.content_width = Inches(8.5)
        self.line_height = Pt(24)

    def heading(self, text: str, level: int, **attrs: Any) -> str:
        """标题内容处理器"""
        if level == 1:
            slide = self.prs.slides.add_slide(self.prs.slide_layouts[0])
            title = slide.shapes.title
            sub_title = slide.placeholders[1]
            title.text = text.strip()
            title.text_frame.paragraphs[0].font.name = self.font_name
            sub_title.text = "由慕课LLMOps平台生成"
            self.current_slide = None
        else:
            slide_layout = self.prs.slide_layouts[5]
            self.current_slide = self.prs.slides.add_slide(slide_layout)
            title_shape = self.current_slide.shapes.title
            title_shape.text = text.strip()
            title_shape.text_frame.paragraphs[0].font.name = self.font_name
            self.content_top = Inches(1.5)
        return ""

    def paragraph(self, text: str) -> str:
        """段落内容处理器"""
        text = text.strip()
        if self.current_slide and len(text):
            self.check_new_slide()
            text_height = self.estimate_text_height(text, font_size=18)
            text_box = self.current_slide.shapes.add_textbox(
                self.content_left,
                self.content_top,
                self.content_width,
                text_height,
            )
            tf = text_box.text_frame
            tf.word_wrap = True
            if tf.paragraphs:
                tf.paragraphs[0]._element.getparent().remove(tf.paragraphs[0]._element)
            p = tf.add_paragraph()
            p.text = text
            p.font.name = self.font_name
            p.font.size = Pt(18)
            self.content_top += text_height
        return ""

    def list(self, text: str, ordered: bool, **attrs: Any) -> str:
        """列表内容处理器"""
        if self.current_slide:
            self.check_new_slide()

        text_box = self.current_slide.shapes.add_textbox(
            self.content_left,
            self.content_top,
            self.content_width,
            Inches(4),
        )
        tf = text_box.text_frame
        tf.word_wrap = True
        tf.clear()

        items = text.strip().split("\n")
        total_height = 0

        for item in items:
            self.check_new_slide()
            p = tf.add_paragraph()
            p.text = item.strip().replace("<li>", "").replace("</li>", "")
            p.level = 0
            p.font.name = self.font_name
            p.font.size = Pt(18)

            item_height = self.estimate_text_height(item, font_size=18)
            total_height += item_height
            self.content_top += item_height

            if total_height > Inches(4):
                total_height = 0
        return ""

    def image(self, text: str, url: str, title: str | None = None) -> str:
        """图片处理器"""
        try:
            if self.current_slide:
                self.check_new_slide()
                if url.startswith("http"):
                    local_path = os.path.join(self.image_folder, os.path.basename(url))
                    urllib.request.urlretrieve(url, local_path)
                else:
                    local_path = url

                pic = self.current_slide.shapes.add_picture(
                    local_path,
                    (self.prs.slide_width - Inches(4)) / 2,
                    self.content_top,
                    width=Inches(4),
                )
                self.content_top += pic.height + Inches(0.5)
        except Exception:
            logger.exception("PPTRenderer图片处理失败，错误信息")
        return ""

    def block_code(self, code: str, info: str | None = None) -> str:
        """代码块内容处理器"""
        if self.current_slide:
            self.check_new_slide()
            text_box = self.current_slide.shapes.add_textbox(
                self.content_left,
                self.content_top,
                self.content_width,
                Inches(2)
            )
            tf = text_box.text_frame
            p = tf.add_paragraph()
            p.text = code.strip()
            p.font.name = 'Consolas'
            p.font.size = Pt(14)
            p.font.color.rgb = RGBColor(0x33, 0x66, 0x99)
            self.content_top += self.line_height * (code.count('\n') + 2)
        return ''

    def check_new_slide(self) -> None:
        """检查是否需要新建幻灯片"""
        if self.content_top >= Inches(6):
            title = ""
            if self.current_slide:
                title_shape = self.current_slide.shapes.title
                if title_shape and title_shape.text:
                    title = title_shape.text

            self.current_slide = self.prs.slides.add_slide(self.prs.slide_layouts[5])
            self.content_top = Inches(1.5)

            if title:
                new_title_shape = self.current_slide.shapes.title
                if new_title_shape:
                    new_title_shape.text = title
                    new_title_shape.text_frame.paragraphs[0].font.name = self.font_name

    @classmethod
    def estimate_text_height(cls, text: str, font_size: int = 20, avg_char_per_line: int = 30) -> float:
        """估算文本高度"""
        lines = max(1, (len(text) // avg_char_per_line) + text.count("\n"))
        line_height = Pt(font_size * 1.2)
        return (lines + 0.3) * line_height


class MarkdownToPPTXArgsSchema(BaseModel):
    markdown: str = Field(description="要生成PPT内容的markdown文档字符串。")


def _generate_pptx_impl(markdown: str) -> str:
    """根据传递的markdown文档内容调用python-pptx和mistune创建pptx文件并存储到cos中"""
    work_dir = None
    try:
        # 1、创建可写的工作目录（沙箱下系统临时目录/0o700 目录不可写，改用项目内目录）
        from .workdir import cleanup_pptx_work_dir, create_pptx_work_dir

        work_dir = create_pptx_work_dir()
        temp_dir = str(work_dir)

        # 2、初始化PPT和渲染器
        prs = Presentation()
        renderer = PPTRenderer(prs, temp_dir)
        # 注意：变量名 md_parser 避免与参数 markdown 冲突
        md_parser = mistune.Markdown(renderer)
        md_parser(markdown)

        # 3、保存输出ppt
        filename = str(uuid.uuid4()) + ".pptx"
        filepath = os.path.join(temp_dir, filename)
        prs.save(filepath)

        # 4、上传并返回URL（与 pptx_from_template 共用同一上传链路）
        from .upload import upload_pptx

        return upload_pptx(filepath)

    except Exception as error:
        logger.exception("markdown_to_pptx出错")
        return f"生成PPT演示文稿失败，错误原因: {error!s}"
    finally:
        if work_dir is not None:
            cleanup_pptx_work_dir(work_dir)


markdown_to_pptx = StructuredTool.from_function(
    func=_generate_pptx_impl,
    name="markdown_to_pptx",
    description="这是一个可以将markdown文本转换成PPT的工具，传递的参数是markdown对应的文本字符串，返回的数据是PPT下载地址。",
    args_schema=MarkdownToPPTXArgsSchema
)
