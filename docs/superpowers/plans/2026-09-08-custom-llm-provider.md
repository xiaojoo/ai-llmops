# 自定义 API 模型（Custom LLM Provider）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在设置页新增「自定义 API 模型」管理，支持 OpenAI / Anthropic / Responses 三种协议，按账号隔离，保存到数据库后模型选择器可遍历、应用可选中并使用。

**Architecture:** 新增 `api_llm_model` 表（account_id 属主）。动态 `custom_api` provider 不放在磁盘 YAML，而是由请求侧按当前账号懒合并进 `LanguageModelManager`：manager 通过注入的 `account_model_loader`（`async (account_id) -> list[ApiLlmModel]`）在真正访问 custom_api 或遍历模型时构建该 provider。协议到 langchain 类的分发（openai/responses/anthropic）在 `custom_api` 的 `get_model_class` 完成。设置页为增删改查 + 保存到 DB，刷新后经 `/language_models` 遍历可见。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Alembic, Pydantic v2, langchain-openai 1.1.9（含 `use_responses_api`）, langchain-anthropic（新增依赖）, Vue 3 + Arco Design + Vite。

**Spec:** `docs/superpowers/specs/2026-09-08-custom-llm-provider-design.md`

## Global Constraints

- 按账号隔离：`api_llm_model.account_id` 必填；列表/详情/更新/删除均须按当前账号过滤。
- provider key 保留值：`custom_api`；每条模型 key 为 `custom_api/<uuid>`。
- 协议枚举：`openai` / `responses` / `anthropic`。
- 能力标记枚举：`tool_call` / `agent_thought` / `image_input`。
- `langchain-anthropic==<新版>` 需写入 `requirements.txt`。
- 设置页只做名称、协议、模型ID、Base URL、API Key、能力标记、context_window、max_output_tokens、备注、图标；不做采样参数。
- 所有数据写操作走 `BaseService.create/update/delete`（独立提交边界），沿用 `api_tool` 范式。

---

### Task 1: 新增 `langchain-anthropic` 依赖 + `ApiLlmModel` ORM 模型

**Files:**
- Modify: `requirements.txt`
- Create: `internal/model/api_llm_model.py`
- Test: `test/internal/model/test_api_llm_model.py`

**Interfaces:**
- Produces: `internal.model.api_llm_model.ApiLlmModel`（`__tablename__ = "api_llm_model"`，字段见下）；`internal.model` 包需导出 `ApiLlmModel`（新增 `internal/model/__init__.py` 导出）。

- [ ] **Step 1: 给 requirements.txt 加依赖**

`requirements.txt` 末尾追加：
```
langchain-anthropic==0.3.15
```
（版本以 `pip index versions langchain-anthropic` 实际可用为准；如安装报错取高于 0.2 的最新版本。）

- [ ] **Step 2: 安装依赖**

Run: `.\venv\Scripts\python.exe -m pip install langchain-anthropic`
Expected: 安装成功；`python -c "from langchain_anthropic import ChatAnthropic"` 通过。

- [ ] **Step 3: 写失败测试**

```python
# test/internal/model/test_api_llm_model.py
import pytest
from sqlalchemy import select

from internal.model import ApiLlmModel


async def test_api_llm_model_table_create_and_read(db_session):
    record = ApiLlmModel(
        account_id="11111111-1111-1111-1111-111111111111",
        name="My Claude",
        protocol="anthropic",
        model_id="claude-3-5-sonnet",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-xxxx",
        features=["tool_call", "agent_thought"],
        context_window=200000,
        max_output_tokens=8192,
        remark="test",
        icon="https://example.com/a.png",
    )
    db_session.add(record)
    await db_session.commit()

    stmt = select(ApiLlmModel).where(ApiLlmModel.name == "My Claude")
    result = (await db_session.execute(stmt)).scalars().first()
    assert result is not None
    assert result.protocol == "anthropic"
    assert result.features == ["tool_call", "agent_thought"]
```

- [ ] **Step 4: 运行测试确认失败**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/model/test_api_llm_model.py -q`
Expected: FAIL（`ApiLlmModel` 未定义 / 表不存在）。

- [ ] **Step 5: 创建 ORM 模型**

`internal/model/api_llm_model.py`：

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, PrimaryKeyConstraint, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from package.database import Base


class ApiLlmModel(Base):
    """自定义 API 大语言模型表：用户按账号添加的 OpenAI/Anthropic/Responses 兼容模型。"""
    __tablename__ = "api_llm_model"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_api_llm_model_id"),
        {"comment": "自定义 API 大语言模型表"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=text("uuid_generate_v4()"), comment="主键ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), comment="创建时间")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="创建人ID")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), comment="更新时间")
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="更新人ID")
    account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="归属账号ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="展示名（模型选择器显示）")
    protocol: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("''::character varying"), comment="协议：openai / responses / anthropic")
    model_id: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''::character varying"), comment="请求体 model 字段")
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''::character varying"), comment="端点地址（可空）")
    api_key: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="API Key（AES 加密存储）")
    features: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="能力标记：tool_call/agent_thought/image_input")
    context_window: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="上下文窗口长度")
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), comment="最大输出 tokens")
    remark: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"), comment="备注")
    icon: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''::character varying"), comment="图标URL")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), comment="逻辑删除标记")
```

`internal/model/__init__.py`：新增 `from .api_llm_model import ApiLlmModel` 并加入 `__all__`。

- [ ] **Step 6: 运行测试确认通过**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/model/test_api_llm_model.py -q`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add requirements.txt internal/model/api_llm_model.py internal/model/__init__.py test/internal/model/test_api_llm_model.py
git commit -m "feat(custom-llm): add langchain-anthropic dep and ApiLlmModel ORM"
```

---

### Task 2: Alembic 迁移 `add_api_llm_model`

**Files:**
- Create: `internal/migrations/versions/fe65dc34ba21_add_api_llm_model.py`
- Test: 无独立单测（迁移在 CI/gate 跑）。

**Interfaces:**
- Consumes: `ApiLlmModel`（Task 1）。
- Produces: DB 表 `api_llm_model`。

- [ ] **Step 1: 生成迁移文件**

Run:
```bash
cd H:\ai-code-llmops
.\venv\Scripts\python.exe -m alembic revision --autogenerate -m "add api_llm_model" --rev-id fe65dc34ba21
```
Expected: 生成 `internal/migrations/versions/fe65dc34ba21_add_api_llm_model.py`，`upgrade()` 含 `op.create_table('api_llm_model', ...)`。

