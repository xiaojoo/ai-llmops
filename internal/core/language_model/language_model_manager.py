#!/usr/bin/env python
"""
@Time    : 2026/1/15 22:36
@Author  : sunxiaojie
@File    : language_model_manager.py
"""
import os
from typing import Awaitable, Callable

import yaml
from pydantic import BaseModel, Field, model_validator

from ...exception import NotFoundException
from .entities.model_entity import BaseLanguageModel, ModelType
from .entities.provider_entity import Provider, ProviderEntity
from .providers.custom_api.models import CUSTOM_API_PROVIDER


class LanguageModelManager(BaseModel):
    """语言模型管理器"""
    provider_map: dict[str, Provider] = Field(default_factory=dict)  # 服务提供者映射

    # 按账号懒加载自定义模型的异步回调：`(account_id) -> Awaitable[list[ApiLlmModel]]`
    custom_model_loader: Callable[[str], Awaitable[list]] | None = Field(default=None, exclude=True)
    # 已懒合并的账号（每个账号只构建一次 custom_api provider）
    _merged_account: str | None = None

    # @root_validator(pre=False)
    # def validate_language_model_manager(cls, values: Dict[str, Any]) -> Dict[str, Any]:
    #     """使用pydantic提供的预设规则校验提供者映射，完成语言模型管理器的初始化"""
    #     # 1.获取当前类所在的路径
    #     current_path = os.path.abspath(__file__)
    #     providers_path = os.path.join(os.path.dirname(current_path), "providers")
    #     providers_yaml_path = os.path.join(providers_path, "providers.yaml")
    #
    #     # 2.读取providers.yaml数据配置获取提供者列表
    #     with open(providers_yaml_path, encoding="utf-8") as f:
    #         providers_yaml_data = yaml.safe_load(f)
    #
    #     # 3.循环读取服务提供者数据并配置模型信息
    #     values["provider_map"] = {}
    #     for index, provider_yaml_data in enumerate(providers_yaml_data):
    #         # 4.获取提供者实体数据结构，并构建服务提供者实体
    #         provider_entity = ProviderEntity(**provider_yaml_data)
    #         values["provider_map"][provider_entity.name] = Provider(
    #             name=provider_entity.name,
    #             position=index + 1,
    #             provider_entity=provider_entity,
    #         )
    #
    #     return values

    @model_validator(mode="after")
    def validate_language_model_manager(self) -> "LanguageModelManager":
        """使用 pydantic 校验完成后初始化服务提供者映射"""

        # 1. 获取当前类所在路径
        current_path = os.path.abspath(__file__)
        providers_path = os.path.join(os.path.dirname(current_path), "providers")
        providers_yaml_path = os.path.join(providers_path, "providers.yaml")

        # 2. 读取 providers.yaml
        with open(providers_yaml_path, encoding="utf-8") as f:
            providers_yaml_data = yaml.safe_load(f)

        # 3. 初始化 provider_map
        self.provider_map = {}

        for index, provider_yaml_data in enumerate(providers_yaml_data):
            provider_entity = ProviderEntity(**provider_yaml_data)

            self.provider_map[provider_entity.name] = Provider(
                name=provider_entity.name,
                position=index + 1,
                provider_entity=provider_entity,
            )

        return self

    def get_provider(self, provider_name: str) -> Provider | None:
        """根据传递的提供者名字获取提供者"""
        provider = self.provider_map.get(provider_name, None)
        if provider is None:
            raise NotFoundException("该模型提供者名字不存在")
        return provider

    async def merge_account_custom_models(self, account_id: str) -> None:
        """按账号懒构建并合并 custom_api provider 进 provider_map（每个账号只构建一次）。

        若未注入 custom_model_loader，或该账号已合并，则直接 no-op。
        """
        if self.custom_model_loader is None:
            return
        if self._merged_account == account_id:
            return

        records = await self.custom_model_loader(account_id)
        if not records:
            # 无自定义记录时不注入 custom_api provider：模型选择器不应出现空分组（spec 5）。
            # 仍标记已合并，避免同请求内重复查询。
            self._merged_account = account_id
            return
        from .providers.custom_api.merger import build_custom_provider

        self.provider_map[CUSTOM_API_PROVIDER] = build_custom_provider(records)
        self._merged_account = account_id

    async def get_provider_async(
            self,
            provider_name: str,
            account_id: str | None = None,
    ) -> Provider | None:
        """异步获取 provider；对 custom_api 且提供了 account_id 时先按账号懒合并。

        get_provider 为同步（不触发合并），本方法供异步上下文使用。
        """
        if (
                provider_name == CUSTOM_API_PROVIDER
                and self.custom_model_loader is not None
                and account_id is not None
        ):
            await self.merge_account_custom_models(account_id)
        return self.provider_map.get(provider_name)

    def get_providers(self) -> list[Provider]:
        """获取所有提供者列表信息"""
        return list(self.provider_map.values())

    def get_model_class_by_provider_and_type(
            self,
            provider_name: str,
            model_type: ModelType,
    ) -> type[BaseLanguageModel] | None:
        """根据传递的提供者名字+模型类型，获取模型类"""
        provider = self.get_provider(provider_name)

        return provider.get_model_class(model_type)

    def get_model_class_by_provider_and_model(
            self,
            provider_name: str,
            model_name: str,
    ) -> type[BaseLanguageModel] | None:

        """根据传递的提供者名字+模型名字获取模型类"""
        # 1.根据名字获取提供者信息
        provider = self.get_provider(provider_name)

        # 2.在提供者下获取该模型实体
        model_entity = provider.get_model_entity(model_name)

        # 3.按模型实体分发模型类（custom_api 走 custom_model_class_provider 按协议分发；
        #    静态 provider 无 resolver，传 model_entity 为 no-op）
        return provider.get_model_class(model_entity.model_type, model_entity=model_entity)

    def resolve_model_config_display(
            self,
            provider_name: str,
            model_name: str,
    ) -> dict[str, str] | None:
        """把应用/会话存储的 provider/model 内部 key 解析为界面显示名。

        返回 {"provider_label", "model_label"}；内部 key 解析不到（提供者/模型
        不在目录中）时返回 None，调用方回退显示原始 key。规则：
        - provider_label：providers.yaml 的展示名（如本地端点 →「本地离线模型」）；
        - model_label：默认取模型 yaml 的 label；若模型声明了 metadata.model_name_env
          （如本地端点 → LOCAL_LLM_MODEL），则优先取该环境变量的实际值，与请求真正
          携带的 model 一致（用户改 /settings 模型名后，应用列表/详情同步变化）。
        """
        provider = self.provider_map.get(provider_name)
        if provider is None:
            return None
        model_entity = provider.model_entity_map.get(model_name)
        if model_entity is None:
            return None

        provider_label = provider.provider_entity.label or provider_name
        model_label = model_entity.label or model_name

        env_key = model_entity.metadata.get("model_name_env") if model_entity.metadata else None
        if env_key:
            model_label = os.getenv(env_key) or model_label

        return {"provider_label": provider_label, "model_label": model_label}
