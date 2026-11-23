#!/usr/bin/env python
"""
@Time    : 2025/12/7 15:34
@Author  : sunxiaojie
@File    : cache_entity.py
"""

# 缓存锁过期时间，单位秒，默认600
LOCK_EXPIRE_TIME = 600

# 更新文档启用状态缓存锁
LOCK_DOCUMENT_UPDATE_ENABLE = "lock:document:update:enabled_{document_id}"

# 更新关键词表缓存锁
LOCK_KEYWORD_TABLE_UPDATE_KEYWORD = "lock:keyword_table:update:keyword_table_{dataset_id}"

# 更新片段启用状态缓存锁
LOCK_SEGMENT_UPDATE_ENABLED = "lock:segment:update:enabled_{segment_id}"