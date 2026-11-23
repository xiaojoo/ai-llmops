#!/usr/bin/env python
"""
@Time    : 2026/1/15 21:29
@Author  : sunxiaojie
@File    : model_entity.py
"""
from abc import ABC
from enum import Enum
from typing import Any, ClassVar

from langchain_core.language_models import BaseLanguageModel as LCBaseLanguageModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from internal.core.language_model.tokenizers.model_tokenizer import (
    count_chat_tokens_for_model,
    count_tokens_for_model,
)


class DefaultModelParameterName(str, Enum):
    """默认的参数名字，一般是所有LLM都有的一些参数"""
    TEMPERATURE = "temperature"  # 温度
    TOP_P = "top_p"  # 核采样率
    PRESENCE_PENALTY = "presence_penalty"  # 存在惩罚
    FREQUENCY_PENALTY = "frequency_penalty"  # 频率惩罚
    MAX_TOKENS = "max_tokens"  # 要生成的内容的最大tokens数


class ModelType(str, Enum):
    """模型类型枚举"""
    CHAT = "chat"  # 聊天模型
    COMPLETION = "completion"  # 文本生成模型


class ModelParameterType(str, Enum):
    """模型参数类型"""
    FLOAT = "float"
    INT = "int"
    STRING = "string"
    BOOLEAN = "boolean"


class ModelParameterOption(BaseModel):
    """模型参数选项配置模型"""
    label: str  # 配置选项标签
    value: Any  # 配置选项对应的值


class ModelParameter(BaseModel):
    """模型参数实体信息"""
    name: str = ""  # 参数名字
    label: str = ""  # 参数标签
    type: ModelParameterType = ModelParameterType.STRING  # 参数类型
    help: str = ""  # 帮助信息
    required: bool = False  # 是否必填
    default: Any | None = None  # 默认参数值
    min: float | None = None  # 最小值
    max: float | None = None  # 最大值
    precision: int = 2  # 保留小数的位数
    options: list[ModelParameterOption] = Field(default_factory=list)  # 可选的参数配置


class ModelFeature(str, Enum):
    """模型特性，用于标记模型支持的特性信息，涵盖工具调用、智能体推理、图片输入"""
    TOOL_CALL = "tool_call"  # 工具调用
    AGENT_THOUGHT = "agent_thought"  # 是否支持智能体推理，一般要求参数量比较大，能回答通用型任务
    IMAGE_INPUT = "image_input"  # 图片输入，多模态大语言模型


class ModelEntity(BaseModel):
    """语言模型实体，记录模型的相关信息"""
    model_name: str = Field(default="", alias="model")  # 模型名字，使用model作为别名
    label: str = ""  # 模型标签
    model_type: ModelType = ModelType.CHAT  # 模型类型
    features: list[ModelFeature] = Field(default_factory=list)  # 模型特征信息
    context_window: int = 0  # 上下文窗口长度(输入+输出的总长度)
    max_output_tokens: int = 0  # 最大输出内容长度(输出)
    attributes: dict[str, Any] = Field(default_factory=dict)  # 模型固定属性字典
    parameters: list[ModelParameter] = Field(default_factory=list)  # 模型参数字段规则列表，用于记录模型的配置参数
    metadata: dict[str, Any] = Field(default_factory=dict)  # 模型元数据，用于存储模型的额外数据，例如价格、词表等等信息