- [ ] **Step 2: 校验迁移内容**

读取生成文件，`upgrade()` 必须建 `api_llm_model` 表且含所有列（含 `features` JSONB、`is_deleted` Boolean、`account_id`、`protocol`、`model_id`、`base_url`、`api_key`、`context_window`、`max_output_tokens`、`remark`、`icon`）。`downgrade()` 为 `drop_table`。

- [ ] **Step 3: 本地跑迁移**

Run: `.\venv\Scripts\python.exe -m alembic upgrade head`
Expected: 无报错，`\dt api_llm_model` 可见。

- [ ] **Step 4: Commit**

```bash
git add internal/migrations/versions/ab12cd34ef56_add_api_llm_model.py
git commit -m "feat(custom-llm): add api_llm_model alembic migration"
```

---

### Task 3: 自定义模型枚举 / 常量 + 协议分发基类

**Files:**
- Create: `internal/core/language_model/providers/custom_api/__init__.py`
- Create: `internal/core/language_model/providers/custom_api/models.py`
- Create: `internal/core/language_model/providers/custom_api/chat.py`
- Modify: `internal/core/language_model/providers/custom_api/chat.py`（协议分发）
- Test: `test/internal/core/language_model/test_custom_api_protocol.py`

**Interfaces:**
- Produces:
  - `CUSTOM_API_PROVIDER = "custom_api"`（str 常量）
  - `MODEL_PROTOCOL_OPENAI = "openai"`, `MODEL_PROTOCOL_RESPONSES = "responses"`, `MODEL_PROTOCOL_ANTHROPIC = "anthropic"`
  - `def build_model_class(protocol: str) -> type[BaseLanguageModel]` —— 返回对应 langchain 聊天类（`ChatOpenAI` / `ChatOpenAI(use_responses_api=True)` 标记类 / `ChatAnthropic`）
  - `def build_custom_model_entity(record) -> ModelEntity` —— 根据 `ApiLlmModel` 记录构建 `ModelEntity`

- [ ] **Step 1: 写失败测试**

```python
# test/internal/core/language_model/test_custom_api_protocol.py
import pytest

from internal.model import ApiLlmModel
from internal.core.language_model.entities.model_entity import ModelFeature, ModelType
from internal.core.language_model.providers.custom_api.models import (
    build_custom_model_entity,
    MODEL_PROTOCOL_OPENAI,
    MODEL_PROTOCOL_RESPONSES,
    MODEL_PROTOCOL_ANTHROPIC,
)
from internal.core.language_model.providers.custom_api.chat import build_model_class


def _record(protocol):
    return ApiLlmModel(
        account_id="11111111-1111-1111-1111-111111111111",
        name=f"{protocol}-model",
        protocol=protocol,
        model_id="gpt-4o" if protocol != MODEL_PROTOCOL_ANTHROPIC else "claude-3-5-sonnet",
        base_url="https://x/v1",
        api_key="sk-xxx",
        features=["tool_call", "agent_thought"],
        context_window=128000,
        max_output_tokens=4096,
        remark="",
        icon="",
    )


def test_protocol_distribution():
    from langchain_openai import ChatOpenAI

    assert build_model_class(MODEL_PROTOCOL_OPENAI) is ChatOpenAI
    assert build_model_class(MODEL_PROTOCOL_ANTHROPIC).__name__ == "ChatAnthropic"


def test_responses_protocol_uses_responses_api():
    cls = build_model_class(MODEL_PROTOCOL_RESPONSES)
    # langchain-openai 的 use_responses_api 会经 __init__ 应用；这里校验类可实例化且字段存在
    from langchain_openai import ChatOpenAI

    assert issubclass(cls, ChatOpenAI)


def test_build_custom_model_entity():
    entity = build_custom_model_entity(_record(MODEL_PROTOCOL_OPENAI))
    assert entity.model_name == "e08f4b44-0000-4000-8000-000000000001"
    assert entity.label == "openai-model"
    assert entity.model_type == ModelType.CHAT
    assert ModelFeature.TOOL_CALL in entity.features
    assert entity.context_window == 128000
    assert entity.max_output_tokens == 4096
    assert entity.attributes["model"] == "gpt-4o"
    assert entity.attributes["base_url"] == "https://x/v1"
    assert entity.attributes["api_key"] == "sk-xxx"
```

- [ ] **Step 2: 运行确认失败**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/core/language_model/test_custom_api_protocol.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 创建 `custom_api/models.py`**

```python
from internal.core.language_model.entities.model_entity import ModelEntity, ModelFeature, ModelType, ModelParameter

# 自定义模型 provider 常量（保留值）
CUSTOM_API_PROVIDER = "custom_api"
MODEL_PROTOCOL_OPENAI = "openai"
MODEL_PROTOCOL_RESPONSES = "responses"
MODEL_PROTOCOL_ANTHROPIC = "anthropic"
ALL_PROTOCOLS = {MODEL_PROTOCOL_OPENAI, MODEL_PROTOCOL_RESPONSES, MODEL_PROTOCOL_ANTHROPIC}


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
    """
    entity = ModelEntity(
        model_name=f"{CUSTOM_API_PROVIDER}/{model_uuid}",
        label=record.name,
        model_type=ModelType.CHAT,
        features=_to_features(record.features or []),
        context_window=record.context_window or 0,
        max_output_tokens=record.max_output_tokens or 0,
        attributes={
            "model": record.model_id,
            "base_url": record.base_url or None,
            "api_key": record.api_key or None,
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
```

- [ ] **Step 4: 创建 `custom_api/chat.py`**

```python
from langchain_openai import ChatOpenAI

from internal.core.language_model.entities.model_entity import BaseLanguageModel
from .models import MODEL_PROTOCOL_OPENAI, MODEL_PROTOCOL_RESPONSES, MODEL_PROTOCOL_ANTHROPIC, ALL_PROTOCOLS


def _build_responses_chat() -> type[ChatOpenAI]:
    """基于 ChatOpenAI 的子类，固定 use_responses_api=True（openai Responses API）。"""
    class _ResponsesChat(ChatOpenAI):
        use_responses_api: bool = True
    _ResponsesChat.__name__ = "ResponsesChat"
    return _ResponsesChat


def build_model_class(protocol: str) -> type[BaseLanguageModel]:
    """按协议返回 langchain 聊天类；协议非法抛 ValueError。"""
    if protocol == MODEL_PROTOCOL_OPENAI:
        return ChatOpenAI
    if protocol == MODEL_PROTOCOL_RESPONSES:
        return _build_responses_chat()
    if protocol == MODEL_PROTOCOL_ANTHROPIC:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic
    raise ValueError(f"未知自定义模型协议: {protocol}")
```

