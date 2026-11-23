from langchain_openai import ChatOpenAI

from internal.core.language_model.entities.model_entity import BaseLanguageModel
from .models import MODEL_PROTOCOL_OPENAI, MODEL_PROTOCOL_RESPONSES, MODEL_PROTOCOL_ANTHROPIC, ALL_PROTOCOLS

_ANTHROPIC_UNAVAILABLE_MSG = (
    "anthropic protocol requires langchain-anthropic (not installed / dependency conflict with "
    "browser-use); install it without upgrading the anthropic SDK beyond 0.76"
)


def _build_responses_chat() -> type[ChatOpenAI]:
    """基于 ChatOpenAI 的子类，固定 use_responses_api=True（openai Responses API）。"""
    class _ResponsesChat(ChatOpenAI):
        use_responses_api: bool = True
    _ResponsesChat.__name__ = "ResponsesChat"
    return _ResponsesChat


def _build_unavailable_anthropic_chat() -> type[BaseLanguageModel]:
    """langchain-anthropic 不可用时的占位类。

    CONTROLLER RULING：langchain-anthropic 未安装（与 browser-use 的 anthropic SDK 版本冲突，
    被刻意 unpin），因此 protocol=anthropic 分支不在此处崩溃（模块加载期），而是返回一个
    实例化时才抛清晰错误信息的类——让该协议成为干净的「当前不支持」，而非硬崩溃。
    """
    class _UnavailableAnthropicChat(BaseLanguageModel):
        def __init__(self, *args, **kwargs):
            raise RuntimeError(_ANTHROPIC_UNAVAILABLE_MSG)

        def generate_prompt(self, *args, **kwargs):
            raise RuntimeError(_ANTHROPIC_UNAVAILABLE_MSG)

        def agenerate_prompt(self, *args, **kwargs):
            raise RuntimeError(_ANTHROPIC_UNAVAILABLE_MSG)

        def invoke(self, *args, **kwargs):
            raise RuntimeError(_ANTHROPIC_UNAVAILABLE_MSG)

    _UnavailableAnthropicChat.__name__ = "UnavailableAnthropicChat"
    return _UnavailableAnthropicChat


def build_model_class(protocol: str) -> type[BaseLanguageModel]:
    """按协议返回 langchain 聊天类；协议非法抛 ValueError。

    - openai   -> ChatOpenAI
    - responses-> ChatOpenAI 子类，固定 use_responses_api=True
    - anthropic-> 尝试导入 langchain_anthropic.ChatAnthropic；
                  导入失败（未安装/版本冲突）时返回占位类，实例化才抛清晰错误。
    """
    if protocol == MODEL_PROTOCOL_OPENAI:
        return ChatOpenAI
    if protocol == MODEL_PROTOCOL_RESPONSES:
        return _build_responses_chat()
    if protocol == MODEL_PROTOCOL_ANTHROPIC:
        try:
            from langchain_anthropic import ChatAnthropic
        except (ImportError, ModuleNotFoundError):
            return _build_unavailable_anthropic_chat()
        return ChatAnthropic
    raise ValueError(f"未知自定义模型协议: {protocol}")
