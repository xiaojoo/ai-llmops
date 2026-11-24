import os

from internal.core.language_model.entities.model_entity import ModelEntity, ModelFeature, ModelType, ModelParameter
from internal.lib.crypto import build_master_key, decrypt_value

# 自定义模型 provider 常量（保留值）
CUSTOM_API_PROVIDER = "custom_api"
MODEL_PROTOCOL_OPENAI = "openai"
MODEL_PROTOCOL_RESPONSES = "responses"
MODEL_PROTOCOL_ANTHROPIC = "anthropic"
ALL_PROTOCOLS = {MODEL_PROTOCOL_OPENAI, MODEL_PROTOCOL_RESPONSES, MODEL_PROTOCOL_ANTHROPIC}


def _master_key() -> bytes:
    """获取加密主密钥（32 字节）：CONFIG_MASTER_KEY 优先，回退 JWT_SECRET_KEY。"""
    secret = os.getenv("CONFIG_MASTER_KEY") or os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("CONFIG_MASTER_KEY 或 JWT_SECRET_KEY 至少配置一个")
    return build_master_key(secret)


def _to_features(raw: list) -> list[ModelFeature]:
    mapping = {
        "tool_call": ModelFeature.TOOL_CALL,
        "agent_thought": ModelFeature.AGENT_THOUGHT,
        "image_input": ModelFeature.IMAGE_INPUT,
    }
    return [mapping[f] for f in raw if f in mapping]


def build_custom_model_entity(record, model_uuid: str) -> ModelEntity:
    """根据 ApiLlmModel 记录构建 ModelEntity。

    model_name = f"custom_api/{model_uuid}"，attributes 携带 model/base_url/api_key，
    供 load_language_model 构造真实实例。

    注意：ModelEntity.model_name 字段定义的 alias 是 "model"（见 model_entity.py，
    model_name: str = Field(default="", alias="model")），且未开启 populate_by_name，
    因此按本项目 YAML 配置惯例用关键字 `model=`（alias）传入，而非字段名 `model_name=`。
    """
    # ORM 记录（由 CustomLlmModelService.create/_update_record 落库）里的 api_key 是 AES 密文。
    # 在此由同一主密钥解密回明文，供 load_language_model 构造真实模型实例；
    # 空 api_key（''）保持 ''。非真实密文数据（如测试直接构造的明文）解密失败时返回原文。
    raw_api_key = record.api_key or ""
    api_key = decrypt_value(raw_api_key, _master_key()) if raw_api_key else ""

    entity = ModelEntity(
        model=f"{CUSTOM_API_PROVIDER}/{model_uuid}",
        label=record.name,
        model_type=ModelType.CHAT,
        features=_to_features(record.features or []),
        context_window=record.context_window or 0,
        max_output_tokens=record.max_output_tokens or 0,
        attributes={
            "model": record.model_id,
            "base_url": record.base_url or None,
            "api_key": api_key,
        },
        parameters=[],  # 本轮不做采样参数模板
        metadata={
            "protocol": record.protocol,
            "remark": record.remark or "",
            "icon": record.icon or "",
            "provider": CUSTOM_API_PROVIDER,
        },
    )
    return entity