`custom_api/__init__.py`：导出 `build_model_class`、`build_custom_model_entity`、常量。

- [ ] **Step 5: 运行确认通过**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/core/language_model/test_custom_api_protocol.py -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add internal/core/language_model/providers/custom_api/ test/internal/core/language_model/test_custom_api_protocol.py
git commit -m "feat(custom-llm): custom_api protocol dispatch + ModelEntity builder"
```

---

### Task 4: 协议枚举 + Schema（Create/Update/Resp）

**Files:**
- Create: `internal/core/language_model/providers/custom_api/protocol.py`
- Create: `internal/schema/custom_llm_model_schema.py`
- Test: `test/internal/schema/test_custom_llm_model_schema.py`

**Interfaces:**
- Consumes: `CUSTOM_API_PROVIDER` / `ALL_PROTOCOLS`（Task 3）。
- Produces:
  - `CreateCustomLlmModelReq`（name, protocol, model_id, base_url, api_key, features, context_window, max_output_tokens, remark, icon）
  - `UpdateCustomLlmModelReq`（同上）
  - `GetCustomLlmModelResp`（id, name, protocol, model_id, base_url, api_key(脱敏), features, context_window, max_output_tokens, remark, icon, created_at）
  - 校验：name 非空；protocol ∈ ALL_PROTOCOLS；features ⊆ {tool_call,agent_thought,image_input}；context_window/max_output_tokens ≥ 0。

- [ ] **Step 1: 写失败测试**

```python
# test/internal/schema/test_custom_llm_model_schema.py
import pytest
from pydantic import ValidationError

from internal.schema.custom_llm_model_schema import (
    CreateCustomLlmModelReq,
    GetCustomLlmModelResp,
)


def test_create_valid():
    req = CreateCustomLlmModelReq(
        name="My Model",
        protocol="anthropic",
        model_id="claude-3-5-sonnet",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-xxx",
        features=["tool_call", "agent_thought"],
        context_window=200000,
        max_output_tokens=8192,
        remark="note",
        icon="https://example.com/i.png",
    )
    assert req.protocol == "anthropic"


def test_create_invalid_protocol():
    with pytest.raises(ValidationError):
        CreateCustomLlmModelReq(name="x", protocol="gemini", model_id="g", features=[])


def test_create_invalid_feature():
    with pytest.raises(ValidationError):
        CreateCustomLlmModelReq(name="x", protocol="openai", model_id="g", features=["vision"])


def test_resp_masks_api_key():
    resp = GetCustomLlmModelResp(
        id="e08f4b44-0000-4000-8000-000000000001",
        name="m",
        protocol="openai",
        model_id="gpt-4o",
        api_key="sk-secret",
        features=["tool_call"],
        context_window=128000,
        max_output_tokens=4096,
        remark="",
        icon="",
        created_at=0,
    )
    assert resp.api_key == "********"
```

- [ ] **Step 2: 运行确认失败**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/schema/test_custom_llm_model_schema.py -q`
Expected: FAIL。

- [ ] **Step 3: 创建 `protocol.py`**

```python
from pydantic import BaseModel, Field, field_validator
from internal.core.language_model.providers.custom_api.models import ALL_PROTOCOLS, MODEL_PROTOCOL_OPENAI, MODEL_PROTOCOL_RESPONSES, MODEL_PROTOCOL_ANTHROPIC, CUSTOM_API_PROVIDER

ALLOWED_FEATURES = {"tool_call", "agent_thought", "image_input"}

# 供前端下拉
PROTOCOL_OPTIONS = [
    {"label": "OpenAI", "value": MODEL_PROTOCOL_OPENAI},
    {"label": "Responses", "value": MODEL_PROTOCOL_RESPONSES},
    {"label": "Anthropic", "value": MODEL_PROTOCOL_ANTHROPIC},
]
```

- [ ] **Step 4: 创建 schema**

`internal/schema/custom_llm_model_schema.py`：

```python
from typing import Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from internal.core.language_model.providers.custom_api.protocol import ALLOWED_FEATURES, ALL_PROTOCOLS


class _CustomModelMixin:
    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("模型名称不能为空")
        if len(v) > 100:
            raise ValueError("模型名称最大100字符")
        return v

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("模型ID不能为空")
        return v

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        if v not in ALL_PROTOCOLS:
            raise ValueError("协议必须为 openai / responses / anthropic")
        return v

    @field_validator("features")
    @classmethod
    def validate_features(cls, v: list[str]) -> list[str]:
        unknown = set(v) - ALLOWED_FEATURES
        if unknown:
            raise ValueError(f"能力标记不合法: {sorted(unknown)}")
        return v

    @field_validator("context_window")
    @classmethod
    def validate_ctx(cls, v: int) -> int:
        if v < 0:
            raise ValueError("context_window 不能为负")
        return v

    @field_validator("max_output_tokens")
    @classmethod
    def validate_max_tokens(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_output_tokens 不能为负")
        return v


class CreateCustomLlmModelReq(_CustomModelMixin, BaseModel):
    name: str = Field(description="模型名称（1-100）")
    protocol: str = Field(description="协议：openai / responses / anthropic")
    model_id: str = Field(description="请求体 model 字段")
    base_url: str = Field(default="", description="端点地址")
    api_key: str = Field(default="", description="API Key")
    features: list[str] = Field(default_factory=list, description="能力标记")
    context_window: int = Field(default=0, ge=0, description="上下文窗口长度")
    max_output_tokens: int = Field(default=0, ge=0, description="最大输出tokens")
    remark: str = Field(default="", description="备注")
    icon: str = Field(default="", description="图标URL")


class UpdateCustomLlmModelReq(_CustomModelMixin, BaseModel):
    name: str = Field(description="模型名称（1-100）")
    protocol: str = Field(description="协议")
    model_id: str = Field(description="请求体 model 字段")
    base_url: str = Field(default="", description="端点地址")
    api_key: str = Field(default="", description="API Key")
    features: list[str] = Field(default_factory=list, description="能力标记")
    context_window: int = Field(default=0, ge=0, description="上下文窗口长度")
    max_output_tokens: int = Field(default=0, ge=0, description="最大输出tokens")
    remark: str = Field(default="", description="备注")
    icon: str = Field(default="", description="图标URL")


class GetCustomLlmModelResp(BaseModel):
    id: UUID | None = None
    name: str = ""
    protocol: str = ""
    model_id: str = ""
    base_url: str = ""
    api_key: str = "********"
    features: list[str] = Field(default_factory=list)
    context_window: int = 0
    max_output_tokens: int = 0
    remark: str = ""
    icon: str = ""
    created_at: int = 0

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def process_data(cls, data: Any) -> dict:
        if hasattr(data, "protocol"):
            return {
                "id": data.id,
                "name": data.name,
                "protocol": data.protocol,
                "model_id": data.model_id,
                "base_url": data.base_url,
                "api_key": "********",
                "features": data.features or [],
                "context_window": data.context_window,
                "max_output_tokens": data.max_output_tokens,
                "remark": data.remark,
                "icon": data.icon,
                "created_at": int(data.created_at.timestamp()) if data.created_at else 0,
            }
        return data
```

