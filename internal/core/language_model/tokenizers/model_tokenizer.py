#!/usr/bin/env python
"""
@Time    : 2026/10/4
@Author  : sunxiaojie
@File    : model_tokenizer.py

按 model_id 选**官方** token 计数口径。

为什么按模型而不是按 provider：provider 目录只说明请求走哪种协议，不决定分词器。
本机 system_config 里 qwen3/local_llm 挂的实际是 `openai/gpt-oss-20b MXFP4`，
它的官方分词器是 o200k_harmony（tiktoken 自带），给它套 Qwen 词表反而是新的错。

口径优先级：
 1) 随仓库分发的官方词表（tokenizers/<family>/tokenizer.json，目前只有 deepseek）
 2) tiktoken 的官方模型映射（gpt-4o→o200k_base、gpt-4/3.5→cl100k_base、gpt-oss→o200k_harmony）
 3) 前两条都没有时退回 cl100k_base 估算（明确是估算，不是官方数）

历史上只有第 3 档且写死：对中文比 DeepSeek 官方词表多算 47%，会让历史裁剪提前丢弃约 46%
的上下文（241 条真实消息实测 235 条 vs 127 条）。UTF-8 字节长度那一档（实测 3.81 倍）已删除。
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_TOKENIZER_DIR = Path(__file__).parent

# 模型名里的关键字 -> 随仓库分发的官方词表目录（目录内需有 tokenizer.json；缺失即视为该口径不可用）
# 用"包含"而不是"前缀"：本机模型名形如 qwen/qwen3.8-27b、qwen_qwen3.5-27b，前缀匹配不上。
_VENDORED_FAMILIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("deepseek",), "deepseek"),
    # Qwen3.5/3.6/3.8 是 248,044(+276) 的新分词器；Qwen3 系（qwen3-coder 等）是 151,643，不同族
    (("qwen3.5", "qwen3.6", "qwen3.8"), "qwen35"),
)

_vendored_cache: dict[str, object | None] = {}
_vendored_failed: set[str] = set()

# llama.cpp / LM Studio 一类端点会把模型写成 "openai/gpt-oss-20b MXFP4"：
# 前缀是协议名、后缀是量化标记，两者都不属于模型名，不去掉就映射不到官方编码
_QUANT_SUFFIX_RE = re.compile(r"\s+[-+]?(?:MXFP4|MXFP8|NF4|Q[2-8](?:_[0-9A-Za-z]+)?|FP16|BF16|INT[48])\s*$", re.I)


def normalize_model_name(model_name: str) -> str:
    """剥掉协议前缀与量化后缀，返回可用于官方映射的模型名。"""
    name = (model_name or "").strip()
    if "/" in name:
        name = name.rsplit("/", 1)[-1].strip()
    name = _QUANT_SUFFIX_RE.sub("", name).strip()
    return name.lower()


def _vendored_tokenizer(family: str):
    """加载 tokenizers/<family>/tokenizer.json；未分发或加载失败返回 None（只试一次）。

    顺带把同目录 `tokenizer_config.json` 里的 `chat_template` 挂上——服务端计的是"整条请求"
    （模板 + 每轮 role 标记），只算正文会少算一大截（本机 qwen3.8-27b 实测：正文 7、
    整条请求 59）。transformers 5 需要在构造后显式赋值，构造参数里传不进去。
    """
    if family in _vendored_cache:
        return _vendored_cache[family]
    tokenizer = None
    if family not in _vendored_failed:
        try:
            import json

            from transformers import PreTrainedTokenizerFast

            candidate = PreTrainedTokenizerFast(
                tokenizer_file=str(_TOKENIZER_DIR / family / "tokenizer.json")
            )
            # 自检：慢速实现/错文件会静默返回空，这里挡住（DeepSeek 官方样例 [19923, 3]）
            if not list(candidate.encode("Hello!")):
                raise RuntimeError("分词器对 'Hello!' 返回空，视为不可用")
            config_path = _TOKENIZER_DIR / family / "tokenizer_config.json"
            if config_path.exists():
                template = json.loads(config_path.read_text(encoding="utf-8")).get("chat_template") or ""
                candidate.chat_template = template
            tokenizer = candidate
            logger.info(
                "官方分词器已加载 family=%s vocab=%s 模板=%s",
                family, tokenizer.vocab_size, "有" if getattr(tokenizer, "chat_template", "") else "无",
            )
        except Exception as exc:  # noqa: BLE001
            _vendored_failed.add(family)
            logger.warning("官方分词器不可用 family=%s：%s", family, exc)
    _vendored_cache[family] = tokenizer
    return tokenizer


def _resolve_vendored(model: str):
    """按模型名找到随仓库分发的官方分词器；没有则 None。"""
    for needles, family in _VENDORED_FAMILIES:
        if any(needle in model for needle in needles):
            return _vendored_tokenizer(family)
    return None


def _count_with_vendored(model: str, text: str) -> int | None:
    tokenizer = _resolve_vendored(model)
    if tokenizer is None:
        return None
    try:
        return len(tokenizer.encode(text))
    except Exception as exc:  # noqa: BLE001
        logger.warning("官方分词器编码失败 model=%s：%s", model, exc)
        return None


def _count_with_tiktoken(model: str, text: str) -> int | None:
    """tiktoken 的官方模型映射；只用于 OpenAI 系模型（其它家的模型名它认不出）。"""
    if not model.startswith(("gpt-", "o1", "o3", "o4", "chatgpt", "text-embedding", "davinci", "babbage", "whisper")):
        return None
    try:
        import tiktoken

        return len(tiktoken.encoding_for_model(model).encode(text))
    except Exception as exc:  # noqa: BLE001
        logger.warning("tiktoken 官方映射失败 model=%s：%s", model, exc)
        return None


def count_tokens_for_model(model_name: str, text: str) -> int | None:
    """按官方口径统计文本 token 数；官方口径全都没有时退回 cl100k_base 估算。

    顺序：随仓库分发的官方词表 > tiktoken 的官方模型映射 > cl100k_base 兜底。
    兜底档对中文会多算（同一份真实语料实测比 DeepSeek 官方多 47%），所以只在没有任何
    官方口径时用；UTF-8 字节长度那一档（实测 3.81x）已删除，不再回来。
    """
    model = normalize_model_name(model_name)
    if not model:
        return None
    if not text:
        return 0
    count = _count_with_vendored(model, text)
    if count is not None:
        return count
    count = _count_with_tiktoken(model, text)
    if count is not None:
        return count
    import tiktoken

    return len(tiktoken.get_encoding("cl100k_base").encode(text))


def count_chat_tokens_for_model(model_name: str, messages: list[dict]) -> int | None:
    """按官方 chat 模板统计**整条请求**的 token 数（含每轮 role 标记、BOS 等）。

    服务端的 prompt_tokens 计的就是这个：本机 qwen3.8-27b 实测模板渲染后编码 59，
    LM Studio 返回的 prompt_tokens 也是 59；只算正文是 7，差 52 全在模板上。
    没有官方词表或词表里没带模板时返回 None，调用方退回正文口径。
    """
    tokenizer = _resolve_vendored(normalize_model_name(model_name))
    if tokenizer is None or not getattr(tokenizer, "chat_template", ""):
        return None
    try:
        rendered = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        if isinstance(rendered, list):  # 少数版本返回 list[str]
            rendered = "".join(rendered)
        # add_special_tokens=False：模板已把特殊符写成字面量，再让分词器补一次会重复计数
        return len(tokenizer.encode(rendered, add_special_tokens=False))
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat 模板计数失败 model=%s，退回正文口径：%s", model_name, exc)
        return None
