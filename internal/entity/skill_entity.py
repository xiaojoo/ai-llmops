#!/usr/bin/env python
"""
@Time    : 2026/3/20 19:04
@Author  : sunxiaojie
@File    : skill_entity.py
"""
import re
from pathlib import Path

from pydantic import BaseModel, Field

SKILLS_ROOT = Path("skills")

FRONTMATTER_RE = re.compile(r"^---\s*\n(?P<fm>.*?)\n---\s*\n", re.DOTALL)

class SkillInput(BaseModel):
    query: str = Field(description="用户的输入内容")