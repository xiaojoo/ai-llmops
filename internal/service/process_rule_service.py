#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/12/3 19:40
@Author : sunxiaojie
@File   : process_rule_service.py
"""
import re
from collections.abc import Callable
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter, TextSplitter

from internal.model import ProcessRule

# Markdown 标题正则（# ~ ######），用于标题感知切分
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


# 默认分隔符常量（模块级，避免可变的类属性默认值）
_DEFAULT_SEPARATORS = [
    r"\n\n", r"\n", r"。|！|？", r"；|;\s", r"，|;\s", r" ", r"",
]


class HeadingAwareTextSplitter(TextSplitter):
    """标题感知切分器。

    按 Markdown 标题层级把文档切成章节块，块内如果超过 chunk_size 再按
    分隔符递归细分；每个子块携带 headings（标题路径）元数据，用于检索后
    的上下文组装（相当于轻量父子块：子块命中时自带父级标题上下文）。
    """

    separators: list[str] = _DEFAULT_SEPARATORS
    is_separator_regex: bool = True

    def __init__(
            self,
            chunk_size: int = 500,
            chunk_overlap: int = 50,
            separators: list[str] | None = None,
            length_function: Callable[[str], int] = len,
            **kwargs,
    ):
        super().__init__(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=length_function,
            **kwargs,
        )
        if separators:
            self.separators = separators

        # 内部使用递归切分器处理章节块内的细分
        self._recursive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=self.separators,
            is_separator_regex=self.is_separator_regex,
            length_function=length_function,
            **kwargs,
        )

    def split_text(self, text: str) -> list[str]:
        """按标题切分为章节块（不含 headings 元数据，split_documents 用它）"""
        return [content for content, _ in self._split_with_headings(text)]

    def split_documents(self, documents) -> list:
        """切分文档并保留 headings 元数据"""
        from langchain_core.documents import Document as LCDocument

        results = []
        for document in documents:
            # 结构感知：表格/图片块不参与切分，原样保留（避免空内容被吞掉）
            if document.metadata.get("content_type") in ("table", "image"):
                results.append(LCDocument(
                    page_content=document.page_content,
                    metadata={**document.metadata, "headings": []},
                ))
                continue
            for content, headings in self._split_with_headings(document.page_content):
                metadata = {**document.metadata, "headings": headings}
                results.append(LCDocument(page_content=content, metadata=metadata))
        return results

    def _split_with_headings(self, text: str) -> list[tuple[str, list[str]]]:
        """按标题层级切分，返回 [(chunk_text, headings_path), ...]"""
        # 1、收集标题位置
        heading_matches = list(HEADING_PATTERN.finditer(text))
        if not heading_matches:
            # 2、无标题：整段按 chunk_size 递归切分，headings 为空
            return [(chunk, []) for chunk in self._recursive_splitter.split_text(text)]

        # 3、按标题切章节
        sections = []
        for i, match in enumerate(heading_matches):
            start = match.start()
            end = heading_matches[i + 1].start() if i + 1 < len(heading_matches) else len(text)
            level = len(match.group(1))
            title = match.group(2).strip()
            body = text[start:end].strip()
            sections.append((level, title, body))

        # 4、构建标题路径（父标题链），章节内超长再递归细分
        results = []
        heading_stack: list[str] = []

        for level, title, body in sections:
            # 维护标题栈：弹出比当前级别更深/同级的标题
            while heading_stack and len(heading_stack) >= level:
                heading_stack.pop()
            heading_stack.append(title)

            if len(body) <= self._chunk_size:
                results.append((body, list(heading_stack)))
                continue

            # 章节超长：递归细分，子块保留完整标题路径
            for chunk in self._recursive_splitter.split_text(body):
                if chunk.strip():
                    results.append((chunk, list(heading_stack)))

        return results


@dataclass
class ProcessRuleService:
    """处理规则服务"""

    @classmethod
    def get_text_splitter_by_process_rule(
            cls,
            process_rule: ProcessRule,
            length_function: Callable[[str], int] = len,
            **kwargs,
    ) -> TextSplitter:
        """根据传递的处理规则+长度计算函数，获取相应的文本分割器。

        规则中 rule.segment.mode == "heading" 时使用标题感知切分，
        默认（recursive / 缺省）使用递归切分，兼容旧配置。
        """
        segment_rule = process_rule.rule.get("segment", {})
        mode = segment_rule.get("mode", "recursive")
        chunk_size = segment_rule["chunk_size"]
        chunk_overlap = segment_rule["chunk_overlap"]
        separators = segment_rule.get("separators")

        if mode == "heading":
            return HeadingAwareTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=separators,
                length_function=length_function,
                **kwargs,
            )

        return RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=segment_rule["separators"],
            is_separator_regex=True,
            length_function=length_function,
            **kwargs,
        )

    @classmethod
    def clean_text_by_process_rule(cls, text: str, process_rule: ProcessRule) -> str:
        """根据传递的处理规则清除多余的字符串"""
        # 1、循环遍历所有与处理规则
        for pre_process_rule in process_rule.rule["pre_process_rules"]:
            # 2、删除多余空格
            if pre_process_rule["id"] == "remove_extra_space" and pre_process_rule.get("enabled", False) is True:
                pattern = r'\n{3}'
                text = re.sub(pattern, '\n\n', text)
                pattern = r'[\t\f\r\x20\u00a0\u1680\u180e\u2000-\u200a\u202f\u205f\u3000]{2,}'
                text = re.sub(pattern, '  ', text)
            # 3、删除多余的URL链接及邮箱
            if pre_process_rule["id"] == "remove_url_and_email" and pre_process_rule.get("enabled", False) is True:
                pattern = r'c[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
                text = re.sub(pattern, '', text)
                pattern = r'https?://[^\s]+'
                text = re.sub(pattern, '', text)
        return text