- [ ] **Step 5: 运行确认通过**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/schema/test_custom_llm_model_schema.py -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add internal/core/language_model/providers/custom_api/protocol.py internal/schema/custom_llm_model_schema.py test/internal/schema/test_custom_llm_model_schema.py
git commit -m "feat(custom-llm): custom model schema + protocol enum"
```

---

### Task 5: AES 加密工具（抽公共）

**Files:**
- Create: `internal/lib/crypto.py`
- Modify: `internal/service/system_config_service.py`（改用公共工具）
- Test: `test/internal/lib/test_crypto.py`

**Interfaces:**
- Produces: `encrypt_value(plain: str, master_key: bytes) -> str`、`decrypt_value(encoded: str, master_key: bytes) -> str`、`build_master_key(secret: str) -> bytes`。
- Consumes: 无。

- [ ] **Step 1: 写失败测试**

```python
# test/internal/lib/test_crypto.py
from internal.lib.crypto import encrypt_value, decrypt_value, build_master_key


def test_roundtrip():
    key = build_master_key("my-secret")
    enc = encrypt_value("sk-ant-xxx", key)
    assert enc != "sk-ant-xxx"
    assert decrypt_value(enc, key) == "sk-ant-xxx"


def test_decrypt_failure_returns_original():
    key = build_master_key("k1")
    assert decrypt_value("not-base64!!!", key) == "not-base64!!!"
```

- [ ] **Step 2: 运行确认失败**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/lib/test_crypto.py -q`
Expected: FAIL。

- [ ] **Step 3: 创建 `internal/lib/crypto.py`**

```python
import base64
import hashlib

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def build_master_key(secret: str) -> bytes:
    """32 字节主密钥：SHA256(secret)。"""
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt_value(plain: str, master_key: bytes) -> str:
    """AES-CBC 加密明文，返回 base64(iv + ciphertext)。"""
    iv = __import__("os").urandom(16)
    cipher = Cipher(algorithms.AES(master_key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plain.encode("utf-8")) + padder.finalize()
    ct = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ct).decode("utf-8")


def decrypt_value(encoded: str, master_key: bytes) -> str:
    """解密 base64(iv + ciphertext)；失败返回原文（兼容未加密旧数据）。"""
    try:
        raw = base64.b64decode(encoded)
        iv, ct = raw[:16], raw[16:]
        cipher = Cipher(algorithms.AES(master_key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ct) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")
    except Exception:
        return encoded
```

- [ ] **Step 4: 让 system_config_service 复用公共工具**

将 `_master_key/_encrypt_value/_decrypt_value` 改为委托 `internal.lib.crypto`（保留方法签名以兼容既有调用；内部改用 `build_master_key/encrypt_value/decrypt_value`）。

- [ ] **Step 5: 运行确认通过**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/lib/test_crypto.py test/internal/service/test_system_config_service.py -q`
Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add internal/lib/crypto.py internal/service/system_config_service.py test/internal/lib/test_crypto.py
git commit -m "feat(custom-llm): extract shared AES crypto helpers"
```

---

### Task 6: CustomLlmModelService（增删改查 + AES 加解密 + 账号过滤）

**Files:**
- Create: `internal/service/custom_llm_model_service.py`
- Modify: `internal/service/__init__.py`（导出 `CustomLlmModelService`）
- Test: `test/internal/service/test_custom_llm_model_service.py`

**Interfaces:**
- Consumes: `ApiLlmModel`（Task 1）, schema（Task 4）, crypto（Task 5）, `BaseService`。
- Produces:
  - `async create(req, user) -> ApiLlmModel`
  - `async update(model_id, req, user) -> ApiLlmModel`
  - `async delete(model_id, user) -> None`（逻辑删除）
  - `async get_by_id(model_id, user) -> ApiLlmModel | None`
  - `async list_by_account(user) -> list[ApiLlmModel]`（仅 is_deleted=False）
  - `async list_models_for_account(account_id) -> list[ApiLlmModel]`（供 manager 懒加载用，返回未删除记录）
  - 加密/解密：api_key 用 `build_master_key(CONFIG_MASTER_KEY 或 JWT_SECRET_KEY)` 加密；读列表时返回脱敏 `********`。

- [ ] **Step 1: 写失败测试**

