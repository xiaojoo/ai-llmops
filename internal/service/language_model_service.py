#!/usr/bin/env python
"""
@Time    : 2026/1/17 16:23
@Author  : sunxiaojie
@File    : language_model_service.py
"""
import mimetypes
import os
from dataclasses import dataclass
from typing import Any

from anyio import to_thread
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from internal.config.settings import get_settings
from internal.core.language_model import LanguageModelManager
from internal.core.language_model.entities.model_entity import BaseLanguageModel
from internal.core.language_model.providers.custom_api.models import CUSTOM_API_PROVIDER
from internal.exception import NotFoundException

from .base_service import BaseService

# 移除共享 anyio CapacityLimiter——多线程各自 asyncio.run 新 loop 共享同一
# limiter 会死锁（首个绑定 loop 的线程挂死），改 asyncio.to_thread。
async def _infer(sync_fn, *args):
    """同步模型调用经线程池桥接（避免跨 loop 死锁）。"""
    import asyncio
    return await asyncio.to_thread(sync_fn, *args)


def _usage_kwargs(model_class: type) -> dict:
    """让流式响应带回 usage，才能"以响应 usage 为准"记账。

    OpenAI 兼容端点的 SSE 默认**不返回** usage，必须带 stream_options.include_usage
    （langchain 侧就是 stream_usage=True）；不支持该字段的模型类（如 ChatAnthropic，
    usage 本来就在 message_start/delta 里）自动跳过。
    """
    return {"stream_usage": True} if "stream_usage" in getattr(model_class, "model_fields", {}) else {}


def _load_default_sync(language_model_manager: LanguageModelManager) -> BaseLanguageModel:
    """加载默认的大语言模型（同步核心）：模型管理器中获取不到模型或者出错时使用默认模型兜底。"""
    # return ChatDeepSeek(model="deepseek-v4-flash", temperature=1, max_tokens=8192)

    # 1、获取deepseek服务提供者与模型类
    provider = language_model_manager.get_provider("deepseek")
    model_entity = provider.get_model_entity("deepseek-v4-flash")
    model_class = provider.get_model_class(model_entity.model_type)

    # 2、实例化模型并返回
    return model_class(
        **model_entity.attributes,
        **_usage_kwargs(model_class),
        temperature=1,
        max_tokens=8192,
        context_window=model_entity.context_window,
        features=model_entity.features,
        metadata=model_entity.metadata,
    )


