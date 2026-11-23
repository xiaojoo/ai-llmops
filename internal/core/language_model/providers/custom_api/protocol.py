from internal.core.language_model.providers.custom_api.models import (
    ALL_PROTOCOLS, MODEL_PROTOCOL_OPENAI, MODEL_PROTOCOL_RESPONSES, MODEL_PROTOCOL_ANTHROPIC, CUSTOM_API_PROVIDER,
)

ALLOWED_FEATURES = {"tool_call", "agent_thought", "image_input"}

# 供前端下拉
PROTOCOL_OPTIONS = [
    {"label": "OpenAI", "value": MODEL_PROTOCOL_OPENAI},
    {"label": "Responses", "value": MODEL_PROTOCOL_RESPONSES},
    {"label": "Anthropic", "value": MODEL_PROTOCOL_ANTHROPIC},
]