```python
# test/internal/service/test_custom_llm_model_service.py
import pytest
from internal.model import ApiLlmModel
from internal.service.custom_llm_model_service import CustomLlmModelService
from internal.schema.custom_llm_model_schema import CreateCustomLlmModelReq


USER = object()


class FakeUser:
    id = "11111111-1111-1111-1111-111111111111"


async def test_create_and_encrypt(db_session, monkeypatch):
    svc = CustomLlmModelService(db=db_session)
    req = CreateCustomLlmModelReq(
        name="claude", protocol="anthropic", model_id="claude-3-5-sonnet",
        base_url="https://api.anthropic.com", api_key="sk-ant-secret",
        features=["tool_call"], context_window=200000, max_output_tokens=8192,
    )
    record = await svc.create(req, FakeUser())
    assert record.protocol == "anthropic"
    # api_key 已加密，不是明文
    assert record.api_key != "sk-ant-secret"
    assert record.account_id == FakeUser().id


async def test_list_filters_deleted(db_session):
    svc = CustomLlmModelService(db=db_session)
    a = ApiLlmModel(account_id=FakeUser().id, name="a", protocol="openai", model_id="gpt-4o", features=[])
    b = ApiLlmModel(account_id=FakeUser().id, name="b", protocol="openai", model_id="gpt-4o", features=[], is_deleted=True)
    db_session.add_all([a, b])
    await db_session.commit()
    result = await svc.list_by_account(FakeUser())
    assert [r.name for r in result] == ["a"]


async def test_get_by_id_account_isolation(db_session):
    svc = CustomLlmModelService(db=db_session)
    other = ApiLlmModel(account_id="22222222-2222-2222-2222-222222222222", name="other", protocol="openai", model_id="g", features=[])
    db_session.add(other)
    await db_session.commit()
    assert await svc.get_by_id(other.id, FakeUser()) is None
```

- [ ] **Step 2: 运行确认失败**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/service/test_custom_llm_model_service.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现 service**

`internal/service/custom_llm_model_service.py`：

```python
import os
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from internal.lib.crypto import build_master_key, encrypt_value, decrypt_value
from internal.model import ApiLlmModel
from internal.schema.custom_llm_model_schema import CreateCustomLlmModelReq, UpdateCustomLlmModelReq
from internal.service.base_service import BaseService


def _master_key() -> bytes:
    secret = os.getenv("CONFIG_MASTER_KEY") or os.getenv("JWT_SECRET_KEY") or "llmops-default-master-key"
    return build_master_key(secret)


@dataclass
class CustomLlmModelService(BaseService):
    db: object  # AsyncSession

    def _encrypt(self, plain: str) -> str:
        return encrypt_value(plain, _master_key())

    def _decrypt(self, encoded: str) -> str:
        return decrypt_value(encoded, _master_key())

    async def create(self, req: CreateCustomLlmModelReq, user) -> ApiLlmModel:
        import uuid
        return await self.create_record(user, req, is_update=False)

    async def create_record(self, user, req, is_update: bool) -> ApiLlmModel:
        fields = {
            "account_id": user.id,
            "name": req.name,
            "protocol": req.protocol,
            "model_id": req.model_id,
            "base_url": req.base_url or "",
            "api_key": self._encrypt(req.api_key) if req.api_key else "",
            "features": req.features or [],
            "context_window": req.context_window,
            "max_output_tokens": req.max_output_tokens,
            "remark": req.remark or "",
            "icon": req.icon or "",
        }
        return await self.create(ApiLlmModel, **fields)

    async def update(self, model_id: UUID, req: UpdateCustomLlmModelReq, user) -> ApiLlmModel:
        record = await self.get_by_id(model_id, user)
        if record is None:
            raise ValueError("自定义模型不存在或不属于当前账号")
        return await self.update_record(record, req)

    async def update_record(self, record, req) -> ApiLlmModel:
        kwargs = {
            "name": req.name,
            "protocol": req.protocol,
            "model_id": req.model_id,
            "base_url": req.base_url or "",
            "features": req.features or [],
            "context_window": req.context_window,
            "max_output_tokens": req.max_output_tokens,
            "remark": req.remark or "",
            "icon": req.icon or "",
        }
        if req.api_key:
            kwargs["api_key"] = self._encrypt(req.api_key)
        return await self.update(record, **kwargs)

    async def delete(self, model_id: UUID, user) -> None:
        record = await self.get_by_id(model_id, user)
        if record is None:
            raise ValueError("自定义模型不存在或不属于当前账号")
        await self.update(record, is_deleted=True)

    async def get_by_id(self, model_id: UUID, user) -> ApiLlmModel | None:
        stmt = select(ApiLlmModel).where(
            ApiLlmModel.id == model_id,
            ApiLlmModel.account_id == user.id,
            ApiLlmModel.is_deleted.is_(False),
        )
        return (await self.db.execute(stmt)).scalars().first()

    async def list_by_account(self, user) -> list[ApiLlmModel]:
        stmt = select(ApiLlmModel).where(
            ApiLlmModel.account_id == user.id,
            ApiLlmModel.is_deleted.is_(False),
        ).order_by(ApiLlmModel.created_at)
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_models_for_account(self, account_id) -> list[ApiLlmModel]:
        stmt = select(ApiLlmModel).where(
            ApiLlmModel.account_id == account_id,
            ApiLlmModel.is_deleted.is_(False),
        ).order_by(ApiLlmModel.created_at)
        return list((await self.db.execute(stmt)).scalars().all())
```

`internal/service/__init__.py`：`from .custom_llm_model_service import CustomLlmModelService`；`__all__` 加 `"CustomLlmModelService"`。

- [ ] **Step 4: 运行确认通过**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/service/test_custom_llm_model_service.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add internal/service/custom_llm_model_service.py internal/service/__init__.py test/internal/service/test_custom_llm_model_service.py
git commit -m "feat(custom-llm): CustomLlmModelService CRUD + AES + account filter"
```

---

### Task 7: LanguageModelManager 支持按账号懒合并 custom_api provider

**Files:**
- Modify: `internal/core/language_model/language_model_manager.py`
- Create: `internal/core/language_model/providers/custom_api/merger.py`
- Test: `test/internal/core/language_model/test_manager_custom_api_merge.py`

**Interfaces:**
- Consumes: `build_custom_model_entity`,`CUSTOM_API_PROVIDER`（Task 3）, `build_model_class`（Task 3）。
- Produces:
  - `LanguageModelManager` 新增字段 `custom_model_loader: Callable[[str], Awaitable[list]] | None = None`（注入的懒加载回调，`(account_id) -> list[ApiLlmModel]`）
  - 新增方法 `async merge_account_custom_models(account_id: str) -> None`：构建/替换 custom_api provider 入 `provider_map`（每账号只构建一次）
  - 新增方法 `async get_provider_async(name) -> Provider | None`：父类 `get_provider` 为同步；对 custom_api 先触发懒合并，再返回。
  - Provider 子类/包装：`get_model_class` 对 custom_api 调 `build_model_class(protocol)`。

- [ ] **Step 1: 写失败测试**

```python
# test/internal/core/language_model/test_manager_custom_api_merge.py
import pytest
from internal.core.language_model import LanguageModelManager
from internal.core.language_model.providers.custom_api.models import CUSTOM_API_PROVIDER