@dataclass
class LanguageModelService(BaseService):
    """语言模型服务（模型加载走线程池桥接）"""
    db: AsyncSession
    language_model_manager: LanguageModelManager

    async def get_language_models(self, account_id: str | None = None) -> list[dict[str, Any]]:
        # 获取LLMops项目中的所有模型列表信息
        # 0. 若提供账号，先按账号懒合并 custom_api（使其分组出现在列表中）。
        #    merge_account_custom_models 在未注入 custom_model_loader 或该账号已合并时 no-op，
        #    因此无账号（account_id=None）时不合并——custom_api 不会凭空出现在列表中。
        if account_id is not None:
            await self.language_model_manager.merge_account_custom_models(account_id)

        # 1. 调用语言模型管理器获取提供商列表
        providers = self.language_model_manager.get_providers()

        # 2. 构建语言模型列表，循环读取数据
        language_models = []
        for provider in providers:
            # 3. 获取提供商实体和模型实体列表
            provider_entity = provider.provider_entity
            model_entities = provider.get_model_entities()

            # 4. 构建响应字典结构
            language_model = {
                "name": provider_entity.name,
                "position": provider_entity.position,
                "label": provider_entity.label,
                "icon": provider_entity.icon,
                "description": provider_entity.description,
                "background": provider_entity.background,
                "support_model_types": provider_entity.supported_model_types,
                "models": [{
                    "model": model_entity.model_name,
                    "label": self._resolve_model_label(provider_entity.name, model_entity),
                    "model_type": model_entity.model_type,
                    "context_window": model_entity.context_window,
                    "max_output_tokens": model_entity.max_output_tokens,
                    "features": model_entity.features,
                    "attributes": self._display_attributes(model_entity),
                    "metadata": model_entity.metadata,
                    "parameters": [
                        {
                            "name": parameter.name,
                            "label": parameter.label,
                            "type": parameter.type.value,
                            "help": parameter.help,
                            "required": parameter.required,
                            "default": parameter.default,
                            "min": parameter.min,
                            "max": parameter.max,
                            "precision": parameter.precision,
                            "options": [{"label": option.label, "value": option.value} for option in parameter.options],
                        } for parameter in model_entity.parameters
                    ],
                } for model_entity in model_entities]
            }
            language_models.append(language_model)

        return language_models

    async def get_language_model(
            self,
            provider_name: str,
            model_name: str,
            account_id: str | None = None,
    ) -> dict[str, Any]:
        # 根据传递的提供者名字+模型名字获取模型详细信息
        # 0. custom_api 为按账号懒合并的虚拟 provider：请求 detail 时若带 account_id，
        #    先按账号合并，使同步 get_provider('custom_api') 能命中（否则 get_provider 抛 NotFound）。
        if provider_name == CUSTOM_API_PROVIDER and account_id is not None:
            await self.language_model_manager.merge_account_custom_models(account_id)

        # 1. 获取提供者+模型实体信息
        provider = self.language_model_manager.get_provider(provider_name)
        if provider is None:
            raise NotFoundException("该服务提供者不存在")

        # 2. 获取模型实体
        model_entity = provider.get_model_entity(model_name)
        if model_entity is None:
            raise NotFoundException("该模型不存在")

        language_model = {
            "model": model_entity.model_name,
            "label": self._resolve_model_label(provider_name, model_entity),
            "model_type": model_entity.model_type,
            "context_window": model_entity.context_window,
            "max_output_tokens": model_entity.max_output_tokens,
            "features": model_entity.features,
            "attributes": self._display_attributes(model_entity),
            "metadata": model_entity.metadata,
            "parameters": [
                {
                    "name": parameter.name,
                    "label": parameter.label,
                    "type": parameter.type.value,
                    "help": parameter.help,
                    "required": parameter.required,
                    "default": parameter.default,
                    "min": parameter.min,
                    "max": parameter.max,
                    "precision": parameter.precision,
                    "options": [{"label": option.label, "value": option.value} for option in parameter.options],
                } for parameter in model_entity.parameters
            ],
        }
        return language_model

    def _display_attributes(self, model_entity: Any) -> dict[str, Any]:
        """序列化给前端的模型 attributes：剔除 api_key，避免把敏感密钥（或密文）暴露到 /language_models。

        api_key 只在 load_language_model 构造真实实例时需要（且已解密），列表/详情响应不返回。
        """
        attributes = dict(model_entity.attributes)
        attributes.pop("api_key", None)
        return attributes

    def _resolve_model_label(self, provider_name: str, model_entity: Any) -> str:
        """模型展示 label：若模型声明 metadata.model_name_env（如本地端点 → LOCAL_LLM_MODEL），
        则该 label 取环境变量实际值；否则用模型 yaml 静态 label。与请求真正携带的 model 一致。"""
        display = self.language_model_manager.resolve_model_config_display(
            provider_name,
            model_entity.model_name,
        )
        if display:
            return display["model_label"]
        return model_entity.label

    async def get_language_model_icon(self, provider_name: str) -> tuple[bytes, str]:
        """根据传递的提供者名字获取提供商对应的图标信息（文件 IO 经 run_in_threadpool 桥接）"""
        # 1. 获取提供者信息
        provider = self.language_model_manager.get_provider(provider_name)
        if provider is None:
            raise NotFoundException("该服务提供者不存在")

        # 2. 获取项目的根路径信息
        root_path = str(get_settings().project_root)

        # 3. 拼接得到提供者所在的文件夹
        provider_path = os.path.join(
            root_path,
            "internal", "core", "language_model", "providers", provider_name,
        )

        # 4. 拼接得到Icon对应的路径
        icon_path = os.path.join(provider_path, "_asset", provider.provider_entity.icon)

        # 5-7. 检测/读取 icon（同步文件 IO 在后台线程执行，不阻塞事件循环）
        return await run_in_threadpool(_read_icon, icon_path)

    async def load_language_model(
            self,
            model_config: dict[str, Any],
            account_id: str | None = None,
    ) -> BaseLanguageModel:
        """根据传递的模型配置加载大语言模型，并返回其实例。

        - custom_api 为按账号懒合并的虚拟 provider：加载前若提供 account_id，先按账号合并，
          使 _load 内同步 get_provider('custom_api') 能命中；
        - langchain 模型构造为同步重活（可能含网络/配置读取），经线程池桥接 +
          同步推理经 asyncio.to_thread 桥接；
        - custom_api 解析失败时**不兜底**默认模型（否则会静默运行 deepseek），直接抛出，
          让误配置的自定义模型显式暴露。
        """
        provider_name = model_config.get("provider", "")
        if provider_name == CUSTOM_API_PROVIDER and account_id is not None:
            await self.language_model_manager.merge_account_custom_models(account_id)

        def _load() -> BaseLanguageModel:
            try:
                # 1. 从model_config中提取出provider、model、parameters
                model_name = model_config.get("model", "")
                parameters = model_config.get("parameters", {})

                # 2. 从模型管理器获取提供者、模型实体、模型类
                provider = self.language_model_manager.get_provider(provider_name)
                model_entity = provider.get_model_entity(model_name)
                # 传入 model_entity：custom_api 的 custom_model_class_provider 需按模型实体
                # metadata["protocol"] 分发模型类；静态 provider 无 resolver，行为不变（no-op）。
                model_class = provider.get_model_class(model_entity.model_type, model_entity=model_entity)

                # 3. 实例化模型后并返回
                return model_class(
                    **model_entity.attributes,
                    **_usage_kwargs(model_class),
                    **parameters,
                    context_window=model_entity.context_window,
                    features=model_entity.features,
                    metadata=model_entity.metadata,
                )

            except Exception:
                # custom_api 解析失败（未合并/无账号错误）时显式抛出，而非静默兜底 deepseek；
                # 静态 provider 仍维持原有兜底行为。
                if provider_name == CUSTOM_API_PROVIDER:
                    raise
                return _load_default_sync(self.language_model_manager)

        return await _infer(_load)

    async def load_default_language_model(self) -> BaseLanguageModel:
        """加载默认的大语言模型（同步构造经线程池桥接）"""
        return await _infer(_load_default_sync, self.language_model_manager)


def _read_icon(icon_path: str) -> tuple[bytes, str]:
    """读取提供者图标（同步文件 IO，供 run_in_threadpool 桥接）"""
    # 5. 检测icon是否存在
    if not os.path.exists(icon_path):
        raise NotFoundException("该模型提供者_asset未提供图标")

    # 6.读取icon的类型
    mimetype, _ = mimetypes.guess_type(icon_path)
    mimetype = mimetype or "application/octet-stream"

    # 7.读取icon的字节数据
    with open(icon_path, "rb") as f:
        return f.read(), mimetype
