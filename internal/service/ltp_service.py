#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/12/1 21:57
@Author : sunxiaojie
@File   : ltp_service.py
"""
import os
from collections import Counter

from ltp import LTP

from internal.entity.stopwords_entity import STOPWORD



class LtpService:
    """LTP 分词 + 关键词提取服务（推理经线程池桥接）"""

    def __init__(self):
        """构造函数：加载停用词和分词模型"""
        self.stopwords = set(STOPWORD)

        cache_dir = os.path.join(os.getcwd(), "internal", "core", "ltp")

        if not os.path.isdir(cache_dir) or not os.listdir(cache_dir):
            raise RuntimeError(f"LTP 本地模型不存在，请提前下载并放入: {cache_dir}")

        self.ltp = LTP(cache_dir=cache_dir)

    def extract_keywords(self, text: str, max_keyword_pre_chunk: int = 10) -> list[str]:
        """根据输入文本提取关键词列表"""

        output = self.ltp.pipeline([text], tasks=["cws"])
        words = output.cws[0]

        # 停用词过滤（剔除停用词且长度大于1的词）
        words = [w for w in words if w not in self.stopwords and len(w.strip()) > 1]

        # 简单词频统计作为关键词
        counter = Counter(words)
        most_common = counter.most_common(max_keyword_pre_chunk)
        keywords = [word for word, _ in most_common]

        return keywords