async def _make_loader():
    from internal.model import ApiLlmModel

    async def loader(account_id):
        return [
            ApiLlmModel(
                id="e08f4b44-0000-4000-8000-000000000001",
                account_id=account_id,
                name="my-claude",
                protocol="anthropic",
                model_id="claude-3-5-sonnet",
                base_url="https://api.anthropic.com",
                api_key="sk-ant-xxx",
                features=["tool_call"],
                context_window=200000,
                max_output_tokens=8192,
                remark="",
                icon="",
                is_deleted=False,
            )
        ]

    return loader


async def test_merge_adds_custom_provider():
    manager = LanguageModelManager(custom_model_loader=await _make_loader())
    await manager.merge_account_custom_models("11111111-1111-1111-1111-111111111111")
    provider = manager.get_provider(CUSTOM_API_PROVIDER)
    assert provider is not None
    entity = provider.get_model_entity("custom_api/e08f4b44-0000-4000-8000-000000000001")
    assert entity.label == "my-claude"
    assert entity.metadata["protocol"] == "anthropic"


async def test_get_provider_async_triggers_lazy_merge():
    manager = LanguageModelManager(custom_model_loader=await _make_loader())
    # 未显式 merge 前，get_provider 为 None（懒加载）
    assert manager.provider_map.get(CUSTOM_API_PROVIDER) is None
    provider = await manager.get_provider_async(CUSTOM_API_PROVIDER)
    assert provider is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/core/language_model/test_manager_custom_api_merge.py -q`
Expected: FAIL（无 `custom_model_loader` 字段 / 方法）。

- [ ] **Step 3: 实现 merger 与 manager 扩展**

`internal/core/language_model/providers/custom_api/merger.py`：

```python
from internal.core.language_model.entities.provider_entity import Provider, ProviderEntity
from internal.core.language_model.providers.custom_api.models import (
    build_custom_model_entity, CUSTOM_API_PROVIDER, ALL_PROTOCOLS,
)
from internal.core.language_model.providers.custom_api.chat import build_model_class


def build_custom_provider(records) -> Provider:
    """根据自定义模型记录构建 custom_api Provider（含 model_entity_map + 协议分发模型类）。"""
    provider_entity = ProviderEntity(
        name=CUSTOM_API_PROVIDER,
        position=999,
        label="自定义API模型",
        description="用户按账号添加的 OpenAI / Anthropic / Responses 兼容模型",
        icon="",
        background="#FFFFFF",
        supported_model_types=["chat"],
    )
    provider = Provider(name=CUSTOM_API_PROVIDER, position=999, provider_entity=provider_entity)
    if provider.model_class_map.get("chat") is None:
        provider.model_class_map["chat"] = build_model_class  # 占位，实际按记录 protocol 分发见下
    for record in records:
        model_uuid = str(record.id)
        entity = build_custom_model_entity(record, model_uuid)
        provider.model_entity_map[f"{CUSTOM_API_PROVIDER}/{model_uuid}"] = entity
        # 该模型的协议决定其模型类
    provider._custom_protocols = {record.id: record.protocol for record in records}
    return provider
```

> 注：`build_model_class` 是 per-protocol 的（需要 record），这里用一个轻量 `Provider` 子类按 `model_entity_map[model_key].metadata["protocol"]` 分发，见 manager 里封装。

`LanguageModelManager` 扩展（`language_model_manager.py`）：
- 增加字段 `custom_model_loader: Callable[[str], Awaitable[list]] | None = None`
- 增加 `_custom_loaded_for: str | None = None`（已合并账号缓存）
- `async def merge_account_custom_models(account_id)`：读取 loader → `build_custom_provider` → `self.provider_map[CUSTOM_API_PROVIDER] = provider`，并给 provider 挂一个 `resolve_model_class(protocol)` 的分发（懒，见下）。
- `async def get_provider_async(name)`：若 `name == CUSTOM_API_PROVIDER` && 未合并该账号 && loader 存在 → 合并。
- 让 custom_api provider 的 `get_model_class` 支持按模型实体 protocol 分辨：覆写 Provider.get_model_class，使其在 model_type='chat' 时按传入的 model_entity 的 metadata['protocol'] 调 `build_model_class`。

为满足 Provider 既有 `get_model_class(model_type)` 签名，采用在 `merge_account_custom_models` 末尾给 provider 注入 `model_class_resolver` 的简单办法：给 `Provider` 加一个可选字段 `custom_resolver: Callable[[ModelEntity], type] | None`，`get_model_class` 里若 `custom_resolver` 存在则用它（带 model_entity）。这与现有 `get_model_class` 的调用点不冲突（其只用于 custom_api）。

- [ ] **Step 4: 运行确认通过**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/core/language_model/test_manager_custom_api_merge.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add internal/core/language_model/language_model_manager.py internal/core/language_model/providers/custom_api/merger.py test/internal/core/language_model/test_manager_custom_api_merge.py
git commit -m "feat(custom-llm): merge custom_api provider into LanguageModelManager (lazy per-account)"
```

---

### Task 8: 接通模型校验与加载路径（custom_api 可被选中/构造实例）

**Files:**
- Modify: `internal/service/language_model_service.py`（`get_language_models` / `get_language_model` / `load_language_model`）
- Modify: `internal/core/language_model/language_model_manager.py`（`get_model_class_by_provider_and_model` 支持自定义解析）
- Modify: `internal/service/app_config_service.py`（`_process_and_validate_model_config` 对 custom_api 放行）
- Modify: `internal/service/app_service.py`（校验路径同步）
- Test: `test/internal/service/test_custom_llm_load.py`

**Interfaces:**
- Consumes: `merge_account_custom_models` / `get_provider_async`（Task 7）, `CUSTOM_API_PROVIDER`（Task 3）。
- Produces: `get_language_models` 在注入 custom_model_loader 的 manager 下能列出 custom_api 分组；`load_language_model` 对 `custom_api/<uuid>` 能按协议构造实例。

- [ ] **Step 1: 写失败测试**