class BaseLanguageModel(LCBaseLanguageModel, ABC):
    """基础语言模型"""
    temperature: float | None = Field(default=1.0)
    max_tokens: int | None = Field(default=8192)
    features: list[ModelFeature] = Field(default_factory=list)  # 模型特性
    metadata: dict[str, Any] = Field(default_factory=dict)  # 模型元数据信息
    context_window: int | None = Field(
        default=None,
        description="模型上下文窗口长度(输入+输出总长度)，用于上下文预算计算；为 None 时表示未知",
    )

    def get_pricing(self) -> tuple[float, float, float]:
        """获取LLM对应的价格信息，返回数据格式为(输入价格、输出价格、单位)"""
        # 1、计算获取输入价格、输出价格、单位
        input_price = self.metadata.get("pricing", {}).get("input", 0.0)
        output_price = self.metadata.get("pricing", {}).get("output", 0.0)
        unit = self.metadata.get("pricing", {}).get("unit", 0.0)

        # 2、返回数据
        return input_price, output_price, unit

    # 图片 token 估算常量：OpenAI 近似单张图 token 开销
    IMAGE_TOKEN_ESTIMATE: ClassVar[int] = 1100

    @staticmethod
    def _count_image_blocks(messages: list[Any]) -> int:
        """统计消息列表中 image_url 内容块数量"""
        count = 0
        for m in messages:
            content = getattr(m, "content", None)
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "image_url":
                        count += 1
        return count

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        """提取消息内容中的文本部分：兼容纯字符串与多模态块列表（只取 text 块）"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts)
        return ""

    @staticmethod
    def _response_usage(response: Any) -> dict:
        """从响应里取官方 usage。

        优先 usage_metadata（langchain 归一化后的），其次 response_metadata.token_usage
        （部分 provider 只填原始字段）。传入分块列表时从后往前找——usage 只在最后一个块上。
        """
        items = response if isinstance(response, list) else [response]
        for item in reversed(items):
            usage = getattr(item, "usage_metadata", None)
            if usage:
                return dict(usage)
            raw = (getattr(item, "response_metadata", None) or {}).get("token_usage") or {}
            if raw:
                return {
                    "input_tokens": raw.get("prompt_tokens"),
                    "output_tokens": raw.get("completion_tokens"),
                }
        return {}

    def count_round_usage(
            self, input_messages: list[Any], response: Any,
    ) -> tuple[int | None, int | None]:
        """这一轮的 (输入 token, 输出 token)。

        口径优先级：**响应里的官方 usage > 官方分词器本地估算 > None**。
        usage 是服务端实际计费数字，比任何本地估算都准；拿不到才退回本地分词器；
        两者都没有时返回 None（调用方按"不知道"处理，不得再用 cl100k/字节兜底）。
        """
        usage = self._response_usage(response)
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if input_tokens is None:
            input_tokens = self.get_num_tokens_safe(input_messages)
        if output_tokens is None:
            output_tokens = self.get_num_tokens_safe([response] if not isinstance(response, list) else response)
        return input_tokens, output_tokens

    @staticmethod
    def _as_chat_messages(messages: list[Any]) -> list[dict] | None:
        """转成 [{"role","content"}] 供官方 chat 模板渲染；有一条转不动就整体返回 None。

        宁可退回正文口径，也不要把 role 猜错——role 错了模板渲染出来的结构和真实请求不一样。
        """
        role_map = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}
        out: list[dict] = []
        for m in messages:
            if isinstance(m, str):
                out.append({"role": "user", "content": m})
                continue
            content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", None)
            if content is None:
                return None
            raw_role = (m.get("role") or m.get("type")) if isinstance(m, dict) else getattr(m, "type", "")
            role = role_map.get(str(raw_role or ""), str(raw_role or ""))
            if role not in ("user", "assistant", "system", "tool"):
                return None
            out.append({"role": role, "content": content})
        return out or None

    def get_num_tokens_safe(self, messages: list[Any]) -> int | None:
        """按模型官方口径统计 token 数；没有官方口径时退回 cl100k_base 估算。

        优先按**整条请求**算（官方词表 + 官方 chat 模板），因为服务端计的就是这个：
        本机 qwen3.8-27b 实测整条请求 59 token，只算正文是 7，差的 52 全在模板上。
        没有官方词表/模板的模型退回正文口径，再没有就落 cl100k 兜底
        （159 条真实消息实测：兜底档比 DeepSeek 官方多算 47.8%、比 Qwen 官方多算 42.7%，
        且不含模板开销，所以只是粗略值）。
        计费不吃这些估算——那部分走 count_round_usage 里的响应 usage。

        多模态消息里的图片按固定 token 估算（IMAGE_TOKEN_ESTIMATE）。
        """
        try:
            # 1、提取文本内容（兼容字符串列表 / 消息字典列表 / LangChain消息对象列表）
            if all(isinstance(m, str) for m in messages):
                text = "\n".join(messages)
            else:
                text = "\n".join(
                    self._extract_text_content(
                        m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
                    )
                    for m in messages
                )
            image_tokens = self._count_image_blocks(messages) * self.IMAGE_TOKEN_ESTIMATE

            # 2、整条请求口径（官方词表 + 官方模板）
            model_name = getattr(self, "model_name", "") or ""
            chat_messages = self._as_chat_messages(messages)
            if chat_messages:
                request_tokens = count_chat_tokens_for_model(model_name, chat_messages)
                if request_tokens is not None:
                    return request_tokens + image_tokens

            # 3、正文口径
            text_tokens = count_tokens_for_model(model_name, text)
            if text_tokens is None:
                return None

            # 4、叠加图片固定 token
            return text_tokens + image_tokens
        except (TypeError, ValueError):
            return None

    # def convert_to_human_message(self, query: str, image_urls: list[str] = None) -> HumanMessage:
    #     """将传递的query+image_url转换成人类消息HumanMessage，如果没有传递image_url或者该LLM不支持image_input输入"""
    #     # 1、判断图片url是否为空，或者该LLM不支持图片输入，则直接返回普通消息
    #     if image_urls is None or len(image_urls) == 0 or ModelFeature.IMAGE_INPUT not in self.features:
    #         return HumanMessage(content=query)
    #
    #     # 2、存在图片输入并且支持多模态输入，则按照OpenAI规则转换成人类消息，如果模型有差异则直接继承重写
    #     # 链接：https://python.langchain.com/docs/how_to/multimodal_inputs/
    #     return HumanMessage(content=[
    #         {"type": "text", "text": query},
    #         *[{"type": "image_url", "image_url": {"url": image_url}} for image_url in image_urls],
    #     ])

    def convert_to_human_message(self, query: str, image_urls: list[str] | None = None) -> HumanMessage:
        """强制构建多模态消息，跳过特性检查"""
        if image_urls and isinstance(image_urls, list) and len(
                image_urls) > 0 and ModelFeature.IMAGE_INPUT in self.features:
            content_list = []

            for url in image_urls:
                # 过滤掉空字符串
                if url and isinstance(url, str):
                    content_list.append({
                        "type": "image_url",
                        "image_url": {"url": url}
                    })

            content_list.append({
                "type": "text",
                "text": query
            })

            return HumanMessage(content=content_list)

        return HumanMessage(content=query)


def build_structured_output_llm(llm: "BaseLanguageModel", schema: type[BaseModel], *, method: str | None = None):
    """统一结构化输出：显式指定 method，避免不同 provider 的 response_format 行为差异。

    - 模型声明 TOOL_CALL 特性 → function_calling（走 tools 参数，不依赖 response_format）；
    - 否则 → json_mode（json_object），调用方提示词需包含 "json" 字样；
    - 显式传入 method 时优先使用。
    """
    if method is None:
        method = "function_calling" if ModelFeature.TOOL_CALL in llm.features else "json_mode"
    return llm.with_structured_output(schema, method=method)
