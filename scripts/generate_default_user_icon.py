#!/usr/bin/env python
"""
生成默认 user 图标（PNG，200x200）：圆形人形头像 + 圆角蓝底，风格对齐项目内置图标。

运行: venv/Scripts/python scripts/generate_default_user_icon.py
输出: internal/core/builtin_apps/default-user-icon.png
"""
import os
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 200
OUT_PATH = Path(__file__).resolve().parent.parent / "internal" / "core" / "builtin_apps" / "default-user-icon.png"

# 圆角矩形背景（蓝）
BG = (0, 130, 255, 255)      # #0082FF
# 人形剪影（白）
FG = (255, 255, 255, 255)


def rounded_rectangle_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1、圆角蓝底（半径 ~ SIZE*1/6，与现有 SVG 圆角一致）
    draw.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=34, fill=BG)

    # 2、人形：头部圆 + 肩部半圆
    head_center = (SIZE / 2, SIZE * 0.38)
    head_radius = SIZE * 0.16
    draw.ellipse(
        [head_center[0] - head_radius, head_center[1] - head_radius,
         head_center[0] + head_radius, head_center[1] + head_radius],
        fill=FG,
    )
    # 肩部（椭圆下半部分）
    body_center = (SIZE / 2, SIZE * 1.02)
    body_w = SIZE * 0.52
    body_h = SIZE * 0.42
    draw.ellipse(
        [body_center[0] - body_w / 2, body_center[1] - body_h / 2,
         body_center[0] + body_w / 2, body_center[1] + body_h / 2],
        fill=FG,
    )

    # 3、应用圆角蒙版（把人形限制在圆角底内，视觉更干净）
    img = Image.composite(img, Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0)), rounded_rectangle_mask(SIZE, 34))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_PATH, "PNG")
    print(f"已生成: {OUT_PATH} ({os.path.getsize(OUT_PATH)} bytes)")


if __name__ == "__main__":
    main()