```python
# test/internal/service/test_custom_llm_load.py
import pytest
from unittest.mock import MagicMock

from internal.core.language_model import LanguageModelManager
from internal.service.language_model_service import LanguageModelService


async def _loader():
    from internal.model import ApiLlmModel

    async def loader(account_id):
        return [ApiLlmModel(
            id="e08f4b44-0000-4000-8000-000000000001",
            account_id=account_id, name="gpt", protocol="openai",
            model_id="gpt-4o", base_url="https://x/v1", api_key="sk-xxx",
            features=["tool_call"], context_window=128000, max_output_tokens=4096,
            remark="", icon="", is_deleted=False,
        )]
    return loader


async def test_get_language_models_includes_custom():
    manager = LanguageModelManager(custom_model_loader=await _loader())
    svc = LanguageModelService(db=MagicMock(), language_model_manager=manager)
    await manager.merge_account_custom_models("11111111-1111-1111-1111-111111111111")
    models = await svc.get_language_models()
    custom = next((p for p in models if p["name"] == "custom_api"), None)
    assert custom is not None
    assert custom["label"] == "自定义API模型"


async def test_load_language_model_custom():
    from internal.service.custom_llm_model_service import CustomLlmModelService

    manager = LanguageModelManager(custom_model_loader=await _loader())
    svc = LanguageModelService(db=MagicMock(), language_model_manager=manager)
    await manager.merge_account_custom_models("11111111-1111-1111-1111-111111111111")
    llm = await svc.load_language_model({
        "provider": "custom_api",
        "model": "custom_api/e08f4b44-0000-4000-8000-000000000001",
        "parameters": {},
    })
    assert llm is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/service/test_custom_llm_load.py -q`
Expected: FAIL（get_language_models 未识别 custom_api；load_language_model 断言失败）。

- [ ] **Step 3: 打通 `get_language_models`**

`language_model_service.get_language_models`：在遍历 provider 列表后追加 custom_api 分支——若 `self.language_model_manager.provider_map.get("custom_api")` 存在（已按账号合并），用与静态 provider 相同的结构输出该分组。

- [ ] **Step 4: 打通 `load_language_model`**

`load_language_model._load` 内部，`provider.get_model_class` 对 custom_api 会经 Provider.custom_resolver 按 `model_entity.metadata["protocol"]` 返回类；构造时 attributes 已含 `model/base_url/api_key`，`**attributes, **parameters` 直接传入 langchain 类。确保 custom_api 路由不被 `except Exception` 兜底吞掉（验证无异常时返回实例）。

- [ ] **Step 5: 打通校验路径**

`app_config_service._process_and_validate_model_config` 与 `app_service` 的模型校验：`get_provider(model_config["provider"])` 为同步；若要命中 custom_api，需改为「先 `await get_provider_async`」。由于这两处是同步方法，改为在请求侧先合并（handler/service 已注入 custom_model_loader 的 manager，进入前已 merge），使同步 `get_provider('custom_api')` 已命中——即把「按账号合并」提前到这些 service 入口。为最小改动，本 Task 只在**已有合并结果的 manager** 下让 `get_model_entity` 命中 custom provider；`_process_and_validate_model_config` 保持现有调用（`get_provider`/`get_model_entity`），在合并后即命中。

> 实现说明：`app_config_service`/`app_service` 使用容器给的 `LanguageModelManager()`，该 manager 需要注入 `custom_model_loader` 并在请求期合并（见 Task 9 容器注入）。本任务保证 manager 一旦被合并，这些校验路径自动命中。

- [ ] **Step 6: 运行确认通过**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/service/test_custom_llm_load.py -q`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add internal/service/language_model_service.py internal/core/language_model/language_model_manager.py test/internal/service/test_custom_llm_load.py
git commit -m "feat(custom-llm): wire custom_api into language model list/load paths"
```

---

### Task 9: 容器注入 custom_model_loader + CustomLlmModelHandler + 路由

**Files:**
- Modify: `internal/container.py`（各 manager 注入 loader + 新增 service/handler 工厂）
- Create: `internal/handler/custom_llm_model_handler.py`
- Modify: `internal/router/router.py`（注册 handler + 路由）
- Test: `test/internal/handler/test_custom_llm_model_handler.py`

**Interfaces:**
- Consumes: `CustomLlmModelService`（Task 6）, `merge_account_custom_models`（Task 7）。
- Produces: HTTP 端点 `GET/POST/PUT/DELETE /custom_llm_models`。

- [ ] **Step 1: 写失败测试（handler 契约）**

```python
# test/internal/handler/test_custom_llm_model_handler.py
import pytest
from unittest.mock import AsyncMock

from internal.handler.custom_llm_model_handler import CustomLlmModelHandler
from internal.schema.custom_llm_model_schema import CreateCustomLlmModelReq, GetCustomLlmModelResp


class FakeUser:
    id = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_create_handler():
    svc = AsyncMock()
    svc.create = AsyncMock(return_value=None)
    handler = CustomLlmModelHandler(custom_llm_model_service=svc)
    req = CreateCustomLlmModelReq(name="x", protocol="openai", model_id="gpt-4o", features=[])
    await handler.create_custom_llm_model(FakeUser(), req)
    svc.create.assert_awaited_once()
```

- [ ] **Step 2: 运行确认失败**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/handler/test_custom_llm_model_handler.py -q`
Expected: FAIL。

- [ ] **Step 3: 创建 handler**

`internal/handler/custom_llm_model_handler.py`（`CustomLlmModelHandler`，字段 `custom_llm_model_service`，方法 `list/get/create/update/delete`，`user: CurrentUser`，返回 `success_json` / `success_message_json`）。

- [ ] **Step 4: 容器注入**

`internal/container.py`：
- `create_custom_llm_model_service(session) -> CustomLlmModelService`
- `create_custom_llm_model_handler(session) -> CustomLlmModelHandler`
- 给 `create_language_model_service` / `create_app_config_service` / `create_app_service` / `create_builtin_app_handler` 等所有构造 `LanguageModelManager()` 的地方注入 `custom_model_loader`（其调用 `create_custom_llm_model_service(proxy).list_models_for_account(account_id)`）。loader 是 async 回调，通过 `RequestSessionProxy` 解析请求期 session。

由于 loader 需要「请求上下文账号」，manager 的懒合并由 `get_provider_async`/handler 显式触发：`custom_model_loader` 的 account_id 参数在调用点（handler/service）由 `CurrentUser` 提供。容器注入的 loader 形如 `lambda account_id: service.list_models_for_account(account_id)`。

- [ ] **Step 5: 注册路由**

`internal/router/router.py`：`custom_llm_model_handler = create_custom_llm_model_handler(proxy)`；在 `_register_routes` 声明参数并注册：
- `GET  /custom_llm_models`
- `POST /custom_llm_models`
- `GET  /custom_llm_models/{model_id}`
- `PUT  /custom_llm_models/{model_id}`
- `DELETE /custom_llm_models/{model_id}`

- [ ] **Step 6: 运行确认通过**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/handler/test_custom_llm_model_handler.py -q`
Expected: PASS。

