#!/usr/bin/env python
"""
@Time    : 2026/5/20
@File    : build_chat_history_doc.py

把 DSH 会话日志（session.jsonl.zstd）中的历史对话提取为 Markdown 文档，
用于知识库检索测试。

用法：
    python scripts/build_chat_history_doc.py [--out 输出路径] [--max-turns N]
"""
import argparse
import json
from pathlib import Path

import zstandard


def load_session_lines(path: str) -> list[dict]:
    """解压 zstd 会话日志并逐行解析 JSON"""
    dctx = zstandard.ZstdDecompressor()
    with open(path, "rb") as f:
        data = dctx.stream_reader(f).read()
    objects = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            objects.append(json.loads(line))
        except Exception:
            continue
    return objects


def extract_text(content) -> str:
    """从 user/message 的 content 结构中提取文本"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "image_url":
                    parts.append("[图片]")
        return "\n".join(p for p in parts if p)
    return str(content)


def extract_assistant_text(content) -> str:
    """从 assistant/message 的 content 中提取文本（兼容 str / list / dict / None）"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                t = item.get("type")
                if t == "text":
                    parts.append(item.get("text", ""))
                elif t == "tool_use":
                    parts.append(f"[工具调用: {item.get('name', '')}]")
                elif t == "thinking":
                    parts.append(f"[思考: {item.get('text', '')}]")
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        if "text" in content:
            return content["text"]
        return json.dumps(content, ensure_ascii=False)
    return str(content)


# 系统注入噪音片段（非真实对话内容）
NOISE_MARKERS = [
    "Current DSH file policy:",
    "Approval policy: ask.",
    "Current runtime context.",
    "This snapshot supersedes earlier",
    "You are interacting with the user through the DeepSeek Harness Web GUI",
    "Paths prefixed with @ are files explicitly referenced",
    "The DeepSeek Harness implementation checkout is at",
]


def is_noise(text: str) -> bool:
    """判断是否为系统注入的噪音内容"""
    t = text.strip()
    if not t:
        return True
    if t in ("null", "None", "undefined"):
        return True
    return any(marker in t for marker in NOISE_MARKERS)


def main() -> None:
    parser = argparse.ArgumentParser(description="从会话日志构建对话 Markdown 文档")
    parser.add_argument(
        "--session",
        default=r"C:\Users\XIAOJOO\.dsh\sessions\--H-ai-code-llmops--\session-f868ca80-f2b8-4aff-9398-b4e366052e8a\session.jsonl.zstd",
        help="会话日志 zstd 路径",
    )
    parser.add_argument("--out", default="scripts/_chat_history.md", help="输出 Markdown 路径")
    parser.add_argument("--max-turns", type=int, default=0, help="最多提取多少轮对话（0=全部）")
    args = parser.parse_args()

    objects = load_session_lines(args.session)
    print(f"解析 {len(objects)} 条记录")

    # 按 seq 排序（会话记录有序，但保险起见按顺序遍历）
    turns = []  # [(user_text, assistant_text)]
    current_user = None
    assistant_parts = []

    for obj in objects:
        t = obj.get("type")
        if t == "user/message":
            # 保存上一轮
            if current_user is not None:
                turns.append((current_user, "\n".join(assistant_parts)))
            current_user = extract_text(obj.get("data", {}).get("content"))
            assistant_parts = []
        elif t == "assistant/message":
            d = obj.get("data", {})
            # 内容在 data.message 里
            message = d.get("message") or {}
            text = extract_assistant_text(message.get("content") if isinstance(message, dict) else message)
            if text:
                assistant_parts.append(text)

    # 收尾
    if current_user is not None:
        turns.append((current_user, "\n".join(assistant_parts)))

    # 过滤噪音轮次（系统上下文 / 空内容）
    clean_turns = [
        (u, a) for u, a in turns
        if not is_noise(u) and not (is_noise(u) and is_noise(a))
    ]

    if args.max_turns > 0:
        clean_turns = clean_turns[-args.max_turns:]

    print(f"提取 {len(turns)} 轮，过滤噪音后 {len(clean_turns)} 轮")

    # 生成 Markdown
    lines = [
        "# 历史对话记录（知识库检索测试用）",
        "",
        "> 本文档由系统会话日志自动生成，用于 RAG 检索测试。",
        "",
    ]
    kept = 0
    for i, (user_text, assistant_text) in enumerate(clean_turns, 1):
        # 跳过用户提问但助手完全没回复的轮次（无检索价值）
        if not assistant_text.strip():
            continue
        kept += 1
        lines.append(f"## 第 {kept} 轮对话")
        lines.append("")
        lines.append("### 用户")
        lines.append("")
        lines.append(user_text.strip())
        lines.append("")
        lines.append("### 助手")
        lines.append("")
        lines.append(assistant_text.strip())
        lines.append("")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"已写入: {out_path} ({out_path.stat().st_size} bytes, {kept} 轮有效对话)")


if __name__ == "__main__":
    main()