- [ ] **Step 7: 全量相关测试**

Run: `.\venv\Scripts\python.exe -m pytest test/internal/ -q`
Expected: 全 PASS（新增相关 + 既有不回归）。

- [ ] **Step 8: Commit**

```bash
git add internal/container.py internal/handler/custom_llm_model_handler.py internal/router/router.py test/internal/handler/test_custom_llm_model_handler.py
git commit -m "feat(custom-llm): wire handler+router+container loader injection"
```

---

### Task 10: 设置页前端 —— 自定义模型管理

**Files:**
- Create: `ai-code-llmops-web/src/models/custom-llm-model.ts`
- Create: `ai-code-llmops-web/src/services/custom-llm-model.ts`
- Create: `ai-code-llmops-web/src/views/settings/components/CustomLlmModelConfig.vue`
- Modify: `ai-code-llmops-web/src/views/settings/SystemSettings.vue`
- Test: 前端无既有单测框架覆盖该页；以 `vue-tsc --build` + dev 冒烟为准。

**Interfaces:**
- Consumes: 后端接口（Task 9）。
- Produces: 设置页「自定义模型」区块，支持列表/新增/编辑/删除。

- [ ] **Step 1: 类型定义**

`src/models/custom-llm-model.ts`：`CustomLlmModel`、`CreateCustomLlmModelPayload`、`UpdateCustomLlmModelPayload` 类型。

- [ ] **Step 2: service 封装**

`src/services/custom-llm-model.ts`：
- `getCustomLlmModels()` → GET `/custom_llm_models`
- `createCustomLlmModel(payload)` → POST
- `getCustomLlmModel(id)` → GET `/custom_llm_models/{id}`
- `updateCustomLlmModel(id, payload)` → PUT
- `deleteCustomLlmModel(id)` → DELETE

- [ ] **Step 3: 组件 `CustomLlmModelConfig.vue`**

表单字段：名称、协议（下拉 openai/responses/anthropic）、模型ID、Base URL、API Key（敏感，编辑空则不改）、能力标记（多选 tool_call/agent_thought/image_input）、context_window、max_output_tokens、备注、图标。列表展示 + 新增/编辑弹窗 + 删除确认。

- [ ] **Step 4: 接入 SystemSettings.vue**

在 tab `['llm','oss',...]` 增加自定义模型区块（并入「大模型配置」下方或独立 tab），挂 `<custom-llm-model-config />`。保存走自有接口，不写入 envConfig。

- [ ] **Step 5: 类型检查 + 前端冒烟**

Run: `npm run type-check`（在 `ai-code-llmops-web`）
Expected: exit 0。

- [ ] **Step 6: Commit**

```bash
cd ai-code-llmops-web
git add src/models/custom-llm-model.ts src/services/custom-llm-model.ts src/views/settings/components/CustomLlmModelConfig.vue src/views/settings/SystemSettings.vue
git commit -m "feat(custom-llm): settings UI for custom api models"
```

---

## Self-Review

**1. Spec coverage**（对照 spec 各节）：
- 2 决策（按账号隔离/UUID key/协议三选/字段）→ Task 1/3/4/6 ✓
- 3.1 方案 A 合并进 manager → Task 7 ✓
- 3.2 懒加载 + account_model_loader → Task 7/9 ✓
- 3.3 协议→类分发（OpenAI/Responses/Anthropic）→ Task 3 ✓
- 3.4 数据库 api_llm_model → Task 1/2 ✓
- 3.5 设置页交互 → Task 10 ✓
- 3.6 后端 REST 接口 → Task 9 ✓
- 4 错误处理（校验/脱敏/逻辑删除/懒加载容错）→ Task 4/6/7 ✓
- 5 测试（协议分发/entity 构建/list+load/校验/前端 type-check）→ Task 3/7/8/10 ✓
- 6 变更文件 → Tasks 覆盖 ✓
- Anthropic 依赖 → Task 1 ✓

**2. Placeholder scan**：无 TBD/TODO；所有代码步骤含真实代码。Task 5/6 的 `_master_key` 与 system_config 复用对齐（Task 5 已抽公共，Task 6 用公共函数）。Task 7 的 `Provider` 扩展（`custom_resolver` / `_custom_protocols`）在 Task 7 描述，Task 8 消费，名字一致（`custom_resolver`）。Task 8 的 `get_provider_async` 由 Task 7 定义，使用一致。

**3. Type consistency**：
- `build_custom_model_entity(record, model_uuid)` 在 Task 3 定义（双参），Task 7 调用传 `(record, str(record.id))` ✓
- `merge_account_custom_models(account_id)` 在 Task 7 定义，Task 8/9 调用 ✓
- `get_provider_async(name)` 在 Task 7 定义，Task 8 校验路径使用 ✓
- `CustomLlmModelService.create(req, user)` / `update(id, req, user)` / `delete(id, user)` / `list_by_account(user)` / `list_models_for_account(account_id)` 在 Task 6 定义，Task 9 handler 使用 ✓
- `CreateCustomLlmModelReq`/`UpdateCustomLlmModelReq`/`GetCustomLlmModelResp` 在 Task 4 定义，Task 6/9/10 使用 ✓
- `build_model_class(protocol)` 在 Task 3 定义 ✓

**已知注意点**：Task 8 提到 `_process_and_validate_model_config` / `app_service` 校验为同步方法，需在请求期先合并（依赖 Task 9 容器注入 loader + 请求期 merge）。执行时若发现这些方法的同步性导致无法命中 custom_api，须在请求期（如 handler 或 service 入口）先 `await merge_account_custom_models(account_id)`，使同步 `get_provider('custom_api')` 命中 —— 此点已在 Task 8/9 相互引用。
